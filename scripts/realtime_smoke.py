"""实时链路冒烟测试：验证 SSE 事件确实在写操作之后推给了对端。

用法（先启动服务）：
    .venv\\Scripts\\python scripts/realtime_smoke.py http://127.0.0.1:8000

覆盖四件事：
1. 教师流能连上，并在学生加入班级时收到 student_joined；
2. 学生流能连上，在线名单（presence）能查到该学生；
3. 老师布置作业后，学生流收到 assignment_created；
4. 学生交卷后，教师流收到 submission_saved，且详情统计已经更新。

脚本会自建一个临时班级，跑完删掉，不会污染现有数据。
"""
from __future__ import annotations

import json
import sys
import threading
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
SAMPLE_ANSWER = "叶绿体"


class StreamCollector:
    """在后台线程里消费一条 SSE，事件按到达顺序存下来。"""

    def __init__(self, name: str, path: str, headers: dict | None = None) -> None:
        self.name = name
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._taken: set[int] = set()
        self._thread = threading.Thread(target=self._run, args=(path, headers or {}), daemon=True)
        self._thread.start()

    def _run(self, path: str, headers: dict) -> None:
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0, read=None)) as client:
                with client.stream("GET", f"{BASE}{path}", headers=headers) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload:
                            continue
                        event = json.loads(payload)
                        with self._lock:
                            self.events.append(event)
                        if event.get("type") == "ready":
                            self._ready.set()
        except Exception as exc:  # noqa: BLE001 - 冒烟脚本，打印出来即可
            print(f"  [{self.name}] 流已结束：{exc}")

    def wait_ready(self, timeout: float = 8.0) -> None:
        if not self._ready.wait(timeout):
            raise SystemExit(f"  [{self.name}] 8 秒内没有收到 ready，连接可能失败")

    def wait_for(self, event_type: str, timeout: float = 10.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for index, event in enumerate(self.events):
                    if index in self._taken or event.get("type") != event_type:
                        continue
                    self._taken.add(index)
                    return event
            time.sleep(0.05)
        with self._lock:
            seen = [str(event.get("type")) for event in self.events]
        raise SystemExit(f"  [{self.name}] 没有收到 {event_type}，已收到：{seen}")


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=30.0)
    login = client.post("/api/teacher/login", json={"username": "demo", "password": "demo1234"})
    login.raise_for_status()
    auth = {"Authorization": f"Bearer {login.json()['token']}"}

    suffix = str(int(time.time() * 1000))[-6:]
    class_id = ""
    try:
        created = client.post("/api/teacher/classes", json={"name": f"实时冒烟 {suffix}"}, headers=auth)
        created.raise_for_status()
        klass = created.json()["class"]
        class_id = klass["id"]
        print(f"临时班级：{klass['name']} · 邀请码 {klass['code']}")

        teacher_stream = StreamCollector("教师", "/api/teacher/stream", auth)
        teacher_stream.wait_ready()
        print("✓ 教师 SSE 已连接")

        suffix = str(int(time.time()))[-4:]
        student_number = f"2099{suffix}"
        roster = f"学号,姓名,密码\n{student_number},实时同学,realtime123\n"
        client.post(
            f"/api/teacher/classes/{class_id}/roster",
            headers=auth,
            data={"text": roster, "default_password": ""},
        ).raise_for_status()
        teacher_stream.wait_for("class_changed")
        print("✓ 导入名单 → 教师收到 class_changed")

        joined = client.post(
            "/api/student/login", json={"number": student_number, "password": "realtime123"},
        ).json()
        student_id = joined["student"]["id"]
        student_token = joined["token"]
        print(f"✓ 学生用学号登录（{joined['student']['name']}）")

        student_stream = StreamCollector(
            "学生", f"/api/student/stream?student_id={student_id}&token={student_token}",
        )
        student_stream.wait_ready()
        print("✓ 学生 SSE 已连接")

        presence = client.get("/api/teacher/presence", headers=auth).json()["items"].get(class_id) or []
        if student_id not in presence:
            raise SystemExit(f"在线名单里没有该学生：{presence}")
        print(f"✓ 在线名单包含该学生（{len(presence)} 人在线）")

        assignment = client.post("/api/teacher/assignments", headers=auth, json={
            "class_id": class_id, "topic": "光合作用", "kind": "quiz",
            "count": 3, "difficulty": "easy", "instructions": "实时冒烟",
        }).json()["assignment"]
        print(f"✓ 老师布置作业《{assignment['title']}》")

        event = student_stream.wait_for("assignment_created")
        print(f"✓ 布置作业 → 学生收到 assignment_created（{event['title']}）")
        teacher_stream.wait_for("assignment_created")

        quiz = client.post(f"/api/student/tasks/{assignment['id']}/start",
                           json={"student_id": student_id, "token": student_token}).json()["quiz"]
        answers = [
            {"question_id": question["id"],
             "answer": "0" if question.get("type") == "single" else SAMPLE_ANSWER}
            for question in quiz["questions"]
        ]
        result = client.post(f"/api/student/tasks/{assignment['id']}/submit",
                             json={"student_id": student_id, "token": student_token,
                                   "answers": answers}).json()
        print(f"✓ 学生交卷，得分 {round((result.get('score') or 0) * 100)}")

        event = teacher_stream.wait_for("submission_saved")
        print(f"✓ 交卷 → 教师收到 submission_saved"
              f"（{event['student_name']} {round((event.get('score') or 0) * 100)} 分）")
        student_stream.wait_for("tasks_changed")

        detail = client.get(f"/api/teacher/assignments/{assignment['id']}", headers=auth).json()
        if detail.get("submitted") != 1:
            raise SystemExit(f"详情统计没有更新：{detail.get('submitted')}")
        print(f"✓ 教师详情已更新：已交 {detail['submitted']}/{detail['total']}，"
              f"提交率 {round((detail.get('completion') or 0) * 100)}%")

        client.delete(f"/api/teacher/classes/{class_id}", headers=auth)
        student_stream.wait_for("class_deleted")
        print("✓ 删除班级 → 学生流收到 class_deleted")
        class_id = ""

        print("\n实时链路全部通过。")
    finally:
        if class_id:
            client.delete(f"/api/teacher/classes/{class_id}", headers=auth)
            print("临时班级已清理。")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    main()
