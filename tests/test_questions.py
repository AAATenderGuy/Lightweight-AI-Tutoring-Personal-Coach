"""题库（P1-8）：录入 / AI 生成草稿 / 审核 / 选题组卷 / 草稿作业 / 换题保护。"""
from __future__ import annotations


def _make_single(client, teacher, **overrides):
    payload = {
        "type": "single",
        "question": "光合作用的主要场所是？",
        "options": ["线粒体", "叶绿体", "细胞核"],
        "answer_index": 1,
        "explanation": "光合作用在叶绿体中进行。",
        "topic": "光合作用",
        "knowledge_point": "光合作用·场所",
    }
    payload.update(overrides)
    response = client.post("/api/teacher/questions", headers=teacher["headers"], json=payload)
    assert response.status_code == 200, response.text
    return response.json()["question"]


def test_manual_create_is_immediately_usable(client, teacher):
    question = _make_single(client, teacher)
    assert question["status"] == "approved"
    assert question["source"] == "manual"

    listing = client.get("/api/teacher/questions", headers=teacher["headers"]).json()
    assert any(item["id"] == question["id"] for item in listing["items"])
    assert "光合作用" in listing["topics"]


def test_question_validation(client, teacher):
    empty = client.post("/api/teacher/questions", headers=teacher["headers"], json={"question": ""})
    assert empty.status_code == 422

    few_options = client.post("/api/teacher/questions", headers=teacher["headers"], json={
        "type": "single", "question": "只有一个选项？", "options": ["A"], "answer_index": 0,
    })
    assert few_options.status_code == 400

    bad_index = client.post("/api/teacher/questions", headers=teacher["headers"], json={
        "type": "single", "question": "越界？", "options": ["A", "B"], "answer_index": 5,
    })
    assert bad_index.status_code == 400


def test_ai_generation_goes_to_draft_box(client, teacher):
    generated = client.post("/api/teacher/questions/generate", headers=teacher["headers"], json={
        "topic": "细胞呼吸", "count": 3,
    })
    assert generated.status_code == 200, generated.text
    items = generated.json()["items"]
    assert len(items) >= 1
    assert all(item["status"] == "draft" for item in items)
    assert all(item["source"] == "ai" for item in items)

    drafts = client.get("/api/teacher/questions", params={"status": "draft"},
                        headers=teacher["headers"]).json()
    assert drafts["drafts"] >= len(items)

    approved = client.post("/api/teacher/questions/approve", headers=teacher["headers"],
                           json={"ids": [item["id"] for item in items]})
    assert approved.json()["approved"] == len(items)


def test_edit_and_delete(client, teacher):
    question = _make_single(client, teacher, question="改之前的题干")
    updated = client.put(f"/api/teacher/questions/{question['id']}", headers=teacher["headers"],
                         json={"question": "改之后的题干", "difficulty": "hard"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["question"]["question"] == "改之后的题干"
    assert updated.json()["question"]["difficulty"] == "hard"

    deleted = client.delete(f"/api/teacher/questions/{question['id']}", headers=teacher["headers"])
    assert deleted.status_code == 200
    listing = client.get("/api/teacher/questions", headers=teacher["headers"]).json()
    assert all(item["id"] != question["id"] for item in listing["items"])


def test_assignment_from_bank_questions(client, teacher, klass, student):
    q1 = _make_single(client, teacher, question="题库题一")
    q2 = _make_single(client, teacher, question="题库题二", answer_index=0)

    created = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
        "class_id": klass["id"], "topic": "光合作用", "kind": "quiz",
        "question_ids": [q1["id"], q2["id"]],
    })
    assert created.status_code == 200, created.text
    assignment = created.json()["assignment"]
    assert assignment["question_count"] == 2

    # 学生能正常作答
    started = client.post(f"/api/student/tasks/{assignment['id']}/start", json={
        "student_id": student["student"]["id"], "token": student["token"],
    })
    assert started.status_code == 200, started.text
    questions = started.json()["quiz"]["questions"]
    assert {item["question"] for item in questions} == {"题库题一", "题库题二"}

    # 组卷是整体拷贝：发布后再改题库，学生手里的题不变
    client.put(f"/api/teacher/questions/{q1['id']}", headers=teacher["headers"],
               json={"question": "题库题一（已改）"})
    restarted = client.post(f"/api/student/tasks/{assignment['id']}/start", json={
        "student_id": student["student"]["id"], "token": student["token"],
    })
    assert any(item["question"] == "题库题一" for item in restarted.json()["quiz"]["questions"])


def test_draft_question_cannot_be_assembled(client, teacher, klass):
    generated = client.post("/api/teacher/questions/generate", headers=teacher["headers"], json={
        "topic": "草稿保护", "count": 2,
    })
    draft_id = generated.json()["items"][0]["id"]
    created = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
        "class_id": klass["id"], "topic": "草稿保护", "question_ids": [draft_id],
    })
    assert created.status_code == 400
    assert "草稿" in created.json()["detail"]


def test_draft_assignment_invisible_until_published(client, teacher, klass, student):
    q1 = _make_single(client, teacher, question="草稿作业题")
    created = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
        "class_id": klass["id"], "topic": "光合作用", "question_ids": [q1["id"]], "draft": True,
    })
    assert created.status_code == 200, created.text
    assignment = created.json()["assignment"]
    assert assignment["state"] == "draft"
    assert assignment["draft"] is True

    tasks = client.get("/api/student/tasks", params={
        "student_id": student["student"]["id"], "token": student["token"],
    }).json()["tasks"]
    assert all(task["id"] != assignment["id"] for task in tasks)

    started = client.post(f"/api/student/tasks/{assignment['id']}/start", json={
        "student_id": student["student"]["id"], "token": student["token"],
    })
    assert started.status_code == 400

    published = client.patch(f"/api/teacher/assignments/{assignment['id']}",
                             headers=teacher["headers"], json={"draft": False})
    assert published.status_code == 200, published.text
    assert published.json()["assignment"]["state"] == "open"

    tasks = client.get("/api/student/tasks", params={
        "student_id": student["student"]["id"], "token": student["token"],
    }).json()["tasks"]
    assert any(task["id"] == assignment["id"] for task in tasks)


def test_questions_locked_after_first_submission(client, teacher, klass, student):
    q1 = _make_single(client, teacher, question="锁定题一")
    q2 = _make_single(client, teacher, question="锁定题二")
    created = client.post("/api/teacher/assignments", headers=teacher["headers"], json={
        "class_id": klass["id"], "topic": "光合作用", "question_ids": [q1["id"]],
    })
    assignment = created.json()["assignment"]

    # 没人交的时候可以换题
    swapped = client.patch(f"/api/teacher/assignments/{assignment['id']}",
                           headers=teacher["headers"], json={"question_ids": [q2["id"]]})
    assert swapped.status_code == 200, swapped.text
    assert swapped.json()["assignment"]["question_count"] == 1

    started = client.post(f"/api/student/tasks/{assignment['id']}/start", json={
        "student_id": student["student"]["id"], "token": student["token"],
    }).json()
    answers = [{"question_id": item["id"], "answer": item["options"][0]}
               for item in started["quiz"]["questions"]]
    submitted = client.post(f"/api/student/tasks/{assignment['id']}/submit", json={
        "student_id": student["student"]["id"], "token": student["token"], "answers": answers,
    })
    assert submitted.status_code == 200, submitted.text

    blocked = client.patch(f"/api/teacher/assignments/{assignment['id']}",
                           headers=teacher["headers"], json={"question_ids": [q1["id"]]})
    assert blocked.status_code == 400
    assert "不能更换题目" in blocked.json()["detail"]


def test_questions_are_private_per_teacher(client, teacher):
    other = client.post("/api/teacher/register", json={
        "username": "qb_outsider", "password": "pass1234", "name": "外人",
    }).json()
    headers = {"Authorization": f"Bearer {other['token']}"}
    mine = _make_single(client, teacher, question="私有题")
    assert client.get("/api/teacher/questions", headers=headers).json()["total"] == 0
    stolen = client.put(f"/api/teacher/questions/{mine['id']}", headers=headers,
                        json={"question": "劫持"})
    assert stolen.status_code == 400
    assert client.delete(f"/api/teacher/questions/{mine['id']}", headers=headers).status_code == 400
