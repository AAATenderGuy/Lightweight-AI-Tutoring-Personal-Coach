"""混合检索：BM25 + 向量（fastembed / bge-small-zh）+ RRF 融合 + 可选 LLM 重排。

设计要点：
- `rack.search()` 的签名不变，内部委派到这里，用 `EDU_RETRIEVAL_MODE` 选路；
- 向量层是**可选**的：没装 fastembed、模型下载失败、离线环境，一律自动退回 BM25，
  检索永远不出错，只是效果退回到 v1.5 的水平；
- 索引落 `data/index/<material_id>-<digest>.npy + .jsonl`，摘要变了（资料重传）自动重建，
  同资料旧索引在重建后清理；
- RRF 只用排名不做分数归一化：BM25 与余弦量纲不同，加权归一化需要调参，RRF 只需 k。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import rag
from ..config import DATA_DIR

log = logging.getLogger("edu.retrieval")

MODES = ("bm25", "dense", "hybrid", "hybrid_rerank")
DEFAULT_MODE = "hybrid"
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"

RRF_K = 60           # RRF 平滑常数，业界默认 60
CANDIDATES = 20      # 每路召回条数
FUSED = 10           # 融合后进入重排的条数
RETRY_AFTER = 60.0   # 模型加载失败后的冷却秒数，期间直接复用错误信息

_encoder_lock = threading.Lock()
_encoder = None
_encoder_error = ""
_encoder_tried_at = 0.0


# ---------------------------------------------------------------- 配置读取
def mode() -> str:
    """当前检索模式；环境变量非法时退回默认值。"""
    raw = (os.environ.get("EDU_RETRIEVAL_MODE") or DEFAULT_MODE).strip().lower()
    return raw if raw in MODES else DEFAULT_MODE


def dense_weight() -> float:
    try:
        value = float(os.environ.get("EDU_RETRIEVAL_DENSE_WEIGHT", "1.0"))
    except ValueError:
        return 1.0
    return max(0.0, min(5.0, value))


def model_name() -> str:
    return (os.environ.get("EDU_EMBED_MODEL") or DEFAULT_MODEL).strip()


def _index_dir() -> Path:
    """向量索引目录；评测脚本会用 EDU_INDEX_DIR 指到临时目录，避免污染真实索引。"""
    return Path(os.environ.get("EDU_INDEX_DIR") or DATA_DIR / "index")


def _model_cache() -> Path:
    return Path(os.environ.get("EDU_MODEL_CACHE") or DATA_DIR / "models")


# ---------------------------------------------------------------- 向量编码
def _encoder_instance():
    """懒加载向量模型；失败后冷却 RETRY_AFTER 秒，期间复用错误信息，之后允许重试。"""
    global _encoder, _encoder_error, _encoder_tried_at
    if _encoder is not None:
        return _encoder
    with _encoder_lock:
        if _encoder is not None:
            return _encoder
        if _encoder_error and time.time() - _encoder_tried_at < RETRY_AFTER:
            raise RuntimeError(_encoder_error)
        _encoder_tried_at = time.time()
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            _encoder_error = "未安装 fastembed，向量检索不可用"
            raise RuntimeError(_encoder_error) from exc
        try:
            cache = _model_cache()
            cache.mkdir(parents=True, exist_ok=True)
            model = TextEmbedding(model_name=model_name(), cache_dir=str(cache))
        except Exception as exc:  # noqa: BLE001 - 网络/磁盘/模型名异常类型不统一
            _encoder_error = f"向量模型加载失败：{exc}"
            raise RuntimeError(_encoder_error) from exc
        _encoder = model
        _encoder_error = ""  # 重试成功后清掉旧错误
        log.info("dense encoder ready model=%s", model_name())
    return _encoder


def warmup() -> None:
    """启动时后台预载向量模型：不阻塞进程，失败只留在 stats 里，检索照常退回 BM25。"""
    if mode() == "bm25":
        return

    def _load() -> None:
        try:
            _encoder_instance()
        except RuntimeError as exc:
            log.warning("向量模型预热失败（检索退回 BM25）：%s", exc)

    threading.Thread(target=_load, name="retrieval-warmup", daemon=True).start()


def available() -> bool:
    """向量层是否可用（会触发一次模型加载，首次约 1–3 秒）。"""
    try:
        _encoder_instance()
        return True
    except RuntimeError:
        return False


def _normalise(vector) -> object:
    import numpy as np

    arr = np.asarray(vector, dtype="float32")
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm else arr


def embed_documents(texts: list[str]):
    """把文本编码成单位向量矩阵（行数 = 文本数）。"""
    import numpy as np

    model = _encoder_instance()
    vectors = [_normalise(vector) for vector in model.embed(list(texts))]
    if not vectors:
        return np.zeros((0, 0), dtype="float32")
    return np.vstack(vectors)


def embed_query(text: str):
    model = _encoder_instance()
    embed = getattr(model, "query_embed", None) or model.embed
    return _normalise(next(iter(embed([text]))))


# ---------------------------------------------------------------- 索引缓存
def _safe_id(value: str) -> str:
    keep = [char if (char.isalnum() or char in "-_") else "_" for char in str(value)]
    return "".join(keep)[:60] or "index"


def _digest(texts: list[str]) -> str:
    hasher = hashlib.sha256()
    hasher.update(model_name().encode("utf-8"))
    for text in texts:
        hasher.update(text.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _paths(material_id: str, digest: str) -> tuple[Path, Path]:
    stem = f"{_safe_id(material_id)}-{digest[:12]}"
    return _index_dir() / f"{stem}.npy", _index_dir() / f"{stem}.jsonl"


def _prune(material_id: str, keep: Path) -> None:
    prefix = _safe_id(material_id) + "-"
    try:
        for path in _index_dir().iterdir():
            if path.name.startswith(prefix) and path != keep and path.suffix == ".npy":
                path.unlink(missing_ok=True)
                path.with_suffix(".jsonl").unlink(missing_ok=True)
    except OSError:
        pass


def material_vectors(material: dict):
    """取（或建）一份资料的向量矩阵，按 chunk 顺序一一对应。"""
    import numpy as np

    chunks = material.get("chunks") or []
    texts = [str(chunk.get("text") or "") for chunk in chunks]
    if not texts:
        return None
    digest = _digest(texts)
    npy, meta = _paths(str(material.get("id")), digest)
    if npy.is_file() and meta.is_file():
        try:
            stored = json.loads(meta.read_text(encoding="utf-8"))
            if stored.get("digest") == digest and stored.get("count") == len(texts):
                return np.load(npy)
        except (OSError, ValueError):
            pass  # 缓存坏了就当没有，重建

    matrix = embed_documents(texts)
    try:
        _index_dir().mkdir(parents=True, exist_ok=True)
        tmp = npy.with_name(npy.name + ".tmp")
        with tmp.open("wb") as handle:
            np.save(handle, matrix)
        tmp.replace(npy)
        meta.write_text(
            json.dumps({
                "material_id": material.get("id"),
                "model": model_name(),
                "dim": int(matrix.shape[1]) if matrix.ndim == 2 else 0,
                "count": len(texts),
                "digest": digest,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        _prune(str(material.get("id")), npy)
    except OSError as exc:
        log.warning("写入向量索引失败 material=%s err=%s", material.get("id"), exc)
    return matrix


# ---------------------------------------------------------------- 召回
def collect(material_ids: list[str] | None = None) -> list[dict]:
    """把存储里的资料摊平成片段列表。"""
    return collect_from_materials(rag._materials(material_ids))


def collect_from_materials(materials: list[dict]) -> list[dict]:
    """把资料摊平成片段列表，向量按 chunk 在资料内的下标对齐（评测脚本也走这条）。"""
    docs: list[dict] = []
    for material in materials:
        for offset, chunk in enumerate(material.get("chunks") or []):
            text = str(chunk.get("text") or "")
            docs.append({
                "material": material,
                "chunk": chunk,
                "offset": offset,
                "tokens": rag.tokenize(text),
            })
    return docs


def bm25_rank(docs: list[dict], query: str, top_k: int = CANDIDATES) -> list[tuple[int, float]]:
    """返回 (片段下标, 分数)，按分数降序。"""
    query_tokens = rag.tokenize(query)[:64]
    if not query_tokens:
        return []
    index = rag._BM25([doc["tokens"] for doc in docs])
    scored = [
        (position, index.score(query_tokens, doc["tokens"]))
        for position, doc in enumerate(docs)
    ]
    scored = [pair for pair in scored if pair[1] > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]


def dense_rank(docs: list[dict], query: str, top_k: int = CANDIDATES) -> list[tuple[int, float]]:
    query_vector = embed_query(query)
    cache: dict[str, object] = {}
    scored: list[tuple[int, float]] = []
    for position, doc in enumerate(docs):
        material = doc["material"]
        key = str(material.get("id"))
        if key not in cache:
            cache[key] = material_vectors(material)
        matrix = cache[key]
        if matrix is None or doc["offset"] >= len(matrix):
            continue
        scored.append((position, float(matrix[doc["offset"]] @ query_vector)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]


def rrf(rankings: list[list[tuple[int, float]]], weights: list[float],
        k: int = RRF_K, top_k: int = FUSED) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion：只吃排名，权重乘在每一路的贡献上。"""
    scores: dict[int, float] = {}
    for ranking, weight in zip(rankings, weights, strict=False):
        if weight <= 0:
            continue
        for rank, (position, _score) in enumerate(ranking, 1):
            scores[position] = scores.get(position, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)[:top_k]


# ---------------------------------------------------------------- LLM 重排
def _complete_sync(messages: list[dict], max_tokens: int = 160) -> str:
    """在同步检索链路里调异步 LLM：有事件循环时丢到线程里跑，避免嵌套 asyncio.run。"""
    from ..llm import llm

    async def run() -> str:
        return await llm.complete(
            messages, temperature=0.0, max_tokens=max_tokens, task="rerank", context={},
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(run())).result()


def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """listwise 重排：一次调用给候选排序；失败就保持融合序，不让检索挂掉。"""
    from ..llm import LLMError, llm

    if not candidates or llm.demo:
        return candidates[:top_k]
    lines = [
        f"[{index}] {doc['material'].get('title') or '未命名资料'}：{rag.preview(doc['chunk'].get('text', ''), 260)}"
        for index, doc in enumerate(candidates, 1)
    ]
    messages = [
        {"role": "system", "content": "你是检索结果重排器。只输出 JSON，不要解释。"},
        {"role": "user", "content": (
            f"问题：{query}\n\n候选片段：\n" + "\n".join(lines) +
            f"\n\n请按与问题的相关程度从高到低排序，最多保留 {top_k} 条；"
            "完全不相干的不要返回。输出格式：{\"order\": [片段编号, ...]}"
        )},
    ]
    try:
        text = _complete_sync(messages)
    except (LLMError, OSError, RuntimeError) as exc:
        log.warning("rerank 失败，保持融合序：%s", exc)
        return candidates[:top_k]
    order = _parse_order(text, len(candidates))
    if not order:
        return candidates[:top_k]
    picked = [candidates[number - 1] for number in order[:top_k]]
    return picked or candidates[:top_k]


def _parse_order(text: str, size: int) -> list[int]:
    raw = (text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(raw[start:end + 1])
    except ValueError:
        return []
    order = payload.get("order") if isinstance(payload, dict) else None
    result: list[int] = []
    for item in order or []:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= size and number not in result:
            result.append(number)
    return result


# ---------------------------------------------------------------- 对外入口
def _public(doc: dict, score: float) -> dict:
    material = doc["material"]
    chunk = doc["chunk"]
    return {
        "material_id": material.get("id"),
        "title": material.get("title") or "未命名资料",
        "chunk_id": chunk.get("id"),
        "chunk_index": doc["offset"] + 1,
        "text": chunk.get("text", ""),
        "score": round(float(score), 6),
    }


def search_docs(query: str, docs: list[dict], top_k: int = 4, mode_: str | None = None) -> list[dict]:
    """在给定片段列表上检索（评测脚本直接复用同一条链路）。"""
    query = (query or "").strip()
    if not query or not docs:
        return []
    chosen = mode_ if mode_ in MODES else mode()

    ranked = bm25_rank(docs, query)
    if chosen in ("dense", "hybrid", "hybrid_rerank"):
        try:
            dense = dense_rank(docs, query)
        except RuntimeError as exc:  # 模型缺失/加载失败：退回 BM25，不让业务报错
            log.warning("向量检索不可用，回退 bm25：%s", exc)
            dense = None
            if chosen == "dense":
                chosen = "bm25"
        if chosen == "dense":
            ranked = dense or []
        elif dense is not None:
            ranked = rrf([ranked, dense], [1.0, dense_weight()])

    picked = [dict(docs[position], score=score) for position, score in ranked]
    if chosen == "hybrid_rerank" and len(picked) > 1:
        picked = rerank(query, picked, top_k)
    return [_public(doc, doc.get("score", 0.0)) for doc in picked[:top_k]]


def search(query: str, material_ids: list[str] | None = None, top_k: int = 4) -> list[dict]:
    """业务入口：从存储里的资料检索。"""
    return search_docs(query, collect(material_ids), top_k)


def stats() -> dict:
    """给评测与健康检查用的索引概况。"""
    total_bytes = 0
    files = 0
    index_dir = _index_dir()
    if index_dir.is_dir():
        for path in index_dir.glob("*.npy"):
            files += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
    return {
        "mode": mode(),
        "dense_weight": dense_weight(),
        "model": model_name(),
        "index_files": files,
        "index_mb": round(total_bytes / 1024 / 1024, 2),
        "dense_ready": _encoder is not None,
        "dense_error": _encoder_error,
    }
