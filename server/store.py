"""存储层门面：默认走 SQLite（P2 · S4），``EDU_STORE=json`` 可退回原来的 JSON 文件。

两套后端对外接口完全一致，业务代码只认 ``save_item / load_item / list_items /
delete_item / read_shared / write_shared``，所以切换后端不需要改任何调用点。

JSON 后端读路径带 mtime 缓存：JSON 全量读盘是旧架构的主要瓶颈（尤其实时化之后，
一条事件会触发多次 list_items）。缓存对调用方不可见：read_json 返回深拷贝。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import db
from .config import DATA_DIR

_LOCK = threading.RLock()
_CACHE: dict[Path, tuple[int, int, Any]] = {}

COLLECTIONS = (
    "materials", "lessons", "quizzes", "chats",
    "teachers", "classes", "students", "assignments", "submissions", "groups",
    "questions", "learning_events",
)
SHARED_NAMES = ("progress", "sessions", "agents")

for _name in COLLECTIONS:
    (DATA_DIR / _name).mkdir(parents=True, exist_ok=True)
(DATA_DIR / "uploads").mkdir(parents=True, exist_ok=True)

_BACKEND = (os.environ.get("EDU_STORE") or "sqlite").strip().lower()
if _BACKEND not in {"json", "sqlite"}:
    logging.getLogger("edu.store").warning("未知的 EDU_STORE=%r，按 sqlite 处理", _BACKEND)
    _BACKEND = "sqlite"

_log = logging.getLogger("edu.store")


def backend() -> str:
    """当前使用的存储后端：``json`` 或 ``sqlite``。"""
    return _BACKEND


def _guard(kind: str, item_id: str) -> None:
    if kind not in COLLECTIONS:
        raise ValueError(f"unknown collection: {kind}")
    if not item_id or any(ch in item_id for ch in "\\/.."):
        raise ValueError("invalid id")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _path(kind: str, item_id: str) -> Path:
    _guard(kind, item_id)
    return DATA_DIR / kind / f"{item_id}.json"


# ---------------------------------------------------------------- JSON 后端底层
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


# ---------------------------------------------------------------- 统一对外接口
def save_item(kind: str, item: dict) -> dict:
    item.setdefault("id", new_id())
    item.setdefault("created_at", time.time())
    _guard(kind, item["id"])
    if _BACKEND == "sqlite":
        db.save_item(kind, item)
    else:
        write_json(_path(kind, item["id"]), item)
    return item


def load_item(kind: str, item_id: str) -> dict | None:
    _guard(kind, item_id)
    if _BACKEND == "sqlite":
        return db.load_item(kind, item_id)
    payload = read_json(_path(kind, item_id), None)
    return payload if isinstance(payload, dict) else None


def list_items(kind: str) -> list[dict]:
    if kind not in COLLECTIONS:
        raise ValueError(f"unknown collection: {kind}")
    if _BACKEND == "sqlite":
        return db.list_items(kind)
    folder = DATA_DIR / kind
    items: list[dict] = []
    for entry in folder.glob("*.json"):
        payload = read_json(entry, None)
        if isinstance(payload, dict):
            items.append(payload)
    items.sort(key=lambda it: it.get("created_at", 0), reverse=True)
    return items


def delete_item(kind: str, item_id: str) -> bool:
    _guard(kind, item_id)
    if _BACKEND == "sqlite":
        return db.delete_item(kind, item_id)
    path = _path(kind, item_id)
    with _LOCK:
        _CACHE.pop(path, None)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False


def read_shared(name: str, default: Any) -> Any:
    if _BACKEND == "sqlite":
        return db.read_shared(name, default)
    return read_json(DATA_DIR / f"{name}.json", default)


def write_shared(name: str, payload: Any) -> None:
    if _BACKEND == "sqlite":
        db.write_shared(name, payload)
    else:
        write_json(DATA_DIR / f"{name}.json", payload)


# ---------------------------------------------------------------- 首次启动引导
def _bootstrap() -> None:
    if _BACKEND != "sqlite":
        return
    db.init()
    if os.environ.get("EDU_AUTO_IMPORT", "1") == "0":
        return
    if db.count_items() > 0:
        return
    has_json = any((DATA_DIR / kind).glob("*.json") for kind in COLLECTIONS)
    if not has_json:
        return
    stats = db.import_from_json(COLLECTIONS, SHARED_NAMES)
    total = sum(stats["items"].values())
    _log.warning(
        "SQLite 库为空，已从 data/ 自动导入 %d 条记录（来源：旧 JSON 文件）；"
        "如需关闭请设置 EDU_AUTO_IMPORT=0，明细见 scripts/migrate_json_to_sqlite.py",
        total,
    )
    if not stats["verified"] or stats["errors"]:
        _log.error("JSON 导入存在异常：errors=%s", stats["errors"][:5])


_bootstrap()
