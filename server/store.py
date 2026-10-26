"""文件型存储：整个项目不需要数据库，所有数据都是 data/ 下的 JSON。

读路径带 mtime 缓存：JSON 全量读盘是当前架构的主要瓶颈（尤其实时化之后，
一条事件会触发多次 list_items），文件没变时直接返回内存副本，写操作同步刷新缓存。
缓存对调用方不可见：read_json 返回深拷贝，调用方可以放心地改。
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import DATA_DIR

_LOCK = threading.RLock()
_CACHE: dict[Path, tuple[int, int, Any]] = {}

COLLECTIONS = (
    "materials", "lessons", "quizzes", "chats",
    "teachers", "classes", "students", "assignments", "submissions",
)
for _name in COLLECTIONS:
    (DATA_DIR / _name).mkdir(parents=True, exist_ok=True)
(DATA_DIR / "uploads").mkdir(parents=True, exist_ok=True)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _path(kind: str, item_id: str) -> Path:
    if kind not in COLLECTIONS:
        raise ValueError(f"unknown collection: {kind}")
    if not item_id or any(ch in item_id for ch in "\\/.."):
        raise ValueError("invalid id")
    return DATA_DIR / kind / f"{item_id}.json"


def _fresh(stat: os.stat_result) -> tuple[int, int]:
    return stat.st_mtime_ns, stat.st_size


def read_json(path: Path, default: Any) -> Any:
    with _LOCK:
        try:
            stat = path.stat()
        except OSError:
            _CACHE.pop(path, None)
            return default
        cached = _CACHE.get(path)
        stamp = _fresh(stat)
        if cached and cached[0] == stamp[0] and cached[1] == stamp[1]:
            return copy.deepcopy(cached[2])
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default
        _CACHE[path] = (stamp[0], stamp[1], payload)
        return copy.deepcopy(payload)


def write_json(path: Path, payload: Any) -> None:
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        try:
            _CACHE[path] = (*_fresh(path.stat()), copy.deepcopy(payload))
        except OSError:
            _CACHE.pop(path, None)


def save_item(kind: str, item: dict) -> dict:
    item.setdefault("id", new_id())
    item.setdefault("created_at", time.time())
    write_json(_path(kind, item["id"]), item)
    return item


def load_item(kind: str, item_id: str) -> dict | None:
    payload = read_json(_path(kind, item_id), None)
    return payload if isinstance(payload, dict) else None


def list_items(kind: str) -> list[dict]:
    folder = DATA_DIR / kind
    items: list[dict] = []
    for entry in folder.glob("*.json"):
        payload = read_json(entry, None)
        if isinstance(payload, dict):
            items.append(payload)
    items.sort(key=lambda it: it.get("created_at", 0), reverse=True)
    return items


def delete_item(kind: str, item_id: str) -> bool:
    path = _path(kind, item_id)
    with _LOCK:
        _CACHE.pop(path, None)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False


def read_shared(name: str, default: Any) -> Any:
    return read_json(DATA_DIR / f"{name}.json", default)


def write_shared(name: str, payload: Any) -> None:
    write_json(DATA_DIR / f"{name}.json", payload)
