"""金文件测试：学生报告 HTML 锁定基线。

报告模板、文案或事件流输出一旦变化，本测试会失败；
确认变化是有意的之后，用 EDU_UPDATE_GOLDEN=1 重建基线。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "golden" / "student_report.html"


def _normalize(html: str) -> str:
    """把时间戳等每次都变的内容归一化，其余逐字节对比。"""
    html = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?", "<TIME>", html)
    return re.sub(r"\d{2}-\d{2} \d{2}:\d{2}", "<TIME>", html)


def _build_report(client, teacher, klass, student) -> str:
    question = client.post("/api/teacher/questions", headers=teacher["headers"], json={
        "type": "single", "question": "金文件题：1+1=？", "options": ["1", "2", "3"],
        "answer_index": 1, "topic": "金文件主题", "knowledge_point": "加法",
    }).json()["question"]
    assignment = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
        "class_id": klass["id"], "topic": "金文件主题", "question_ids": [question["id"]],
    }).json()["assignment"]
    sid, token = student["student"]["id"], student["token"]
    started = client.post(f"/api/student/tasks/{assignment['id']}/start",
                          json={"student_id": sid, "token": token}).json()
    answers = [{"question_id": item["id"], "answer": "1"} for item in started["quiz"]["questions"]]
    submitted = client.post(f"/api/student/tasks/{assignment['id']}/submit",
                            json={"student_id": sid, "token": token, "answers": answers})
    assert submitted.status_code == 200
    report = client.get(f"/api/teacher/students/{sid}/report.html", headers=teacher["headers"])
    assert report.status_code == 200
    return report.text


def test_student_report_html_golden(client, teacher, klass, student):
    html = _normalize(_build_report(client, teacher, klass, student))
    if os.environ.get("EDU_UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(html, encoding="utf-8")
        pytest.skip("已重建金文件基线")
    assert GOLDEN.exists(), "金文件不存在，先以 EDU_UPDATE_GOLDEN=1 跑一次生成基线"
    expected = GOLDEN.read_text(encoding="utf-8")
    assert html == expected, (
        "学生报告 HTML 与金文件不一致。若这是有意的模板/文案变更，"
        "请复核差异后以 EDU_UPDATE_GOLDEN=1 重建基线。"
    )
