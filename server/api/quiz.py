from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import store
from ..llm import LLMError
from ..schemas import QuizRequest, QuizSubmitRequest, SimilarQuizRequest
from ..services import quiz as quiz_service
from .limits import rate_limit

router = APIRouter(tags=["quiz"])


@router.post("/quiz/generate", dependencies=[rate_limit("quiz")])
async def generate_quiz(payload: QuizRequest) -> dict:
    try:
        return {"quiz": await quiz_service.generate(
            topic=payload.topic.strip(),
            material_ids=payload.material_ids,
            count=payload.count,
            difficulty=payload.difficulty,
        )}
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"出题失败：{exc}") from exc


@router.post("/quiz/{quiz_id}/submit")
async def submit_quiz(quiz_id: str, payload: QuizSubmitRequest) -> dict:
    quiz = store.load_item("quizzes", quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="测验不存在或已过期，请重新生成。")
    return await quiz_service.grade(quiz, [item.model_dump() for item in payload.answers])


@router.post("/quiz/{quiz_id}/similar", dependencies=[rate_limit("quiz")])
async def similar_quiz(quiz_id: str, payload: SimilarQuizRequest) -> dict:
    quiz = store.load_item("quizzes", quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="原测验不存在，无法生成相似题。")
    try:
        return {"quiz": await quiz_service.similar(
            quiz,
            count=payload.count,
            focus_points=[point.strip()[:60] for point in payload.focus_points if point.strip()],
        )}
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"生成相似题失败：{exc}") from exc
