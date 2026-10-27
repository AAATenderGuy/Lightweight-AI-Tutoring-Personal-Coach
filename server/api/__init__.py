"""HTTP API 汇总。"""
from __future__ import annotations

from fastapi import APIRouter

from .. import db, store
from ..config import APP_NAME, APP_SUBTITLE, VERSION
from ..config import settings as app_settings
from ..observability import health_extra
from . import chat, classroom, events, materials, ocr, progress, quiz, student, teacher
from . import settings as settings_api

api_router = APIRouter(prefix="/api")

api_router.include_router(chat.router)
api_router.include_router(classroom.router)
api_router.include_router(materials.router)
api_router.include_router(ocr.router)
api_router.include_router(quiz.router)
api_router.include_router(progress.router)
api_router.include_router(settings_api.router)
api_router.include_router(teacher.router)
api_router.include_router(student.router)
api_router.include_router(events.router)


@api_router.get("/health")
async def health() -> dict:
    payload = {
        "ok": True,
        "name": APP_NAME,
        "subtitle": APP_SUBTITLE,
        "version": VERSION,
        "mode": "demo" if app_settings.is_demo else "live",
        "model": app_settings.model,
        "materials": len(store.list_items("materials")),
        "lessons": len(store.list_items("lessons")),
        "classes": len(store.list_items("classes")),
        "teachers": len(store.list_items("teachers")),
        "store": store.backend(),
    }
    if store.backend() == "sqlite":
        payload.update(db.info())
    payload.update(health_extra())
    return payload
