"""教师账号与会话。

只依赖标准库：密码用 PBKDF2-SHA256 加盐存储；登录态落盘到 data/sessions.json，
重启服务后不需要重新登录。磁盘上只保存 token 的 SHA-256，即使 data/ 被拷走，
也不能直接拿来登录。
"""
from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time

from .. import store

TOKEN_TTL = 12 * 3600
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,24}$")

_LOCK = threading.RLock()
_TOKENS: dict[str, dict] = {}


def _key(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _save() -> None:
    store.write_shared("sessions", _TOKENS)


def _load() -> None:
    stored = store.read_shared("sessions", {})
    if not isinstance(stored, dict):
        return
    now = time.time()
    with _LOCK:
        for key, entry in stored.items():
            if not isinstance(entry, dict):
                continue
            if float(entry.get("exp") or 0) > now:
                _TOKENS[str(key)] = entry
    if len(_TOKENS) != len(stored):
        _save()


_load()

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo1234"
DEMO_NAME = "演示教师"


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000).hex()


def _find_by_username(username: str) -> dict | None:
    target = username.strip().lower()
    for teacher in store.list_items("teachers"):
        if str(teacher.get("username", "")).lower() == target:
            return teacher
    return None


def find_by_username(username: str) -> dict | None:
    return _find_by_username(username or "")


def public(teacher: dict) -> dict:
    return {
        "id": teacher.get("id"),
        "username": teacher.get("username"),
        "name": teacher.get("name") or teacher.get("username"),
        "created_at": teacher.get("created_at"),
        "last_login": teacher.get("last_login"),
    }


def _check_password(password: str) -> str:
    if len(password) < 6:
        raise ValueError("密码至少 6 位。")
    if len(password) > 72:
        raise ValueError("密码太长（最多 72 位）。")
    return password


def register(username: str, password: str, name: str) -> dict:
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise ValueError("用户名需为 3–24 位字母、数字、下划线、点或短横线。")
    _check_password(password)
    with _LOCK:
        if _find_by_username(username):
            raise ValueError("这个用户名已被占用，换一个或直接登录。")
        salt = secrets.token_hex(16)
        teacher = store.save_item("teachers", {
            "id": store.new_id("tc_"),
            "username": username,
            "name": (name or username).strip()[:24],
            "salt": salt,
            "password_hash": _hash(password, salt),
            "created_at": time.time(),
            "last_login": time.time(),
        })
    return {"teacher": public(teacher), "token": issue_token(teacher["id"])}


def login(username: str, password: str) -> dict:
    teacher = _find_by_username(username or "")
    if not teacher:
        raise ValueError("账号或密码不正确。")
    salt = str(teacher.get("salt") or "")
    expected = str(teacher.get("password_hash") or "")
    if not salt or not expected or _hash(password or "", salt) != expected:
        raise ValueError("账号或密码不正确。")
    teacher["last_login"] = time.time()
    store.save_item("teachers", teacher)
    return {"teacher": public(teacher), "token": issue_token(teacher["id"])}


def change_password(teacher_id: str, old_password: str, new_password: str) -> None:
    teacher = store.load_item("teachers", teacher_id)
    if not teacher:
        raise ValueError("账号不存在。")
    salt = str(teacher.get("salt") or "")
    if _hash(old_password or "", salt) != str(teacher.get("password_hash") or ""):
        raise ValueError("原密码不正确。")
    _check_password(new_password)
    new_salt = secrets.token_hex(16)
    teacher["salt"] = new_salt
    teacher["password_hash"] = _hash(new_password, new_salt)
    store.save_item("teachers", teacher)


# ---------------------------------------------------------------- 会话
def issue_token(teacher_id: str) -> str:
    token = secrets.token_urlsafe(24)
    with _LOCK:
        _TOKENS[_key(token)] = {"teacher_id": teacher_id, "exp": time.time() + TOKEN_TTL}
        _save()
    return token


def resolve(token: str) -> dict | None:
    if not token:
        return None
    key = _key(token)
    with _LOCK:
        entry = _TOKENS.get(key)
        if not entry:
            return None
        if entry["exp"] < time.time():
            _TOKENS.pop(key, None)
            _save()
            return None
        teacher = store.load_item("teachers", entry["teacher_id"])
    return public(teacher) if teacher else None


def logout(token: str) -> None:
    with _LOCK:
        if _TOKENS.pop(_key(token), None) is not None:
            _save()


def ensure_demo_teacher() -> None:
    """首次启动时放一个演示账号，方便直接体验教师工作台。"""
    if store.list_items("teachers"):
        return
    try:
        register(DEMO_USERNAME, DEMO_PASSWORD, DEMO_NAME)
    except ValueError:
        pass
