"""教师工作台 API：登录、班级、作业、统计与导出。"""
from __future__ import annotations

import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse

from ..llm import LLMError
from ..schemas import (
    AssignmentCreate, AssignmentUpdate, ClassCreate, ClassUpdate, PasswordChange,
    PracticeRequest, StudentPasswordReset, SubmissionGrade, TeacherLogin, TeacherRegister,
)
from ..services import auth, classes, roster, uploads
from .limits import rate_limit

router = APIRouter(tags=["teacher"])
auth.ensure_demo_teacher()


def _token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def current_teacher(request: Request) -> dict:
    teacher = auth.resolve(_token(request))
    if not teacher:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录。")
    return teacher


def _bad(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


# ---------------------------------------------------------------- 账号
@router.post("/teacher/register", dependencies=[rate_limit("register", 10)])
async def register(payload: TeacherRegister) -> dict:
    try:
        return auth.register(payload.username, payload.password, payload.name)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/teacher/login", dependencies=[rate_limit("login", 20)])
async def login(payload: TeacherLogin) -> dict:
    try:
        return auth.login(payload.username, payload.password)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/teacher/logout")
async def logout(request: Request) -> dict:
    auth.logout(_token(request))
    return {"ok": True}


@router.get("/teacher/me")
async def me(request: Request) -> dict:
    return {"teacher": current_teacher(request)}


@router.put("/teacher/password")
async def change_password(request: Request, payload: PasswordChange) -> dict:
    teacher = current_teacher(request)
    try:
        auth.change_password(teacher["id"], payload.old_password, payload.new_password)
    except ValueError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


# ---------------------------------------------------------------- 概览
@router.get("/teacher/overview")
async def overview(request: Request) -> dict:
    teacher = current_teacher(request)
    return classes.overview(teacher["id"])


# ---------------------------------------------------------------- 班级
@router.get("/teacher/classes")
async def list_classes(request: Request) -> dict:
    teacher = current_teacher(request)
    return {"items": classes.list_classes(teacher["id"])}


@router.post("/teacher/classes")
async def create_class(request: Request, payload: ClassCreate) -> dict:
    teacher = current_teacher(request)
    try:
        return {"class": classes.create_class(
            teacher["id"], name=payload.name, subject=payload.subject, grade=payload.grade,
        )}
    except ValueError as exc:
        raise _bad(exc) from exc


@router.get("/teacher/classes/{class_id}")
async def class_detail(request: Request, class_id: str) -> dict:
    teacher = current_teacher(request)
    try:
        return classes.class_detail(teacher["id"], class_id)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.patch("/teacher/classes/{class_id}")
async def update_class(request: Request, class_id: str, payload: ClassUpdate) -> dict:
    teacher = current_teacher(request)
    try:
        return {"class": classes.update_class(
            teacher["id"], class_id, name=payload.name, subject=payload.subject,
            grade=payload.grade, archived=payload.archived,
        )}
    except ValueError as exc:
        raise _bad(exc) from exc


@router.delete("/teacher/classes/{class_id}")
async def delete_class(request: Request, class_id: str) -> dict:
    teacher = current_teacher(request)
    try:
        return classes.delete_class(teacher["id"], class_id)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/teacher/classes/{class_id}/code")
async def refresh_code(request: Request, class_id: str) -> dict:
    teacher = current_teacher(request)
    try:
        return {"class": classes.regenerate_code(teacher["id"], class_id)}
    except ValueError as exc:
        raise _bad(exc) from exc


@router.delete("/teacher/classes/{class_id}/students/{student_id}")
async def remove_student(request: Request, class_id: str, student_id: str) -> dict:
    teacher = current_teacher(request)
    try:
        return classes.remove_student(teacher["id"], class_id, student_id)
    except ValueError as exc:
        raise _bad(exc) from exc


# ---------------------------------------------------------------- 名单与学号登录
@router.post("/teacher/classes/{class_id}/roster", dependencies=[rate_limit("roster", 20)])
async def import_roster(request: Request, class_id: str,
                        text: str = Form(""),
                        default_password: str = Form(""),
                        file: UploadFile | None = File(None)) -> dict:
    """导入学生名单：上传 CSV 或直接粘贴。返回一次性初始密码列表。"""
    teacher = current_teacher(request)
    content = text
    if file is not None:
        try:
            data = await uploads.read_upload(file, limit=2 * 1024 * 1024)
            content = roster.decode_roster(data)
        except (uploads.UploadError, roster.RosterError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not content.strip():
        raise HTTPException(status_code=400, detail="请上传 CSV 或粘贴名单内容。")
    try:
        return classes.import_roster(
            teacher["id"], class_id, text=content, default_password=default_password,
        )
    except ValueError as exc:
        raise _bad(exc) from exc


@router.get("/teacher/classes/{class_id}/roster.csv")
async def export_roster(request: Request, class_id: str) -> Response:
    teacher = current_teacher(request)
    try:
        filename, content = classes.roster_csv(teacher["id"], class_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _file(content, "text/csv; charset=utf-8", filename)


@router.post("/teacher/classes/{class_id}/students/{student_id}/password")
async def reset_student_password(request: Request, class_id: str, student_id: str,
                                 payload: StudentPasswordReset) -> dict:
    teacher = current_teacher(request)
    try:
        return classes.reset_student_password(
            teacher["id"], class_id, student_id, payload.password,
        )
    except ValueError as exc:
        raise _bad(exc) from exc


@router.get("/teacher/classes/{class_id}/export.csv")
async def export_class(request: Request, class_id: str) -> Response:
    teacher = current_teacher(request)
    try:
        filename, content = classes.class_csv(teacher["id"], class_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _file(content, "text/csv; charset=utf-8", filename)


@router.get("/teacher/classes/{class_id}/report.html")
async def class_report(request: Request, class_id: str) -> Response:
    """整班成绩报告：带统计图表的自包含 HTML。"""
    teacher = current_teacher(request)
    try:
        filename, content = classes.class_report(teacher["id"], class_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _file(content.encode("utf-8"), "text/html; charset=utf-8", filename)


# ---------------------------------------------------------------- 作业
@router.get("/teacher/assignments")
async def list_assignments(request: Request, class_id: str = "") -> dict:
    teacher = current_teacher(request)
    return {"items": classes.list_assignments(teacher["id"], class_id)}


@router.post("/teacher/assignments", dependencies=[rate_limit("teacher-generate", 40)])
async def create_assignment(request: Request, payload: AssignmentCreate) -> dict:
    teacher = current_teacher(request)
    try:
        assignment = await classes.create_assignment(
            teacher["id"], class_id=payload.class_id, title=payload.title, topic=payload.topic,
            kind=payload.kind, submission_mode=payload.submission_mode,
            count=payload.count, difficulty=payload.difficulty,
            due_at=payload.due_at, instructions=payload.instructions,
            rubric=payload.rubric, reveal=payload.reveal,
        )
    except ValueError as exc:
        raise _bad(exc) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"assignment": assignment}


@router.get("/teacher/assignments/{assignment_id}")
async def assignment_detail(request: Request, assignment_id: str) -> dict:
    teacher = current_teacher(request)
    try:
        return classes.assignment_detail(teacher["id"], assignment_id)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.patch("/teacher/assignments/{assignment_id}")
async def update_assignment(request: Request, assignment_id: str, payload: AssignmentUpdate) -> dict:
    teacher = current_teacher(request)
    try:
        return {"assignment": classes.update_assignment(
            teacher["id"], assignment_id, title=payload.title, instructions=payload.instructions,
            rubric=payload.rubric, due_at=payload.due_at, reveal=payload.reveal,
            closed=payload.closed,
        )}
    except ValueError as exc:
        raise _bad(exc) from exc


@router.delete("/teacher/assignments/{assignment_id}")
async def delete_assignment(request: Request, assignment_id: str) -> dict:
    teacher = current_teacher(request)
    try:
        return classes.delete_assignment(teacher["id"], assignment_id)
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/teacher/assignments/{assignment_id}/practice",
             dependencies=[rate_limit("teacher-generate", 40)])
async def practice(request: Request, assignment_id: str, payload: PracticeRequest) -> dict:
    teacher = current_teacher(request)
    try:
        assignment = await classes.practice_assignment(
            teacher["id"], assignment_id, count=payload.count,
            focus_points=payload.focus_points, due_at=payload.due_at,
        )
    except ValueError as exc:
        raise _bad(exc) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"assignment": assignment}


@router.get("/teacher/assignments/{assignment_id}/export.csv")
async def export_assignment(request: Request, assignment_id: str) -> Response:
    teacher = current_teacher(request)
    try:
        filename, content = classes.assignment_csv(teacher["id"], assignment_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _file(content, "text/csv; charset=utf-8", filename)


@router.get("/teacher/students/{student_id}/report.html")
async def student_report(request: Request, student_id: str) -> Response:
    teacher = current_teacher(request)
    try:
        filename, content = classes.student_report(teacher["id"], student_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    return _file(content.encode("utf-8"), "text/html; charset=utf-8", filename)


# ---------------------------------------------------------------- 提交与批改
@router.get("/teacher/submissions/{submission_id}")
async def submission_detail(request: Request, submission_id: str) -> dict:
    teacher = current_teacher(request)
    try:
        return {"submission": classes.submission_detail(teacher["id"], submission_id)}
    except ValueError as exc:
        raise _bad(exc) from exc


@router.patch("/teacher/submissions/{submission_id}")
async def grade_submission(request: Request, submission_id: str, payload: SubmissionGrade) -> dict:
    """教师复核：覆盖 AI 分数并保留修改记录，score 用百分制传入。"""
    teacher = current_teacher(request)
    try:
        return classes.regrade_submission(
            teacher["id"], submission_id,
            score=payload.score / 100,
            feedback=payload.feedback,
            note=payload.note,
        )
    except ValueError as exc:
        raise _bad(exc) from exc


@router.post("/teacher/submissions/{submission_id}/regrade-ai",
             dependencies=[rate_limit("teacher-generate", 40)])
async def regrade_submission_ai(request: Request, submission_id: str) -> dict:
    teacher = current_teacher(request)
    try:
        return await classes.regrade_submission_ai(teacher["id"], submission_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/teacher/submissions/{submission_id}/files/{file_id}")
async def download_submission_file(request: Request, submission_id: str, file_id: str):
    teacher = current_teacher(request)
    try:
        path, filename = classes.submission_file_for_teacher(teacher["id"], submission_id, file_id)
    except ValueError as exc:
        raise _bad(exc) from exc
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=filename)


def _file(content: bytes, media_type: str, filename: str) -> Response:
    quoted = quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )
