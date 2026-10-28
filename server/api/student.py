"""学生端：加入班级、查看任务、在线作答、提交附件与回看结果。

学生身份 = student_id + 入班时签发的 token；token 由本机密钥 HMAC 生成，
换设备重新用「邀请码 + 姓名 + 学号」加入会复用档案并拿到新 token。
"""
from __future__ import annotations

import mimetypes

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..schemas import JoinRequest, StudentIdRequest, StudentLogin, StudentSubmitRequest
from ..services import classes, identity, learning, mastery, uploads
from .limits import rate_limit

router = APIRouter(tags=["student"])


def _bad(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


def _auth(student_id: str, token: str) -> None:
    if not identity.verify(student_id, token):
        raise HTTPException(status_code=401, detail="学生身份已失效，请重新加入班级。")


@router.post("/student/login", dependencies=[rate_limit("student-login", 30)])
async def login(payload: StudentLogin) -> dict:
    try:
        return classes.student_login(payload.number, payload.password, payload.code)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/student/join", dependencies=[rate_limit("join", 30)])
async def join(payload: JoinRequest) -> dict:
    try:
        return classes.join(payload.code, payload.name, payload.number)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.get("/student/tasks")
async def tasks(student_id: str, token: str = "") -> dict:
    _auth(student_id, token)
    try:
        return classes.student_tasks(student_id)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/student/tasks/{assignment_id}/start")
async def start(assignment_id: str, payload: StudentIdRequest) -> dict:
    _auth(payload.student_id, payload.token)
    try:
        return classes.start_task(assignment_id, payload.student_id)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.get("/student/tasks/{assignment_id}/result")
async def result(assignment_id: str, student_id: str, token: str = "") -> dict:
    _auth(student_id, token)
    try:
        return classes.task_result(assignment_id, student_id)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/student/tasks/{assignment_id}/submit", dependencies=[rate_limit("submit", 60)])
async def submit(assignment_id: str, payload: StudentSubmitRequest) -> dict:
    _auth(payload.student_id, payload.token)
    try:
        return await classes.submit_task(
            assignment_id, payload.student_id, [item.model_dump() for item in payload.answers],
        )
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/student/tasks/{assignment_id}/submit-file", dependencies=[rate_limit("submit-file", 30)])
async def submit_file(assignment_id: str, student_id: str = Form(...), token: str = Form(""),
                      note: str = Form(""), file: UploadFile = File(...)) -> dict:
    _auth(student_id, token)
    try:
        data = await uploads.read_upload(file)
    except uploads.UploadError as exc:
        status = 413 if "太大" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    try:
        return await classes.submit_file(
            assignment_id, student_id,
            filename=file.filename or "作业.txt", data=data, note=note,
        )
    except uploads.UploadError as exc:
        raise _bad(exc) from exc
    except ValueError as exc:
        raise _bad(exc) from exc


@router.get("/student/timeline")
async def timeline(student_id: str, token: str = "") -> dict:
    """学习轨迹：这名学生的事件时间线 + 从事件流聚合出的掌握度。"""
    _auth(student_id, token)
    progress = mastery.student_progress(student_id)
    return {
        "events": learning.student_timeline(student_id),
        "topics": progress["topics"],
        "stats": progress["stats"],
    }


@router.get("/student/submissions/{submission_id}/files/{file_id}")
async def download_file(submission_id: str, file_id: str, student_id: str, token: str = ""):
    _auth(student_id, token)
    try:
        path, filename = classes.submission_file_for_student(student_id, submission_id, file_id)
    except (ValueError, uploads.UploadError) as exc:
        raise _bad(exc) from exc
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=filename)
