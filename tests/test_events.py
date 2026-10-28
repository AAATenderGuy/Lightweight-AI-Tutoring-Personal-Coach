"""学习事件流（P1-6）：四个写入点、掌握度从事件聚合、遗留回退、时间线。"""
from __future__ import annotations

from server import store
from server.services.mastery import compute_mastery


def _personal_events():
    return [row for row in store.list_items("learning_events") if not row.get("student_id")]


def _submit_quiz(client, topic):
    created = client.post("/api/quiz/generate", json={"topic": topic, "count": 2})
    assert created.status_code == 200, created.text
    quiz = created.json()["quiz"]
    answers = [{"question_id": item["id"], "answer": item["question"]} for item in quiz["questions"]]
    submitted = client.post(f"/api/quiz/{quiz['id']}/submit", json={"answers": answers})
    assert submitted.status_code == 200, submitted.text
    return quiz, submitted.json()


def test_personal_quiz_events_feed_progress(client):
    quiz, result = _submit_quiz(client, "事件流单元测试主题A")

    events = [row for row in _personal_events() if row.get("topic") == "事件流单元测试主题A"]
    kinds = {row["kind"] for row in events}
    assert "attempt" in kinds and "quiz" in kinds
    attempts = [row for row in events if row["kind"] == "attempt"]
    assert len(attempts) == len(quiz["questions"])  # 每题一条，不按知识点折叠

    # 掌握度 = 事件流按题目顺序聚合出的加权分，与提交结果逐题对应
    expected = compute_mastery([item["score"] for item in result["results"]])
    progress = client.get("/api/progress").json()
    topic = next(item for item in progress["topics"] if item["topic"] == "事件流单元测试主题A")
    assert topic["mastery"] == expected
    assert any("事件流单元测试主题A" in row.get("topic", "") for row in progress["events"])


def test_reset_progress_clears_personal_events(client, teacher):
    _submit_quiz(client, "事件流待清理主题")
    assert any(row.get("topic") == "事件流待清理主题" for row in _personal_events())

    assert client.delete("/api/progress").status_code == 401
    cleared = client.delete("/api/progress", headers=teacher["headers"])
    assert cleared.status_code == 200
    assert all(row.get("topic") != "事件流待清理主题" for row in _personal_events())


def test_legacy_progress_fallback(client, teacher):
    # 清空个人事件后，旧共享档里的进度仍然能显示（升级不丢数据）
    client.delete("/api/progress", headers=teacher["headers"])
    store.write_shared("progress", {
        "topics": {
            "遗留主题": {
                "attempts": [{"ts": 1, "score": 1.0}, {"ts": 2, "score": 1.0}],
                "points": {}, "updated_at": 2, "lessons": [],
            },
        },
        "events": [],
    })
    progress = client.get("/api/progress").json()
    assert any(item["topic"] == "遗留主题" for item in progress["topics"])
    client.delete("/api/progress", headers=teacher["headers"])


def _bank_assignment(client, teacher, klass, topic):
    question = client.post("/api/teacher/questions", headers=teacher["headers"], json={
        "type": "single", "question": f"{topic}·题一", "options": ["错", "对", "错"],
        "answer_index": 1, "topic": topic, "knowledge_point": f"{topic}·点一",
    }).json()["question"]
    created = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
        "class_id": klass["id"], "topic": topic, "question_ids": [question["id"]],
    })
    assert created.status_code == 200, created.text
    return created.json()["assignment"]


def test_assignment_events_feed_student_timeline(client, teacher, klass, student):
    assignment = _bank_assignment(client, teacher, klass, "事件流作业主题")
    sid, token = student["student"]["id"], student["token"]

    started = client.post(f"/api/student/tasks/{assignment['id']}/start",
                          json={"student_id": sid, "token": token}).json()
    answers = [{"question_id": item["id"], "answer": "1"}  # 作答传选项序号
               for item in started["quiz"]["questions"]]
    submitted = client.post(f"/api/student/tasks/{assignment['id']}/submit",
                            json={"student_id": sid, "token": token, "answers": answers})
    assert submitted.status_code == 200, submitted.text

    denied = client.get("/api/student/timeline", params={"student_id": sid, "token": "wrong"})
    assert denied.status_code == 401

    timeline = client.get("/api/student/timeline", params={"student_id": sid, "token": token}).json()
    assert any(row["kind"] == "assignment" and row["score"] == 1.0 for row in timeline["events"])
    topic = next(item for item in timeline["topics"] if item["topic"] == "事件流作业主题")
    # 只有一次作答记录时，掌握度受「证据不足」上限约束（1 次封顶 0.5）
    assert topic["mastery"] == 0.5
    assert topic["points"][0]["name"] == "事件流作业主题·点一"

    # 教师导出的学习报告里带学习轨迹段
    report = client.get(f"/api/teacher/students/{sid}/report.html", headers=teacher["headers"])
    assert report.status_code == 200
    assert "学习轨迹" in report.text and "事件流作业主题" in report.text


def test_file_submission_regrade_appends_latest_score(client, teacher, klass, student):
    sid, token = student["student"]["id"], student["token"]

    def submit_and_regrade(topic, teacher_score):
        created = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
            "class_id": klass["id"], "topic": topic, "submission_mode": "file",
            "instructions": "写一段话",
        })
        assert created.status_code == 200, created.text
        assignment = created.json()["assignment"]
        submitted = client.post(
            f"/api/student/tasks/{assignment['id']}/submit-file",
            data={"student_id": sid, "token": token},
            files={"file": ("作业.txt", "这是我的作业内容。".encode())},
        )
        assert submitted.status_code == 200, submitted.text
        submission_id = f"sb_{assignment['id']}_{sid}"
        regraded = client.patch(f"/api/teacher/submissions/{submission_id}",
                                headers=teacher["headers"], json={"score": teacher_score})
        assert regraded.status_code == 200, regraded.text

    # 同主题交两次文件作业，教师分别改分为 30 与 88：
    # 掌握度若等于按 [0.30, 0.88] 的加权结果，说明两次都是「改分后的最新分」在起作用
    submit_and_regrade("事件流文件作业", 30)
    submit_and_regrade("事件流文件作业", 88)

    from server.services import mastery
    progress = mastery.student_progress(sid)
    topic = next(item for item in progress["topics"] if item["topic"] == "事件流文件作业")
    assert topic["attempts"] == 2
    assert topic["mastery"] == compute_mastery([0.30, 0.88])
