"""Edu 轻量级教学服务的运行时配置。

配置优先级：data/settings.json（界面保存） > .env > 内置默认值。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

APP_NAME = "Edu"
APP_SUBTITLE = "轻量级 AI 教学服务"
VERSION = "1.5.0"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("EDU_DATA_DIR") or ROOT / "data").expanduser().resolve()
WEB_DIST = ROOT / "web" / "dist"


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析，避免引入额外依赖。"""
    if not path.is_file():
        return
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")

DEFAULTS = {
    "base_url": os.environ.get("EDU_BASE_URL", "https://api.deepseek.com/v1").strip(),
    "model": os.environ.get("EDU_MODEL", "deepseek-chat").strip(),
    "api_key": os.environ.get("EDU_API_KEY", "").strip(),
    "temperature": 0.6,
}


def _as_temperature(value: object, fallback: float = 0.6) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.5, number))


class Settings:
    """进程内共享的可变配置。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data = dict(DEFAULTS)
        self._path = DATA_DIR / "settings.json"
        self._load()

    # ---------------------------------------------------------------- 读写
    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(stored, dict):
            return
        with self._lock:
            for key in ("base_url", "model", "api_key"):
                value = stored.get(key)
                if isinstance(value, str) and value.strip():
                    self._data[key] = value.strip()
            if "temperature" in stored:
                self._data["temperature"] = _as_temperature(stored["temperature"])

    def save(self) -> None:
        with self._lock:
            payload = dict(self._data)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # ---------------------------------------------------------------- 访问
    @property
    def api_key(self) -> str:
        with self._lock:
            return self._data["api_key"]

    @property
    def base_url(self) -> str:
        with self._lock:
            return self._data["base_url"].rstrip("/")

    @property
    def model(self) -> str:
        with self._lock:
            return self._data["model"]

    @property
    def temperature(self) -> float:
        with self._lock:
            return self._data["temperature"]

    @property
    def is_demo(self) -> bool:
        return not self.api_key

    def endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def snapshot(self) -> dict:
        """返回给前端的配置：密钥只暴露打码结果。"""
        with self._lock:
            data = dict(self._data)
        key = data.get("api_key", "")
        return {
            "base_url": data["base_url"],
            "model": data["model"],
            "temperature": data["temperature"],
            "has_key": bool(key),
            "demo": not key,
            "key_hint": _mask_key(key),
        }

    def update(self, *, base_url: str | None = None, model: str | None = None,
               api_key: str | None = None, temperature: float | None = None) -> dict:
        with self._lock:
            if base_url is not None and base_url.strip():
                self._data["base_url"] = base_url.strip().rstrip("/")
            if model is not None and model.strip():
                self._data["model"] = model.strip()
            if api_key is not None:
                self._data["api_key"] = api_key.strip()
            if temperature is not None:
                self._data["temperature"] = _as_temperature(temperature)
        self.save()
        return self.snapshot()


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 8}{key[-4:]}"


DATA_DIR.mkdir(parents=True, exist_ok=True)
settings = Settings()
