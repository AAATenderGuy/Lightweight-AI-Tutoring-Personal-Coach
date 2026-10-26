from __future__ import annotations

from fastapi import APIRouter

from .. import store
from ..services import mastery

router = APIRouter(tags=["progress"])


@router.get("/progress")
async def get_progress() -> dict:
    return mastery.progress_payload()


@router.delete("/progress")
async def reset_progress() -> dict:
    store.write_shared("progress", {"topics": {}, "events": []})
    return {"ok": True}
