"""课堂答疑：把当前页上下文与多轮对话拼成教师提示词。"""
from __future__ import annotations

from .. import prompts


def discuss_messages(
    *,
    lesson: dict,
    scene: dict,
    question: str,
    history: list[dict] | None = None,
) -> list[dict]:
    topic = lesson.get("title") or lesson.get("topic") or ""
    bullets = "；".join(scene.get("bullets") or [])
    notes = scene.get("notes") or scene.get("prompt") or ""
    context = (
        f"课堂主题：{topic}\n"
        f"当前页面：{scene.get('title', '')}（{scene.get('type', '')}）\n"
        f"页面要点：{bullets or '（无）'}\n"
        f"讲解词：{notes or '（无）'}"
    )
    system = prompts.TEACHER_SYSTEM + "\n\n### 当前课堂上下文\n" + context
    messages: list[dict] = [{"role": "system", "content": system}]

    used_chars = 0
    for item in reversed((history or [])[-10:]):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()[:2000]
        if not content:
            continue
        if used_chars + len(content) > 6000:
            break
        role = "assistant" if item.get("role") in ("assistant", "teacher") else "user"
        messages.append({"role": role, "content": content})
        used_chars += len(content)
    messages[1:] = list(reversed(messages[1:]))

    messages.append({"role": "user", "content": question})
    return messages
