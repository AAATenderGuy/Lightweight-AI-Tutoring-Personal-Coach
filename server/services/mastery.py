"""掌握度模型。

策略沿用 DeepTutor：近期表现权重更高，且证据不足时给掌握度设上限，
避免“蒙对一题就算掌握”。策略集中在本文件，方便替换成 IRT/BKT。

事实来源是学习事件流（services/events.py）：作答、测验、上课都先落成事件，
掌握度只是事件流按主题/知识点聚合出的一个视图，随时可以重算。
旧的 ``progress`` 共享档不再写入，仅在“还没有任何事件”时作为遗留数据回退读取。
"""
from __future__ import annotations

from .. import store
from . import learning as learning_service

RECENCY_WEIGHTS: tuple[float, ...] = (0.5, 0.7, 0.85, 0.95, 1.0)
CONFIDENCE_CAP: dict[int, float] = {1: 0.5, 2: 0.8}

MAX_TOPIC_ATTEMPTS = 40
MAX_POINT_ATTEMPTS = 20


def compute_mastery(correctness: list[float]) -> float:
    if not correctness:
        return 0.0
    recent = correctness[-len(RECENCY_WEIGHTS):]
    weights = RECENCY_WEIGHTS[-len(recent):]
    score = sum(
        weight * max(0.0, min(1.0, float(value)))
        for value, weight in zip(recent, weights, strict=True)
    ) / sum(weights)
    return round(min(score, CONFIDENCE_CAP.get(len(recent), 1.0)), 3)


def mastery_label(score: float) -> str:
    if score >= 0.85:
        return "已掌握"
    if score >= 0.6:
        return "基本掌握"
    if score > 0:
        return "需巩固"
    return "未开始"


def record_attempt(topic: str, point: str, score: float, *, source: str = "", feedback: str = "",
                   silent: bool = False) -> None:
    """记一次作答。``source`` 传产生它的业务对象 id（如测验 id），聚合时同引用取最新。"""
    topic = (topic or "未分类主题").strip()[:60]
    point = (point or topic).strip()[:60]
    score = max(0.0, min(1.0, float(score)))
    learning_service.record(
        learning_service.ATTEMPT, topic=topic, point=point, score=score, ref_id=source,
    )
    if not silent:
        learning_service.record(
            "note", topic=topic, point=point, score=score,
            summary=(feedback or f"练习「{point}」")[:160],
        )


def log_event(*, kind: str, topic: str, summary: str, score: float | None = None) -> None:
    learning_service.record(kind, topic=topic, summary=summary, score=score)


def record_lesson(lesson: dict) -> None:
    topic = (lesson.get("topic") or lesson.get("title") or "未命名课堂").strip()[:60]
    learning_service.record(
        learning_service.LESSON, topic=topic, ref_id=str(lesson.get("id") or ""),
        summary=f"生成课堂《{lesson.get('title') or topic}》",
    )


def _aggregate(rows: list[dict]) -> dict:
    """把 attempt 事件聚成 主题→知识点→分数序列（时间升序）。

    同一 (ref_id, point) 只保留最新一条：重交或教师改分追加的是新事件，
    聚合时后者覆盖前者，事件流本身保持只增不改。
    """
    latest: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (str(row.get("ref_id") or row.get("id")), str(row.get("point") or ""))
        if key not in latest or float(row.get("ts") or 0) >= float(latest[key].get("ts") or 0):
            latest[key] = row
    ordered = sorted(latest.values(), key=lambda item: float(item.get("ts") or 0))

    topics: dict[str, dict] = {}
    for row in ordered:
        topic = str(row.get("topic") or "未分类主题")
        point = str(row.get("point") or topic)
        score = max(0.0, min(1.0, float(row.get("score") or 0)))
        ts = float(row.get("ts") or 0)
        entry = topics.setdefault(topic, {"attempts": [], "points": {}, "updated_at": 0.0})
        entry["attempts"].append(score)
        entry["updated_at"] = max(entry["updated_at"], ts)
        entry["points"].setdefault(point, []).append(score)
    for entry in topics.values():
        entry["attempts"] = entry["attempts"][-MAX_TOPIC_ATTEMPTS:]
        entry["points"] = {
            name: scores[-MAX_POINT_ATTEMPTS:] for name, scores in entry["points"].items()
        }
    return topics


def _topics_payload(topics: dict[str, dict], lessons: dict[str, list] | None = None) -> list[dict]:
    out = []
    for name, entry in topics.items():
        scores = entry.get("attempts") or []
        mastery = compute_mastery(scores)
        points = []
        for point_name, point_scores in (entry.get("points") or {}).items():
            point_mastery = compute_mastery(point_scores)
            points.append({
                "name": point_name,
                "mastery": point_mastery,
                "label": mastery_label(point_mastery) if point_scores else "未开始",
                "attempts": len(point_scores),
            })
        points.sort(key=lambda item: item["mastery"])
        out.append({
            "topic": name,
            "mastery": mastery,
            "label": mastery_label(mastery) if scores else "未开始",
            "attempts": len(scores),
            "points": points,
            "lessons": (lessons or {}).get(name, []),
            "updated_at": entry.get("updated_at") or 0,
        })
    out.sort(key=lambda item: (item["mastery"], -item["updated_at"]))
    return out


def _recommendations(topics: list[dict]) -> list[dict]:
    recommendations = []
    for item in topics:
        for point in item["points"]:
            if point["attempts"] and point["mastery"] < 0.7:
                recommendations.append({
                    "topic": item["topic"],
                    "point": point["name"],
                    "mastery": point["mastery"],
                    "reason": f"「{point['name']}」掌握度 {int(point['mastery'] * 100)}%，建议再练一次。",
                })
            if len(recommendations) >= 4:
                break
        if len(recommendations) >= 4:
            break
    if not recommendations:
        recommendations.append({
            "topic": "",
            "point": "",
            "mastery": 0,
            "reason": "还没有练习记录。先上传资料、生成一堂课，再做一次随堂测验吧。",
        })
    return recommendations


def _payload_from_topics(topics: list[dict], feed: list[dict]) -> dict:
    total_attempts = sum(item["attempts"] for item in topics)
    weighted_sum = sum(item["mastery"] for item in topics)
    return {
        "topics": topics,
        "recommendations": _recommendations(topics),
        "stats": {
            "topics": len(topics),
            "attempts": total_attempts,
            "average_mastery": round(weighted_sum / len(topics), 3) if topics else 0.0,
        },
        "events": feed[:20],
    }


def _legacy_payload() -> dict:
    """旧共享档回退：升级前留下的 progress 数据在新事件流为空时仍然可见。"""
    data = store.read_shared("progress", {"topics": {}, "events": []})
    if not isinstance(data, dict) or not data.get("topics"):
        return _payload_from_topics([], [])
    legacy: dict[str, dict] = {}
    lessons: dict[str, list] = {}
    for name, entry in data["topics"].items():
        scores = [max(0.0, min(1.0, float(a.get("score") or 0)))
                  for a in (entry.get("attempts") or [])][-MAX_TOPIC_ATTEMPTS:]
        points = {
            point_name: [max(0.0, min(1.0, float(a.get("score") or 0)))
                         for a in (point_entry.get("attempts") or [])][-MAX_POINT_ATTEMPTS:]
            for point_name, point_entry in (entry.get("points") or {}).items()
        }
        legacy[name] = {
            "attempts": scores,
            "points": points,
            "updated_at": float(entry.get("updated_at") or 0),
        }
        lessons[name] = entry.get("lessons") or []
    feed = [row for row in (data.get("events") or []) if isinstance(row, dict)]
    return _payload_from_topics(_topics_payload(legacy, lessons), feed)


def progress_payload() -> dict:
    """本机个人学习进度：从个人范围（student_id 为空）的事件流聚合。"""
    rows = learning_service.list_events(student_id="", limit=2000)
    attempts = [row for row in rows if row.get("kind") == learning_service.ATTEMPT]
    if not rows:
        return _legacy_payload()

    lessons: dict[str, list] = {}
    feed = []
    for row in rows:  # rows 新的在前
        kind = row.get("kind")
        if kind == learning_service.LESSON:
            topic = row.get("topic") or "未分类主题"
            bucket = lessons.setdefault(topic, [])
            if len(bucket) < 20:
                bucket.append({"id": row.get("ref_id"), "title": row.get("summary", "").replace("生成课堂《", "").rstrip("》"), "ts": row.get("ts")})
        if kind != learning_service.ATTEMPT:
            feed.append({
                "ts": row.get("ts"),
                "kind": kind,
                "topic": row.get("topic") or "",
                "summary": row.get("summary") or "",
                **({"score": row["score"]} if row.get("score") is not None else {}),
            })
    return _payload_from_topics(_topics_payload(_aggregate(attempts), lessons), feed)


def student_progress(student_id: str) -> dict:
    """某个学生的掌握度视图：只聚合这名学生的事件（班级作业/测验）。"""
    rows = learning_service.list_events(student_id=student_id, limit=2000)
    attempts = [row for row in rows if row.get("kind") == learning_service.ATTEMPT]
    return _payload_from_topics(_topics_payload(_aggregate(attempts)), [])


def reset_progress() -> None:
    """清空本机个人进度：个人事件 + 旧共享档一起清，班级数据不动。"""
    learning_service.clear_personal()
    store.write_shared("progress", {"topics": {}, "events": []})
