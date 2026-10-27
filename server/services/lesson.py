"""课堂生成与规范化。"""
from __future__ import annotations

import time
from typing import Any

from .. import prompts, rag, store
from ..llm import LLMError, llm

SCENE_TYPES = {"cover", "content", "discussion", "quiz", "summary"}


def _text(value: Any, limit: int = 400) -> str:
    return str(value or "").strip()[:limit]


def _bullets(value: Any, limit: int = 6) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = _text(item, 90)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def normalise_lesson(raw: dict, *, topic: str, level: str = "beginner") -> dict:
    title = _text(raw.get("title"), 60) or f"{topic}：迷你课堂"
    scenes_in = raw.get("scenes")
    if not isinstance(scenes_in, list) or not scenes_in:
        raise LLMError("课堂结构为空，请重试。")

    scenes: list[dict] = []
    for item in scenes_in:
        if not isinstance(item, dict):
            continue
        scene_type = str(item.get("type") or "content").strip().lower()
        if scene_type not in SCENE_TYPES:
            scene_type = "content"
        scene: dict[str, Any] = {
            "id": f"s{len(scenes) + 1}",
            "type": scene_type,
            "title": _text(item.get("title"), 60) or ("本课回顾" if scene_type == "summary" else "未命名小节"),
        }
        if scene_type == "cover":
            scene["subtitle"] = _text(item.get("subtitle"), 80)
        scene["bullets"] = _bullets(item.get("bullets"))
        if scene_type in {"content", "discussion"}:
            scene["notes"] = _text(item.get("notes"), 600)
            scene["prompt"] = _text(item.get("prompt"), 200)
        if scene_type == "discussion":
            scene["hints"] = _bullets(item.get("hints"), 3)
        if scene_type == "quiz":
            questions = []
            for question in item.get("questions") or []:
                if not isinstance(question, dict):
                    continue
                text = _text(question.get("question"), 300)
                if not text:
                    continue
                entry: dict[str, Any] = {
                    "type": "single" if question.get("options") else "short",
                    "question": text,
                    "explanation": _text(question.get("explanation"), 300),
                    "knowledge_point": _text(question.get("knowledge_point"), 60) or f"{topic}·随堂检测",
                }
                options = _bullets(question.get("options"), 6)
                if options:
                    entry["options"] = options
                    try:
                        answer_index = int(question.get("answer_index", 0))
                    except (TypeError, ValueError):
                        answer_index = 0
                    entry["answer_index"] = max(0, min(len(options) - 1, answer_index))
                else:
                    entry["answer"] = _text(question.get("answer"), 300)
                questions.append(entry)
                if len(questions) >= 6:
                    break
            scene["questions"] = questions
        scenes.append(scene)

    if not scenes:
        raise LLMError("课堂没有可用的页面，请重试。")
    if scenes[0]["type"] != "cover":
        scenes.insert(0, {
            "id": "s0",
            "type": "cover",
            "title": title,
            "subtitle": f"{level} · 迷你课堂",
            "bullets": [],
        })
    for index, scene in enumerate(scenes, 1):
        scene["id"] = f"s{index}"

    objectives = _bullets(raw.get("objectives"), 5)
    return {
        "id": store.new_id("lsn_"),
        "title": title,
        "summary": _text(raw.get("summary"), 200),
        "level": str(raw.get("level") or level),
        "topic": topic,
        "objectives": objectives,
        "scenes": scenes,
        "created_at": time.time(),
        "scene_count": len(scenes),
    }


async def generate(*, topic: str, level: str, duration: int, material_ids: list[str], scene_count: int) -> tuple[dict, list[dict]]:
    sources = rag.search(topic, material_ids or None, top_k=6)
    messages = [
        {"role": "system", "content": prompts.LESSON_SYSTEM},
        {"role": "user", "content": prompts.lesson_prompt(
            topic=topic, level=level, duration=duration, sources=sources, scene_count=scene_count
        )},
    ]
    raw = await llm.json(
        messages,
        temperature=0.7,
        max_tokens=3200,
        task="lesson",
        context={"topic": topic, "level": level, "duration": duration, "sources": sources},
    )
    lesson = normalise_lesson(raw, topic=topic, level=level)
    store.save_item("lessons", lesson)
    return lesson, sources


def list_lessons() -> list[dict]:
    items = store.list_items("lessons")
    return [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "summary": item.get("summary"),
            "level": item.get("level"),
            "scene_count": len(item.get("scenes") or []),
            "created_at": item.get("created_at"),
        }
        for item in items
    ]
