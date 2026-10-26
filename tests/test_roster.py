"""名单导入与学号登录：解析、密码、重置、导出、多班同号。"""
from __future__ import annotations


def _import(client, teacher, klass, *, text="", default_password="", file=None):
    data = {"text": text, "default_password": default_password}
    if file is None:
        return client.post(
            f"/api/teacher/classes/{klass['id']}/roster", headers=teacher["headers"], data=data,
        )
    return client.post(
        f"/api/teacher/classes/{klass['id']}/roster", headers=teacher["headers"], data=data, files=file,
    )


def test_import_roster_with_passwords(client, teacher, klass):
    response = _import(
        client, teacher, klass,
        text="学号,姓名,密码\n2024101,张三,zhang123\n2024102,李四,li456\n",
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["created"] == 2
    assert data["updated"] == 0
    assert {"number": "2024101", "name": "张三", "password": "zhang123"} in data["credentials"]
    login = client.post(
        "/api/student/login", json={"number": "2024101", "password": "zhang123"},
    )
    assert login.status_code == 200
    assert login.json()["student"]["name"] == "张三"


def test_import_file_without_password_generates_pin(client, teacher, klass):
    file = {"file": ("名单.csv", "2024201,王五\n".encode("utf-8"), "text/csv")}
    response = _import(client, teacher, klass, file=file)
    assert response.status_code == 200, response.text
    credential = response.json()["credentials"][0]
    assert len(credential["password"]) == 6
    login = client.post(
        "/api/student/login", json={"number": "2024201", "password": credential["password"]},
    )
    assert login.status_code == 200


def test_default_password_is_used_when_missing(client, teacher, klass):
    response = _import(
        client, teacher, klass, text="学号\t姓名\n2024301\t赵六\n", default_password="init888",
    )
    assert response.status_code == 200, response.text
    assert response.json()["credentials"][0]["password"] == "init888"
    assert client.post(
        "/api/student/login", json={"number": "2024301", "password": "init888"},
    ).status_code == 200


def test_reimport_resets_password_and_keeps_submissions(client, teacher, klass):
    first = _import(client, teacher, klass, text="学号,姓名,密码\n2024401,钱七,oldpass1\n").json()
    login = client.post(
        "/api/student/login", json={"number": "2024401", "password": "oldpass1"},
    ).json()
    student_id = login["student"]["id"]

    second = _import(client, teacher, klass, text="学号,姓名,密码\n2024401,钱七,newpass9\n").json()
    assert second["updated"] == 1 and second["created"] == 0
    assert client.post(
        "/api/student/login", json={"number": "2024401", "password": "oldpass1"},
    ).status_code == 400
    new_login = client.post(
        "/api/student/login", json={"number": "2024401", "password": "newpass9"},
    )
    assert new_login.status_code == 200
    assert new_login.json()["student"]["id"] == student_id
    assert first["credentials"][0]["number"] == "2024401"


def test_roster_export_has_status_but_no_plaintext_password(client, teacher, klass):
    _import(client, teacher, klass, text="学号,姓名,密码\n2024501,孙八,secret123\n")
    response = client.get(
        f"/api/teacher/classes/{klass['id']}/roster.csv", headers=teacher["headers"],
    )
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    assert "学号" in text and "姓名" in text and "密码状态" in text
    assert "2024501" in text
    assert "secret123" not in text


def test_teacher_can_reset_student_password(client, teacher, klass):
    _import(client, teacher, klass, text="学号,姓名,密码\n2024601,周九,first123\n")
    login = client.post(
        "/api/student/login", json={"number": "2024601", "password": "first123"},
    ).json()
    student_id = login["student"]["id"]
    response = client.post(
        f"/api/teacher/classes/{klass['id']}/students/{student_id}/password",
        headers=teacher["headers"], json={"password": ""},
    )
    assert response.status_code == 200, response.text
    new_password = response.json()["password"]
    assert len(new_password) == 6
    assert client.post(
        "/api/student/login", json={"number": "2024601", "password": new_password},
    ).status_code == 200
    assert client.post(
        "/api/student/login", json={"number": "2024601", "password": "first123"},
    ).status_code == 400


def test_other_teacher_cannot_import_roster(client, teacher, klass):
    other = client.post("/api/teacher/register", json={
        "username": "roster-other", "password": "secret123", "name": "其他老师",
    }).json()
    headers = {"Authorization": f"Bearer {other['token']}"}
    response = client.post(
        f"/api/teacher/classes/{klass['id']}/roster",
        headers=headers, data={"text": "学号,姓名,密码\n1,甲,xxxx"},
    )
    assert response.status_code == 400


def test_same_number_in_two_classes_requires_code(client, teacher, klass):
    class_a = _import(client, teacher, klass, text="学号,姓名,密码\n7777777,双班生,pw123456\n")
    assert class_a.status_code == 200

    second = client.post(
        "/api/teacher/classes", headers=teacher["headers"], json={"name": "第二个班"},
    ).json()["class"]
    try:
        _import(client, teacher, second, text="学号,姓名,密码\n7777777,双班生,pw123456\n")
        ambiguous = client.post(
            "/api/student/login", json={"number": "7777777", "password": "pw123456"},
        )
        assert ambiguous.status_code == 400
        assert "多个班级" in ambiguous.json()["detail"]

        with_code = client.post(
            "/api/student/login",
            json={"number": "7777777", "password": "pw123456", "code": second["code"]},
        )
        assert with_code.status_code == 200
        assert with_code.json()["klass"]["id"] == second["id"]
    finally:
        client.delete(f"/api/teacher/classes/{second['id']}", headers=teacher["headers"])


def test_header_without_name_is_rejected(client, teacher, klass):
    response = _import(client, teacher, klass, text="学号,密码\n123,x\n")
    assert response.status_code == 400
    assert "姓名" in response.json()["detail"]
