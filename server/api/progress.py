from __future__ import annotations

from fastapi import APIRouter, Request

from ..services import mastery
from .teacher import current_teacher

router = APIRouter(tags=["progress"])


@router.get("/progress")
async def get_progress() -> dict:
    return mastery.progress_payload()


@router.delete("/progress")
async def reset_progress(request: Request) -> dict:
    # 清空进度是不可逆的全局操作，要求教师身份
    current_teacher(request)
    mastery.reset_progress()
    return {"ok": True}
