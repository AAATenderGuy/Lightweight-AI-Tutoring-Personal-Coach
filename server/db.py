"""SQLite 存储后端（P2 · S4）。

表结构刻意做得泛化：``items`` 以 (collection, id) 为主键，业务字段整体序列化进
``data`` 列。好处是业务代码一行都不用改，却能拿到真正的数据库能力：
事务写入、单文件备份、按集合/属主/父级的索引。

``owner_id`` / ``parent_id`` 只是从 JSON 里派生出来的索引提示列，不是权威数据；
读的时候永远解析 ``data``，避免两份数据打架。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .observability import logger

DB_PATH = Path(os.environ.get("EDU_DB_PATH") or DATA_DIR / "edu.sqlite3").expanduser()
BACKUP_DIR = DB_PATH.parent / "backups"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BACKUP_KEEP = 5

# 派生索引列用到的字段，按优先级排列。
OWNER_KEYS = ("teacher_id", "owner_id")
PARENT_KEYS = ("class_id", "assignment_id", "lesson_id", "material_id", "quiz_id")

log = logger("edu.db")

_WRITE_LOCK = threading.RLock()
_INIT_LOCK = threading.Lock()
_LOCAL = threading.local()
_APPLIED: list[str] = []
_INITED = False


# ---------------------------------------------------------------- 连接与迁移
def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _connect() -> sqlite3.Connection:
    """每线程一个连接（FastAPI 的同步路由跑在线程池里，不能共用单连接）。"""
    global _INITED
    if not _INITED:
        with _INIT_LOCK:
            if not _INITED:
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                bootstrap = _open()
                _APPLIED.extend(_migrate(bootstrap))
                bootstrap.close()
                _INITED = True
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = _open()
        conn.execute("PRAGMA foreign_keys=ON")
        _LOCAL.conn = conn
    return conn


def _snapshot(conn: sqlite3.Connection) -> None:
    """迁移前快照。没有 down 脚本，回滚就靠这份文件。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"pre-migrate-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
    with sqlite3.connect(target) as dst:
        conn.backup(dst)
    log.warning("迁移前已备份：%s", target)
    for stale in sorted(BACKUP_DIR.glob("pre-migrate-*.sqlite3"))[:-BACKUP_KEEP]:
        stale.unlink(missing_ok=True)


def _migrate(conn: sqlite3.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL)"
    )
    applied = {int(row["version"]) for row in conn.execute("SELECT version FROM schema_migrations")}
    pending: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        try:
            version = int(path.name.split("_", 1)[0])
        except ValueError:
            continue
        if version not in applied:
            pending.append((version, path))
    if not pending:
        return []
    # 已有库要升级时才备份；全新库没有东西可备份。
    if applied:
        _snapshot(conn)

    ran: list[str] = []
    for _version, path in pending:
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)",
            (_version, path.name, time.time()),
        )
        ran.append(path.name)
    conn.commit()
    return ran


def init() -> list[str]:
    """确保连接与迁移就绪；返回本次调用中新应用的迁移文件名（幂等）。"""
    _connect()
    with _INIT_LOCK:
        ran = list(_APPLIED)
        _APPLIED.clear()
    if ran:
        log.info("migrations applied: %s", ", ".join(ran))
    return ran


def applied_migrations() -> list[dict]:
    rows = _connect().execute("SELECT version, name, applied_at FROM schema_migrations ORDER BY version").fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------- 读写
def _derive(item: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _as_created(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def save_item(collection: str, item: dict) -> None:
    payload = json.dumps(item, ensure_ascii=False)
    with _WRITE_LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO items(collection, id, created_at, owner_id, parent_id, data)"
            " VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(collection, id) DO UPDATE SET"
            "   created_at=excluded.created_at, owner_id=excluded.owner_id,"
            "   parent_id=excluded.parent_id, data=excluded.data",
            (
                collection,
                item["id"],
                _as_created(item.get("created_at")),
                _derive(item, OWNER_KEYS),
                _derive(item, PARENT_KEYS),
                payload,
            ),
        )


def load_item(collection: str, item_id: str) -> dict | None:
    row = _connect().execute(
        "SELECT data FROM items WHERE collection=? AND id=?", (collection, item_id),
    ).fetchone()
    return json.loads(row["data"]) if row else None


def list_items(collection: str) -> list[dict]:
    rows = _connect().execute(
        "SELECT data FROM items WHERE collection=? ORDER BY created_at DESC", (collection,),
    ).fetchall()
    return [json.loads(row["data"]) for row in rows]


def delete_item(collection: str, item_id: str) -> bool:
    with _WRITE_LOCK, _connect() as conn:
        cursor = conn.execute("DELETE FROM items WHERE collection=? AND id=?", (collection, item_id))
        return cursor.rowcount > 0


def count_items(collection: str | None = None) -> int:
    if collection is None:
        row = _connect().execute("SELECT COUNT(*) AS n FROM items").fetchone()
    else:
        row = _connect().execute("SELECT COUNT(*) AS n FROM items WHERE collection=?", (collection,)).fetchone()
    return int(row["n"])


def info() -> dict:
    """给 /api/health 用的存储概况（WAL 模式下 -wal 文件里也有数据，一起算）。"""
    size = 0
    for path in (DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal")):
        try:
            size += path.stat().st_size
        except OSError:
            continue
    migrations = applied_migrations()
    return {
        "db_path": str(DB_PATH),
        "db_size_kb": round(size / 1024, 1),
        "schema_version": migrations[-1]["version"] if migrations else 0,
    }


def read_shared(name: str, default: Any) -> Any:
    row = _connect().execute("SELECT data FROM shared WHERE name=?", (name,)).fetchone()
    if row is None:
        return default
    return json.loads(row["data"])


def write_shared(name: str, payload: Any) -> None:
    data = json.dumps(payload, ensure_ascii=False)
    with _WRITE_LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO shared(name, data, updated_at) VALUES(?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (name, data, time.time()),
        )


# ---------------------------------------------------------------- 审计
def append_audit(rows: list[dict]) -> None:
    """批量写入审计行（调用方已决定要不要记）。"""
    if not rows:
        return
    with _WRITE_LOCK, _connect() as conn:
        conn.executemany(
            "INSERT INTO audit(at, actor_id, actor_name, action, target, result, ip)"
            " VALUES(?,?,?,?,?,?,?)",
            [
                (
                    float(row.get("at") or time.time()),
                    row.get("actor_id"),
                    row.get("actor_name"),
                    str(row.get("action") or ""),
                    row.get("target"),
                    row.get("result"),
                    row.get("ip"),
                )
                for row in rows
            ],
        )


def list_audit(limit: int = 100, *, actor_id: str | None = None) -> list[dict]:
    sql = "SELECT at, actor_id, actor_name, action, target, result, ip FROM audit"
    args: list[Any] = []
    if actor_id:
        sql += " WHERE actor_id=?"
        args.append(actor_id)
    sql += " ORDER BY at DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 100), 500)))
    return [dict(row) for row in _connect().execute(sql, args).fetchall()]


# ---------------------------------------------------------------- 从 JSON 导入
def import_from_json(
    collections: Iterable[str],
    shared_names: Iterable[str],
    *,
    data_dir: Path = DATA_DIR,
    apply: bool = True,
    overwrite: bool = False,
) -> dict:
    """把 data/ 下的 JSON 灌进 SQLite。

    返回 ``{items: {collection: n}, shared: {name: n}, skipped: n, errors: [...], verified: bool}``。
    ``apply=False`` 时只统计不写入（--dry-run）。导入后逐条回读比对，确认没有丢数据。
    """
    init()
    stats: dict[str, Any] = {"items": {}, "shared": {}, "skipped": 0, "errors": [], "verified": True}

    for collection in collections:
        folder = data_dir / collection
        imported = 0
        if not folder.is_dir():
            stats["items"][collection] = 0
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                stats["errors"].append(f"{path.name}: {exc}")
                continue
            if not isinstance(payload, dict):
                stats["errors"].append(f"{path.name}: 不是 JSON 对象")
                continue
            payload.setdefault("id", path.stem)
            payload.setdefault("created_at", 0)
            exists = load_item(collection, payload["id"]) is not None
            if exists and not overwrite:
                stats["skipped"] += 1
                if apply and load_item(collection, payload["id"]) != payload:
                    stats["verified"] = False
                continue
            if apply:
                save_item(collection, payload)
                if load_item(collection, payload["id"]) != payload:
                    stats["verified"] = False
                    stats["errors"].append(f"{collection}/{path.name}: 回读不一致")
            imported += 1
        stats["items"][collection] = imported

    for name in shared_names:
        path = data_dir / f"{name}.json"
        if not path.is_file():
            stats["shared"][name] = 0
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            stats["errors"].append(f"{path.name}: {exc}")
            continue
        if apply:
            write_shared(name, payload)
            if read_shared(name, None) != payload:
                stats["verified"] = False
                stats["errors"].append(f"{path.name}: 回读不一致")
        stats["shared"][name] = 1

    return stats
