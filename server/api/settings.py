from __future__ import annotations

import time

from fastapi import APIRouter

from ..config import settings as app_settings
from ..llm import LLMError, llm
from ..schemas import SettingsPayload

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings() -> dict:
    return app_settings.snapshot()


@router.put("/settings")
async def update_settings(payload: SettingsPayload) -> dict:
    return app_settings.update(
        base_url=payload.base_url,
        model=payload.model,
        api_key=payload.api_key,
        temperature=payload.temperature,
    )


@router.post("/settings/test")
async def test_connection() -> dict:
    if app_settings.is_demo:
        return {"ok": False, "demo": True, "message": "尚未配置 API Key，当前为离线演示模式。"}
    started = time.perf_counter()
    try:
        reply = await llm.complete(
            [{"role": "user", "content": "请只回复：OK"}],
            temperature=0,
            max_tokens=16,
            task="chat",
            context={},
        )
    except LLMError as exc:
        return {"ok": False, "demo": False, "message": str(exc)}
    elapsed = time.perf_counter() - started
    return {
        "ok": True,
        "demo": False,
        "message": f"连接成功：{app_settings.model} · {elapsed:.1f}s",
        "reply": reply.strip()[:60],
    }
