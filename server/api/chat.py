from __future__ import annotations

import asyncio

from fastapi import APIRouter

from .. import rag
from ..llm import LLMError, llm
from ..schemas import ChatRequest
from ..services import chat as chat_service
from .limits import rate_limit
from .sse import encode, stream_response

router = APIRouter(tags=["chat"])


@router.post("/chat/stream", dependencies=[rate_limit("chat")])
async def chat_stream(payload: ChatRequest):
    async def events():
        try:
            sources = []
            if payload.use_materials:
                # 追问往往只有“为什么”，带上上一轮问题能提高检索命中率。
                query_parts = [payload.message]
                for item in reversed(payload.history[-4:]):
                    if item.role == "user" and item.content.strip():
                        query_parts.append(item.content.strip())
                        break
                sources = rag.search(" ".join(query_parts), payload.material_ids or None, top_k=4)
            public_sources = [
                {
                    "index": index,
                    "title": source.get("title", ""),
                    "material_id": source.get("material_id", ""),
                    "preview": rag.preview(source.get("text", ""), 180),
                }
                for index, source in enumerate(sources, 1)
            ]
            yield encode({"type": "meta", "sources": public_sources, "demo": llm.demo})

            messages = chat_service.build_messages(
                message=payload.message,
                mode=payload.mode,
                history=[item.model_dump() for item in payload.history],
                sources=sources,
            )
            async for piece in llm.stream(
                messages,
                temperature=0.7,
                max_tokens=1400,
                task="chat",
                context={"sources": sources},
            ):
                yield encode({"type": "delta", "text": piece})
            yield encode({"type": "done"})
        except LLMError as exc:
            yield encode({"type": "error", "message": str(exc)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            yield encode({"type": "error", "message": f"对话服务异常：{exc}"})

    return stream_response(events())
