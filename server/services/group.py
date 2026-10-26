"""小组互动：可配置的多智能体讨论编排（主持人 + 角色 Agent）。"""
from __future__ import annotations

from .. import prompts
from ..llm import LLMError, llm
from . import agents as agent_service


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def transcript(history: list[dict]) -> str:
    lines: list[str] = []
    for item in history[-10:]:
        content = _text(item.get("content"), 500)
        if not content:
            continue
        speaker = "学生" if item.get("role") == "user" else (_text(item.get("agent"), 20) or "同学")
        lines.append(f"{speaker}：{content}")
    return "\n".join(lines)


def _rotate(agents: list[dict], history: list[dict], count: int) -> list[dict]:
    if not agents:
        return []
    start = len(history) % len(agents)
    count = max(1, min(count, len(agents)))
    return [dict(agents[(start + index) % len(agents)]) for index in range(count)]


async def plan_turn(
    *,
    config: dict,
    lesson: dict,
    scene: dict,
    message: str,
    history: list[dict],
    mode: str,
) -> tuple[list[dict], str]:
    """主持人决定本轮发言人；无模型/Demo 模式回退为按历史轮换。"""
    agents = config["agents"]
    max_speakers = int(config.get("max_speakers", 2))

    if llm.demo or len(agents) <= max_speakers:
        return _rotate(agents, history, max_speakers), "轮换发言"

    messages = [
        {"role": "system", "content": prompts.GROUP_PLANNER_SYSTEM},
        {"role": "user", "content": prompts.group_planner_prompt(
            agents=agents,
            lesson=lesson,
            scene=scene,
            message=message,
            transcript=transcript(history),
            mode=mode,
            max_speakers=max_speakers,
        )},
    ]
    try:
        raw = await llm.json(
            messages,
            temperature=0.2,
            max_tokens=500,
            task="orchestrator",
            context={
                "topic": lesson.get("title") or lesson.get("topic"),
                "scene": scene.get("title"),
                "message": message,
                "mode": mode,
            },
        )
    except LLMError:
        return _rotate(agents, history, max_speakers), "主持人暂时不可用，按轮换发言"

    by_id = {agent["id"]: agent for agent in agents}
    selected: list[dict] = []
    for item in raw.get("speakers") or []:
        if not isinstance(item, dict):
            continue
        agent = by_id.get(_text(item.get("id"), 40))
        if not agent or any(picked["id"] == agent["id"] for picked in selected):
            continue
        picked = dict(agent)
        picked["focus"] = _text(item.get("focus"), 80)
        selected.append(picked)
        if len(selected) >= max_speakers:
            break

    if len(selected) < min(2, max_speakers):
        return _rotate(agents, history, max_speakers), "主持人安排不完整，按轮换发言"
    reason = _text(raw.get("reason"), 120) or "主持人已安排本轮发言"
    return selected, reason


def build_messages(
    *,
    agent: dict,
    lesson: dict,
    scene: dict,
    message: str,
    history: list[dict],
    mode: str,
) -> list[dict]:
    topic = lesson.get("title") or lesson.get("topic") or ""
    bullets = "；".join(scene.get("bullets") or [])
    notes = scene.get("notes") or scene.get("prompt") or ""
    page_context = (
        f"课堂主题：{topic}\n"
        f"当前页面：{scene.get('title', '')}\n"
        f"页面要点：{bullets or '（无）'}\n"
        f"讲解词：{notes or '（无）'}"
    )
    focus = _text(agent.get("focus"), 80)
    system = (
        prompts.GROUP_SYSTEM
        + f"\n\n### 你的角色\n你是「{agent['name']}」，小组里的{agent['role']}。\n"
        + agent["instruction"]
        + "\n\n### 当前课堂上下文\n"
        + page_context
    )
    if focus:
        system += f"\n\n### 本轮主持人安排\n请重点处理：{focus}"

    history_text = transcript(history)
    if mode == "auto":
        topic_line = _text(scene.get("prompt") or scene.get("title") or "当前页", 200)
        task = (
            f"讨论题：{topic_line}\n"
            f"请以「{agent['name']}」的身份，先和小组同学展开讨论。"
            "直接给出你的观点或追问，可以点名回应其他同学，60-120 字。"
        )
    else:
        task = (
            f"学生刚刚说：{message}\n"
            f"请以「{agent['name']}」的身份回应学生，并可以接着其他同学的话往下说。"
            "只推进一个点，60-120 字。"
        )

    user = (f"【小组讨论记录】\n{history_text}\n\n" if history_text else "") + f"【本轮任务】\n{task}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def public_agents(config: dict) -> list[dict]:
    return [agent_service.public_agent(agent) for agent in config["agents"]]
