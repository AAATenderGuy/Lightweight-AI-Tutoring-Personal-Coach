"""班级、学生、作业与提交。

全部基于 data/ 下的 JSON：没有数据库，也没有后台任务。
一次作业的提交单独存成一条记录，id 由「作业 + 学生」决定，
所以重复提交是覆盖而不是堆积。
"""
from __future__ import annotations

import asyncio
import secrets
import shutil
import time
from statistics import mean

from .. import store
from . import grading as grading_service
from . import identity
from . import quiz as quiz_service
from . import reports
from . import roster as roster_service
from . import uploads
from .events import bus

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
KINDS = ("quiz", "homework")
SUBMISSION_MODES = ("quiz", "file")

# 同一份提交的读改写要串行：学生双开标签页同时交卷时，attempts 不能丢。
_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


def _submission_id(assignment_id: str, student_id: str) -> str:
    return f"sb_{assignment_id}_{student_id}"


# ---------------------------------------------------------------- 小工具
def _text(value: object, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _new_code() -> str:
    used = {str(item.get("code") or "").upper() for item in store.list_items("classes")}
    while True:
        code = "".join(CODE_ALPHABET[byte % len(CODE_ALPHABET)] for byte in secrets.token_bytes(6))
        if code not in used:
            return code


def _classes_of(teacher_id: str) -> list[dict]:
    items = [item for item in store.list_items("classes") if item.get("teacher_id") == teacher_id]
    items.sort(key=lambda item: (bool(item.get("archived")), -float(item.get("created_at") or 0)))
    return items


def _own_class(teacher_id: str, class_id: str) -> dict:
    klass = store.load_item("classes", class_id)
    if not klass or klass.get("teacher_id") != teacher_id:
        raise ValueError("班级不存在，或不属于当前账号。")
    return klass


def _students_of(class_id: str) -> list[dict]:
    items = [item for item in store.list_items("students") if item.get("class_id") == class_id]
    items.sort(key=lambda item: float(item.get("created_at") or 0))
    return items


def _assignments_of(class_id: str) -> list[dict]:
    items = [item for item in store.list_items("assignments") if item.get("class_id") == class_id]
    items.sort(key=lambda item: -float(item.get("created_at") or 0))
    return items


def _submissions_of(assignment_id: str) -> list[dict]:
    items = [item for item in store.list_items("submissions") if item.get("assignment_id") == assignment_id]
    items.sort(key=lambda item: float(item.get("submitted_at") or 0))
    return items


def _submission_of(assignment_id: str, student_id: str) -> dict | None:
    return store.load_item("submissions", f"sb_{assignment_id}_{student_id}")


def _load_quiz(assignment: dict) -> dict:
    quiz_id = assignment.get("quiz_id") or ""
    if not quiz_id:
        return {}
    return store.load_item("quizzes", quiz_id) or {}


def _avg(values: list[float]) -> float:
    return round(mean(values), 3) if values else 0.0


def _due_state(assignment: dict) -> str:
    due = _number(assignment.get("due_at"))
    if assignment.get("closed"):
        return "closed"
    if due and due < time.time():
        return "expired"
    return "open"


def _progress(assignment: dict, students: list[dict], submissions: list[dict]) -> dict:
    total = len(students)
    scored = [_number(item.get("score")) for item in submissions if item.get("score") is not None]
    return {
        "submitted": len(submissions),
        "total": total,
        "completion": round(len(submissions) / total, 3) if total else 0.0,
        "avg_score": _avg(scored),
    }


def _assignment_public(assignment: dict, *, class_name: str = "", students: list[dict] | None = None,
                       submissions: list[dict] | None = None) -> dict:
    students = students if students is not None else _students_of(assignment["class_id"])
    submissions = submissions if submissions is not None else _submissions_of(assignment["id"])
    return {
        "id": assignment.get("id"),
        "class_id": assignment.get("class_id"),
        "class_name": class_name,
        "title": assignment.get("title"),
        "kind": assignment.get("kind", "homework"),
        "submission_mode": assignment.get("submission_mode", "quiz"),
        "topic": assignment.get("topic"),
        "question_count": assignment.get("question_count", 0),
        "difficulty": assignment.get("difficulty", "medium"),
        "instructions": assignment.get("instructions", ""),
        "rubric": assignment.get("rubric", ""),
        "due_at": _number(assignment.get("due_at")),
        "reveal": bool(assignment.get("reveal", True)),
        "closed": bool(assignment.get("closed")),
        "state": _due_state(assignment),
        "created_at": assignment.get("created_at"),
        **_progress(assignment, students, submissions),
    }


def _student_public(student: dict) -> dict:
    return {
        "id": student.get("id"),
        "name": student.get("name"),
        "number": student.get("number", ""),
        "class_id": student.get("class_id"),
        "created_at": student.get("created_at"),
        "last_seen": student.get("last_seen"),
        "last_login": student.get("last_login"),
        "has_password": bool(student.get("password_hash")),
    }


# ---------------------------------------------------------------- 班级
def list_classes(teacher_id: str) -> list[dict]:
    all_submissions = store.list_items("submissions")
    result = []
    for klass in _classes_of(teacher_id):
        students = _students_of(klass["id"])
        assignments = _assignments_of(klass["id"])
        ids = {item["id"] for item in assignments}
        scored = [_number(item.get("score")) for item in all_submissions if item.get("assignment_id") in ids]
        submitted = len([item for item in all_submissions if item.get("assignment_id") in ids])
        result.append({
            "id": klass["id"],
            "name": klass.get("name"),
            "subject": klass.get("subject", ""),
            "grade": klass.get("grade", ""),
            "code": klass.get("code"),
            "archived": bool(klass.get("archived")),
            "created_at": klass.get("created_at"),
            "student_count": len(students),
            "assignment_count": len(assignments),
            "open_count": len([item for item in assignments if _due_state(item) == "open"]),
            "submitted": submitted,
            "avg_score": _avg(scored),
        })
    return result


def create_class(teacher_id: str, *, name: str, subject: str = "", grade: str = "") -> dict:
    name = _text(name, 40)
    if not name:
        raise ValueError("班级名称不能为空。")
    klass = store.save_item("classes", {
        "id": store.new_id("cl_"),
        "teacher_id": teacher_id,
        "name": name,
        "subject": _text(subject, 40),
        "grade": _text(grade, 40),
        "code": _new_code(),
        "archived": False,
        "created_at": time.time(),
    })
    bus.publish(f"teacher:{teacher_id}", "class_changed", class_id=klass["id"])
    return _class_public(klass)


def _class_public(klass: dict) -> dict:
    students = _students_of(klass["id"])
    assignments = _assignments_of(klass["id"])
    return {
        "id": klass["id"],
        "name": klass.get("name"),
        "subject": klass.get("subject", ""),
        "grade": klass.get("grade", ""),
        "code": klass.get("code"),
        "archived": bool(klass.get("archived")),
        "created_at": klass.get("created_at"),
        "student_count": len(students),
        "assignment_count": len(assignments),
    }


def update_class(teacher_id: str, class_id: str, *, name: str | None = None,
                 subject: str | None = None, grade: str | None = None,
                 archived: bool | None = None) -> dict:
    klass = _own_class(teacher_id, class_id)
    if name is not None and name.strip():
        klass["name"] = _text(name, 40)
    if subject is not None:
        klass["subject"] = _text(subject, 40)
    if grade is not None:
        klass["grade"] = _text(grade, 40)
    if archived is not None:
        klass["archived"] = bool(archived)
    store.save_item("classes", klass)
    bus.publish(f"teacher:{teacher_id}", "class_changed", class_id=klass["id"])
    return _class_public(klass)


def regenerate_code(teacher_id: str, class_id: str) -> dict:
    klass = _own_class(teacher_id, class_id)
    klass["code"] = _new_code()
    store.save_item("classes", klass)
    bus.publish(f"teacher:{teacher_id}", "class_changed", class_id=klass["id"])
    return _class_public(klass)


def delete_class(teacher_id: str, class_id: str) -> dict:
    klass = _own_class(teacher_id, class_id)
    assignments = _assignments_of(class_id)
    for assignment in assignments:
        for submission in _submissions_of(assignment["id"]):
            store.delete_item("submissions", submission["id"])
        store.delete_item("assignments", assignment["id"])
        shutil.rmtree(uploads.UPLOAD_ROOT / assignment["id"], ignore_errors=True)
    for student in _students_of(class_id):
        store.delete_item("students", student["id"])
    store.delete_item("classes", klass["id"])
    bus.publish(f"class:{class_id}", "class_deleted", class_id=class_id)
    bus.publish(f"teacher:{teacher_id}", "class_changed", class_id=klass["id"], removed=True)
    return {"ok": True, "assignments": len(assignments)}


def class_detail(teacher_id: str, class_id: str) -> dict:
    klass = _own_class(teacher_id, class_id)
    students = _students_of(class_id)
    assignments = _assignments_of(class_id)
    all_submissions = store.list_items("submissions")

    per_student: dict[str, list[float]] = {}
    for item in all_submissions:
        if item.get("class_id") != class_id:
            continue
        per_student.setdefault(str(item.get("student_id")), []).append(_number(item.get("score")))

    assignment_items = []
    for assignment in assignments:
        submissions = [item for item in all_submissions if item.get("assignment_id") == assignment["id"]]
        assignment_items.append(_assignment_public(
            assignment, class_name=klass.get("name", ""), students=students, submissions=submissions,
        ))

    student_items = []
    for student in students:
        scores = per_student.get(student["id"], [])
        student_items.append({
            **_student_public(student),
            "submitted": len(scores),
            "avg_score": _avg(scores),
        })

    all_scores = [score for scores in per_student.values() for score in scores]
    return {
        "class": _class_public(klass),
        "students": student_items,
        "assignments": assignment_items,
        "stats": {
            "students": len(students),
            "assignments": len(assignments),
            "submissions": len(all_scores),
            "avg_score": _avg(all_scores),
        },
    }


def remove_student(teacher_id: str, class_id: str, student_id: str) -> dict:
    _own_class(teacher_id, class_id)
    student = store.load_item("students", student_id)
    if not student or student.get("class_id") != class_id:
        raise ValueError("学生不在这个班级里。")
    for assignment in _assignments_of(class_id):
        submission = _submission_of(assignment["id"], student_id)
        if submission:
            for item in submission.get("files") or []:
                try:
                    uploads.resolve(item.get("rel", "")).unlink()
                except (OSError, ValueError):
                    pass
            store.delete_item("submissions", submission["id"])
    store.delete_item("students", student_id)
    bus.publish(f"class:{class_id}", "student_left",
                student_id=student_id, name=student.get("name"))
    bus.publish(f"teacher:{teacher_id}", "student_left",
                class_id=class_id, student_id=student_id, name=student.get("name"))
    bus.publish(f"student:{student_id}", "student_gone", class_id=class_id)
    return {"ok": True}


# ---------------------------------------------------------------- 学生加入
def join(code: str, name: str, number: str = "") -> dict:
    code = _text(code, 12).upper()
    name = _text(name, 20)
    number = _text(number, 20)
    if not code:
        raise ValueError("请填写班级邀请码。")
    if not name:
        raise ValueError("请填写姓名或昵称。")
    klass = None
    for item in store.list_items("classes"):
        if str(item.get("code") or "").upper() == code:
            klass = item
            break
    if not klass:
        raise ValueError("邀请码不存在，请向老师确认。")
    if klass.get("archived"):
        raise ValueError("这个班级已归档，暂不接收新同学。")
    if any(item.get("password_hash") for item in _students_of(klass["id"])):
        raise ValueError("这个班已启用学号登录，请用学号 + 密码登录。")

    existing = None
    for student in _students_of(klass["id"]):
        if student.get("name") == name and str(student.get("number") or "") == number:
            existing = student
            break
    if existing:
        existing["last_seen"] = time.time()
        store.save_item("students", existing)
        student = existing
    else:
        student = store.save_item("students", {
            "id": store.new_id("st_"),
            "class_id": klass["id"],
            "name": name,
            "number": number,
            "created_at": time.time(),
            "last_seen": time.time(),
        })
    teacher = store.load_item("teachers", klass.get("teacher_id") or "")
    bus.publish(f"class:{klass['id']}", "student_joined",
                student_id=student["id"], name=student.get("name"), returning=bool(existing))
    if klass.get("teacher_id"):
        bus.publish(f"teacher:{klass['teacher_id']}", "student_joined",
                    class_id=klass["id"], student_id=student["id"],
                    name=student.get("name"), returning=bool(existing))
    return {
        "student": _student_public(student),
        "token": identity.student_token(student["id"]),
        "klass": {
            "id": klass["id"],
            "name": klass.get("name"),
            "subject": klass.get("subject", ""),
            "code": klass.get("code"),
            "teacher_name": (teacher or {}).get("name") or "任课教师",
        },
    }


def student_tasks(student_id: str) -> dict:
    student = store.load_item("students", student_id)
    if not student:
        raise ValueError("学生档案不存在，请重新加入班级。")
    klass = store.load_item("classes", student.get("class_id") or "")
    if not klass:
        raise ValueError("班级已被删除，请向老师要新的邀请码。")
    teacher = store.load_item("teachers", klass.get("teacher_id") or "")
    tasks = []
    for assignment in _assignments_of(klass["id"]):
        submission = _submission_of(assignment["id"], student_id)
        state = _due_state(assignment)
        if submission:
            status = "done"
        elif state == "open":
            status = "todo"
        else:
            status = "missed"
        tasks.append({
            **_assignment_public(assignment, class_name=klass.get("name", "")),
            "status": status,
            "score": _number(submission.get("score")) if submission else None,
            "submitted_at": submission.get("submitted_at") if submission else None,
            "attempts": int(submission.get("attempts") or 0) if submission else 0,
        })
    tasks.sort(key=lambda item: (item["status"] == "done", -float(item.get("created_at") or 0)))
    return {
        "student": _student_public(student),
        "klass": {
            "id": klass["id"],
            "name": klass.get("name"),
            "subject": klass.get("subject", ""),
            "code": klass.get("code"),
            "teacher_name": (teacher or {}).get("name") or "任课教师",
        },
        "tasks": tasks,
    }


# ---------------------------------------------------------------- 名单与学号登录
def import_roster(teacher_id: str, class_id: str, *, text: str, default_password: str = "") -> dict:
    """教师导入名单：学号 + 姓名 + 初始密码；已存在的学号会重置密码并保留提交记录。"""
    klass = _own_class(teacher_id, class_id)
    parsed = roster_service.parse_roster(text)
    if default_password and len(default_password) < 4:
        raise ValueError("默认密码至少 4 位。")
    existing = {str(item.get("number") or "").strip(): item for item in _students_of(class_id)}
    credentials: list[dict] = []
    created = updated = 0
    now = time.time()
    for row in parsed["rows"]:
        number = row["number"]
        password = row["password"] or default_password or roster_service.generate_password()
        if len(password) < 4:
            password = roster_service.generate_password()
        salt, digest = roster_service.hash_password(password)
        current = existing.get(number)
        if current:
            current.update({
                "name": row["name"],
                "salt": salt,
                "password_hash": digest,
                "password_set_at": now,
                "roster_imported_at": now,
            })
            store.save_item("students", current)
            updated += 1
        else:
            student = store.save_item("students", {
                "id": store.new_id("st_"),
                "class_id": class_id,
                "name": row["name"],
                "number": number,
                "salt": salt,
                "password_hash": digest,
                "password_set_at": now,
                "roster_imported_at": now,
                "created_at": now,
                "last_seen": 0,
            })
            existing[number] = student
            created += 1
        credentials.append({"number": number, "name": row["name"], "password": password})
    bus.publish(f"teacher:{teacher_id}", "class_changed", class_id=class_id)
    bus.publish(f"class:{class_id}", "roster_changed", class_id=class_id, count=len(credentials))
    return {
        "class": _class_public(klass),
        "created": created,
        "updated": updated,
        "total": len(credentials),
        "errors": parsed["errors"],
        "duplicates": parsed["duplicates"],
        "credentials": credentials,
    }


def student_login(number: str, password: str, code: str = "") -> dict:
    """学号 + 密码登录；同一学号在多个班时要求再填班级邀请码。"""
    number = _text(number, 32)
    code = _text(code, 12).upper()
    if not number or not password:
        raise ValueError("请填写学号和密码。")
    candidates: list[tuple[dict, dict]] = []
    for student in store.list_items("students"):
        if str(student.get("number") or "").strip() != number:
            continue
        klass = store.load_item("classes", student.get("class_id") or "")
        if not klass or klass.get("archived"):
            continue
        if code and str(klass.get("code") or "").upper() != code:
            continue
        candidates.append((student, klass))
    if not candidates:
        raise ValueError("学号或密码不正确。")
    matched = [
        (student, klass) for student, klass in candidates
        if roster_service.verify_password(
            password, str(student.get("salt") or ""), str(student.get("password_hash") or ""),
        )
    ]
    if not matched:
        raise ValueError("学号或密码不正确。")
    if len(matched) > 1:
        names = "、".join(str(klass.get("name") or "") for _, klass in matched[:3])
        raise ValueError(f"这个学号在多个班级里（{names}），请填写班级邀请码后再登录。")
    student, _klass = matched[0]
    student["last_seen"] = time.time()
    student["last_login"] = time.time()
    store.save_item("students", student)
    payload = student_tasks(student["id"])
    payload["token"] = identity.student_token(student["id"])
    return payload


def reset_student_password(teacher_id: str, class_id: str, student_id: str, password: str = "") -> dict:
    _own_class(teacher_id, class_id)
    student = store.load_item("students", student_id)
    if not student or student.get("class_id") != class_id:
        raise ValueError("学生不在这个班级里。")
    new_password = str(password or "").strip() or roster_service.generate_password()
    if len(new_password) < 4:
        raise ValueError("密码至少 4 位。")
    salt, digest = roster_service.hash_password(new_password)
    student.update({"salt": salt, "password_hash": digest, "password_set_at": time.time()})
    store.save_item("students", student)
    bus.publish(f"teacher:{teacher_id}", "class_changed", class_id=class_id)
    return {"ok": True, "student": _student_public(student), "password": new_password}


def roster_csv(teacher_id: str, class_id: str) -> tuple[str, bytes]:
    klass = _own_class(teacher_id, class_id)
    students = _students_of(class_id)
    rows = [["学号", "姓名", "密码状态", "最后登录"]]
    for student in students:
        last = student.get("last_login") or student.get("last_seen") or 0
        rows.append([
            str(student.get("number") or ""),
            str(student.get("name") or ""),
            "已设置" if student.get("password_hash") else "未设置",
            time.strftime("%Y-%m-%d %H:%M", time.localtime(float(last))) if last else "",
        ])
    safe_name = str(klass.get("name") or "班级").replace("/", "_").replace("\\", "_")
    return f"{safe_name}-学生名单.csv", reports._csv(rows)


# ---------------------------------------------------------------- 作业
def list_assignments(teacher_id: str, class_id: str = "") -> list[dict]:
    class_map = {item["id"]: item for item in _classes_of(teacher_id)}
    all_submissions = store.list_items("submissions")
    items = []
    for assignment in store.list_items("assignments"):
        if assignment.get("teacher_id") != teacher_id:
            continue
        if class_id and assignment.get("class_id") != class_id:
            continue
        klass = class_map.get(assignment.get("class_id") or "")
        if not klass:
            continue
        students = _students_of(klass["id"])
        submissions = [item for item in all_submissions if item.get("assignment_id") == assignment["id"]]
        items.append(_assignment_public(
            assignment, class_name=klass.get("name", ""), students=students, submissions=submissions,
        ))
    items.sort(key=lambda item: -float(item.get("created_at") or 0))
    return items


async def create_assignment(teacher_id: str, *, class_id: str, title: str, topic: str,
                            kind: str = "homework", submission_mode: str = "quiz",
                            count: int = 4, difficulty: str = "medium",
                            due_at: float = 0.0, instructions: str = "",
                            rubric: str = "", reveal: bool = True) -> dict:
    klass = _own_class(teacher_id, class_id)
    topic = _text(topic, 120)
    if not topic:
        raise ValueError("请填写作业主题。")
    kind = kind if kind in KINDS else "homework"
    submission_mode = submission_mode if submission_mode in SUBMISSION_MODES else "quiz"
    count = max(1, min(8, int(count or 4)))
    if submission_mode == "file":
        quiz_id = ""
        question_count = 0
        default_title = f"{topic} · 作业"
    else:
        quiz = await quiz_service.generate(topic=topic, material_ids=[], count=count, difficulty=difficulty)
        stored = store.load_item("quizzes", quiz["id"]) or {}
        quiz_id = quiz["id"]
        question_count = len(stored.get("questions") or [])
        default_title = quiz.get("title") or f"{topic} · 作业"
    assignment = store.save_item("assignments", {
        "id": store.new_id("as_"),
        "class_id": class_id,
        "teacher_id": teacher_id,
        "title": _text(title, 80) or default_title,
        "kind": kind,
        "submission_mode": submission_mode,
        "topic": topic,
        "quiz_id": quiz_id,
        "question_count": question_count,
        "difficulty": difficulty,
        "instructions": _text(instructions, 300),
        "rubric": _text(rubric, 1500),
        "due_at": max(0.0, float(due_at or 0)),
        "reveal": bool(reveal),
        "closed": False,
        "created_at": time.time(),
    })
    bus.publish(f"class:{class_id}", "assignment_created",
                assignment_id=assignment["id"], title=assignment["title"])
    bus.publish(f"teacher:{teacher_id}", "assignment_created",
                class_id=class_id, assignment_id=assignment["id"], title=assignment["title"])
    return _assignment_public(assignment, class_name=klass.get("name", ""))


def update_assignment(teacher_id: str, assignment_id: str, *, title: str | None = None,
                      instructions: str | None = None, rubric: str | None = None,
                      due_at: float | None = None,
                      reveal: bool | None = None, closed: bool | None = None) -> dict:
    assignment = store.load_item("assignments", assignment_id)
    if not assignment or assignment.get("teacher_id") != teacher_id:
        raise ValueError("作业不存在。")
    if title is not None and title.strip():
        assignment["title"] = _text(title, 80)
    if instructions is not None:
        assignment["instructions"] = _text(instructions, 300)
    if rubric is not None:
        assignment["rubric"] = _text(rubric, 1500)
    if due_at is not None:
        assignment["due_at"] = max(0.0, float(due_at))
    if reveal is not None:
        assignment["reveal"] = bool(reveal)
    if closed is not None:
        assignment["closed"] = bool(closed)
    store.save_item("assignments", assignment)
    bus.publish(f"class:{assignment['class_id']}", "assignment_updated",
                assignment_id=assignment["id"], title=assignment.get("title"))
    bus.publish(f"teacher:{teacher_id}", "assignment_updated",
                class_id=assignment["class_id"], assignment_id=assignment["id"],
                title=assignment.get("title"))
    klass = store.load_item("classes", assignment["class_id"]) or {}
    return _assignment_public(assignment, class_name=klass.get("name", ""))


def delete_assignment(teacher_id: str, assignment_id: str) -> dict:
    assignment = store.load_item("assignments", assignment_id)
    if not assignment or assignment.get("teacher_id") != teacher_id:
        raise ValueError("作业不存在。")
    class_id = assignment.get("class_id") or ""
    for submission in _submissions_of(assignment_id):
        store.delete_item("submissions", submission["id"])
    store.delete_item("assignments", assignment_id)
    shutil.rmtree(uploads.UPLOAD_ROOT / assignment_id, ignore_errors=True)
    if class_id:
        bus.publish(f"class:{class_id}", "assignment_deleted", assignment_id=assignment_id)
    bus.publish(f"teacher:{teacher_id}", "assignment_deleted",
                class_id=class_id, assignment_id=assignment_id)
    return {"ok": True}


def assignment_detail(teacher_id: str, assignment_id: str) -> dict:
    assignment = store.load_item("assignments", assignment_id)
    if not assignment or assignment.get("teacher_id") != teacher_id:
        raise ValueError("作业不存在。")
    klass = store.load_item("classes", assignment["class_id"]) or {}
    students = _students_of(assignment["class_id"])
    submissions = _submissions_of(assignment_id)
    by_student = {str(item.get("student_id")): item for item in submissions}
    quiz = _load_quiz(assignment)
    questions = quiz.get("questions") or []

    question_stats = []
    for index, question in enumerate(questions):
        answered = wrong = 0
        for submission in submissions:
            result = next(
                (item for item in (submission.get("results") or [])
                 if str(item.get("question_id")) == str(question.get("id"))),
                None,
            )
            if not result:
                continue
            if str(result.get("submitted") or "").strip() == "":
                continue
            answered += 1
            if not result.get("correct"):
                wrong += 1
        correct_text = ""
        if question.get("type") == "single":
            options = question.get("options") or []
            idx = int(question.get("answer_index") or 0)
            if 0 <= idx < len(options):
                correct_text = f"{'ABCDEF'[idx]}. {options[idx]}"
        else:
            correct_text = str(question.get("answer") or "")
        question_stats.append({
            "index": index + 1,
            "id": question.get("id"),
            "question": question.get("question"),
            "type": question.get("type"),
            "knowledge_point": question.get("knowledge_point", ""),
            "correct_text": correct_text,
            "explanation": question.get("explanation", ""),
            "answered": answered,
            "wrong": wrong,
            "error_rate": round(wrong / answered, 3) if answered else 0.0,
        })

    knowledge: dict[str, dict] = {}
    for submission in submissions:
        for result in submission.get("results") or []:
            point = str(result.get("knowledge_point") or "未标注知识点")[:60]
            entry = knowledge.setdefault(point, {"point": point, "attempts": 0, "wrong": 0, "scores": []})
            entry["attempts"] += 1
            entry["scores"].append(_number(result.get("score")))
            if not result.get("correct"):
                entry["wrong"] += 1
    knowledge_items = []
    for entry in knowledge.values():
        knowledge_items.append({
            "point": entry["point"],
            "attempts": entry["attempts"],
            "wrong": entry["wrong"],
            "error_rate": round(entry["wrong"] / entry["attempts"], 3) if entry["attempts"] else 0.0,
            "avg_score": _avg(entry["scores"]),
        })
    knowledge_items.sort(key=lambda item: (-item["error_rate"], -item["wrong"]))

    submission_items = []
    for submission in submissions:
        ai = submission.get("ai") or {}
        submission_items.append({
            "id": submission.get("id"),
            "student_id": submission.get("student_id"),
            "student_name": submission.get("student_name"),
            "number": next((s.get("number", "") for s in students if s["id"] == submission.get("student_id")), ""),
            "kind": submission.get("kind", "quiz"),
            "score": _number(submission.get("score")),
            "correct_count": int(submission.get("correct_count") or 0),
            "total": int(submission.get("total") or 0),
            "attempts": int(submission.get("attempts") or 0),
            "submitted_at": submission.get("submitted_at"),
            "files": submission.get("files") or [],
            "note": submission.get("note", ""),
            "text_chars": len(submission.get("text") or ""),
            "ai_score": submission.get("ai_score"),
            "ai_feedback": ai.get("feedback", ""),
            "ai_demo": bool(ai.get("demo")),
            "ai_model": ai.get("model", ""),
            "teacher_score": submission.get("teacher_score"),
            "teacher_feedback": submission.get("teacher_feedback", ""),
            "teacher_note": submission.get("teacher_note", ""),
            "graded_by": submission.get("graded_by", ""),
            "graded_at": submission.get("graded_at"),
            "needs_review": bool(submission.get("needs_review") or ai.get("needs_review")),
        })
    submission_items.sort(key=lambda item: -item["score"])
    missing = [
        {"id": student["id"], "name": student.get("name"), "number": student.get("number", "")}
        for student in students if student["id"] not in by_student
    ]
    graded_ai = sum(1 for item in submission_items if item["ai_score"] is not None)
    graded_teacher = sum(1 for item in submission_items if item["teacher_score"] is not None)
    pending_review = sum(1 for item in submission_items if item["needs_review"])

    return {
        **_assignment_public(
            assignment, class_name=klass.get("name", ""), students=students, submissions=submissions,
        ),
        "questions": question_stats,
        "knowledge": knowledge_items,
        "submissions": submission_items,
        "missing": missing,
        "graded_ai": graded_ai,
        "graded_teacher": graded_teacher,
        "needs_review_count": pending_review,
    }


async def practice_assignment(teacher_id: str, assignment_id: str, *,
                              count: int = 4, focus_points: list[str] | None = None,
                              due_at: float = 0.0) -> dict:
    assignment = store.load_item("assignments", assignment_id)
    if not assignment or assignment.get("teacher_id") != teacher_id:
        raise ValueError("作业不存在。")
    if assignment.get("submission_mode") == "file":
        raise ValueError("文件作业不支持薄弱点补练，请改用新的文件作业。")
    quiz = _load_quiz(assignment)
    if not quiz:
        raise ValueError("原作业的题目已不存在，无法生成补练。")
    focus = [_text(point, 60) for point in (focus_points or []) if _text(point, 60)][:4]
    new_quiz = await quiz_service.similar(quiz, count=max(1, min(8, count)), focus_points=focus)
    klass = store.load_item("classes", assignment["class_id"]) or {}
    new_assignment = store.save_item("assignments", {
        "id": store.new_id("as_"),
        "class_id": assignment["class_id"],
        "teacher_id": teacher_id,
        "title": f"{assignment.get('title')} · 薄弱点补练",
        "kind": "homework",
        "topic": assignment.get("topic"),
        "quiz_id": new_quiz["id"],
        "question_count": len(new_quiz.get("questions") or []),
        "difficulty": assignment.get("difficulty") or "medium",
        "instructions": (
            f"针对 {('、'.join(focus))} 的补练，题目难度与原作业一致。"
            if focus else "根据原作业错题自动生成的补练。"
        ),
        "due_at": max(0.0, float(due_at or 0)),
        "reveal": True,
        "closed": False,
        "created_at": time.time(),
    })
    return _assignment_public(new_assignment, class_name=klass.get("name", ""))


# ---------------------------------------------------------------- 学生作答
def _task_assignment(assignment_id: str, student_id: str) -> tuple[dict, dict, dict]:
    student = store.load_item("students", student_id)
    if not student:
        raise ValueError("学生档案不存在，请重新加入班级。")
    assignment = store.load_item("assignments", assignment_id)
    if not assignment:
        raise ValueError("作业不存在或已被删除。")
    if assignment.get("class_id") != student.get("class_id"):
        raise ValueError("这份作业不属于你所在的班级。")
    return assignment, student, _load_quiz(assignment)


def start_task(assignment_id: str, student_id: str) -> dict:
    assignment, student, quiz = _task_assignment(assignment_id, student_id)
    if _due_state(assignment) != "open":
        raise ValueError("这份作业已截止或已关闭，不能再作答。")
    submission = _submission_of(assignment_id, student_id)
    if assignment.get("submission_mode") == "file":
        return {
            "assignment": _assignment_public(assignment),
            "quiz": None,
            "submitted": bool(submission),
            "attempts": int((submission or {}).get("attempts") or 0),
            "files": (submission or {}).get("files") or [],
        }
    if not quiz:
        raise ValueError("题目已丢失，请联系老师重新布置。")
    return {
        "assignment": _assignment_public(assignment),
        "quiz": quiz_service.public_quiz(quiz),
        "submitted": bool(submission),
        "attempts": int((submission or {}).get("attempts") or 0),
    }


def _student_result(result: dict, reveal: bool) -> dict:
    items = []
    for item in result.get("results") or []:
        entry = {
            "question_id": item.get("question_id"),
            "question": item.get("question"),
            "type": item.get("type"),
            "options": item.get("options") or [],
            "knowledge_point": item.get("knowledge_point"),
            "submitted": item.get("submitted"),
            "correct": bool(item.get("correct")),
            "score": _number(item.get("score")),
        }
        if reveal:
            entry["correct_index"] = item.get("correct_index")
            entry["correct_answer"] = item.get("correct_answer")
            entry["explanation"] = item.get("explanation", "")
            entry["feedback"] = item.get("feedback", "")
        items.append(entry)
    return {
        "score": _number(result.get("score")),
        "correct_count": int(result.get("correct_count") or 0),
        "total": int(result.get("total") or 0),
        "results": items,
        "reveal": reveal,
    }


def _file_result_payload(assignment: dict, submission: dict) -> dict:
    ai = submission.get("ai") or {}
    return {
        "kind": "file",
        "submission_id": submission.get("id"),
        "assignment_id": assignment.get("id"),
        "title": assignment.get("title"),
        "score": _number(submission.get("score")),
        "submitted_at": submission.get("submitted_at"),
        "attempts": int(submission.get("attempts") or 0),
        "files": submission.get("files") or [],
        "note": submission.get("note", ""),
        "text_chars": len(submission.get("text") or ""),
        "ai_score": submission.get("ai_score"),
        "ai_feedback": ai.get("feedback", ""),
        "ai_demo": bool(ai.get("demo")),
        "ai_model": ai.get("model", ""),
        "ai_criteria": ai.get("criteria") or [],
        "ai_strengths": ai.get("strengths") or [],
        "ai_improvements": ai.get("improvements") or [],
        "teacher_score": submission.get("teacher_score"),
        "teacher_feedback": submission.get("teacher_feedback", ""),
        "teacher_note": submission.get("teacher_note", ""),
        "graded_by": submission.get("graded_by", ""),
        "graded_at": submission.get("graded_at"),
        "needs_review": bool(submission.get("needs_review") or ai.get("needs_review")),
        "reveal": bool(assignment.get("reveal", True)),
        "results": [],
        "correct_count": 0,
        "total": 0,
    }


def task_result(assignment_id: str, student_id: str) -> dict:
    """学生回看自己已经提交的作业。"""
    assignment, _student, quiz = _task_assignment(assignment_id, student_id)
    submission = _submission_of(assignment_id, student_id)
    if not submission:
        raise ValueError("还没有提交过这份作业。")
    if assignment.get("submission_mode") == "file" or submission.get("kind") == "file":
        return _file_result_payload(assignment, submission)
    payload = _student_result({
        "score": submission.get("score"),
        "correct_count": submission.get("correct_count"),
        "total": submission.get("total"),
        "results": submission.get("results") or [],
    }, bool(assignment.get("reveal", True)))
    payload.update({
        "assignment_id": assignment_id,
        "title": assignment.get("title"),
        "attempts": int(submission.get("attempts") or 0),
        "submitted_at": submission.get("submitted_at"),
    })
    if submission.get("teacher_score") is not None:
        payload["teacher_score"] = submission.get("teacher_score")
        payload["teacher_feedback"] = submission.get("teacher_feedback", "")
        payload["graded_by"] = submission.get("graded_by", "")
    return payload


async def submit_task(assignment_id: str, student_id: str, answers: list[dict]) -> dict:
    assignment, student, quiz = _task_assignment(assignment_id, student_id)
    if _due_state(assignment) != "open":
        raise ValueError("这份作业已截止或已关闭，不能再提交。")
    if assignment.get("submission_mode") == "file":
        raise ValueError("这份作业需要提交附件，不能在线作答。")
    if not quiz:
        raise ValueError("题目已丢失，请联系老师重新布置。")
    result = await quiz_service.grade(quiz, answers, track=False)
    submission_id = _submission_id(assignment_id, student_id)
    async with _lock_for(submission_id):
        existing = _submission_of(assignment_id, student_id) or {}
        submission = {
            "id": submission_id,
            "assignment_id": assignment_id,
            "class_id": assignment.get("class_id"),
            "student_id": student_id,
            "student_name": student.get("name"),
            "kind": "quiz",
            "score": _number(result.get("score")),
            "correct_count": int(result.get("correct_count") or 0),
            "total": int(result.get("total") or 0),
            "results": result.get("results") or [],
            "attempts": int(existing.get("attempts") or 0) + 1,
            "submitted_at": time.time(),
            "created_at": existing.get("created_at") or time.time(),
        }
        store.save_item("submissions", submission)
    bus.publish(f"teacher:{assignment['teacher_id']}", "submission_saved",
                class_id=assignment.get("class_id"), assignment_id=assignment_id,
                assignment_title=assignment.get("title"),
                student_id=student_id, student_name=student.get("name"),
                score=submission["score"], attempts=submission["attempts"])
    bus.publish(f"assignment:{assignment_id}", "submission_saved",
                student_id=student_id, student_name=student.get("name"))
    bus.publish(f"student:{student_id}", "tasks_changed", assignment_id=assignment_id)
    payload = _student_result(result, bool(assignment.get("reveal", True)))
    payload.update({
        "assignment_id": assignment_id,
        "title": assignment.get("title"),
        "attempts": submission["attempts"],
    })
    return payload


async def submit_file(assignment_id: str, student_id: str, *, filename: str,
                      data: bytes, note: str = "") -> dict:
    """学生提交文件作业：落盘 → 抽取文本 → AI 批改 → 写入提交记录。"""
    assignment, student, _quiz = _task_assignment(assignment_id, student_id)
    if assignment.get("submission_mode") != "file":
        raise ValueError("这份作业需要在线作答，不能提交附件。")
    if _due_state(assignment) != "open":
        raise ValueError("这份作业已截止或已关闭，不能再提交。")
    uploads.check_name(filename)
    text, hint = await asyncio.to_thread(uploads.extract_for_grading, filename, data)
    submission_id = _submission_id(assignment_id, student_id)
    file_meta = uploads.store_file(assignment_id, submission_id, filename, data)
    ai = await grading_service.grade_submission(
        topic=assignment.get("topic") or assignment.get("title") or "",
        instructions=assignment.get("instructions") or "",
        rubric=assignment.get("rubric") or "",
        text=text,
        filename=file_meta["filename"],
    )
    if hint:
        ai["needs_review"] = True
        ai["feedback"] = f"{ai.get('feedback', '')} {hint}".strip()
        if ai.get("score") is None:
            ai["score"] = 0.0
    async with _lock_for(submission_id):
        existing = _submission_of(assignment_id, student_id) or {}
        for old in existing.get("files") or []:
            if old.get("rel") == file_meta["rel"]:
                continue  # 同一份文件重新上传时，新文件已经写到这个路径
            try:
                uploads.resolve(old.get("rel", "")).unlink()
            except (OSError, ValueError):
                pass
        submission = {
            "id": submission_id,
            "assignment_id": assignment_id,
            "class_id": assignment.get("class_id"),
            "teacher_id": assignment.get("teacher_id"),
            "student_id": student_id,
            "student_name": student.get("name"),
            "kind": "file",
            "files": [file_meta],
            "note": _text(note, 500),
            "text": text[:20_000],
            "score": _number(ai.get("score")),
            "ai": ai,
            "ai_score": ai.get("score"),
            "teacher_score": None,
            "teacher_feedback": "",
            "teacher_note": "",
            "needs_review": bool(ai.get("needs_review")),
            "attempts": int(existing.get("attempts") or 0) + 1,
            "submitted_at": time.time(),
            "created_at": existing.get("created_at") or time.time(),
        }
        store.save_item("submissions", submission)
    bus.publish(f"teacher:{assignment['teacher_id']}", "submission_saved",
                class_id=assignment.get("class_id"), assignment_id=assignment_id,
                assignment_title=assignment.get("title"), kind="file",
                student_id=student_id, student_name=student.get("name"),
                score=submission["score"], attempts=submission["attempts"])
    bus.publish(f"assignment:{assignment_id}", "submission_saved", student_id=student_id)
    bus.publish(f"student:{student_id}", "tasks_changed", assignment_id=assignment_id)
    return _file_result_payload(assignment, submission)


def _teacher_submission(teacher_id: str, submission_id: str) -> tuple[dict, dict]:
    submission = store.load_item("submissions", submission_id)
    if not submission:
        raise ValueError("提交记录不存在。")
    assignment = store.load_item("assignments", submission.get("assignment_id") or "")
    if not assignment or assignment.get("teacher_id") != teacher_id:
        raise ValueError("提交记录不存在，或不属于当前账号。")
    return submission, assignment


def _submission_view(submission: dict) -> dict:
    ai = submission.get("ai") or {}
    return {
        "id": submission.get("id"),
        "student_id": submission.get("student_id"),
        "student_name": submission.get("student_name"),
        "kind": submission.get("kind", "quiz"),
        "score": _number(submission.get("score")),
        "ai_score": submission.get("ai_score"),
        "ai_feedback": ai.get("feedback", ""),
        "teacher_score": submission.get("teacher_score"),
        "teacher_feedback": submission.get("teacher_feedback", ""),
        "teacher_note": submission.get("teacher_note", ""),
        "graded_by": submission.get("graded_by", ""),
        "graded_at": submission.get("graded_at"),
        "needs_review": bool(submission.get("needs_review")),
        "attempts": int(submission.get("attempts") or 0),
        "submitted_at": submission.get("submitted_at"),
        "files": submission.get("files") or [],
        "regrade_history": submission.get("regrade_history") or [],
    }


def submission_detail(teacher_id: str, submission_id: str) -> dict:
    submission, _assignment = _teacher_submission(teacher_id, submission_id)
    return _submission_view(submission)


def regrade_submission(teacher_id: str, submission_id: str, *, score: float,
                       feedback: str = "", note: str = "") -> dict:
    """教师复核：用百分制传入，最终分数覆盖 AI 分，并保留原始分与修改记录。"""
    submission, assignment = _teacher_submission(teacher_id, submission_id)
    teacher = store.load_item("teachers", teacher_id) or {}
    final = round(max(0.0, min(1.0, float(score))), 3)
    previous = submission.get("teacher_score")
    history = list(submission.get("regrade_history") or [])[-19:]
    history.append({
        "score": final,
        "previous": previous,
        "feedback": _text(feedback, 2000),
        "note": _text(note, 300),
        "by": teacher.get("name") or teacher.get("username") or "",
        "at": time.time(),
    })
    submission.update({
        "teacher_score": final,
        "score": final,
        "teacher_feedback": _text(feedback, 2000),
        "teacher_note": _text(note, 300),
        "graded_by": teacher.get("name") or teacher.get("username") or "",
        "graded_at": time.time(),
        "needs_review": False,
        "regrade_history": history,
    })
    store.save_item("submissions", submission)
    bus.publish(f"teacher:{teacher_id}", "submission_graded",
                class_id=assignment.get("class_id"), assignment_id=assignment["id"],
                submission_id=submission_id, student_id=submission.get("student_id"),
                student_name=submission.get("student_name"), score=final)
    bus.publish(f"student:{submission.get('student_id')}", "tasks_changed",
                assignment_id=assignment["id"])
    return {"ok": True, "submission": _submission_view(submission)}


async def regrade_submission_ai(teacher_id: str, submission_id: str) -> dict:
    """教师重新触发一次 AI 批改（例如学生重新提交或换了模型）。"""
    submission, assignment = _teacher_submission(teacher_id, submission_id)
    text = submission.get("text") or ""
    files = submission.get("files") or []
    filename = files[0].get("filename", "作业") if files else "作业"
    ai = await grading_service.grade_submission(
        topic=assignment.get("topic") or assignment.get("title") or "",
        instructions=assignment.get("instructions") or "",
        rubric=assignment.get("rubric") or "",
        text=text,
        filename=filename,
    )
    submission["ai"] = ai
    submission["ai_score"] = ai.get("score")
    submission["needs_review"] = bool(ai.get("needs_review"))
    if submission.get("teacher_score") is None:
        submission["score"] = _number(ai.get("score"))
    store.save_item("submissions", submission)
    bus.publish(f"teacher:{teacher_id}", "submission_graded",
                class_id=assignment.get("class_id"), assignment_id=assignment["id"],
                submission_id=submission_id, student_id=submission.get("student_id"),
                student_name=submission.get("student_name"), score=submission["score"])
    bus.publish(f"student:{submission.get('student_id')}", "tasks_changed",
                assignment_id=assignment["id"])
    return {"ok": True, "submission": _submission_view(submission)}


def _file_of(submission: dict, file_id: str) -> tuple:
    for item in submission.get("files") or []:
        if str(item.get("id")) == str(file_id):
            return uploads.resolve(item.get("rel", "")), item.get("filename") or "作业"
    raise ValueError("文件不存在或已被清理。")


def submission_file_for_teacher(teacher_id: str, submission_id: str, file_id: str) -> tuple:
    submission, _assignment = _teacher_submission(teacher_id, submission_id)
    return _file_of(submission, file_id)


def submission_file_for_student(student_id: str, submission_id: str, file_id: str) -> tuple:
    submission = store.load_item("submissions", submission_id)
    if not submission or submission.get("student_id") != student_id:
        raise ValueError("提交记录不存在。")
    return _file_of(submission, file_id)


# ---------------------------------------------------------------- 教师概览
def overview(teacher_id: str) -> dict:
    classes = _classes_of(teacher_id)
    class_ids = {item["id"] for item in classes}
    students = [item for item in store.list_items("students") if item.get("class_id") in class_ids]
    assignments = [item for item in store.list_items("assignments") if item.get("teacher_id") == teacher_id]
    submissions = [item for item in store.list_items("submissions") if item.get("class_id") in class_ids]
    class_map = {item["id"]: item.get("name") for item in classes}

    open_assignments = [item for item in assignments if _due_state(item) == "open"]
    assignment_map = {item["id"]: item for item in assignments}
    total_slots = len(assignments) * len(students)
    submission_rate = round(len(submissions) / total_slots, 3) if total_slots else 0.0

    upcoming = []
    for assignment in open_assignments:
        submitted = {item.get("student_id") for item in submissions if item.get("assignment_id") == assignment["id"]}
        roster = [item for item in students if item.get("class_id") == assignment["class_id"]]
        upcoming.append({
            "id": assignment["id"],
            "title": assignment.get("title"),
            "class_name": class_map.get(assignment["class_id"], ""),
            "kind": assignment.get("kind", "homework"),
            "due_at": _number(assignment.get("due_at")),
            "submitted": len(submitted),
            "total": len(roster),
            "missing": len([item for item in roster if item["id"] not in submitted]),
        })
    upcoming.sort(key=lambda item: (item["due_at"] or float("inf"), -item["missing"]))

    knowledge: dict[str, dict] = {}
    for submission in submissions:
        for result in submission.get("results") or []:
            point = str(result.get("knowledge_point") or "未标注知识点")[:60]
            entry = knowledge.setdefault(point, {
                "point": point, "attempts": 0, "wrong": 0,
                "assignment_id": submission.get("assignment_id") or "",
            })
            entry["attempts"] += 1
            if not result.get("correct"):
                entry["wrong"] += 1
            if not entry["assignment_id"]:
                entry["assignment_id"] = submission.get("assignment_id") or ""
    weak_points = [
        {
            "point": entry["point"],
            "attempts": entry["attempts"],
            "wrong": entry["wrong"],
            "error_rate": round(entry["wrong"] / entry["attempts"], 3) if entry["attempts"] else 0.0,
            "assignment_id": entry["assignment_id"],
            "assignment_title": (assignment_map.get(entry["assignment_id"]) or {}).get("title", ""),
        }
        for entry in knowledge.values() if entry["wrong"]
    ]
    weak_points.sort(key=lambda item: (-item["error_rate"], -item["wrong"]))

    recent = []
    for submission in sorted(submissions, key=lambda item: -float(item.get("submitted_at") or 0))[:8]:
        assignment = assignment_map.get(submission.get("assignment_id") or "")
        recent.append({
            "student_name": submission.get("student_name"),
            "assignment_title": (assignment or {}).get("title"),
            "class_name": class_map.get(submission.get("class_id"), ""),
            "score": _number(submission.get("score")),
            "submitted_at": submission.get("submitted_at"),
        })

    return {
        "stats": {
            "classes": len(classes),
            "students": len(students),
            "assignments": len(assignments),
            "open": len(open_assignments),
            "submissions": len(submissions),
            "submission_rate": submission_rate,
            "avg_score": _avg([_number(item.get("score")) for item in submissions]),
        },
        "upcoming": upcoming[:5],
        "weak_points": weak_points[:6],
        "recent": recent,
    }


# ---------------------------------------------------------------- 导出
def class_csv(teacher_id: str, class_id: str) -> tuple[str, bytes]:
    klass = _own_class(teacher_id, class_id)
    students = _students_of(class_id)
    assignments = _assignments_of(class_id)
    submissions = [item for item in store.list_items("submissions") if item.get("class_id") == class_id]
    return f"{klass.get('name')}-成绩汇总.csv", reports.csv_class_scores(klass, students, assignments, submissions)


def class_report(teacher_id: str, class_id: str) -> tuple[str, str]:
    """整班成绩报告（HTML，含统计图表）。"""
    klass = _own_class(teacher_id, class_id)
    teacher = store.load_item("teachers", teacher_id) or {}
    students = _students_of(class_id)
    assignments = _assignments_of(class_id)
    submissions = [item for item in store.list_items("submissions") if item.get("class_id") == class_id]
    html = reports.html_class_report(
        klass=klass,
        teacher_name=teacher.get("name") or teacher.get("username", ""),
        students=students, assignments=assignments, submissions=submissions,
    )
    safe_name = str(klass.get("name") or "班级").replace("/", "_").replace("\\", "_")
    return f"{safe_name}-成绩报告.html", html


def assignment_csv(teacher_id: str, assignment_id: str) -> tuple[str, bytes]:
    assignment = store.load_item("assignments", assignment_id)
    if not assignment or assignment.get("teacher_id") != teacher_id:
        raise ValueError("作业不存在。")
    klass = store.load_item("classes", assignment["class_id"]) or {}
    students = _students_of(assignment["class_id"])
    submissions = _submissions_of(assignment_id)
    quiz = _load_quiz(assignment)
    return (
        f"{klass.get('name', '班级')}-{assignment.get('title', '作业')}-明细.csv",
        reports.csv_assignment(assignment, students, submissions, quiz.get("questions") or []),
    )


def student_report(teacher_id: str, student_id: str) -> tuple[str, str]:
    student = store.load_item("students", student_id)
    if not student:
        raise ValueError("学生不存在。")
    klass = _own_class(teacher_id, student.get("class_id") or "")
    teacher = store.load_item("teachers", teacher_id) or {}
    assignments = _assignments_of(klass["id"])
    submissions = [
        item for item in store.list_items("submissions")
        if item.get("student_id") == student_id and item.get("class_id") == klass["id"]
    ]
    html = reports.html_student_report(
        student=student, klass=klass, teacher_name=teacher.get("name") or teacher.get("username", ""),
        assignments=assignments, submissions=submissions,
    )
    safe_name = str(student.get("name") or "学生").replace("/", "_").replace("\\", "_")
    return f"{safe_name}-学习报告.html", html
