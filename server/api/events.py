"""实时事件流（SSE）：学生端、教师端各一条长连接，外加在线名单快照。

协议：每个事件都是一行 `data: {json}`，`type` 说明「什么变了」，
客户端据此调用自己原有的接口重新拉取。另有 `: ping` 心跳（15 秒）用于
保活和感知断线；`ready` 是首帧，告诉客户端订阅了哪些主题。

为什么用 SSE 而不是 WebSocket：本项目只有服务端 -> 客户端这一个方向，
浏览器自带 EventSource 语义、FastAPI 原生 StreamingResponse 即可实现，
不需要给 requirements.txt 增加 websockets 依赖。
"""
from __future__ import annotations

import asyncio
import json
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import store
from ..services import auth, identity
from ..services.events import bus, presence
from .teacher import current_teacher

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15.0
TOKEN_CHECK_EVERY = 4  # 每 4 次心跳（约 60 秒）复核一次教师登录态


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def _stream(request: Request, topics: list[str], hello: dict,
            on_open: Callable[[], None] | None = None,
            on_close: Callable[[], None] | None = None,
            validate: Callable[[], bool] | None = None) -> StreamingResponse:
    """把一个（或一组）主题包装成 SSE 响应。

    订阅发生在生成器内部：如果客户端连上就立刻断开、生成器根本没启动，
    就不会留下没人清理的订阅。
    """

    async def generator():
        queue = bus.subscribe(topics)
        if on_open:
            on_open()
        try:
            yield _sse({"type": "ready", "topics": topics, **hello})
            beats = 0
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    beats += 1
                    if validate and beats % TOKEN_CHECK_EVERY == 0 and not validate():
                        yield _sse({"type": "unauthorized", "reason": "登录已过期"})
                        break
                    yield ": ping\n\n"
                    continue
                yield _sse(event)
        finally:
            if on_close:
                on_close()
            bus.unsubscribe(queue, topics)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- 学生端
@router.get("/student/stream")
async def student_stream(request: Request, student_id: str, token: str = "") -> StreamingResponse:
    # 优先用请求头，避免令牌出现在 URL 与访问日志里；查询参数只作兼容。
    token = token or request.headers.get("x-student-token", "")
    if not identity.verify(student_id, token):
        raise HTTPException(status_code=401, detail="学生身份已失效，请重新加入班级。")
    student = store.load_item("students", student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生档案不存在，请重新加入班级。")
    klass = store.load_item("classes", student.get("class_id") or "")
    if not klass:
        raise HTTPException(status_code=404, detail="班级已被删除，请向老师要新的邀请码。")

    class_id = klass["id"]
    teacher_id = klass.get("teacher_id") or ""
    name = student.get("name")

    def announce(event_type: str) -> None:
        if teacher_id:
            bus.publish(
                f"teacher:{teacher_id}", event_type,
                class_id=class_id, student_id=student_id, name=name,
            )

    def on_open() -> None:
        if presence.enter(class_id, student_id):
            announce("student_online")

    def on_close() -> None:
        if presence.leave(class_id, student_id):
            announce("student_offline")

    return _stream(
        request,
        [f"student:{student_id}", f"class:{class_id}"],
        {"student_id": student_id, "class_id": class_id, "name": name},
        on_open=on_open,
        on_close=on_close,
    )


# ---------------------------------------------------------------- 教师端
@router.get("/teacher/stream")
async def teacher_stream(request: Request) -> StreamingResponse:
    teacher = current_teacher(request)
    token = _bearer(request)

    def still_valid() -> bool:
        return auth.resolve(token) is not None

    return _stream(
        request,
        [f"teacher:{teacher['id']}"],
        {"teacher_id": teacher["id"]},
        validate=still_valid,
    )


@router.get("/teacher/presence")
async def presence_snapshot(request: Request) -> dict:
    """在线名单快照：老师刚打开页面时，先拿到已有连接，再靠事件增量维护。"""
    teacher = current_teacher(request)
    owned = [item for item in store.list_items("classes") if item.get("teacher_id") == teacher["id"]]
    return {"items": {item["id"]: presence.online(item["id"]) for item in owned}}
