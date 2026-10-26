"""教师工作台冒烟测试：登录 → 建班 → 学生加入 → 布置作业 → 提交 → 统计 → 导出。

用法（服务已启动）：
    .venv/Scripts/python scripts/teacher_smoke.py http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import sys
import time

import httpx

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def show(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    with httpx.Client(timeout=120, trust_env=False) as client:
        show("教师登录")
        response = client.post(f"{BASE}/api/teacher/login", json={"username": "demo", "password": "demo1234"})
        response.raise_for_status()
        token = response.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("teacher:", response.json()["teacher"]["name"])

        show("创建班级")
        response = client.post(
            f"{BASE}/api/teacher/classes",
            json={"name": f"冒烟测试班 {int(__import__('time').time()) % 10000}", "subject": "生物"},
            headers=headers,
        )
        response.raise_for_status()
        klass = response.json()["class"]
        print("class:", klass["name"], "code:", klass["code"])

        show("导入名单并登录")
        suffix = str(int(time.time()))[-4:]
        numbers = (f"2024{suffix}1", f"2024{suffix}2")
        roster = (
            f"学号,姓名,密码\n{numbers[0]},林小雨,lin123456\n{numbers[1]},陈可,chen123456\n"
        )
        response = client.post(
            f"{BASE}/api/teacher/classes/{klass['id']}/roster",
            headers=headers,
            data={"text": roster, "default_password": ""},
        )
        response.raise_for_status()
        print("imported:", response.json()["total"], "人")
        students = []
        for number, password in ((numbers[0], "lin123456"), (numbers[1], "chen123456")):
            response = client.post(
                f"{BASE}/api/student/login", json={"number": number, "password": password},
            )
            response.raise_for_status()
            data = response.json()
            students.append((data["student"]["id"], data["token"]))
            print("login:", data["student"]["name"])

        show("布置随堂测验")
        response = client.post(
            f"{BASE}/api/teacher/assignments",
            json={
                "class_id": klass["id"],
                "topic": "光合作用",
                "kind": "quiz",
                "count": 3,
                "difficulty": "medium",
                "reveal": True,
            },
            headers=headers,
        )
        response.raise_for_status()
        assignment = response.json()["assignment"]
        print("assignment:", assignment["title"], "| 题数", assignment["question_count"])

        show("学生作答")
        response = client.post(
            f"{BASE}/api/student/tasks/{assignment['id']}/start",
            json={"student_id": students[0][0], "token": students[0][1]},
        )
        response.raise_for_status()
        quiz = response.json()["quiz"]
        answers = [
            {"question_id": question["id"], "answer": "光合作用把光能转成化学能，需要叶绿体、二氧化碳和水。"}
            for question in quiz["questions"]
        ]
        response = client.post(
            f"{BASE}/api/student/tasks/{assignment['id']}/submit",
            json={"student_id": students[0][0], "token": students[0][1], "answers": answers},
        )
        response.raise_for_status()
        print("score:", response.json()["score"], "| 答对", response.json()["correct_count"])

        show("学生任务列表")
        response = client.get(
            f"{BASE}/api/student/tasks",
            params={"student_id": students[1][0], "token": students[1][1]},
        )
        response.raise_for_status()
        print("tasks:", [(item["title"], item["status"]) for item in response.json()["tasks"]])

        show("教师查看作业统计")
        response = client.get(f"{BASE}/api/teacher/assignments/{assignment['id']}", headers=headers)
        response.raise_for_status()
        detail = response.json()
        print(json.dumps({
            "submitted": detail["submitted"],
            "total": detail["total"],
            "avg_score": detail["avg_score"],
            "missing": [item["name"] for item in detail["missing"]],
            "questions": [(item["index"], item["wrong"], item["error_rate"]) for item in detail["questions"]],
            "knowledge": [(item["point"], item["error_rate"]) for item in detail["knowledge"]],
        }, ensure_ascii=False))

        show("文件作业：提交、AI 批改、教师下载与复核")
        response = client.post(
            f"{BASE}/api/teacher/assignments",
            json={
                "class_id": klass["id"],
                "topic": "光合作用实验报告",
                "kind": "homework",
                "submission_mode": "file",
                "instructions": "提交一份实验报告",
                "rubric": "写出光反应与暗反应的区别",
                "reveal": True,
            },
            headers=headers,
        )
        response.raise_for_status()
        file_assignment = response.json()["assignment"]
        response = client.post(
            f"{BASE}/api/student/tasks/{file_assignment['id']}/submit-file",
            data={"student_id": students[0][0], "token": students[0][1], "note": "实验报告"},
            files={"file": ("报告.txt", "光反应在类囊体薄膜上进行，暗反应在叶绿体基质中进行。".encode("utf-8"), "text/plain")},
        )
        response.raise_for_status()
        graded = response.json()
        print("ai score:", graded["score"], "| feedback:", graded["ai_feedback"][:40])
        response = client.get(f"{BASE}/api/teacher/assignments/{file_assignment['id']}", headers=headers)
        response.raise_for_status()
        file_detail = response.json()
        submission = file_detail["submissions"][0]
        print("files:", [(item["filename"], item["size"]) for item in submission["files"]])
        response = client.get(
            f"{BASE}/api/teacher/submissions/{submission['id']}/files/{submission['files'][0]['id']}",
            headers=headers,
        )
        response.raise_for_status()
        print("download bytes:", len(response.content))
        response = client.patch(
            f"{BASE}/api/teacher/submissions/{submission['id']}",
            json={"score": 90, "feedback": "论证完整，结论明确", "note": "复核加分"},
            headers=headers,
        )
        response.raise_for_status()
        print("teacher score:", response.json()["submission"]["score"])

        show("薄弱点补练")
        response = client.post(
            f"{BASE}/api/teacher/assignments/{assignment['id']}/practice",
            json={"count": 3, "focus_points": [item["point"] for item in detail["knowledge"][:2]]},
            headers=headers,
        )
        response.raise_for_status()
        print("practice:", response.json()["assignment"]["title"])

        show("导出")
        response = client.get(f"{BASE}/api/teacher/classes/{klass['id']}/export.csv", headers=headers)
        response.raise_for_status()
        print("class csv:", response.text.strip().splitlines()[0])
        response = client.get(f"{BASE}/api/teacher/assignments/{assignment['id']}/export.csv", headers=headers)
        response.raise_for_status()
        print("assignment csv:", response.text.strip().splitlines()[0])
        response = client.get(f"{BASE}/api/teacher/students/{students[0][0]}/report.html", headers=headers)
        response.raise_for_status()
        print("report html:", len(response.text), "chars")

        response = client.get(f"{BASE}/api/teacher/classes/{klass['id']}/report.html", headers=headers)
        response.raise_for_status()
        report = response.text
        sections = [name for name in ("成绩分布", "作业完成情况", "学生排名", "成绩矩阵", "薄弱知识点")
                    if name in report]
        print("class report html:", len(report), "chars")
        print("  章节:", "、".join(sections))
        print("  含 SVG 图表:", "<svg" in report, "| 含柱状图:", "hist" in report)
        print("  content-type:", response.headers.get("content-type"))
        print("  文件名头:", response.headers.get("content-disposition"))

        show("概览")
        response = client.get(f"{BASE}/api/teacher/overview", headers=headers)
        response.raise_for_status()
        print(json.dumps(response.json()["stats"], ensure_ascii=False))
        print("\n全部通过。")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    main()
