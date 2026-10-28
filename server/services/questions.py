"""题库（P1-8）：教师可复用的题目资产。

三种入库途径：手工录入（直接可用）、AI 批量生成（先进草稿箱）、拍题收录。
布置作业时可以从题库选题组卷；「前后测平行卷」也在这里按知识点+难度抽取。

设计上的一条铁律：题目属于教师个人，不跨教师共享；作业引用的题目在组卷时
**整体拷贝**进 quiz，之后改题库不影响已发布的作业（避免学生做到一半题变了）。
"""
from __future__ import annotations

import time
from typing import Any

from .. import store
from ..llm import LLMError

STATUSES = ("draft", "approved")
SOURCES = ("manual", "ai")
QUESTION_TYPES = ("single", "short")
DIFFICULTIES = ("easy", "medium", "hard")

MAX_QUESTIONS_PER_TEACHER = 2000


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _normalise(payload: dict, *, topic_fallback: str = "") -> dict:
    """把外部输入裁剪成合法题目；不合法直接 ValueError。"""
    question = _text(payload.get("question"), 400)
    if not question:
        raise ValueError("题干不能为空。")
    qtype = payload.get("type")
    options = [str(o).strip()[:160] for o in (payload.get("options") or []) if str(o).strip()][:6]
    if qtype is None:
        qtype = "single" if options else "short"
    if qtype not in QUESTION_TYPES:
        raise ValueError("题型只支持 single / short。")

    entry: dict[str, Any] = {
        "type": qtype,
        "question": question,
        "topic": _text(payload.get("topic"), 60) or topic_fallback,
        "knowledge_point": _text(payload.get("knowledge_point"), 60)
        or f"{_text(payload.get('topic'), 60) or topic_fallback}·核心概念",
        "explanation": _text(payload.get("explanation"), 400),
        "difficulty": payload.get("difficulty") if payload.get("difficulty") in DIFFICULTIES else "medium",
    }
    if qtype == "single":
        if len(options) < 2:
            raise ValueError("选择题至少需要 2 个选项。")
        try:
            answer_index = int(payload.get("answer_index", 0))
        except (TypeError, ValueError):
            answer_index = 0
        if not 0 <= answer_index < len(options):
            raise ValueError("answer_index 超出选项范围。")
        entry.update({"options": options, "answer_index": answer_index})
    else:
        entry.update({"options": [], "answer": _text(payload.get("answer"), 600)})
    return entry


def _public(question: dict) -> dict:
    return {
        "id": question.get("id"),
        "type": question.get("type"),
        "question": question.get("question"),
        "options": question.get("options") or [],
        "answer_index": question.get("answer_index"),
        "answer": question.get("answer", ""),
        "explanation": question.get("explanation", ""),
        "topic": question.get("topic", ""),
        "knowledge_point": question.get("knowledge_point", ""),
        "difficulty": question.get("difficulty", "medium"),
        "source": question.get("source", "manual"),
        "status": question.get("status", "approved"),
        "created_at": question.get("created_at"),
        "updated_at": question.get("updated_at"),
    }


def _mine(teacher_id: str) -> list[dict]:
    return [q for q in store.list_items("questions") if q.get("teacher_id") == teacher_id]


def list_questions(teacher_id: str, *, topic: str = "", status: str = "",
                   keyword: str = "") -> dict:
    items = _mine(teacher_id)
    if status in STATUSES:
        items = [q for q in items if q.get("status") == status]
    if topic.strip():
        items = [q for q in items if q.get("topic") == topic.strip()]
    if keyword.strip():
        needle = keyword.strip().lower()
        items = [q for q in items
                 if needle in str(q.get("question", "")).lower()
                 or needle in str(q.get("knowledge_point", "")).lower()]
    topics = sorted({q.get("topic") for q in _mine(teacher_id) if q.get("topic")})
    return {
        "items": [_public(q) for q in items],
        "topics": topics,
        "total": len(_mine(teacher_id)),
        "drafts": sum(1 for q in _mine(teacher_id) if q.get("status") == "draft"),
    }


def _load_own(teacher_id: str, question_id: str) -> dict:
    question = store.load_item("questions", question_id)
    if not question or question.get("teacher_id") != teacher_id:
        raise ValueError("题目不存在。")
    return question


def create_question(teacher_id: str, payload: dict, *, source: str = "manual",
                    status: str | None = None) -> dict:
    if len(_mine(teacher_id)) >= MAX_QUESTIONS_PER_TEACHER:
        raise ValueError(f"题库最多 {MAX_QUESTIONS_PER_TEACHER} 题，请先清理。")
    if source not in SOURCES:
        source = "manual"
    # 手工录入默认直接可用；AI 生成默认进草稿箱等审核
    status = status if status in STATUSES else ("approved" if source == "manual" else "draft")
    now = time.time()
    question = store.save_item("questions", {
        "id": store.new_id("qn_"),
        "teacher_id": teacher_id,
        **_normalise(payload),
        "source": source,
        "status": status,
        "created_at": now,
        "updated_at": now,
    })
    return _public(question)


def update_question(teacher_id: str, question_id: str, payload: dict) -> dict:
    question = _load_own(teacher_id, question_id)
    merged = {**question, **{k: v for k, v in payload.items()
                             if k in {"question", "options", "answer_index", "answer",
                                      "explanation", "topic", "knowledge_point",
                                      "difficulty", "type"}}}
    normalised = _normalise(merged, topic_fallback=question.get("topic", ""))
    question.update(normalised)
    # 改过内容的 AI 草稿保持草稿状态，等教师点「审核通过」
    if "status" in payload and payload["status"] in STATUSES:
        question["status"] = payload["status"]
    question["updated_at"] = time.time()
    store.save_item("questions", question)
    return _public(question)


def delete_question(teacher_id: str, question_id: str) -> None:
    _load_own(teacher_id, question_id)
    store.delete_item("questions", question_id)


def approve(teacher_id: str, question_ids: list[str]) -> dict:
    done = 0
    for question_id in question_ids[:200]:
        question = store.load_item("questions", question_id)
        if question and question.get("teacher_id") == teacher_id:
            question["status"] = "approved"
            question["updated_at"] = time.time()
            store.save_item("questions", question)
            done += 1
    return {"approved": done}


async def generate_drafts(teacher_id: str, *, topic: str, count: int,
                          difficulty: str = "medium",
                          material_ids: list[str] | None = None) -> dict:
    """AI 批量出题 → 全部进草稿箱。复用出题链路，但不存 quiz，只拆题入库。"""
    from . import quiz as quiz_service

    topic = _text(topic, 120)
    if not topic:
        raise ValueError("请填写出题主题。")
    count = max(1, min(10, int(count or 4)))
    quiz = await quiz_service.generate(topic=topic, material_ids=material_ids or [],
                                       count=count, difficulty=difficulty)
    stored = store.load_item("quizzes", quiz["id"]) or {}
    store.delete_item("quizzes", quiz["id"])  # 题库场景不保留 quiz 壳
    created = []
    for raw in stored.get("questions") or []:
        created.append(create_question(teacher_id, raw, source="ai", status="draft"))
    if not created:
        raise LLMError("没有生成有效题目，请重试。")
    return {"items": created, "topic": topic}


def assemble_quiz(teacher_id: str, question_ids: list[str], *, title: str,
                  topic: str) -> dict:
    """选题组卷：题目整体拷贝进 quiz，之后改题库不影响已发布的作业。"""
    picked: list[dict] = []
    seen: set[str] = set()
    for question_id in question_ids:
        if question_id in seen:
            continue
        seen.add(question_id)
        question = store.load_item("questions", question_id)
        if not question or question.get("teacher_id") != teacher_id:
            raise ValueError("选题里有不属于你的题目。")
        if question.get("status") != "approved":
            raise ValueError(f"《{_text(question.get('question'), 20)}…」还在草稿箱，先审核再组卷。")
        picked.append(question)
    if not picked:
        raise ValueError("请至少选择一道题。")
    if len(picked) > 30:
        raise ValueError("一份作业最多 30 题。")
    questions = []
    for index, question in enumerate(picked, 1):
        entry = {
            "id": f"q{index}",
            "bank_id": question["id"],
            "type": question["type"],
            "question": question["question"],
            "explanation": question.get("explanation", ""),
            "knowledge_point": question.get("knowledge_point", ""),
        }
        if question["type"] == "single":
            entry.update({"options": question.get("options") or [],
                          "answer_index": int(question.get("answer_index", 0))})
        else:
            entry.update({"answer": question.get("answer", "")})
        questions.append(entry)
    quiz = store.save_item("quizzes", {
        "id": store.new_id("qz_"),
        "title": _text(title, 80) or f"{topic} · 作业",
        "topic": topic,
        "difficulty": "medium",
        "questions": questions,
        "created_at": time.time(),
        "source": "bank",
    })
    return quiz
