"""审计日志（P2 · S6）。

验收口径只有两条：关键动作之后一定能在审计里找到对应行；审计本身也受权限约束，
普通教师看不到、组长与部署者能看。
"""
from __future__ import annotations

import pytest

from server.services import audit


def _register(client, username: str) -> dict:
    response = client.post(
        "/api/teacher/register",
        json={"username": username, "password": "pass1234", "name": username},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {"id": data["teacher"]["id"], "role": data["teacher"]["role"],
            "headers": {"Authorization": f"Bearer {data['token']}"}}


def _actions(limit: int = 200) -> list[str]:
    return [row["action"] for row in audit.recent(limit)]


def test_login_success_and_failure_are_recorded(client):
    client.post("/api/teacher/login", json={"username": "demo", "password": "demo1234"})
    client.post("/api/teacher/login", json={"username": "demo", "password": "wrong-pass"})
    rows = audit.recent(20)
    assert rows[0]["action"] == audit.LOGIN and rows[0]["result"] == "failed"
    assert any(row["action"] == audit.LOGIN and row["result"] == "ok" for row in rows)


def test_class_workflow_is_audited(client, teacher):
    klass = client.post("/api/teacher/classes", json={"name": "审计班"},
                        headers=teacher["headers"]).json()["class"]
    imported = client.post(
        f"/api/teacher/classes/{klass['id']}/roster", headers=teacher["headers"],
        data={"text": "学号,姓名,密码\n29001,审计小明,pass1234\n"},
    )
    assert imported.status_code == 200, imported.text
    student = client.post("/api/student/login",
                          json={"number": "29001", "password": "pass1234"}).json()

    assignment = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
        "class_id": klass["id"], "topic": "审计作业", "kind": "homework",
        "submission_mode": "file", "instructions": "提交一段说明", "rubric": "写清楚就行",
    }).json()["assignment"]
    submitted = client.post(
        f"/api/student/tasks/{assignment['id']}/submit-file",
        data={"student_id": student["student"]["id"], "token": student["token"], "note": "说明"},
        files={"file": ("说明.txt", "这是一段审计测试说明。".encode(), "text/plain")},
    )
    assert submitted.status_code == 200, submitted.text
    submission_id = submitted.json()["submission_id"]
    graded = client.patch(f"/api/teacher/submissions/{submission_id}", headers=teacher["headers"],
                          json={"score": 90, "feedback": "可以"})
    assert graded.status_code == 200, graded.text

    actions = _actions()
    for action in (audit.CLASS_CREATE, audit.ROSTER_IMPORT,
                   audit.ASSIGNMENT_CREATE, audit.SUBMISSION_GRADE):
        assert action in actions, f"缺少审计动作 {action}"

    client.delete(f"/api/teacher/classes/{klass['id']}", headers=teacher["headers"])
    assert audit.CLASS_DELETE in _actions()


def test_group_changes_are_audited(client):
    lead = _register(client, "s6a_lead")
    member = _register(client, "s6a_member")
    group = client.post("/api/teacher/groups", json={"name": "审计教研组"},
                        headers=lead["headers"]).json()["group"]
    added = client.post(f"/api/teacher/groups/{group['id']}/members",
                        json={"username": "s6a_member"}, headers=lead["headers"])
    assert added.status_code == 200, added.text
    removed = client.delete(f"/api/teacher/groups/{group['id']}/members/{member['id']}",
                            headers=lead["headers"])
    assert removed.status_code == 200, removed.text
    client.delete(f"/api/teacher/groups/{group['id']}", headers=lead["headers"])

    actions = _actions()
    for action in (audit.GROUP_CREATE, audit.GROUP_MEMBER_ADD,
                   audit.GROUP_MEMBER_REMOVE, audit.GROUP_UPDATE):
        assert action in actions, f"缺少审计动作 {action}"


def test_audit_visibility_follows_role(client, teacher):
    plain = _register(client, "s6a_plain")
    assert plain["role"] == "teacher"
    assert client.get("/api/teacher/audit", headers=plain["headers"]).status_code == 403

    lead = _register(client, "s6a_viewer")
    group = client.post("/api/teacher/groups", json={"name": "审计可见组"},
                        headers=lead["headers"]).json()["group"]
    try:
        visible = client.get("/api/teacher/audit", params={"limit": 10}, headers=lead["headers"])
        assert visible.status_code == 200, visible.text
        items = visible.json()["items"]
        assert 0 < len(items) <= 10
    finally:
        client.delete(f"/api/teacher/groups/{group['id']}", headers=lead["headers"])

    owner = client.get("/api/teacher/audit", headers=teacher["headers"])
    assert owner.status_code == 200


def test_lead_sees_only_own_group_and_no_ips(client, teacher):
    """组长的审计是「本组视图」：看不到组外教师的记录，IP 只留给部署者。"""
    outsider = _register(client, "s6b_out")
    outsider_class = client.post("/api/teacher/classes", json={"name": "组外班级"},
                                 headers=outsider["headers"]).json()["class"]
    lead = _register(client, "s6b_lead")
    member = _register(client, "s6b_member")
    group = client.post("/api/teacher/groups", json={"name": "本组视图组"},
                        headers=lead["headers"]).json()["group"]
    try:
        added = client.post(f"/api/teacher/groups/{group['id']}/members",
                            json={"username": "s6b_member"}, headers=lead["headers"])
        assert added.status_code == 200, added.text
        member_class = client.post("/api/teacher/classes", json={"name": "组内班级"},
                                   headers=member["headers"])
        assert member_class.status_code == 200, member_class.text

        items = client.get("/api/teacher/audit", params={"limit": 200},
                           headers=lead["headers"]).json()["items"]
        assert items, "组长至少能看到自己的记录"
        actor_ids = {str(row["actor_id"]) for row in items}
        assert outsider["id"] not in actor_ids, "组长的审计不能看到组外教师"
        assert member["id"] in actor_ids and lead["id"] in actor_ids
        assert all(not row["ip"] for row in items), "组长的审计不应包含 IP"

        owner_items = client.get("/api/teacher/audit", params={"limit": 200},
                                 headers=teacher["headers"]).json()["items"]
        assert any(row["ip"] for row in owner_items), "部署者保留 IP"
        assert outsider["id"] in {str(row["actor_id"]) for row in owner_items}
    finally:
        if member_class.status_code == 200:
            client.delete(f"/api/teacher/classes/{member_class.json()['class']['id']}",
                          headers=member["headers"])
        client.delete(f"/api/teacher/classes/{outsider_class['id']}", headers=outsider["headers"])
        client.delete(f"/api/teacher/groups/{group['id']}", headers=lead["headers"])


@pytest.mark.parametrize("limit", [0, 10000])
def test_limit_is_clamped(client, teacher, limit):
    rows = client.get("/api/teacher/audit", params={"limit": limit},
                      headers=teacher["headers"]).json()["items"]
    assert 1 <= len(rows) <= 500
