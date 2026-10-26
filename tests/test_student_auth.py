"""学生身份：学号登录、令牌校验与邀请码回退边界。"""
from __future__ import annotations


def test_tasks_requires_valid_token(client, student):
    student_id = student["student"]["id"]
    assert client.get("/api/student/tasks", params={"student_id": student_id}).status_code == 401
    assert client.get(
        "/api/student/tasks", params={"student_id": student_id, "token": "wrong-token"},
    ).status_code == 401
    ok = client.get(
        "/api/student/tasks", params={"student_id": student_id, "token": student["token"]},
    )
    assert ok.status_code == 200
    assert ok.json()["student"]["id"] == student_id


def test_other_students_token_cannot_read(client, student):
    other = client.post(
        "/api/student/login", json={"number": "2024002", "password": "pass5678"},
    ).json()
    response = client.get(
        "/api/student/tasks",
        params={"student_id": student["student"]["id"], "token": other["token"]},
    )
    assert response.status_code == 401


def test_login_is_deterministic_and_repeatable(client, student):
    again = client.post(
        "/api/student/login", json={"number": "2024001", "password": "pass1234"},
    )
    assert again.status_code == 200
    data = again.json()
    assert data["student"]["id"] == student["student"]["id"]
    assert data["token"] == student["token"]
    assert data["klass"]["name"] == student["klass"]["name"]


def test_login_rejects_wrong_password(client, roster):
    response = client.post(
        "/api/student/login", json={"number": "2024001", "password": "wrong-password"},
    )
    assert response.status_code == 400
    assert "学号或密码不正确" in response.json()["detail"]


def test_login_rejects_unknown_number(client, roster):
    response = client.post(
        "/api/student/login", json={"number": "9999999", "password": "pass1234"},
    )
    assert response.status_code == 400


def test_invite_join_disabled_after_roster_import(client, klass, roster):
    response = client.post(
        "/api/student/join",
        json={"code": klass["code"], "name": "新同学", "number": "99"},
    )
    assert response.status_code == 400
    assert "学号" in response.json()["detail"]


def test_start_requires_token(client, klass, teacher, student):
    assignment = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
        "class_id": klass["id"], "topic": "测量", "kind": "quiz", "count": 2,
    }).json()["assignment"]
    response = client.post(
        f"/api/student/tasks/{assignment['id']}/start",
        json={"student_id": student["student"]["id"], "token": "nope"},
    )
    assert response.status_code == 401
