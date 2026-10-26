"""掌握度模型。

直接沿用 DeepTutor 的策略：近期表现权重更高，且证据不足时给掌握度设上限，
避免“蒙对一题就算掌握”。策略集中在本文件，方便替换成 IRT/BKT。
"""
from __future__ import annotations

import threading
import time

from .. import store

RECENCY_WEIGHTS: tuple[float, ...] = (0.5, 0.7, 0.85, 0.95, 1.0)
CONFIDENCE_CAP: dict[int, float] = {1: 0.5, 2: 0.8}

_LOCK = threading.RLock()


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


def _load() -> dict:
    data = store.read_shared("progress", {"topics": {}, "events": []})
    if not isinstance(data, dict):
        data = {"topics": {}, "events": []}
    data.setdefault("topics", {})
    data.setdefault("events", [])
    return data


def _save(data: dict) -> None:
    store.write_shared("progress", data)


def record_attempt(topic: str, point: str, score: float, *, source: str = "", feedback: str = "",
                   silent: bool = False) -> None:
    topic = (topic or "未分类主题").strip()[:60]
    point = (point or topic).strip()[:60]
    score = max(0.0, min(1.0, float(score)))
    now = time.time()
    with _LOCK:
        data = _load()
        entry = data["topics"].setdefault(topic, {"attempts": [], "points": {}, "updated_at": now})
        entry["attempts"].append({"ts": now, "score": round(score, 3), "source": source})
        entry["attempts"] = entry["attempts"][-40:]
        entry["updated_at"] = now
        point_entry = entry.setdefault("points", {}).setdefault(point, {"attempts": []})
        point_entry["attempts"].append({"ts": now, "score": round(score, 3)})
        point_entry["attempts"] = point_entry["attempts"][-20:]
        entry.setdefault("lessons", [])
        if not silent:
            data["events"].insert(0, {
                "ts": now,
                "kind": "attempt",
                "topic": topic,
                "point": point,
                "score": round(score, 3),
                "feedback": feedback[:160],
            })
            data["events"] = data["events"][:60]
        _save(data)


def log_event(*, kind: str, topic: str, summary: str, score: float | None = None) -> None:
    with _LOCK:
        data = _load()
        event = {"ts": time.time(), "kind": kind, "topic": topic, "summary": summary[:160]}
        if score is not None:
            event["score"] = round(float(score), 3)
        data["events"].insert(0, event)
        data["events"] = data["events"][:60]
        _save(data)


def record_lesson(lesson: dict) -> None:
    topic = (lesson.get("topic") or lesson.get("title") or "未命名课堂").strip()[:60]
    now = time.time()
    with _LOCK:
        data = _load()
        entry = data["topics"].setdefault(topic, {"attempts": [], "points": {}, "updated_at": now})
        entry.setdefault("lessons", []).insert(0, {
            "id": lesson.get("id"),
            "title": lesson.get("title"),
            "ts": now,
        })
        entry["lessons"] = entry["lessons"][:20]
        entry["updated_at"] = now
        data["events"].insert(0, {
            "ts": now,
            "kind": "lesson",
            "topic": topic,
            "summary": f"生成课堂《{lesson.get('title') or topic}》",
        })
        data["events"] = data["events"][:60]
        _save(data)


def progress_payload() -> dict:
    data = _load()
    topics = []
    total_attempts = 0
    weighted_sum = 0.0
    for name, entry in data["topics"].items():
        attempts = entry.get("attempts") or []
        scores = [float(a.get("score", 0)) for a in attempts]
        mastery = compute_mastery(scores)
        total_attempts += len(scores)
        weighted_sum += mastery
        points = []
        for point_name, point_entry in (entry.get("points") or {}).items():
            point_scores = [float(a.get("score", 0)) for a in (point_entry.get("attempts") or [])]
            point_mastery = compute_mastery(point_scores)
            points.append({
                "name": point_name,
                "mastery": point_mastery,
                "label": mastery_label(point_mastery) if point_scores else "未开始",
                "attempts": len(point_scores),
            })
        points.sort(key=lambda item: item["mastery"])
        topics.append({
            "topic": name,
            "mastery": mastery,
            "label": mastery_label(mastery) if scores else "未开始",
            "attempts": len(scores),
            "points": points,
            "lessons": entry.get("lessons") or [],
            "updated_at": entry.get("updated_at") or 0,
        })
    topics.sort(key=lambda item: (item["mastery"], -item["updated_at"]))

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

    return {
        "topics": topics,
        "recommendations": recommendations,
        "stats": {
            "topics": len(topics),
            "attempts": total_attempts,
            "average_mastery": round(weighted_sum / len(topics), 3) if topics else 0.0,
        },
        "events": data["events"][:20],
    }
