"""教研组与权限（P2 · S6）。

覆盖权限矩阵里的允许与拒绝两类格子；用三个真实账号（部署者 / 组长 / 普通教师）
而不是直接改数据，保证走的是同一条 API 路径。
"""
from __future__ import annotations

import pytest

from server.services import perms


def _register(client, username: str, name: str = "") -> dict:
    response = client.post(
        "/api/teacher/register",
        json={"username": username, "password": "pass1234", "name": name or username},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {"id": data["teacher"]["id"], "role": data["teacher"]["role"],
            "headers": {"Authorization": f"Bearer {data['token']}"}}


@pytest.fixture(scope="module")
def actors(client):
    lead = _register(client, "s6_lead", "组长")
    member = _register(client, "s6_member", "组员")
    outsider = _register(client, "s6_outsider", "组外教师")
    return {"lead": lead, "member": member, "outsider": outsider}


@pytest.fixture(scope="module")
def group(client, actors):
    response = client.post("/api/teacher/groups", json={"name": "S6 数学教研组"},
                           headers=actors["lead"]["headers"])
    assert response.status_code == 200, response.text
    group = response.json()["group"]
    added = client.post(f"/api/teacher/groups/{group['id']}/members",
                        json={"username": "s6_member"}, headers=actors["lead"]["headers"])
    assert added.status_code == 200, added.text
    yield added.json()["group"]
    client.delete(f"/api/teacher/groups/{group['id']}", headers=actors["lead"]["headers"])


@pytest.fixture(scope="module")
def shared_class(client, actors, group):
    response = client.post(
        "/api/teacher/classes",
        json={"name": "S6 共享班", "group_id": group["id"]},
        headers=actors["lead"]["headers"],
    )
    assert response.status_code == 200, response.text
    klass = response.json()["class"]
    assert klass["group_id"] == group["id"]
    yield klass
    client.delete(f"/api/teacher/classes/{klass['id']}", headers=actors["lead"]["headers"])


def test_first_account_is_owner_and_new_ones_are_teachers(client, actors):
    me = client.get("/api/teacher/me", headers=_demo_headers(client)).json()
    assert me["teacher"]["role"] == "owner"
    assert actors["member"]["role"] == "teacher"
    login = client.post("/api/teacher/login", json={"username": "s6_member", "password": "pass1234"}).json()
    assert login["teacher"]["role"] == "teacher"


def test_group_creator_becomes_lead(client, actors, group):
    assert group["owner_id"] == actors["lead"]["id"]
    assert group["member_count"] == 2
    login = client.post("/api/teacher/login", json={"username": "s6_lead", "password": "pass1234"}).json()
    assert login["teacher"]["role"] == "lead"


def test_member_sees_shared_class_as_readonly(client, actors, shared_class):
    items = client.get("/api/teacher/classes", headers=actors["member"]["headers"]).json()["items"]
    listed = next((item for item in items if item["id"] == shared_class["id"]), None)
    assert listed is not None, "组员应能看到组内班级"
    assert listed["readonly"] is True


def test_outsider_cannot_see_shared_class(client, actors, shared_class):
    response = client.get(f"/api/teacher/classes/{shared_class['id']}",
                          headers=actors["outsider"]["headers"])
    assert response.status_code == 400


def test_member_can_read_but_not_write(client, actors, shared_class):
    detail = client.get(f"/api/teacher/classes/{shared_class['id']}", headers=actors["member"]["headers"])
    assert detail.status_code == 200
    assert detail.json()["class"]["readonly"] is True
    # 组员能看班级结构，但看不到分数（成绩只对创建者 / 组长开放）
    assert detail.json()["can_view_grades"] is False
    assert all(item["avg_score"] is None for item in detail.json()["students"])
    assert detail.json()["stats"]["avg_score"] is None

    report = client.get(f"/api/teacher/classes/{shared_class['id']}/report.html",
                        headers=actors["member"]["headers"])
    assert report.status_code == 400

    csv = client.get(f"/api/teacher/classes/{shared_class['id']}/export.csv",
                     headers=actors["member"]["headers"])
    assert csv.status_code == 400

    patch = client.patch(f"/api/teacher/classes/{shared_class['id']}", json={"name": "改个名"},
                         headers=actors["member"]["headers"])
    assert patch.status_code == 400

    assignment = client.post("/api/teacher/assignments", json={
        "class_id": shared_class["id"], "topic": "组员越权布置", "count": 2,
    }, headers=actors["member"]["headers"])
    assert assignment.status_code == 400


def test_lead_can_write_group_class(client, actors, shared_class):
    response = client.patch(f"/api/teacher/classes/{shared_class['id']}",
                            json={"grade": "高一"}, headers=actors["lead"]["headers"])
    assert response.status_code == 200
    assert response.json()["class"]["grade"] == "高一"


def test_member_sees_no_scores_in_lists(client, actors, shared_class):
    created = client.post("/api/teacher/assignments", json={
        "class_id": shared_class["id"], "topic": "组内成绩可见性", "count": 2,
    }, headers=actors["lead"]["headers"])
    assert created.status_code == 200, created.text

    items = client.get("/api/teacher/assignments", headers=actors["member"]["headers"]).json()["items"]
    shared = next(item for item in items if item["class_id"] == shared_class["id"])
    assert shared["avg_score"] is None

    overview = client.get("/api/teacher/overview", headers=actors["member"]["headers"]).json()
    assert overview["stats"]["avg_score"] is None

    lead_view = client.get("/api/teacher/assignments", headers=actors["lead"]["headers"]).json()["items"]
    assert next(item for item in lead_view if item["class_id"] == shared_class["id"])["avg_score"] is not None


def test_only_lead_or_owner_can_invite(client, actors, group):
    denied = client.post(f"/api/teacher/groups/{group['id']}/members",
                         json={"username": "s6_outsider"}, headers=actors["member"]["headers"])
    assert denied.status_code == 400

    unknown = client.post(f"/api/teacher/groups/{group['id']}/members",
                          json={"username": "no_such_user"}, headers=actors["lead"]["headers"])
    assert unknown.status_code == 400

    allowed = client.post(f"/api/teacher/groups/{group['id']}/members",
                          json={"username": "s6_outsider"}, headers=actors["lead"]["headers"])
    assert allowed.status_code == 200
    assert allowed.json()["group"]["member_count"] == 3
    assert client.delete(
        f"/api/teacher/groups/{group['id']}/members/{actors['outsider']['id']}",
        headers=actors["lead"]["headers"],
    ).status_code == 200


def test_class_cannot_join_foreign_group(client, actors, group):
    response = client.post("/api/teacher/classes",
                           json={"name": "偷偷挂组", "group_id": group["id"]},
                           headers=actors["outsider"]["headers"])
    assert response.status_code == 400


def test_role_backfill_gives_owner_to_earliest_account(client):
    assert perms.backfill() == 0, "role 已补齐，重复调用应为空操作"
    teachers = client.get("/api/teacher/me", headers=_demo_headers(client)).json()
    assert perms.role_of(teachers["teacher"]) == "owner"


def _demo_token(client) -> str:
    response = client.post("/api/teacher/login", json={"username": "demo", "password": "demo1234"})
    assert response.status_code == 200
    return response.json()["token"]


def _demo_headers(client) -> dict:
    return {"Authorization": f"Bearer {_demo_token(client)}"}
