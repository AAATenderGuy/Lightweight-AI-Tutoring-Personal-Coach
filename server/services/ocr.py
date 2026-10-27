"""拍题 OCR（P2 · S5）：图片 → 可编辑文字。

选 `rapidocr`（ONNX Runtime 后端，模型约 27MB）而不是 PaddleOCR：Python 3.14
没有 `paddlepaddle` 的 cp314 轮子，根本装不上。

这里只做**印刷体**识别。手写体与公式的准确率有限，所以接口逐行返回置信度，
前端把低置信度的行标灰，明确提示「请人工核对」，不假装全对。
"""
from __future__ import annotations

import io
import threading
import time
from typing import Any

from PIL import Image, ImageOps

MAX_BYTES = 8 * 1024 * 1024  # 拍一张作业照片足够，再大只会更慢
MAX_SIDE = 1600  # 长边上限：缩到这个尺寸后识别率基本不变，速度提升明显
LOW_SCORE = 0.6  # 低于此分数：前端提示人工核对
MIN_SCORE = 0.25  # 低于此分数：当作噪点丢弃

_LOCK = threading.Lock()
_ENGINE: Any = None
_ENGINE_ERROR = ""


class OcrError(ValueError):
    """可以直接展示给用户的错误。"""


def available() -> bool:
    """OCR 依赖是否装好（没装时应答 503，而不是把服务起不来）。"""
    try:
        import rapidocr  # noqa: F401
    except Exception:  # noqa: BLE001 - 缺依赖的原因很多，这里只需要真假
        return False
    return True


def _engine() -> Any:
    global _ENGINE, _ENGINE_ERROR
    if _ENGINE is not None:
        return _ENGINE
    with _LOCK:
        if _ENGINE is not None:
            return _ENGINE
        try:
            from rapidocr import RapidOCR
        except Exception as exc:  # noqa: BLE001
            _ENGINE_ERROR = str(exc)
            raise OcrError("OCR 组件未安装，请执行 pip install -r requirements.txt 后重启服务。") from exc
        try:
            _ENGINE = RapidOCR()
        except Exception as exc:  # noqa: BLE001
            _ENGINE_ERROR = str(exc)
            raise OcrError(f"OCR 引擎初始化失败：{exc}") from exc
    return _ENGINE


def prepare_image(data: bytes) -> Image.Image:
    """解码、纠正 EXIF 方向、统一 RGB、限制长边。纯函数，方便单测。"""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001 - PIL 抛的异常类型五花八门
        raise OcrError("无法读取这张图片，请换 JPG / PNG 后重试。") from exc
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    long_side = max(image.size)
    if long_side > MAX_SIDE:
        scale = MAX_SIDE / long_side
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    return image


def extract(data: bytes, *, filename: str = "") -> dict:
    """识别一张图片，返回 {text, lines, width, height, elapsed_ms, low_confidence}。"""
    if not data:
        raise OcrError("图片是空的，请重新选择。")
    if len(data) > MAX_BYTES:
        raise OcrError(f"图片太大，最多 {MAX_BYTES // 1024 // 1024} MB。")

    image = prepare_image(data)
    engine = _engine()

    import numpy as np  # 跟着 rapidocr 一起装，放在这里避免拖慢服务启动

    array = np.ascontiguousarray(np.asarray(image)[:, :, ::-1])  # RGB → BGR，OpenCV 习惯
    started = time.perf_counter()
    try:
        result = engine(array)
    except Exception as exc:  # noqa: BLE001
        raise OcrError("识别失败，请重试或换一张更清晰的图片。") from exc
    elapsed_ms = (time.perf_counter() - started) * 1000

    txts = list(getattr(result, "txts", None) or ())
    scores = list(getattr(result, "scores", None) or ())
    lines: list[dict] = []
    for index, raw in enumerate(txts):
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            score = float(scores[index])
        except (IndexError, TypeError, ValueError):
            score = 0.0
        if score < MIN_SCORE:
            continue
        lines.append({"text": text, "score": round(score, 3), "low": score < LOW_SCORE})

    return {
        "text": "\n".join(line["text"] for line in lines),
        "lines": lines,
        "width": image.width,
        "height": image.height,
        "elapsed_ms": round(elapsed_ms),
        "filename": filename,
        "low_confidence": any(line["low"] for line in lines),
    }
