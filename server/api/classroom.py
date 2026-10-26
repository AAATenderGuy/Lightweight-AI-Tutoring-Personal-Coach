from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from .. import rag, store
from ..llm import LLMError, llm
from ..schemas import DiscussRequest, GroupAgentsPayload, GroupDiscussRequest, LessonRequest
from ..services import (
    agents as agent_service,
    discussion,
    export_pptx,
    group as group_service,
    lesson as lesson_service,
    mastery,
    quiz as quiz_service,
)
from .limits import rate_limit
from .sse import encode, stream_response

router = APIRouter(tags=["classroom"])


@router.post("/classroom/generate", dependencies=[rate_limit("classroom")])
async def generate_lesson(payload: LessonRequest):
    async def events():
        topic = payload.topic.strip()
        yield encode({"type": "status", "text": "正在检索相关资料…"})
        try:
            await asyncio.sleep(0)
            lesson, sources = await lesson_service.generate(
                topic=topic,
                level=payload.level,
                duration=payload.duration,
                material_ids=payload.material_ids,
                scene_count=payload.scene_count,
            )
        except LLMError as exc:
            yield encode({"type": "error", "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            yield encode({"type": "error", "message": f"课堂生成失败：{exc}"})
            return
        mastery.record_lesson(lesson)
        yield encode({"type": "status", "text": "正在整理页面…"})
        yield encode({
            "type": "lesson",
            "lesson": lesson,
            "demo": llm.demo,
            "sources": [
                {"title": source.get("title"), "preview": rag.preview(source.get("text", ""), 140)}
                for source in sources
            ],
        })
        yield encode({"type": "done"})

    return stream_response(events())


@router.get("/classroom/lessons")
async def list_lessons() -> dict:
    return {"items": lesson_service.list_lessons()}


@router.get("/classroom/lessons/{lesson_id}")
async def get_lesson(lesson_id: str) -> dict:
    lesson = store.load_item("lessons", lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="课堂不存在或已删除。")
    return {"lesson": lesson}


@router.delete("/classroom/lessons/{lesson_id}")
async def delete_lesson(lesson_id: str) -> dict:
    if not store.delete_item("lessons", lesson_id):
        raise HTTPException(status_code=404, detail="课堂不存在或已删除。")
    return {"ok": True}


@router.post("/classroom/lessons/{lesson_id}/quiz", dependencies=[rate_limit("classroom")])
async def lesson_quiz(lesson_id: str) -> dict:
    lesson = store.load_item("lessons", lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="课堂不存在或已删除。")
    try:
        return {"quiz": quiz_service.quiz_from_lesson(lesson)}
    except LLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/classroom/lessons/{lesson_id}/export/pptx")
async def export_lesson_pptx(lesson_id: str):
    lesson = store.load_item("lessons", lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="课堂不存在或已删除。")
    try:
        content = export_pptx.build(lesson)
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="导出 PPT 需要 python-pptx，请运行：pip install -r requirements.txt",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"导出 PPT 失败：{exc}") from exc

    filename = f"{lesson.get('title') or '课堂'}.pptx"
    filename = re.sub(r'[\\/:*?"<>|]+', "-", filename)[:100]
    disposition = f"attachment; filename=\"lesson.pptx\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(content)),
            "Cache-Control": "no-store",
        },
    )


@router.get("/classroom/group/agents")
async def group_agents() -> dict:
    return agent_service.load()


@router.put("/classroom/group/agents")
async def save_group_agents(payload: GroupAgentsPayload) -> dict:
    try:
        return agent_service.save(payload.model_dump())
    except agent_service.AgentConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/classroom/group/agents/reset")
async def reset_group_agents() -> dict:
    return agent_service.reset()


@router.post("/classroom/group-discuss", dependencies=[rate_limit("classroom")])
async def group_discuss(payload: GroupDiscussRequest):
    lesson = store.load_item("lessons", payload.lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="课堂不存在或已删除。")
    scene = next((item for item in lesson.get("scenes", []) if item.get("id") == payload.scene_id), None)
    if not scene:
        raise HTTPException(status_code=404, detail="页面不存在。")
    if payload.mode == "chat" and not payload.message.strip():
        raise HTTPException(status_code=400, detail="先说点什么，再让同学回应你。")

    history = [item.model_dump() for item in payload.history]
    config = agent_service.load()

    async def events():
        try:
            speakers, reason = await group_service.plan_turn(
                config=config,
                lesson=lesson,
                scene=scene,
                message=payload.message,
                history=history,
                mode=payload.mode,
            )
            yield encode({
                "type": "meta",
                "agents": group_service.public_agents(config),
                "speakers": [agent_service.public_agent(agent) for agent in speakers],
                "reason": reason,
                "mode": payload.mode,
                "demo": llm.demo,
            })
            for agent in speakers:
                public = agent_service.public_agent(agent)
                yield encode({"type": "agent_start", "agent": public})
                messages = group_service.build_messages(
                    agent=agent,
                    lesson=lesson,
                    scene=scene,
                    message=payload.message,
                    history=history,
                    mode=payload.mode,
                )
                parts: list[str] = []
                async for piece in llm.stream(
                    messages,
                    temperature=0.8,
                    max_tokens=450,
                    task="group",
                    context={
                        "agent": agent,
                        "question": payload.message or scene.get("prompt") or scene.get("title", ""),
                        "title": scene.get("title", ""),
                        "mode": payload.mode,
                        "history": history,
                    },
                ):
                    parts.append(piece)
                    yield encode({"type": "delta", "agent": public, "text": piece})
                content = "".join(parts).strip()
                if not content:
                    yield encode({
                        "type": "error",
                        "message": f"{agent['name']} 暂时没有发言，请再试一次。",
                        "agent": public,
                    })
                    return
                history.append({"role": "assistant", "agent": agent["name"], "content": content})
                yield encode({"type": "agent_end", "agent": public})
            yield encode({"type": "done"})
        except LLMError as exc:
            yield encode({"type": "error", "message": str(exc)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            yield encode({"type": "error", "message": f"小组讨论异常：{exc}"})

    return stream_response(events())


@router.post("/classroom/discuss", dependencies=[rate_limit("classroom")])
async def discuss(payload: DiscussRequest):
    lesson = store.load_item("lessons", payload.lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="课堂不存在或已删除。")
    scene = next((item for item in lesson.get("scenes", []) if item.get("id") == payload.scene_id), None)
    if not scene:
        raise HTTPException(status_code=404, detail="页面不存在。")

    history = [item.model_dump() for item in payload.history]

    async def events():
        try:
            messages = discussion.discuss_messages(
                lesson=lesson,
                scene=scene,
                question=payload.question,
                history=history,
            )
            yield encode({"type": "meta", "role": "teacher", "demo": llm.demo})
            async for piece in llm.stream(
                messages,
                temperature=0.75,
                max_tokens=600,
                task="teacher",
                context={
                    "topic": lesson.get("title") or lesson.get("topic"),
                    "title": scene.get("title", ""),
                    "question": payload.question,
                    "history": history,
                },
            ):
                yield encode({"type": "delta", "text": piece})
            yield encode({"type": "done"})
        except LLMError as exc:
            yield encode({"type": "error", "message": str(exc)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            yield encode({"type": "error", "message": f"课堂答疑异常：{exc}"})

    return stream_response(events())
