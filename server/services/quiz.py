"""出题与判分。"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .. import prompts, rag, store
from ..llm import LLMError, llm
from . import grading as grading_service


def _text(value: Any, limit: int = 400) -> str:
    return str(value or "").strip()[:limit]


def _normalise_questions(raw_questions: Any, topic: str) -> list[dict]:
    if not isinstance(raw_questions, list):
        raise LLMError("模型没有返回题目，请重试。")
    questions: list[dict] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        question = _text(item.get("question"), 400)
        if not question:
            continue
        options = [str(option).strip()[:160] for option in (item.get("options") or []) if str(option).strip()]
        entry: dict[str, Any] = {
            "id": f"q{len(questions) + 1}",
            "question": question,
            "explanation": _text(item.get("explanation"), 400),
            "knowledge_point": _text(item.get("knowledge_point"), 60) or f"{topic}·核心概念",
        }
        if options:
            try:
                answer_index = int(item.get("answer_index", 0))
            except (TypeError, ValueError):
                answer_index = 0
            entry.update({
                "type": "single",
                "options": options[:6],
                "answer_index": max(0, min(len(options[:6]) - 1, answer_index)),
            })
        else:
            entry.update({
                "type": "short",
                "answer": _text(item.get("answer"), 600),
            })
        questions.append(entry)
    if not questions:
        raise LLMError("没有生成有效题目，请重试。")
    return questions


def public_quiz(quiz: dict, *, reveal: bool = False) -> dict:
    """给前端的版本：默认隐藏正确答案；练习模式（reveal）返回答案与详解。"""
    questions = []
    for item in quiz.get("questions", []):
        entry = {
            "id": item.get("id"),
            "type": item.get("type"),
            "question": item.get("question"),
            "options": item.get("options") or [],
            "knowledge_point": item.get("knowledge_point"),
        }
        if reveal:
            entry["explanation"] = item.get("explanation", "")
            if item.get("type") == "single":
                entry["answer_index"] = int(item.get("answer_index", 0))
            else:
                entry["answer"] = item.get("answer", "")
        questions.append(entry)
    return {
        "id": quiz.get("id"),
        "title": quiz.get("title"),
        "topic": quiz.get("topic"),
        "difficulty": quiz.get("difficulty"),
        "created_at": quiz.get("created_at"),
        "questions": questions,
        "source": quiz.get("source", "generated"),
        "parent_id": quiz.get("parent_id"),
        "practice": bool(quiz.get("practice")) or reveal,
    }


async def generate(*, topic: str, material_ids: list[str], count: int, difficulty: str) -> dict:
    sources = rag.search(topic, material_ids or None, top_k=6)
    messages = [
        {"role": "system", "content": prompts.QUIZ_SYSTEM},
        {"role": "user", "content": prompts.quiz_prompt(
            topic=topic, sources=sources, count=count, difficulty=difficulty
        )},
    ]
    raw = await llm.json(
        messages,
        temperature=0.5,
        max_tokens=2400,
        task="quiz",
        context={"topic": topic, "count": count, "sources": sources},
    )
    quiz = {
        "id": store.new_id("qz_"),
        "title": _text(raw.get("title"), 80) or f"{topic} · 随堂测验",
        "topic": topic,
        "difficulty": difficulty,
        "questions": _normalise_questions(raw.get("questions"), topic),
        "created_at": time.time(),
        "source": "generated",
    }
    store.save_item("quizzes", quiz)
    return public_quiz(quiz)


def quiz_from_lesson(lesson: dict) -> dict:
    questions = prompts.lesson_quiz_questions(lesson)
    if not questions:
        raise LLMError("这堂课没有可提交的检测题。")
    for index, question in enumerate(questions, 1):
        question["id"] = f"q{index}"
    quiz = {
        "id": store.new_id("qz_"),
        "title": f"{lesson.get('title', '课堂')} · 随堂检测",
        "topic": lesson.get("topic") or lesson.get("title") or "课堂",
        "difficulty": lesson.get("level") or "beginner",
        "questions": questions,
        "created_at": time.time(),
        "source": "lesson",
        "lesson_id": lesson.get("id"),
    }
    store.save_item("quizzes", quiz)
    return public_quiz(quiz)


def _variant(quiz: dict) -> int:
    return sum(ord(char) for char in str(quiz.get("id") or "")) % 7


async def similar(quiz: dict, *, count: int, focus_points: list[str]) -> dict:
    """基于原卷生成同知识点的变式练习，直接返回答案与详解。"""
    topic = quiz.get("topic") or quiz.get("title") or "本课内容"
    sources = rag.search(topic, None, top_k=4)
    messages = [
        {"role": "system", "content": prompts.QUIZ_SYSTEM},
        {"role": "user", "content": prompts.similar_quiz_prompt(
            quiz=quiz, count=count, focus_points=focus_points, sources=sources
        )},
    ]
    raw = await llm.json(
        messages,
        temperature=0.65,
        max_tokens=2600,
        task="quiz",
        context={
            "topic": topic,
            "count": count,
            "sources": sources,
            "focus_points": focus_points,
            "similar": True,
            "variant": _variant(quiz),
        },
    )
    new_quiz = {
        "id": store.new_id("qz_"),
        "title": _text(raw.get("title"), 80) or f"{quiz.get('title') or topic} · 举一反三",
        "topic": topic,
        "difficulty": quiz.get("difficulty") or "medium",
        "questions": _normalise_questions(raw.get("questions"), topic),
        "created_at": time.time(),
        "source": "similar",
        "parent_id": quiz.get("id"),
        "practice": True,
    }
    store.save_item("quizzes", new_quiz)
    return public_quiz(new_quiz, reveal=True)


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


async def _grade_short(question: dict, answer: str, semaphore: asyncio.Semaphore) -> dict:
    if not answer.strip():
        return {"score": 0.0, "correct": False, "feedback": "这题还没有作答。", "missing": ["作答内容"]}
    async with semaphore:
        messages = [
            {"role": "system", "content": prompts.GRADE_SYSTEM},
            {"role": "user", "content": prompts.grade_prompt(
                question=question.get("question", ""),
                reference=question.get("answer", ""),
                answer=answer,
                knowledge_point=question.get("knowledge_point", ""),
            )},
        ]
        try:
            raw = await llm.json(
                messages,
                temperature=0.1,
                max_tokens=500,
                task="grade",
                context={
                    "question": question.get("question", ""),
                    "reference": question.get("answer", ""),
                    "answer": answer,
                },
            )
        except LLMError as exc:
            return {"score": 0.0, "correct": False, "feedback": f"评分失败：{exc}", "missing": []}
    score = grading_service.normalize_score(raw.get("score"))
    score, needs_review = grading_service.review_decision(
        score, answer, has_reference=bool(question.get("answer")),
    )
    feedback = _text(raw.get("feedback"), 300) or "已评分。"
    if needs_review:
        feedback += "（本题评分已标记为待复核）"
    return {
        "score": score,
        "correct": bool(raw.get("correct", score >= 0.6)) or score >= 0.6,
        "feedback": feedback,
        "missing": [str(item)[:60] for item in (raw.get("missing") or [])][:4],
        "needs_review": needs_review,
    }


async def grade(quiz: dict, answers: list[dict], *, track: bool = True) -> dict:
    """判分。

    track=False 用于班级作业：成绩只写进提交记录，不混入本机的个人学习进度。
    """
    from . import mastery as mastery_service

    answer_map: dict[str, str] = {}
    for item in answers:
        if isinstance(item, dict):
            answer_map[str(item.get("question_id"))] = str(item.get("answer", ""))
    semaphore = asyncio.Semaphore(4)
    questions = quiz.get("questions", [])

    async def grade_one(question: dict) -> dict:
        submitted = answer_map.get(str(question.get("id")), "")
        if question.get("type") == "single":
            picked_text = submitted.strip()
            picked: int | None = None
            if picked_text.isdigit():
                picked = int(picked_text)
            elif len(picked_text) == 1 and picked_text.upper() in "ABCDEF":
                picked = "ABCDEF".index(picked_text.upper())
            correct_index = int(question.get("answer_index", 0))
            score = 1.0 if picked == correct_index else 0.0
            feedback = "回答正确。" if score else "这个选项不对。先回到题干找出限制条件，再对照解析。"
            result = {
                "score": score,
                "correct": score >= 1.0,
                "feedback": feedback,
                "missing": [],
            }
        else:
            result = await _grade_short(question, submitted, semaphore)
        return {
            "question_id": question.get("id"),
            "question": question.get("question"),
            "type": question.get("type"),
            "options": question.get("options") or [],
            "knowledge_point": question.get("knowledge_point"),
            "submitted": submitted,
            "correct_index": (
                int(question.get("answer_index", 0))
                if question.get("type") == "single"
                else None
            ),
            "correct_answer": (
                question.get("options", [])[int(question.get("answer_index", 0))]
                if question.get("type") == "single" and question.get("options")
                else question.get("answer", "")
            ),
            "explanation": question.get("explanation", ""),
            **result,
        }

    results = await asyncio.gather(*(grade_one(question) for question in questions))
    total = round(sum(item["score"] for item in results) / len(results), 3) if results else 0.0
    topic = quiz.get("topic") or "未分类主题"

    if track:
        for item in results:
            mastery_service.record_attempt(
                topic,
                item.get("knowledge_point") or topic,
                item["score"],
                source=quiz.get("id", ""),
                silent=True,
            )
        mastery_service.log_event(
            kind="quiz",
            topic=topic,
            summary=f"完成测验《{quiz.get('title', '')}》，得分 {int(total * 100)}",
            score=total,
        )

    payload = {
        "quiz_id": quiz.get("id"),
        "title": quiz.get("title"),
        "topic": topic,
        "score": total,
        "correct_count": sum(1 for item in results if item["correct"]),
        "total": len(results),
        "results": results,
    }
    if track:
        payload["mastery"] = mastery_service.progress_payload()["topics"]
    return payload
