"""导师对话的消息拼装。"""
from __future__ import annotations

from .. import prompts


def build_messages(
    *,
    message: str,
    mode: str,
    history: list[dict],
    sources: list[dict],
) -> list[dict]:
    system = prompts.tutor_system(mode)
    system += "\n\n### 参考资料\n" + prompts.context_block(sources)
    messages: list[dict] = [{"role": "system", "content": system}]

    # 只保留最近若干轮，并限制总字符数，避免长对话撑爆上下文。
    recent: list[dict] = []
    used_chars = 0
    for item in reversed(history[-12:]):
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()[:4000]
        if not content:
            continue
        if used_chars + len(content) > 10000:
            break
        recent.append({"role": role, "content": content})
        used_chars += len(content)
    messages.extend(reversed(recent))

    messages.append({"role": "user", "content": message[:8000]})
    return messages
