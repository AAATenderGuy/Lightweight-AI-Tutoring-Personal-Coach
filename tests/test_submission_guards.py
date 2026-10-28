"""提交与部署配置的安全边界。

三件事必须成立：
1. 改模型地址 / 清空进度是部署级操作，没有教师身份进不来；
2. 默认不向学生透露正确答案（reveal=False），要讲评由教师主动打开；
3. 一份作业最多交 3 次，且重交不能把教师已经复核的分数冲掉。
"""
from __future__ import annotations


def _create_quiz(client, teacher, klass, **overrides):
    payload = {"class_id": klass["id"], "topic": "光合作用", "kind": "quiz", "count": 2}
    payload.update(overrides)
    response = client.post("/api/teacher/assignments", headers=teacher["headers"], json=payload)
    assert response.status_code == 200, response.text
    return response.json()["assignment"]


def _answers(client, assignment_id, student):
    started = client.post(f"/api/student/tasks/{assignment_id}/start", json={
        "student_id": student["student"]["id"], "token": student["token"],
    })
    assert started.status_code == 200, started.text
    questions = started.json()["quiz"]["questions"]
    return [
        {"question_id": item["id"], "answer": (item.get("options") or ["答案"])[0]}
        for item in questions
    ]


def _submit(client, assignment_id, student, answers):
    return client.post(f"/api/student/tasks/{assignment_id}/submit", json={
        "student_id": student["student"]["id"], "token": student["token"], "answers": answers,
    })


def test_settings_update_requires_teacher_login(client, teacher):
    anonymous = client.put("/api/settings", json={"model": "someone-else-model"})
    assert anonymous.status_code == 401
    allowed = client.put("/api/settings", json={}, headers=teacher["headers"])
    assert allowed.status_code == 200


def test_progress_reset_requires_teacher_login(client, teacher):
    assert client.delete("/api/progress").status_code == 401
    assert client.delete("/api/progress", headers=teacher["headers"]).status_code == 200


def test_reveal_is_off_by_default(client, teacher, klass, student):
    assignment = _create_quiz(client, teacher, klass)
    assert assignment["reveal"] is False

    answers = _answers(client, assignment["id"], student)
    result = _submit(client, assignment["id"], student, answers)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["reveal"] is False
    for item in body["results"]:
        assert "correct_answer" not in item
        assert "correct_index" not in item

    later = client.get(f"/api/student/tasks/{assignment['id']}/result", params={
        "student_id": student["student"]["id"], "token": student["token"],
    }).json()
    assert later["reveal"] is False
    assert all("correct_answer" not in item for item in later["results"])


def test_reveal_can_be_turned_on_by_teacher(client, teacher, klass, student):
    assignment = _create_quiz(client, teacher, klass, reveal=True)
    answers = _answers(client, assignment["id"], student)
    body = _submit(client, assignment["id"], student, answers).json()
    assert body["reveal"] is True
    assert all("correct_answer" in item for item in body["results"])


def test_fourth_submission_is_rejected(client, teacher, klass, student):
    assignment = _create_quiz(client, teacher, klass)
    answers = _answers(client, assignment["id"], student)
    for attempt in (1, 2, 3):
        response = _submit(client, assignment["id"], student, answers)
        assert response.status_code == 200, response.text
        assert response.json()["attempts"] == attempt

    blocked = _submit(client, assignment["id"], student, answers)
    assert blocked.status_code == 400
    assert "最多提交 3 次" in blocked.json()["detail"]


def test_resubmission_keeps_teacher_grade(client, teacher, klass, student):
    assignment = _create_quiz(client, teacher, klass)
    answers = _answers(client, assignment["id"], student)
    first = _submit(client, assignment["id"], student, answers)
    assert first.status_code == 200, first.text
    submission_id = f"sb_{assignment['id']}_{student['student']['id']}"

    graded = client.patch(f"/api/teacher/submissions/{submission_id}", headers=teacher["headers"],
                          json={"score": 88, "feedback": "思路清楚"})
    assert graded.status_code == 200, graded.text

    again = _submit(client, assignment["id"], student, answers)
    assert again.status_code == 200, again.text

    detail = client.get(f"/api/teacher/assignments/{assignment['id']}",
                        headers=teacher["headers"]).json()
    submission = next(item for item in detail["submissions"] if item["id"] == submission_id)
    assert submission["teacher_score"] == 0.88
    assert submission["teacher_feedback"] == "思路清楚"
