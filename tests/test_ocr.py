"""拍题 OCR（P2 · S5）：图片预处理、接口参数校验、真实识别。"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from server.services import ocr


def _png(size=(900, 300), text: str = "EDU OCR TEST 2026") -> bytes:
    """用 PIL 默认字体画一张白底黑字的图，作为可复现的测试图片。"""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=64)
    except TypeError:  # Pillow < 10.1 不支持 size 参数
        font = ImageFont.load_default()
    draw.text((40, 100), text, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_status_reports_engine(client):
    payload = client.get("/api/ocr/status").json()
    assert payload["available"] is ocr.available()
    assert payload["max_mb"] == 8
    assert 0 < payload["low_score"] <= 1


def test_rejects_non_image_upload(client):
    response = client.post(
        "/api/ocr/extract",
        files={"file": ("homework.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 400
    assert "图片" in response.json()["detail"]


def test_prepare_image_limits_long_side():
    big = Image.new("RGB", (4000, 1000), "white")
    buffer = io.BytesIO()
    big.save(buffer, format="PNG")
    image = ocr.prepare_image(buffer.getvalue())
    assert max(image.size) == ocr.MAX_SIDE
    assert image.mode == "RGB"


def test_prepare_image_rejects_garbage():
    with pytest.raises(ocr.OcrError):
        ocr.prepare_image(b"definitely not an image")


def test_extract_rejects_empty_and_oversized():
    with pytest.raises(ocr.OcrError):
        ocr.extract(b"")
    with pytest.raises(ocr.OcrError):
        ocr.extract(b"0" * (ocr.MAX_BYTES + 1))


@pytest.mark.skipif(not ocr.available(), reason="未安装 rapidocr，跳过真实推理")
def test_extract_reads_printed_text():
    result = ocr.extract(_png(), filename="quiz.png")
    assert result["filename"] == "quiz.png"
    assert result["lines"], result
    assert "OCR" in result["text"].upper()
    assert result["elapsed_ms"] >= 0
    assert set(result) >= {"text", "lines", "width", "height", "low_confidence"}


@pytest.mark.skipif(not ocr.available(), reason="未安装 rapidocr，跳过真实推理")
def test_extract_endpoint_returns_text(client):
    response = client.post(
        "/api/ocr/extract",
        files={"file": ("quiz.png", _png(), "image/png")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "OCR" in payload["text"].upper()
    assert isinstance(payload["lines"], list)


def test_missing_dependency_returns_503(client, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)
    response = client.post(
        "/api/ocr/extract",
        files={"file": ("quiz.png", _png(), "image/png")},
    )
    assert response.status_code == 503
    assert "OCR" in response.json()["detail"]
