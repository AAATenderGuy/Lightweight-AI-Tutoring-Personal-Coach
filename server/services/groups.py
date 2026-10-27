"""教研组（P2 · S6）。

一个组有组长（创建者）和若干成员；班级通过 `class.group_id` 挂到组上，
组内成员可以**读**别人的班级与报告，组长还能看分数并管组。
组的权威数据在存储层的 `groups` 集合里，成员列表内联在文档中。
"""
from __future__ import annotations

import time

from .. import store
from . import auth, perms


class GroupError(ValueError):
    """可以直接展示给教师的错误。"""


def _load(group_id: str) -> dict:
    group = store.load_item("groups", group_id or "")
    if not group:
        raise GroupError("教研组不存在或已删除。")
    return group


def _member_ids(group: dict) -> set[str]:
    return {str(item.get("teacher_id")) for item in group.get("members") or []}


def _teacher(teacher_id: str) -> dict | None:
    return store.load_item("teachers", teacher_id or "")


def _sync_role(teacher_id: str) -> None:
    """组成员变化后把全局角色同步为 lead / teacher（owner 不动）。"""
    teacher = _teacher(teacher_id)
    if not teacher or perms.role_of(teacher) == "owner":
        return
    leading = any(
        group.get("owner_id") == teacher_id or perms.member_role(group, teacher_id) == "lead"
        for group in perms.groups_of(teacher_id)
    )
    role = "lead" if leading else "teacher"
    if teacher.get("role") != role:
        perms.touch_teacher_role(teacher_id, role)


def public(group: dict) -> dict:
    members = []
    for item in group.get("members") or []:
        teacher = _teacher(str(item.get("teacher_id"))) or {}
        members.append({
            "teacher_id": item.get("teacher_id"),
            "name": teacher.get("name") or teacher.get("username") or "已注销账号",
            "username": teacher.get("username"),
            "role": item.get("role") or "member",
            "joined_at": item.get("joined_at"),
        })
    owner = _teacher(str(group.get("owner_id"))) or {}
    return {
        "id": group.get("id"),
        "name": group.get("name"),
        "owner_id": group.get("owner_id"),
        "owner_name": owner.get("name") or owner.get("username") or "已注销账号",
        "members": members,
        "member_count": len(members) + 1,
        "created_at": group.get("created_at"),
    }


def list_for(teacher: dict) -> list[dict]:
    groups = perms.groups_of(teacher.get("id") or "")
    if perms.role_of(teacher) == "owner":
        groups = store.list_items("groups")
    return [public(group) for group in groups]


def create(teacher: dict, name: str) -> dict:
    name = (name or "").strip()
    if not (2 <= len(name) <= 30):
        raise GroupError("组名需为 2–30 个字。")
    group = store.save_item("groups", {
        "id": store.new_id("grp_"),
        "name": name,
        "owner_id": teacher.get("id"),
        "members": [],
        "created_at": time.time(),
    })
    _sync_role(teacher.get("id") or "")
    return public(group)


def update(teacher: dict, group_id: str, *, name: str | None = None) -> dict:
    group = _load(group_id)
    if not perms.can_manage_group(teacher, group):
        raise GroupError("只有组长或部署者可以修改教研组。")
    if name is not None:
        name = name.strip()
        if not (2 <= len(name) <= 30):
            raise GroupError("组名需为 2–30 个字。")
        group["name"] = name
    return public(store.save_item("groups", group))


def add_member(teacher: dict, group_id: str, username: str) -> dict:
    group = _load(group_id)
    if not perms.can_manage_group(teacher, group):
        raise GroupError("只有组长或部署者可以邀请成员。")
    target = auth.find_by_username(username or "")
    if not target:
        raise GroupError("找不到这个用户名，请让对方先注册账号。")
    target_id = str(target.get("id"))
    if target_id == group.get("owner_id") or target_id in _member_ids(group):
        raise GroupError("这位老师已经在组里了。")
    group.setdefault("members", []).append({
        "teacher_id": target_id,
        "role": "member",
        "joined_at": time.time(),
    })
    saved = public(store.save_item("groups", group))
    _sync_role(target_id)
    return saved


def remove_member(teacher: dict, group_id: str, teacher_id: str) -> dict:
    group = _load(group_id)
    if not perms.can_manage_group(teacher, group):
        raise GroupError("只有组长或部署者可以移除成员。")
    before = len(group.get("members") or [])
    group["members"] = [item for item in group.get("members") or [] if str(item.get("teacher_id")) != teacher_id]
    if len(group["members"]) == before:
        raise GroupError("这位老师不在组里。")
    saved = public(store.save_item("groups", group))
    _sync_role(teacher_id)
    return saved


def delete(teacher: dict, group_id: str) -> dict:
    group = _load(group_id)
    if not perms.can_manage_group(teacher, group):
        raise GroupError("只有组长或部署者可以解散教研组。")
    member_ids = _member_ids(group)
    # 组解散后，班级要脱钩，否则会变成「没有组却挂着 group_id」的孤儿
    for klass in store.list_items("classes"):
        if str(klass.get("group_id") or "") == group_id:
            klass.pop("group_id", None)
            store.save_item("classes", klass)
    store.delete_item("groups", group_id)
    for teacher_id in member_ids:
        _sync_role(teacher_id)
    _sync_role(group.get("owner_id") or "")
    return {"ok": True, "id": group_id}
