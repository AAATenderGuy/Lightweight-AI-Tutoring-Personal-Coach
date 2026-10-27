"""文件作业：提交、AI 批改、教师下载、教师复核与越权边界。"""
from __future__ import annotations

CONTENT = "光反应在类囊体薄膜上进行，暗反应在叶绿体基质中进行。".encode()


def _create_file_assignment(client, teacher, klass, **overrides):
    payload = {
        "class_id": klass["id"],
        "topic": "光合作用",
        "kind": "homework",
        "submission_mode": "file",
        "instructions": "提交一份实验报告",
        "rubric": "需要写出光反应与暗反应的区别",
    }
    payload.update(overrides)
    response = client.post("/api/teacher/assignments", headers=teacher["headers"], json=payload)
    assert response.status_code == 200, response.text
    return response.json()["assignment"]


def _submit(client, assignment_id, student, filename="报告.txt", content=CONTENT):
    return client.post(
        f"/api/student/tasks/{assignment_id}/submit-file",
        data={"student_id": student["student"]["id"], "token": student["token"], "note": "实验报告"},
        files={"file": (filename, content, "text/plain")},
    )


def test_file_assignment_creation_skips_quiz(client, teacher, klass):
    assignment = _create_file_assignment(client, teacher, klass)
    assert assignment["submission_mode"] == "file"
    assert assignment["question_count"] == 0
    assert assignment["rubric"].startswith("需要写出")


def test_submit_file_grades_downloads_and_regrades(client, teacher, klass, student):
    assignment = _create_file_assignment(client, teacher, klass)
    response = _submit(client, assignment["id"], student)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["kind"] == "file"
    assert 0.0 <= result["score"] <= 1.0
    assert result["ai_feedback"]
    assert result["submission_id"] == f"sb_{assignment['id']}_{student['student']['id']}"
    file_id = result["files"][0]["id"]

    detail = client.get(f"/api/teacher/assignments/{assignment['id']}", headers=teacher["headers"]).json()
    assert detail["graded_ai"] == 1
    submission = detail["submissions"][0]
    assert submission["files"][0]["id"] == file_id
    download = client.get(
        f"/api/teacher/submissions/{submission['id']}/files/{file_id}",
        headers=teacher["headers"],
    )
    assert download.status_code == 200
    assert download.content == CONTENT

    own = client.get(
        f"/api/student/submissions/{submission['id']}/files/{file_id}",
        params={"student_id": student["student"]["id"], "token": student["token"]},
    )
    assert own.status_code == 200 and own.content == CONTENT

    other = client.post(
        "/api/student/login", json={"number": "2024002", "password": "pass5678"},
    ).json()
    stolen = client.get(
        f"/api/student/submissions/{submission['id']}/files/{file_id}",
        params={"student_id": other["student"]["id"], "token": other["token"]},
    )
    assert stolen.status_code == 400

    graded = client.patch(
        f"/api/teacher/submissions/{submission['id']}", headers=teacher["headers"],
        json={"score": 88, "feedback": "论证完整，结论明确", "note": "加 3 分"},
    )
    assert graded.status_code == 200, graded.text
    assert graded.json()["submission"]["score"] == 0.88
    assert graded.json()["submission"]["teacher_score"] == 0.88

    detail = client.get(f"/api/teacher/assignments/{assignment['id']}", headers=teacher["headers"]).json()
    assert detail["graded_teacher"] == 1
    assert detail["submissions"][0]["teacher_feedback"] == "论证完整，结论明确"

    student_result = client.get(
        f"/api/student/tasks/{assignment['id']}/result",
        params={"student_id": student["student"]["id"], "token": student["token"]},
    ).json()
    assert student_result["teacher_score"] == 0.88
    assert student_result["teacher_feedback"] == "论证完整，结论明确"

    again = client.post(
        f"/api/teacher/submissions/{submission['id']}/regrade-ai", headers=teacher["headers"],
    )
    assert again.status_code == 200, again.text
    assert again.json()["submission"]["ai_score"] is not None
    assert again.json()["submission"]["score"] == 0.88


def test_other_teacher_cannot_read_or_grade(client, teacher, klass, student):
    assignment = _create_file_assignment(client, teacher, klass)
    result = _submit(client, assignment["id"], student).json()
    other = client.post("/api/teacher/register", json={
        "username": "other-teacher", "password": "secret123", "name": "其他老师",
    }).json()
    headers = {"Authorization": f"Bearer {other['token']}"}
    submission_id = result["submission_id"]
    assert client.get(f"/api/teacher/submissions/{submission_id}", headers=headers).status_code == 400
    assert client.patch(
        f"/api/teacher/submissions/{submission_id}", headers=headers, json={"score": 100},
    ).status_code == 400


def test_file_assignment_rejects_quiz_submit_and_vice_versa(client, teacher, klass, student):
    file_assignment = _create_file_assignment(client, teacher, klass)
    quiz_answer = client.post(
        f"/api/student/tasks/{file_assignment['id']}/submit",
        json={"student_id": student["student"]["id"], "token": student["token"], "answers": []},
    )
    assert quiz_answer.status_code == 400

    quiz_assignment = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
        "class_id": klass["id"], "topic": "测量", "kind": "quiz", "count": 2,
    }).json()["assignment"]
    upload = _submit(client, quiz_assignment["id"], student)
    assert upload.status_code == 400


def test_resubmitting_same_file_keeps_download_available(client, teacher, klass, student):
    assignment = _create_file_assignment(client, teacher, klass)
    first = _submit(client, assignment["id"], student, filename="报告.txt", content=CONTENT)
    assert first.status_code == 200
    first_result = first.json()

    second = _submit(client, assignment["id"], student, filename="报告.txt", content=CONTENT)
    assert second.status_code == 200, second.text
    second_result = second.json()
    assert second_result["attempts"] == 2

    download = client.get(
        f"/api/student/submissions/{second_result['submission_id']}/files/{second_result['files'][0]['id']}",
        params={"student_id": student["student"]["id"], "token": student["token"]},
    )
    assert download.status_code == 200
    assert download.content == CONTENT
    assert first_result["files"][0]["id"] == second_result["files"][0]["id"]


def test_oversized_upload_is_rejected(client, teacher, klass, student, monkeypatch):
    from server.services import uploads
    monkeypatch.setattr(uploads, "MAX_SUBMISSION_BYTES", 64)
    assignment = _create_file_assignment(client, teacher, klass)
    response = _submit(client, assignment["id"], student, content=b"x" * 1024)
    assert response.status_code == 413
