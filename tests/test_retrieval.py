"""混合检索：分块、BM25、RRF、向量缓存与降级路径。

向量编码用假编码器替代（`embed_documents` / `embed_query` 打桩），
测试不下载模型、不联网。
"""
from __future__ import annotations

import math

import pytest

from server import rag
from server.services import retrieval


def _docs(*texts: str) -> list[dict]:
    material = {
        "id": "mat_test",
        "title": "测试资料",
        "chunks": [{"id": f"c{index + 1}", "text": text} for index, text in enumerate(texts)],
    }
    return retrieval.collect_from_materials([material])


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EDU_RETRIEVAL_DENSE_WEIGHT", raising=False)


def test_chunk_text_keeps_chunks_inside_dense_window():
    text = "光合作用把光能转成化学能。" * 200
    chunks = rag.chunk_text(text)
    assert len(chunks) > 3
    assert max(len(chunk) for chunk in chunks) <= 560


def test_rrf_puts_mutual_agreement_first():
    # 片段 2 在两路都排第 1；片段 0/1 各只在一路靠前
    fused = retrieval.rrf([[(0, 9.0), (2, 5.0)], [(1, 8.0), (2, 4.0)]], [1.0, 1.0], top_k=3)
    assert fused[0][0] == 2


def test_bm25_rank_prefers_matching_chunk():
    docs = _docs("光合作用发生在叶绿体，把光能转成化学能。", "细胞呼吸在线粒体中进行，释放能量。")
    ranked = retrieval.bm25_rank(docs, "线粒体 呼吸")
    assert ranked and ranked[0][0] == 1


def test_dense_rank_uses_offsets(monkeypatch):
    import numpy as np

    docs = _docs("第一段讲光合作用。", "第二段讲细胞呼吸。", "第三段讲蒸腾作用。")
    monkeypatch.setattr(retrieval, "embed_query", lambda text: np.array([0.0, 1.0], dtype="float32"))
    monkeypatch.setattr(
        retrieval, "material_vectors",
        lambda material: np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]], dtype="float32"),
    )
    ranked = retrieval.dense_rank(docs, "细胞呼吸")
    assert ranked[0][0] == 1


def test_search_docs_falls_back_to_bm25_when_dense_missing(monkeypatch):
    docs = _docs("光合作用发生在叶绿体。", "细胞呼吸发生在线粒体。")

    def boom(*_args, **_kwargs):
        raise RuntimeError("向量模型加载失败")

    monkeypatch.setattr(retrieval, "dense_rank", boom)
    results = retrieval.search_docs("线粒体", docs, top_k=2, mode_="hybrid")
    assert results and results[0]["chunk_id"] == "c2"


def test_search_docs_dense_only_mode(monkeypatch):
    import numpy as np

    docs = _docs("光合作用发生在叶绿体。", "细胞呼吸发生在线粒体。")
    monkeypatch.setattr(retrieval, "embed_query", lambda text: np.array([1.0, 0.0], dtype="float32"))
    monkeypatch.setattr(
        retrieval, "material_vectors",
        lambda material: np.array([[0.0, 1.0], [1.0, 0.0]], dtype="float32"),
    )
    results = retrieval.search_docs("任意问题", docs, top_k=1, mode_="dense")
    assert results[0]["chunk_id"] == "c2"


def test_vector_index_is_cached_and_rebuilt_on_change(monkeypatch, tmp_path):
    import numpy as np

    monkeypatch.setenv("EDU_INDEX_DIR", str(tmp_path))
    calls: list[int] = []

    def fake_embed(texts):
        calls.append(len(texts))
        return np.ones((len(texts), 4), dtype="float32")

    monkeypatch.setattr(retrieval, "embed_documents", fake_embed)
    material = {"id": "mat_a", "title": "A", "chunks": [{"id": "c1", "text": "甲"}, {"id": "c2", "text": "乙"}]}

    first = retrieval.material_vectors(material)
    second = retrieval.material_vectors(material)
    assert first.shape == (2, 4) and second.shape == (2, 4)
    assert calls == [2]  # 第二次命中缓存，没有再编码
    assert len(list(tmp_path.glob("*.npy"))) == 1

    material["chunks"][1]["text"] = "丙"  # 内容变了 → 摘要变 → 重建并清理旧索引
    retrieval.material_vectors(material)
    assert calls == [2, 2]
    assert len(list(tmp_path.glob("*.npy"))) == 1


def test_rerank_is_skipped_in_demo(monkeypatch):
    docs = _docs("光合作用。", "细胞呼吸。")
    called: list[int] = []

    def fake_complete(messages, max_tokens=160):
        called.append(1)
        return '{"order": [2, 1]}'

    monkeypatch.setattr(retrieval, "_complete_sync", fake_complete)
    assert retrieval.rerank("问题", docs, top_k=2) == docs[:2]
    assert called == []


def test_parse_order_drops_duplicates_and_out_of_range():
    assert retrieval._parse_order('{"order": [2, 2, 5, 1]}', 3) == [2, 1]
    assert retrieval._parse_order("不是 JSON", 3) == []


def test_search_end_to_end_on_store(monkeypatch):
    from server import store

    material = {
        "id": "mat_e2e",
        "title": "叶绿体讲义",
        "chunks": [
            {"id": "c1", "text": "光合作用在叶绿体的类囊体上进行，光反应产生 ATP 和 NADPH。"},
            {"id": "c2", "text": "暗反应在叶绿体基质中固定二氧化碳，生成葡萄糖。"},
        ],
        "created_at": 1.0,
    }
    store.save_item("materials", material)
    try:
        results = rag.search("暗反应在哪里固定二氧化碳", ["mat_e2e"], top_k=1)
        assert results and results[0]["chunk_id"] == "c2"
        assert results[0]["chunk_index"] == 2
        assert results[0]["title"] == "叶绿体讲义"
        assert math.isfinite(results[0]["score"])
    finally:
        store.delete_item("materials", "mat_e2e")
