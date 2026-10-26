"""小组角色配置：默认值在 default_agents.json，运行时可编辑并保存在 data/agents.json。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import store

DEFAULTS_PATH = Path(__file__).resolve().parent.parent / "default_agents.json"
MIN_AGENTS = 2
MAX_AGENTS = 6
MAX_INSTRUCTION = 400


class AgentConfigError(ValueError):
    """可以直接展示给用户的小组配置错误。"""


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _normalise(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise AgentConfigError("小组配置格式不正确。")
    raw_agents = payload.get("agents")
    if not isinstance(raw_agents, list):
        raise AgentConfigError("小组配置缺少 agents 列表。")

    agents: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_agents, 1):
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 20)
        role = _text(item.get("role"), 20)
        instruction = _text(item.get("instruction"), MAX_INSTRUCTION)
        if not name or not role or not instruction:
            continue
        agent_id = _text(item.get("id"), 40) or f"agent_{index}"
        agent_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", agent_id).strip("-") or f"agent_{index}"
        while agent_id in seen:
            agent_id = f"{agent_id}_2"
        seen.add(agent_id)
        agents.append({
            "id": agent_id,
            "name": name,
            "role": role,
            "instruction": instruction,
        })

    if not (MIN_AGENTS <= len(agents) <= MAX_AGENTS):
        raise AgentConfigError(f"小组需要 {MIN_AGENTS}-{MAX_AGENTS} 位同学，当前为 {len(agents)} 位。")

    try:
        max_speakers = int(payload.get("max_speakers", 2))
    except (TypeError, ValueError):
        max_speakers = 2
    max_speakers = max(1, min(3, max_speakers, len(agents)))
    return {"version": 1, "max_speakers": max_speakers, "agents": agents}


def _defaults() -> dict:
    try:
        payload = json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AgentConfigError("默认小组配置缺失或损坏，请检查 server/default_agents.json。") from exc
    return _normalise(payload)


def load() -> dict:
    stored = store.read_shared("agents", None)
    if isinstance(stored, dict):
        try:
            return _normalise(stored)
        except AgentConfigError:
            pass
    config = _defaults()
    store.write_shared("agents", config)
    return config


def save(payload: dict) -> dict:
    config = _normalise(payload)
    store.write_shared("agents", config)
    return config


def reset() -> dict:
    config = _defaults()
    store.write_shared("agents", config)
    return config


def public_agent(agent: dict) -> dict:
    """给讨论界面/SSE 的角色信息，不含提示词。"""
    return {
        "id": agent.get("id"),
        "name": agent.get("name"),
        "role": agent.get("role"),
    }
