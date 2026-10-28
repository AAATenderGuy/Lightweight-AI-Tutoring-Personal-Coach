"""审计日志（P2 · S6）。

只记「谁、什么时候、对什么、做了什么、结果如何」，不记业务内容本身
（不写学生答案、不写密码），所以可以直接给评审看，也不构成新的隐私面。

SQLite 后端写 `audit` 表（0002 迁移），`EDU_STORE=json` 时退化为
`data/audit.jsonl` 追加文件，两者读取接口一致。
"""
from __future__ import annotations

import json
import time

from .. import db, store
from ..config import DATA_DIR
from ..observability import logger
from . import perms

log = logger("edu.audit")

JSONL = DATA_DIR / "audit.jsonl"
MAX_ROWS = 500

# 动作名统一在这里，避免各处字符串拼错
LOGIN = "teacher.login"
LOGOUT = "teacher.logout"
REGISTER = "teacher.register"
PASSWORD = "teacher.password"
ROSTER_IMPORT = "class.roster_import"
CLASS_CREATE = "class.create"
CLASS_DELETE = "class.delete"
ASSIGNMENT_CREATE = "assignment.create"
ASSIGNMENT_DELETE = "assignment.delete"
SUBMISSION_GRADE = "submission.grade"
EXPORT = "report.export"
GROUP_CREATE = "group.create"
GROUP_UPDATE = "group.update"
GROUP_MEMBER_ADD = "group.member_add"
GROUP_MEMBER_REMOVE = "group.member_remove"


def _row(action: str, actor: dict | None, target: str, result: str, ip: str) -> dict:
    return {
        "at": time.time(),
        "actor_id": (actor or {}).get("id"),
        "actor_name": (actor or {}).get("name") or (actor or {}).get("username"),
        "action": action,
        "target": target,
        "result": result,
        "ip": ip,
    }


def record(action: str, *, actor: dict | None = None, target: str = "", result: str = "ok", ip: str = "") -> None:
    row = _row(action, actor, target, result, ip)
    log.info("audit action=%s actor=%s target=%s result=%s", action, row["actor_id"], target or "-", result)
    if store.backend() == "json":
        try:
            with JSONL.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:  # 审计失败不能影响主流程
            log.warning("审计写入失败：%s", exc)
        return
    try:
        db.append_audit([row])
    except Exception as exc:  # noqa: BLE001 - 同上，审计是旁路
        log.warning("审计写入失败：%s", exc)


def recent(limit: int = 100) -> list[dict]:
    limit = max(1, min(int(limit or 100), MAX_ROWS))
    if store.backend() == "json":
        if not JSONL.is_file():
            return []
        rows = []
        for line in JSONL.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(rows))[:limit]
    return db.list_audit(limit)


def visible_for(teacher: dict, limit: int = 100) -> list[dict]:
    """按请求者裁剪的审计视图。

    部署者（owner）看全部；组长只看到自己与所在组的记录，且 IP 一律打码——
    审计是给「管这一摊的人」看的，不是全平台的监控面板。
    """
    limit = max(1, min(int(limit or 100), MAX_ROWS))
    rows = recent(MAX_ROWS)
    if perms.role_of(teacher) == "owner":
        return rows[:limit]
    allowed = {str(teacher.get("id") or "")}
    for group in perms.groups_of(teacher.get("id") or ""):
        if perms.can_manage_group(teacher, group):
            allowed.add(str(group.get("owner_id") or ""))
            allowed.update(str(item.get("teacher_id") or "") for item in group.get("members") or [])
    rows = [{**row, "ip": ""} for row in rows if str(row.get("actor_id") or "") in allowed]
    return rows[:limit]
