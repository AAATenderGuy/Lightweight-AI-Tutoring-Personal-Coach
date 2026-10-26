"""导出安全：CSV 单元格不能变成 Excel 公式。"""
from __future__ import annotations

from server.services import reports


def test_formula_prefixes_are_escaped():
    payload = reports._csv([["=1+1", "+2", "-3", "@x", "正常", "", "=cmd|' /C calc'!A0"]])
    text = payload.decode("utf-8-sig")
    assert "'=1+1" in text
    assert "'+2" in text
    assert "'-3" in text
    assert "'@x" in text
    assert "'=cmd" in text
    assert "正常" in text


def test_bom_is_preserved():
    payload = reports._csv([["姓名"]])
    assert payload.startswith(b"\xef\xbb\xbf")


def test_class_csv_escapes_student_name(client, teacher, klass):
    joined = client.post("/api/student/join", json={
        "code": klass["code"], "name": "=1+1", "number": "07",
    })
    assert joined.status_code == 200, joined.text
    response = client.get(
        f"/api/teacher/classes/{klass['id']}/export.csv", headers=teacher["headers"],
    )
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    assert "'=1+1" in text
