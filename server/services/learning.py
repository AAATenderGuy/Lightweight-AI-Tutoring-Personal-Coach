"""学习事件流（P1 · 统一 learning_event）。

课堂、作业、测验产生的学习痕迹统一追加到 ``learning_events`` 集合，
掌握度、学生时间线、教师报告里的学习轨迹都从这条事件流聚合——
事件是唯一事实来源，掌握度只是它的一个视图。

事件只追加不修改（教师复核改分 = 再追加一条同引用的新事件，聚合时取最新），
这样任何时候都能重放出当时看到的学习轨迹。

写入失败只记日志不抛错：事件流是旁路记录，不能反过来影响作答主流程。

注意：本模块是「学习事件流」，与 events.py 的「进程内 SSE 事件总线」是两回事。
"""
from __future__ import annotations

import time

from .. import store
from ..observability import logger

log = logger("edu.learning")

# 事件类型统一在这里，避免各处字符串拼错
ATTEMPT = "attempt"                # 一次作答（按题目/知识点记分，掌握度的原料）
QUIZ = "quiz"                      # 完成一整份随堂测验（摘要事件）
ASSIGNMENT = "assignment"          # 提交班级作业（摘要事件）
DISCUSS = "discuss"                # 课堂答疑提问
GROUP_DISCUSS = "group_discuss"    # 小组讨论发言
LESSON = "lesson"                  # 生成一堂课

KIND_LABELS = {
    ATTEMPT: "作答",
    QUIZ: "测验",
    ASSIGNMENT: "作业",
    DISCUSS: "答疑",
    GROUP_DISCUSS: "讨论",
    LESSON: "课堂",
}

MAX_TOPIC = 60
MAX_SUMMARY = 160


def record(kind: str, *, topic: str = "", point: str = "", score: float | None = None,
           student_id: str = "", class_id: str = "", ref_id: str = "",
           summary: str = "", source: str = "") -> dict | None:
    """追加一条学习事件。

    - ``student_id`` 为空表示本机个人模式（班级体系之外的自学痕迹）；
    - ``ref_id`` 指向产生事件的业务对象（测验/提交记录/课堂），
      同一引用再次记分（重交、教师改分）时聚合取最新一条；
    - ``source`` 标记作答来源（如 ``assignment``），个人测验留空。
    """
    event = {
        "id": store.new_id("ev_"),
        "ts": time.time(),
        "kind": str(kind or "")[:24],
        "topic": str(topic or "").strip()[:MAX_TOPIC],
        "point": str(point or "").strip()[:MAX_TOPIC],
        "student_id": str(student_id or ""),
        "class_id": str(class_id or ""),
        "ref_id": str(ref_id or ""),
        "source": str(source or "")[:24],
        "summary": str(summary or "")[:MAX_SUMMARY],
    }
    if score is not None:
        event["score"] = round(max(0.0, min(1.0, float(score))), 3)
    try:
        return store.save_item("learning_events", event)
    except Exception as exc:  # noqa: BLE001 - 事件流是旁路，不能打断主流程
        log.warning("学习事件写入失败：%s", exc)
        return None


def list_events(*, student_id: str | None = None, class_id: str | None = None,
                kinds: tuple[str, ...] | None = None, limit: int = 200) -> list[dict]:
    """按条件读事件，新的在前。

    ``student_id=None`` 表示不按学生过滤；要取「个人模式」请显式传空字符串。
    """
    limit = max(1, min(int(limit or 200), 2000))
    rows = store.list_items("learning_events")
    out = []
    for row in rows:
        if student_id is not None and str(row.get("student_id") or "") != student_id:
            continue
        if class_id is not None and str(row.get("class_id") or "") != class_id:
            continue
        if kinds is not None and row.get("kind") not in kinds:
            continue
        out.append(row)
    out.sort(key=lambda item: -float(item.get("ts") or 0))
    return out[:limit]


def clear_personal() -> int:
    """清空本机个人模式的事件（重置学习进度用），班级事件不动。"""
    removed = 0
    for row in store.list_items("learning_events"):
        if str(row.get("student_id") or ""):
            continue
        try:
            store.delete_item("learning_events", row["id"])
            removed += 1
        except (KeyError, ValueError):
            continue
    return removed


def student_timeline(student_id: str, limit: int = 60) -> list[dict]:
    """学生端时间线：摘要事件为主，逐题作答太碎不进时间线。"""
    rows = list_events(
        student_id=student_id,
        kinds=(QUIZ, ASSIGNMENT, DISCUSS, GROUP_DISCUSS, LESSON),
        limit=limit,
    )
    return [
        {
            "id": row["id"],
            "ts": row.get("ts"),
            "kind": row.get("kind"),
            "label": KIND_LABELS.get(row.get("kind"), "记录"),
            "topic": row.get("topic") or "",
            "summary": row.get("summary") or "",
            "score": row.get("score"),
        }
        for row in rows
    ]
