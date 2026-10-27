"""可观测性：结构化日志 + 请求追踪 ID。

设计要点（三条，都是踩过坑之后的结论）：

1. 用**纯 ASGI 中间件**而不是 ``@app.middleware("http")``。
   ``BaseHTTPMiddleware`` 会把下游应用放在子 task 里执行，``ContextVar``
   的修改不会回传到外层，结果就是「访问日志有 rid，业务日志没有 rid」。
2. 用 ``ContextVar`` 而不是 threading.local。
   FastAPI 的同步路由跑在线程池里，异步路由跑在事件循环里，只有 ContextVar
   在两种执行模型下都能正确传递。
3. 日志格式固定成一行 key=value。
   答辩现场用 ``Select-String``/``grep`` 就能按 rid 串起整条链路，不需要引日志系统。
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders

from .config import APP_NAME, DATA_DIR, LOG_DIR, LOG_LEVEL, LOG_SLOW_MS

# ---------------------------------------------------------------- 请求上下文

REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
STARTED_AT = time.time()

_CONFIGURE_LOCK = False


def current_request_id() -> str:
    return REQUEST_ID.get()


def logger(name: str = "edu") -> logging.Logger:
    """业务模块统一入口：``log = observability.logger(__name__)``。"""
    return logging.getLogger(name)


# ---------------------------------------------------------------- 日志格式

class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = REQUEST_ID.get()
        return True


_FORMAT = "%(asctime)s %(levelname)-5s rid=%(request_id)s %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """幂等：重复调用（reload / pytest 多次导入）不会叠加 handler。"""
    global _CONFIGURE_LOCK
    if _CONFIGURE_LOCK:
        return
    _CONFIGURE_LOCK = True

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)
    rid_filter = _RequestIdFilter()  # Formatter 没有 addFilter，过滤器必须挂在 handler 上

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 控制台：控制在 LOG_LEVEL 以上，保持启动时的体验不变
    console = logging.StreamHandler()
    console.setLevel(LOG_LEVEL)
    console.setFormatter(formatter)
    console.addFilter(rid_filter)
    root.addHandler(console)

    # 文件：滚动保存，答辩现场可回溯
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            LOG_DIR / "app.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(LOG_LEVEL)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(rid_filter)
        root.addHandler(file_handler)
    except OSError:
        logging.getLogger("edu").warning("日志目录不可写，仅输出到控制台：%s", LOG_DIR)

    # uvicorn 的访问日志会和我们的中间件重复，关掉它自己的
    logging.getLogger("uvicorn.access").disabled = True


# ---------------------------------------------------------------- ASGI 中间件

_QUIET_PREFIXES = ("/assets/", "/favicon.ico")
_log = logging.getLogger("edu.access")


class AccessLog:
    """记录 method / path / status / 耗时 / rid，并回写 X-Request-Id。"""

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1").strip()
        rid = incoming[:64] or uuid.uuid4().hex[:12]
        token = REQUEST_ID.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message):  # noqa: ANN001
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                MutableHeaders(scope=message)["X-Request-Id"] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            path = scope.get("root_path", "") + scope.get("path", "")
            level = logging.INFO
            if status >= 500:
                level = logging.ERROR
            elif elapsed >= LOG_SLOW_MS:
                level = logging.WARNING
            target = _log
            if scope.get("method") == "GET" and path.startswith(_QUIET_PREFIXES):
                level = logging.DEBUG
            target.log(
                level,
                "method=%s path=%s status=%s dur=%.1fms",
                scope.get("method"), path, status, elapsed,
            )
            REQUEST_ID.reset(token)


def health_extra() -> dict:
    """给 /api/health 补充运行时信息，答辩时可用来证明服务还活着。"""
    return {
        "uptime_s": int(time.time() - STARTED_AT),
        "pid": os.getpid(),
        "data_dir": str(DATA_DIR),
        "log_file": str(LOG_DIR / "app.log"),
    }


__all__ = [
    "AccessLog",
    "APP_NAME",
    "REQUEST_ID",
    "current_request_id",
    "health_extra",
    "logger",
    "setup_logging",
]
