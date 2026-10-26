"""轻量检索：文本分块 + BM25，不依赖向量库和外部模型。"""
from __future__ import annotations

import math
import re
from collections import Counter

from . import store

_WORD = re.compile(r"[a-zA-Z0-9_]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_SENTENCE = re.compile(r"[^。！？!?\n]+[。！？!?\n]?")


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = _WORD.findall(text)
    for run in _CJK_RUN.findall(text):
        tokens.extend(run)
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE.findall(text)]
    return [p for p in parts if p]


def chunk_text(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()] or [text]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for sentence in split_sentences(paragraph) or [paragraph]:
            while len(sentence) > size * 2:  # 超长句强制切开
                if current.strip():
                    chunks.append(current.strip())
                    current = ""
                chunks.append(sentence[: size * 2])
                sentence = sentence[size * 2:]
            if not current.strip():
                current = sentence
            elif len(current) + len(sentence) <= size:
                current += sentence
            else:
                chunks.append(current.strip())
                current = (current[-overlap:] if overlap else "") + sentence
        if current.strip():
            current = current.rstrip() + "\n"
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk.strip()]


class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.n = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.n) if self.n else 0.0
        self.df: Counter[str] = Counter()
        for doc in docs:
            self.df.update(set(doc))

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, query: list[str], doc: list[str]) -> float:
        if not doc or not query:
            return 0.0
        tf = Counter(doc)
        dl = len(doc)
        total = 0.0
        for term in query:
            freq = tf.get(term, 0)
            if not freq:
                continue
            denom = freq + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            total += self.idf(term) * freq * (self.k1 + 1) / denom
        return total


def _materials(material_ids: list[str] | None) -> list[dict]:
    items = store.list_items("materials")
    if material_ids:
        wanted = set(material_ids)
        items = [it for it in items if it.get("id") in wanted]
    return items


def search(query: str, material_ids: list[str] | None = None, top_k: int = 4) -> list[dict]:
    """返回与 query 最相关的资料片段（含来源信息）。"""
    if not query.strip():
        return []
    materials = _materials(material_ids)
    docs: list[tuple[dict, dict, list[str]]] = []
    for material in materials:
        for chunk in material.get("chunks", []) or []:
            text = chunk.get("text", "")
            docs.append((material, chunk, tokenize(text)))
    if not docs:
        return []

    query_tokens = tokenize(query)[:64]
    if not query_tokens:
        return []

    index = _BM25([d[2] for d in docs])
    scored = [(index.score(query_tokens, d[2]), d) for d in docs]
    scored = [pair for pair in scored if pair[0] > 0]
    if not scored:
        return []
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best = scored[0][0]
    results = []
    for score, (material, chunk, _tokens) in scored:
        if score < best * 0.15:
            break
        results.append({
            "material_id": material.get("id"),
            "title": material.get("title") or "未命名资料",
            "chunk_id": chunk.get("id"),
            "text": chunk.get("text", ""),
            "score": round(score, 3),
        })
        if len(results) >= top_k:
            break
    return results


def preview(text: str, limit: int = 180) -> str:
    cleaned = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", text, flags=re.M)
    cleaned = cleaned.replace("**", "").replace("`", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")
