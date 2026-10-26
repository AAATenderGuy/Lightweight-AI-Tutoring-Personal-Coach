from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import store
from ..services import materials as service
from ..services import uploads
from .limits import rate_limit

router = APIRouter(tags=["materials"])


@router.get("/materials")
async def list_materials() -> dict:
    return {"items": service.list_materials()}


@router.post("/materials", dependencies=[rate_limit("upload", 30)])
async def upload_material(file: UploadFile = File(...)) -> dict:
    try:
        data = await uploads.read_upload(file, limit=service.MAX_BYTES)
    except uploads.UploadError as exc:
        status = 413 if "太大" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    try:
        item = service.create(file.filename or "upload.txt", data)
    except service.MaterialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": item["id"],
        "title": item["title"],
        "filename": item["filename"],
        "chars": item["chars"],
        "chunks": len(item["chunks"]),
        "preview": item["preview"],
        "created_at": item["created_at"],
    }


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str) -> dict:
    if not store.delete_item("materials", material_id):
        raise HTTPException(status_code=404, detail="资料不存在或已删除。")
    return {"ok": True}
