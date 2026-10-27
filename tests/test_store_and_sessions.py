"""存储缓存、教师会话持久化、上传限额。"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from server import store
from server.services import auth, uploads


def test_read_json_returns_independent_copy():
    store.save_item("lessons", {"id": "lsn_cache_case", "title": "缓存"})
    first = store.load_item("lessons", "lsn_cache_case")
    first["title"] = "外部修改"
    second = store.load_item("lessons", "lsn_cache_case")
    assert second["title"] == "缓存"
    store.delete_item("lessons", "lsn_cache_case")
    assert store.load_item("lessons", "lsn_cache_case") is None


def test_teacher_session_survives_reload(client, teacher):
    saved = dict(auth._TOKENS)
    auth._TOKENS.clear()
    auth._load()
    assert auth.resolve(teacher["token"]) is not None
    auth._TOKENS.clear()
    auth._TOKENS.update(saved)


def test_raw_token_is_not_written_to_disk(teacher):
    """磁盘上只保留 token 的 SHA-256：扫一遍数据目录，明文 token 不应出现。"""
    token = teacher["token"]
    root = Path(os.environ["EDU_DATA_DIR"])
    hits = [
        str(path)
        for path in root.rglob("*")
        if path.is_file() and token in path.read_bytes().decode("utf-8", "ignore")
    ]
    assert hits == [], hits


def test_sessions_are_persisted_in_store(teacher):
    stored = store.read_shared("sessions", {})
    assert stored, "登录态应写进存储层，重启后免登录"
    assert teacher["token"] not in stored


def test_read_upload_rejects_oversized_stream():
    class FakeUpload:
        headers: dict = {}

        def __init__(self) -> None:
            self.calls = 0

        async def read(self, size: int) -> bytes:
            self.calls += 1
            return b"x" * size

    async def run() -> None:
        with pytest.raises(uploads.UploadError):
            await uploads.read_upload(FakeUpload(), limit=1024 * 1024)

    asyncio.run(run())


def test_resolve_blocks_path_traversal():
    with pytest.raises(uploads.UploadError):
        uploads.resolve("../settings.json")
