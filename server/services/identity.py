"""学生身份令牌。

学生不需要注册账号：加入班级时服务端用本机密钥签一个 HMAC 令牌，
之后所有学生接口都校验 (student_id, token) 是否匹配。
换设备时用同样的「邀请码 + 姓名 + 学号」重新加入，会复用原档案并拿到新令牌，
所以既能防冒用，也不会丢历史成绩。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from ..config import DATA_DIR

_SECRET_FILE = DATA_DIR / "secret.key"
_SECRET: bytes | None = None


def _secret() -> bytes:
    global _SECRET
    if _SECRET:
        return _SECRET
    try:
        _SECRET = _SECRET_FILE.read_bytes().strip()
    except OSError:
        _SECRET = b""
    if not _SECRET:
        _SECRET = secrets.token_hex(32).encode("utf-8")
        try:
            _SECRET_FILE.write_bytes(_SECRET)
            os.chmod(_SECRET_FILE, 0o600)
        except OSError:
            pass
    return _SECRET


def student_token(student_id: str) -> str:
    message = f"student:{student_id}".encode("utf-8")
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()[:40]


def verify(student_id: str, token: str) -> bool:
    if not student_id or not token:
        return False
    try:
        return hmac.compare_digest(student_token(student_id), str(token))
    except (TypeError, ValueError):
        return False
