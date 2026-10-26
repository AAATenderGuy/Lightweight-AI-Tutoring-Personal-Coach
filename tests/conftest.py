"""测试入口：用临时数据目录，强制演示模式，避免碰到真实 data/ 与外部模型。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["EDU_DATA_DIR"] = tempfile.mkdtemp(prefix="edu-tests-")
os.environ["EDU_RATE_LIMIT"] = "0"
os.environ["EDU_API_KEY"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def teacher(client):
    response = client.post("/api/teacher/login", json={"username": "demo", "password": "demo1234"})
    assert response.status_code == 200, response.text
    data = response.json()
    return {"token": data["token"], "headers": {"Authorization": f"Bearer {data['token']}"}}


@pytest.fixture
def klass(client, teacher):
    response = client.post(
        "/api/teacher/classes", json={"name": "测试班"}, headers=teacher["headers"],
    )
    assert response.status_code == 200, response.text
    klass = response.json()["class"]
    yield klass
    client.delete(f"/api/teacher/classes/{klass['id']}", headers=teacher["headers"])


@pytest.fixture
def roster(client, teacher, klass):
    response = client.post(
        f"/api/teacher/classes/{klass['id']}/roster",
        headers=teacher["headers"],
        data={"text": "学号,姓名,密码\n2024001,小明,pass1234\n2024002,小红,pass5678"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def student(client, roster):
    response = client.post(
        "/api/student/login", json={"number": "2024001", "password": "pass1234"},
    )
    assert response.status_code == 200, response.text
    return response.json()
