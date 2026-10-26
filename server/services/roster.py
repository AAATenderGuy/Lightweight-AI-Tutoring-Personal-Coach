"""学生名单导入：CSV 解析、密码哈希与初始密码生成。

教师从教务系统导出名单（学号、姓名、初始密码），在班级页导入。
密码用 PBKDF2-SHA256 加盐存储，和教师账号同一套强度；明文只在导入结果里
返回一次，方便老师把初始密码发给学生。
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets

MAX_ROWS = 500
PBKDF2_ROUNDS = 120_000

HEADER_ALIASES = {
    "number": {"学号", "学籍号", "考号", "账号", "studentid", "student_id", "number", "id"},
    "name": {"姓名", "名字", "学生姓名", "name", "studentname"},
    "password": {"密码", "初始密码", "登录密码", "password", "pwd"},
}
COLUMN_ORDER = ("number", "name", "password")


class RosterError(ValueError):
    """可以直接展示给教师的导入错误。"""


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS,
    ).hex()
    return salt, digest


def verify_password(password: str, salt: str, expected: str) -> bool:
    if not salt or not expected:
        return False
    try:
        salt_bytes = bytes.fromhex(salt)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode("utf-8"), salt_bytes, PBKDF2_ROUNDS,
    ).hex()
    return secrets.compare_digest(digest, str(expected))


def generate_password() -> str:
    """6 位数字初始密码，方便口头/纸质分发。"""
    return f"{secrets.randbelow(900_000) + 100_000}"


def _safe_text(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _normalise(value: object) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "")).lower()


def decode_roster(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RosterError("无法识别文件编码，请另存为 UTF-8 或 GBK 的 CSV。")


def _detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def parse_roster(text: str) -> dict:
    """解析名单文本，返回 {rows, errors, duplicates}。

    支持：
    - 带表头：学号,姓名,密码（列顺序任意、允许别名）
    - 不带表头：第一列学号、第二列姓名、第三列密码（密码可省略）
    - 逗号 / 分号 / 制表符分隔
    """
    raw = str(text or "").replace("\ufeff", "").strip()
    if not raw:
        raise RosterError("没有读到名单内容，请粘贴或上传 CSV。")
    sample = "\n".join(raw.splitlines()[:5])
    delimiter = _detect_delimiter(sample)
    reader = csv.reader(io.StringIO(raw), delimiter=delimiter)
    rows: list[tuple[str, ...]] = []
    for row in reader:
        cells = [str(cell).strip() for cell in row]
        if not cells or all(not cell for cell in cells):
            continue
        if cells[0].startswith("#"):
            continue
        rows.append(tuple(cells))
    if not rows:
        raise RosterError("名单是空的。")

    mapping = {key: index for index, key in enumerate(COLUMN_ORDER)}
    start = 0
    first = [_normalise(cell) for cell in rows[0]]
    if any(cell in HEADER_ALIASES["number"] for cell in first):
        found: dict[str, int] = {}
        for index, cell in enumerate(first):
            for key, aliases in HEADER_ALIASES.items():
                if cell in aliases and key not in found:
                    found[key] = index
        if "number" not in found:
            raise RosterError("表头里没有找到「学号」列。")
        if "name" not in found:
            raise RosterError("表头里没有找到「姓名」列。")
        mapping = found
        start = 1

    result = []
    errors: list[str] = []
    seen: dict[str, int] = {}
    duplicates = 0
    for line_number, row in enumerate(rows[start:], start + 1):
        def pick(key: str) -> str:
            index = mapping.get(key)
            if index is None or index >= len(row):
                return ""
            return row[index]

        number = _safe_text(pick("number"), 32)
        name = _safe_text(pick("name"), 20)
        password = str(pick("password")).strip()[:72]
        if not number and not name:
            continue
        if not number:
            errors.append(f"第 {line_number} 行缺少学号")
            continue
        if not name:
            errors.append(f"学号 {number} 缺少姓名")
            continue
        if re.search(r"[\s,;/]", number):
            errors.append(f"学号「{number}」包含空格或分隔符")
            continue
        if number in seen:
            duplicates += 1
            result[seen[number]] = {"number": number, "name": name, "password": password}
            continue
        seen[number] = len(result)
        result.append({"number": number, "name": name, "password": password})

    if not result:
        detail = "；".join(errors[:3]) if errors else "没有解析到有效行"
        raise RosterError(f"名单里没有可导入的学生：{detail}")
    if len(result) > MAX_ROWS:
        raise RosterError(f"一次最多导入 {MAX_ROWS} 人，请拆分成多个班级。")
    return {"rows": result, "errors": errors, "duplicates": duplicates}
