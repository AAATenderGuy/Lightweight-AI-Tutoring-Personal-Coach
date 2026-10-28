"""Edu 服务入口：一个进程同时提供 API 和已构建的前端。"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import api_router
from .config import APP_NAME, APP_SUBTITLE, DATA_DIR, ROOT, VERSION, WEB_DIST
from .llm import LLMError
from .observability import AccessLog, logger, setup_logging
from .services import retrieval

setup_logging()
log = logger("edu.main")

PLACEHOLDER = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>Edu · 前端尚未构建</title>
<style>
  body{margin:0;background:#fff;color:#161616;font:16px/1.7 system-ui,"Segoe UI","Microsoft YaHei",sans-serif}
  main{max-width:640px;margin:12vh auto;padding:0 24px}
  h1{font-size:22px;font-weight:600;margin:0 0 8px}
  p{color:#555;margin:6px 0}
  code{background:#f4f4f2;border:1px solid #e4e4e2;border-radius:4px;padding:2px 6px;font-size:14px}
  pre{background:#fafaf9;border:1px solid #e4e4e2;border-radius:6px;padding:16px;overflow:auto;font-size:14px}
</style></head><body><main>
  <h1>前端还没有构建</h1>
  <p>后端 API 已经在运行。要显示界面，请在 <code>edu/web</code> 目录执行一次构建：</p>
  <pre>cd web
npm install
npm run build</pre>
  <p>然后刷新本页；或者直接运行 <code>start.bat</code>，它会自动完成构建。</p>
</main></body></html>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting %s v%s data_dir=%s", APP_NAME, VERSION, DATA_DIR)
    print(f"\n  {APP_NAME} · {APP_SUBTITLE}  v{VERSION}")
    print(f"  数据目录：{DATA_DIR}")
    retrieval.warmup()  # 后台预载向量模型，不阻塞启动
    yield
    log.info("stopped %s v%s", APP_NAME, VERSION)


app = FastAPI(title=f"{APP_NAME} API", version=VERSION, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
# 注意顺序：后加的中间件先执行，所以 AccessLog 放在 CORS 之后注册，
# 让 CORS 仍然最先给响应加上跨域头。
app.add_middleware(AccessLog)


@app.exception_handler(LLMError)
async def handle_llm_error(_request: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.get("/eval", response_class=HTMLResponse, include_in_schema=False)
async def eval_report() -> str:
    """检索评测报告：`scripts/eval_retrieval.py` 跑完会覆盖 data/eval/latest.html。"""
    for path in (DATA_DIR / "eval" / "latest.html", ROOT / "data" / "eval" / "latest.html"):
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="ignore")
    return (
        "<!doctype html><meta charset='utf-8'><title>检索评测</title>"
        "<body style=\"font:16px/1.8 system-ui,'Microsoft YaHei',sans-serif;max-width:720px;margin:60px auto\">"
        "<h1>检索评测报告</h1>"
        "<p>还没有跑过评测。在仓库根目录执行 <code>python scripts/eval_retrieval.py</code>，"
        "完成后刷新本页即可看到 BM25 / 混合检索 / 重排的 ablation 表。</p></body>"
    )


def _mount_frontend() -> None:
    index = WEB_DIST / "index.html"
    if not index.is_file():
        @app.get("/", response_class=HTMLResponse)
        async def placeholder() -> str:
            return PLACEHOLDER
        return

    no_cache = {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    }
    assets = WEB_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/", include_in_schema=False)
    async def index_page() -> FileResponse:
        return FileResponse(index, headers=no_cache)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        candidate = (WEB_DIST / path).resolve()
        if candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers=no_cache)


_mount_frontend()


def _free_port(host: str, start: int) -> int:
    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((bind_host, port))
            except OSError:
                continue
            return port
    return start


def main() -> None:
    parser = argparse.ArgumentParser(description="Edu 轻量级 AI 教学服务")
    parser.add_argument("--host", default=os.environ.get("EDU_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("EDU_PORT", "0")))
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码变更后自动重载")
    args = parser.parse_args()

    port = args.port if args.port else _free_port(args.host, 8000)
    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{display_host}:{port}"

    if not args.no_browser and os.environ.get("EDU_OPEN_BROWSER", "1") != "0":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"\n  ➜ 打开浏览器访问：{url}\n")

    if args.reload:
        uvicorn.run("server.main:app", host=args.host, port=port, reload=True, reload_dirs=["server"],
                    access_log=False)
    else:
        uvicorn.run(app, host=args.host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    main()
