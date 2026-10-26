"""HTTP API 汇总。"""
from __future__ import annotations

from fastapi import APIRouter

from .. import store
from ..config import APP_NAME, APP_SUBTITLE, VERSION, settings as app_settings
from . import chat, classroom, materials, progress, quiz
from . import settings as settings_api
from . import student, teacher
from . import events

api_router = APIRouter(prefix="/api")

api_router.include_router(chat.router)
api_router.include_router(classroom.router)
api_router.include_router(materials.router)
api_router.include_router(quiz.router)
api_router.include_router(progress.router)
api_router.include_router(settings_api.router)
api_router.include_router(teacher.router)
api_router.include_router(student.router)
api_router.include_router(events.router)


@api_router.get("/health")
async def health() -> dict:
    return {
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
    }
