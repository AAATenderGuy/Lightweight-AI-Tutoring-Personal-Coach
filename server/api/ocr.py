"""拍题 OCR 接口（P2 · S5）。"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from ..services import ocr, uploads
from .limits import rate_limit

router = APIRouter(tags=["ocr"])


@router.get("/ocr/status")
async def ocr_status() -> dict:
    ready = ocr.available()
    return {
        "available": ready,
        "engine": "rapidocr" if ready else "",
        "max_mb": ocr.MAX_BYTES // 1024 // 1024,
        "low_score": ocr.LOW_SCORE,
    }


@router.post("/ocr/extract", dependencies=[rate_limit("ocr", 20)])
async def extract(file: UploadFile = File(...)) -> dict:
    if not ocr.available():
        raise HTTPException(status_code=503, detail="OCR 组件未安装，无法识别图片。")
    suffix = uploads.suffix_of(file.filename or "")
    if suffix not in uploads.IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="只支持 JPG / PNG / WEBP 图片。")
    try:
        data = await uploads.read_upload(file, limit=ocr.MAX_BYTES)
    except uploads.UploadError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    try:
        # 推理是 CPU 密集的（一张作业照片约 1–3 秒），放线程池，别卡住 SSE。
        return await run_in_threadpool(ocr.extract, data, filename=file.filename or "")
    except ocr.OcrError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
