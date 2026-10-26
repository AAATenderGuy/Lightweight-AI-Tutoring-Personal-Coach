"""上传文件的通用处理：分块限额读取、格式白名单、文本提取、落盘与安全解析。

为什么不用 `await file.read()` 一把梭：上传大小只有在读完之后才知道，
一个 2 GB 的请求会先把内存吃满。这里按 1 MB 分块读，超过上限立即中止。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..config import DATA_DIR
from . import materials

MAX_SUBMISSION_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 20_000
CHUNK = 1024 * 1024

ALLOWED_SUFFIXES = {
    ".pdf", ".docx", ".pptx", ".txt", ".md", ".markdown",
    ".png", ".jpg", ".jpeg", ".webp",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

UPLOAD_ROOT = DATA_DIR / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class UploadError(ValueError):
    """可以直接展示给上传者的错误。"""


def suffix_of(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def check_name(filename: str) -> str:
    suffix = suffix_of(filename)
    if suffix not in ALLOWED_SUFFIXES:
        allowed = " / ".join(sorted(item.lstrip(".") for item in ALLOWED_SUFFIXES))
        raise UploadError(f"不支持的文件格式，可以提交：{allowed}。")
    return suffix


async def read_upload(file, *, limit: int | None = None) -> bytes:
    """分块读取并累计大小，超限立即抛错，不把整个文件驻留内存。"""
    limit = MAX_SUBMISSION_BYTES if limit is None else limit
    declared = 0
    try:
        declared = int((file.headers or {}).get("content-length") or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared and declared > limit + 2 * 1024 * 1024:
        raise UploadError(f"文件太大，最多 {round(limit / 1024 / 1024)} MB。")

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UploadError(f"文件太大，最多 {round(limit / 1024 / 1024)} MB。")
        chunks.append(chunk)
    if total == 0:
        raise UploadError("上传的文件是空的，请重新选择。")
    return b"".join(chunks)


def extract_for_grading(filename: str, data: bytes) -> tuple[str, str]:
    """返回 (可批改文本, 提示)。图片无法提取文字时给出明确说明。"""
    suffix = suffix_of(filename)
    if suffix in IMAGE_SUFFIXES:
        return "", "图片作业无法自动提取文字，已转教师人工批改。"
    try:
        text = materials.extract_text(filename, data, max_bytes=MAX_SUBMISSION_BYTES)
    except materials.MaterialError as exc:
        raise UploadError(str(exc)) from exc
    text = text.strip()
    if not text:
        return "", "没有从文件里提取到文字，可能扫描件没有文字层，已转教师人工批改。"
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n…（内容过长，已截断）"
    return text, ""


def store_file(assignment_id: str, submission_id: str, filename: str, data: bytes) -> dict:
    """把文件写到 data/uploads/<assignment>/<submission>/<file_id><ext>。"""
    for value in (assignment_id, submission_id):
        if not _SAFE_ID.match(str(value or "")):
            raise UploadError("内部标识不合法，无法保存文件。")
    suffix = check_name(filename)
    file_id = f"f_{hashlib.sha256(data).hexdigest()[:16]}"
    folder = UPLOAD_ROOT / assignment_id / submission_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{file_id}{suffix}"
    path.write_bytes(data)
    return {
        "id": file_id,
        "filename": Path(filename or "作业").name[:120],
        "suffix": suffix,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "rel": f"{assignment_id}/{submission_id}/{file_id}{suffix}",
    }


def resolve(rel: str) -> Path:
    """把相对路径还原成绝对路径，并确保没有跳出 uploads 目录。"""
    if not rel or ".." in rel:
        raise UploadError("文件路径不合法。")
    path = (UPLOAD_ROOT / rel).resolve()
    root = UPLOAD_ROOT.resolve()
    if root not in path.parents and path != root:
        raise UploadError("文件路径不合法。")
    if not path.is_file():
        raise UploadError("文件不存在或已被清理。")
    return path
