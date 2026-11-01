"""统一登录 / 注册：不选身份，只靠输入判定。"""
from __future__ import annotations


def test_teacher_login_by_username(client):
    response = client.post("/api/auth/login", json={"account": "demo", "password": "demo1234"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["role"] == "teacher"
    assert data["teacher"]["username"] == "demo"
    assert data["token"]


def test_student_login_by_number(client, roster):
    response = client.post("/api/auth/login", json={"account": "2024001", "password": "pass1234"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["role"] == "student"
    assert data["student"]["number"] == "2024001"
    assert data["klass"]["id"]


def test_unknown_account_is_rejected(client):
    response = client.post("/api/auth/login", json={"account": "nobody-here", "password": "whatever"})
    assert response.status_code == 400


def test_wrong_password_is_rejected(client, roster):
    response = client.post("/api/auth/login", json={"account": "2024001", "password": "wrong-password"})
    assert response.status_code == 400


def test_register_with_invite_joins_class(client, klass):
    response = client.post(
        "/api/auth/register",
        json={"invite": klass["code"], "name": "新同学", "account": "3001"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["role"] == "student"
    assert data["klass"]["id"] == klass["id"]
    assert data["token"]


def test_register_without_invite_creates_teacher(client):
    response = client.post(
        "/api/auth/register",
        json={"name": "李老师", "account": "li.laoshi", "password": "secret123"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["role"] == "teacher"
    assert data["teacher"]["username"] == "li.laoshi"

    again = client.post("/api/auth/login", json={"account": "li.laoshi", "password": "secret123"})
    assert again.status_code == 200, again.text
    assert again.json()["role"] == "teacher"


def test_numeric_username_is_refused(client):
    response = client.post(
        "/api/auth/register",
        json={"name": "数字老师", "account": "8888888", "password": "secret123"},
    )
    assert response.status_code == 400
    assert "纯数字" in response.json()["detail"]
