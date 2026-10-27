"""教研组与权限（P2 · S6）。

三种角色：

- `owner`：部署者，第一个注册的账号（通常是 `demo`），看得到全部班级，能管任何组
- `lead`：教研组长，组创建者；能管本组成员，能读写组内全部班级
- `teacher`：普通教师，默认角色；只能写自己创建的班级，组内别的班只能读

判断集中在 `can_view_class` / `can_edit_class` / `can_view_grades` 三个函数，
`services/classes.py` 里只把「读」入口改成 `write=False`，不重写 57KB 的业务逻辑。
"""
from __future__ import annotations

import time

from .. import store

ROLES = ("owner", "lead", "teacher")


def role_of(teacher: dict | None) -> str:
    """没有 role 字段的老数据按「最早注册的账号是 owner」回推，不需要迁移脚本。"""
    if not teacher:
        return ""
    role = str(teacher.get("role") or "")
    if role in ROLES:
        return role
    teachers = store.list_items("teachers")
    if not teachers:
        return "teacher"
    first = min(teachers, key=lambda item: float(item.get("created_at") or 0))
    return "owner" if first.get("id") == teacher.get("id") else "teacher"


def backfill() -> int:
    """启动时补齐老数据的 role 字段，之后 role_of 不再需要全表扫描。"""
    teachers = store.list_items("teachers")
    if not teachers:
        return 0
    first = min(teachers, key=lambda item: float(item.get("created_at") or 0))
    fixed = 0
    for teacher in teachers:
        if str(teacher.get("role") or "") in ROLES:
            continue
        teacher["role"] = "owner" if teacher.get("id") == first.get("id") else "teacher"
        store.save_item("teachers", teacher)
        fixed += 1
    return fixed


def groups_of(teacher_id: str) -> list[dict]:
    """自己所在（或被邀请进）的教研组。"""
    return [
        group for group in store.list_items("groups")
        if group.get("owner_id") == teacher_id
        or any(member.get("teacher_id") == teacher_id for member in group.get("members") or [])
    ]


def group_ids_of(teacher_id: str) -> set[str]:
    return {str(group.get("id")) for group in groups_of(teacher_id)}


def member_role(group: dict, teacher_id: str) -> str:
    if group.get("owner_id") == teacher_id:
        return "lead"
    for member in group.get("members") or []:
        if member.get("teacher_id") == teacher_id:
            return str(member.get("role") or "member")
    return ""


def can_manage_group(teacher: dict, group: dict) -> bool:
    if role_of(teacher) == "owner":
        return True
    if group.get("owner_id") == teacher.get("id"):
        return True
    return member_role(group, teacher.get("id") or "") == "lead"


def is_lead_anywhere(teacher: dict) -> bool:
    if role_of(teacher) == "owner":
        return True
    return any(can_manage_group(teacher, group) for group in groups_of(teacher.get("id") or ""))


def can_view_class(teacher: dict, klass: dict) -> bool:
    if role_of(teacher) == "owner":
        return True
    if klass.get("teacher_id") == teacher.get("id"):
        return True
    group_id = str(klass.get("group_id") or "")
    return bool(group_id) and group_id in group_ids_of(teacher.get("id") or "")


def can_edit_class(teacher: dict, klass: dict) -> bool:
    """建/改/删班级、布置作业、导入名单：owner 或班级创建者。"""
    if role_of(teacher) == "owner":
        return True
    if klass.get("teacher_id") == teacher.get("id"):
        return True
    return False


def can_view_grades(teacher: dict, klass: dict) -> bool:
    """看学生提交与改分：owner、班级创建者、同组的组长；同组普通教师不行。"""
    if can_edit_class(teacher, klass):
        return True
    group_id = str(klass.get("group_id") or "")
    if not group_id:
        return False
    for group in groups_of(teacher.get("id") or ""):
        if str(group.get("id")) == group_id and can_manage_group(teacher, group):
            return True
    return False


def touch_teacher_role(teacher_id: str, role: str) -> dict | None:
    """把角色写进教师记录（`lead` / `teacher`），返回更新后的记录。"""
    if role not in ROLES:
        raise ValueError("未知角色。")
    teacher = store.load_item("teachers", teacher_id)
    if not teacher:
        return None
    teacher["role"] = role
    teacher["role_updated_at"] = time.time()
    return store.save_item("teachers", teacher)
