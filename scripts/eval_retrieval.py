"""检索 ablation：A0 BM25 / A1 Dense / A2 RRF（权重扫）/ A3 +LLM rerank。

用法（在仓库根目录）：
    python scripts/eval_retrieval.py            # 跑全部配置，输出 docs/eval/results-YYYYMMDD.md
    python scripts/eval_retrieval.py --build    # 重建查询集与标注（默认仅在缺失时生成）
    python scripts/eval_retrieval.py --limit 20 # 冒烟跑，只取前 20 条查询

语料：README.md、docs/COMPETITION_REVIEW.md、docs/REVIEW.md，按标题分节后用
`rag.chunk_text`（450/100）切块。查询集两类：
- heading：取小节标题当查询，该小节所有块都算正例（一条查询多个正例）；
- sentence：从块里抽一句原句当查询，正例是所在块（措辞重合度高，对 BM25 有利）。

不联网也能跑：A0/A1/A2 只需本机 ONNX 模型；A3 需要配置 API Key，演示模式会跳过并注明。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 必须在导入 server 之前把数据目录指到临时位置：评测不碰真实 data/。
os.environ.setdefault("EDU_DATA_DIR", tempfile.mkdtemp(prefix="edu-eval-"))
os.environ.setdefault("EDU_INDEX_DIR", tempfile.mkdtemp(prefix="edu-eval-index-"))
# 模型缓存放仓库 data/models，避免每次评测都重新下载 95MB。
os.environ.setdefault("EDU_MODEL_CACHE", str(ROOT / "data" / "models"))
os.environ.setdefault("EDU_LOG_LEVEL", "WARNING")

from server import rag  # noqa: E402
from server.services import retrieval  # noqa: E402

CORPUS_FILES = ("README.md", "docs/COMPETITION_REVIEW.md", "docs/REVIEW.md")
EVAL_DIR = ROOT / "docs" / "eval"
QUERIES = EVAL_DIR / "queries.jsonl"
QRELS = EVAL_DIR / "qrels.jsonl"
HEADING = re.compile(r"^#{1,3}[ \t]+(.+?)\s*$", re.M)
TOP_K = 10
CONFIGS = (
    ("A0 BM25", "bm25", 1.0),
    ("A1 Dense", "dense", 1.0),
    ("A2 RRF w=0.5", "hybrid", 0.5),
    ("A2 RRF w=0.8", "hybrid", 0.8),
    ("A2 RRF w=1.0", "hybrid", 1.0),
    ("A3 RRF+Rerank", "hybrid_rerank", 1.0),
)


# ---------------------------------------------------------------- 语料
def load_corpus() -> list[dict]:
    materials: list[dict] = []
    for relative in CORPUS_FILES:
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        chunks: list[dict] = []
        sections: list[tuple[str, int, int]] = []   # (标题, 起始块号, 块数)
        for title, body in _split_sections(text):
            pieces = rag.chunk_text(body)
            if not pieces:
                continue
            start = len(chunks)
            for piece in pieces:
                chunks.append({"id": f"c{len(chunks) + 1}", "text": piece})
            sections.append((title, start, len(pieces)))
        if chunks:
            materials.append({
                "id": f"doc-{Path(relative).stem}",
                "title": relative,
                "chunks": chunks,
                "sections": sections,
            })
    return materials


def _split_sections(text: str) -> list[tuple[str, str]]:
    matches = list(HEADING.finditer(text))
    if not matches:
        return [("（全文）", text)]
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result.append((match.group(1).strip(), text[match.end():end].strip()))
    return result


# ---------------------------------------------------------------- 查询集
def build_queries(materials: list[dict]) -> tuple[list[dict], list[dict]]:
    queries: list[dict] = []
    qrels: list[dict] = []
    seen: set[str] = set()

    def add(query: str, kind: str, positive: list[str], material: str, section: str) -> None:
        key = query.strip()
        if not key or key in seen:
            return
        seen.add(key)
        qid = f"q{len(queries) + 1:03d}"
        queries.append({"qid": qid, "query": key, "type": kind, "material": material, "section": section})
        for chunk in positive:
            qrels.append({"qid": qid, "chunk": chunk, "rel": 1})

    for material in materials:
        for title, start, count in material["sections"]:
            heading = re.sub(r"\s+", " ", title).strip()
            if not 4 <= len(heading) <= 30 or "目录" in heading:
                continue
            positive = [f"{material['id']}:c{start + offset + 1}" for offset in range(count)]
            add(heading, "heading", positive, material["id"], heading)

    for material in materials:
        chunks = material["chunks"]
        step = max(1, len(chunks) // 30)
        for position in range(0, len(chunks), step):
            chunk = chunks[position]
            sentence = _pick_sentence(chunk["text"])
            if not sentence:
                continue
            add(sentence, "sentence", [f"{material['id']}:{chunk['id']}"], material["id"], "")
    return queries, qrels


def _pick_sentence(text: str) -> str:
    for sentence in rag.split_sentences(text):
        sentence = re.sub(r"^[\s>#\-*|\d.]*", "", sentence).strip()
        sentence = sentence.replace("**", "").replace("`", "")
        if "http" in sentence or sentence.startswith("|"):
            continue
        if 18 <= len(sentence) <= 60 and sentence.endswith(("。", "？", "！")):
            return sentence.rstrip("。！？")
    return ""


def load_or_build(materials: list[dict], rebuild: bool) -> tuple[list[dict], list[dict]]:
    if rebuild or not QUERIES.is_file() or not QRELS.is_file():
        queries, qrels = build_queries(materials)
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        _write_jsonl(QUERIES, queries)
        _write_jsonl(QRELS, qrels)
        return queries, qrels
    queries = _read_jsonl(QUERIES)
    qrels = _read_jsonl(QRELS)
    return queries, qrels


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------- 指标
def recall_at(ranked: list[str], relevant: set[str], k: int = TOP_K) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr_at(ranked: list[str], relevant: set[str], k: int = TOP_K) -> float:
    for position, key in enumerate(ranked[:k], 1):
        if key in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at(ranked: list[str], relevant: set[str], k: int = TOP_K) -> float:
    if not relevant:
        return 0.0
    dcg = sum(1.0 / math.log2(position + 1) for position, key in enumerate(ranked[:k], 1) if key in relevant)
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(ratio * (len(ordered) - 1))))
    return ordered[index]


# ---------------------------------------------------------------- 评测
def evaluate(config_name: str, mode: str, weight: float, docs: list[dict],
             queries: list[dict], qrels: dict[str, set[str]]) -> dict:
    os.environ["EDU_RETRIEVAL_MODE"] = mode
    os.environ["EDU_RETRIEVAL_DENSE_WEIGHT"] = str(weight)
    recalls: list[float] = []
    mrrs: list[float] = []
    ndcgs: list[float] = []
    latencies: list[float] = []
    for item in queries:
        started = time.perf_counter()
        results = retrieval.search_docs(item["query"], docs, top_k=TOP_K, mode_=mode)
        latencies.append((time.perf_counter() - started) * 1000)
        ranked = [f"{row['material_id']}:{row['chunk_id']}" for row in results]
        relevant = qrels.get(item["qid"], set())
        recalls.append(recall_at(ranked, relevant))
        mrrs.append(mrr_at(ranked, relevant))
        ndcgs.append(ndcg_at(ranked, relevant))
    return {
        "name": config_name,
        "mode": mode,
        "weight": weight,
        "recall": sum(recalls) / len(recalls) if recalls else 0.0,
        "mrr": sum(mrrs) / len(mrrs) if mrrs else 0.0,
        "ndcg": sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
        "p50": percentile(latencies, 0.5),
        "p95": percentile(latencies, 0.95),
        "per_query": {"recall": recalls, "mrr": mrrs, "ndcg": ndcgs},
    }


def bootstrap_delta(baseline: list[float], candidate: list[float],
                    rounds: int = 1000, seed: int = 42) -> tuple[float, float, float]:
    """配对 bootstrap：返回 (均值差, 95% 下界, 95% 上界)。"""
    if len(baseline) != len(candidate) or not baseline:
        return 0.0, 0.0, 0.0
    diffs = [candidate[i] - baseline[i] for i in range(len(baseline))]
    rng = random.Random(seed)
    samples = []
    for _ in range(rounds):
        picks = [rng.randrange(len(diffs)) for _ in range(len(diffs))]
        samples.append(sum(diffs[index] for index in picks) / len(diffs))
    samples.sort()
    return (
        sum(diffs) / len(diffs),
        samples[int(0.025 * rounds)],
        samples[int(0.975 * rounds) - 1],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Edu 检索 ablation")
    parser.add_argument("--build", action="store_true", help="重建查询集与标注")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条查询（冒烟）")
    parser.add_argument("--rerank", action="store_true", help="强制包含 A3（需 API Key）")
    args = parser.parse_args()

    materials = load_corpus()
    queries, qrels_rows = load_or_build(materials, args.build)
    if args.limit:
        queries = queries[: args.limit]
    keep = {item["qid"] for item in queries}
    qrels: dict[str, set[str]] = {}
    for row in qrels_rows:
        if row["qid"] in keep:
            qrels.setdefault(row["qid"], set()).add(row["chunk"])

    docs = retrieval.collect_from_materials(materials)
    print(f"语料 {len(materials)} 份资料 / {len(docs)} 块；查询 {len(queries)} 条；正例 {sum(len(v) for v in qrels.values())} 个")

    dense_ready = retrieval.available()
    if dense_ready:
        started = time.perf_counter()
        for material in materials:
            retrieval.material_vectors(material)
        build_seconds = time.perf_counter() - started
        print(f"向量建库 {build_seconds:.2f}s，索引 {retrieval.stats()['index_mb']} MB")
    else:
        build_seconds = 0.0
        print(f"向量层不可用（{retrieval.stats()['dense_error']}），只跑 BM25")

    configs = [CONFIGS[0]]
    if dense_ready:
        configs += list(CONFIGS[1:5])
    from server.llm import llm
    if args.rerank or (dense_ready and not llm.demo):
        configs.append(CONFIGS[-1])
    else:
        print("跳过 A3：演示模式没有 API Key，rerank 无从调用")

    results = []
    for name, mode, weight in configs:
        row = evaluate(name, mode, weight, docs, queries, qrels)
        results.append(row)
        print(f"{name:<16} R@10={row['recall']:.3f} MRR@10={row['mrr']:.3f} "
              f"nDCG@10={row['ndcg']:.3f} P50={row['p50']:.1f}ms P95={row['p95']:.1f}ms")

    report = _render(results, queries, qrels, materials, docs, build_seconds)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    output = EVAL_DIR / f"results-{time.strftime('%Y%m%d')}.md"
    output.write_text(report, encoding="utf-8")
    page = ROOT / "data" / "eval" / "latest.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        _render_html(results, queries, materials, docs, build_seconds, output.name),
        encoding="utf-8",
    )
    print(f"报告已写入 {output}（服务启动后访问 /eval 可看 HTML 版）")
    return 0


def _render(results: list[dict], queries: list[dict], qrels: dict[str, set[str]],
            materials: list[dict], docs: list[dict], build_seconds: float) -> str:
    baseline = results[0]
    lines = [
        "# 检索 ablation 结果",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 语料：{len(materials)} 份资料 / {len(docs)} 块（chunk 450 字、重叠 100）",
        f"- 查询：{len(queries)} 条（heading {sum(1 for q in queries if q['type'] == 'heading')} / "
        f"sentence {sum(1 for q in queries if q['type'] == 'sentence')}），"
        f"正例 {sum(len(v) for v in qrels.values())} 个",
        f"- 向量模型：{retrieval.model_name()}；建库 {build_seconds:.2f}s；"
        f"索引 {retrieval.stats()['index_mb']} MB",
        f"- 指标口径：{TOP_K} 条截断，nDCG 用二元相关",
        "",
        "## 主表",
        "",
        "| 配置 | Recall@10 | MRR@10 | nDCG@10 | P50 (ms) | P95 (ms) |",
        "|---|---|---|---|---|---|",
    ]
    for row in results:
        lines.append(
            f"| {row['name']} | {row['recall']:.3f} | {row['mrr']:.3f} | {row['ndcg']:.3f} "
            f"| {row['p50']:.1f} | {row['p95']:.1f} |"
        )
    if len(results) > 1:
        lines += [
            "",
            "## 配对 bootstrap（对 A0，1000 次重采样，95% 置信区间）",
            "",
            "| 对比 | ΔRecall@10 | ΔMRR@10 | ΔnDCG@10 |",
            "|---|---|---|---|",
        ]
        for row in results[1:]:
            cells = []
            for metric in ("recall", "mrr", "ndcg"):
                delta, low, high = bootstrap_delta(baseline["per_query"][metric], row["per_query"][metric])
                star = "*" if low > 0 else ""
                cells.append(f"{delta:+.3f} [{low:+.3f}, {high:+.3f}]{star}")
            lines.append(f"| {row['name']} | " + " | ".join(cells) + " |")
        lines += ["", "`*` 表示区间下界 > 0，即该层相对 A0 的提升在 95% 水平上可区分。"]
    lines += [
        "",
        "## 怎么读这张表",
        "",
        "- 查询集第一类是**小节标题**（一条查询对应整节多个正例），第二类是**从块里抽的原句**，"
        "后者与原文措辞重合，天然对 BM25 有利；这批数字偏保守，不代表真实提问分布。",
        "- 小语料（百余块）上 BM25 本身就强，混合检索的优势通常要在更大语料、更口语化的提问上才显现。",
        "- 延迟包含查询编码；A3 还包含一次 LLM 调用，未配置 Key 时不出现在表里。",
        "",
    ]
    return "\n".join(lines)


def _render_html(results: list[dict], queries: list[dict], materials: list[dict],
                 docs: list[dict], build_seconds: float, source: str) -> str:
    rows = "".join(
        f"<tr><td>{row['name']}</td><td>{row['recall']:.3f}</td><td>{row['mrr']:.3f}</td>"
        f"<td>{row['ndcg']:.3f}</td><td>{row['p50']:.1f}</td><td>{row['p95']:.1f}</td></tr>"
        for row in results
    )
    significance = ""
    if len(results) > 1:
        baseline = results[0]
        body = []
        for row in results[1:]:
            cells = []
            for metric in ("recall", "mrr", "ndcg"):
                delta, low, high = bootstrap_delta(baseline["per_query"][metric], row["per_query"][metric])
                star = "<b>*</b>" if low > 0 else ""
                cells.append(f"{delta:+.3f} [{low:+.3f}, {high:+.3f}]{star}")
            body.append(f"<tr><td>{row['name']}</td>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
        significance = (
            "<h2>配对 bootstrap（对 A0，95% 置信区间）</h2>"
            "<table><thead><tr><th>对比</th><th>ΔRecall@10</th><th>ΔMRR@10</th><th>ΔnDCG@10</th></tr></thead>"
            "<tbody>" + "".join(body) + "</tbody></table>"
            "<p class='note'>下界 &gt; 0 记 <b>*</b>，表示相对 BM25 的提升在 95% 水平上可区分。</p>"
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Edu · 检索评测</title>
<style>
  body{{margin:0;padding:48px 24px;background:#fff;color:#161616;
       font:15px/1.75 system-ui,"Segoe UI","Microsoft YaHei",sans-serif}}
  main{{max-width:860px;margin:0 auto}}
  h1{{font-size:26px;margin:0 0 6px}} h2{{font-size:18px;margin:32px 0 10px}}
  .meta{{color:#666;font-size:13px;margin:0 0 24px}}
  table{{width:100%;border-collapse:collapse;font-size:14px}}
  th,td{{border:1px solid #e5e5e5;padding:8px 10px;text-align:left}}
  th{{background:#fafafa;font-weight:600}} td:not(:first-child){{text-align:right}}
  .note{{color:#666;font-size:13px}}
  code{{background:#f5f5f5;padding:1px 5px;border-radius:4px}}
</style></head><body><main>
<h1>检索 ablation 报告</h1>
<p class="meta">{len(materials)} 份资料 / {len(docs)} 块 · 查询 {len(queries)} 条 ·
向量模型 {retrieval.model_name()} · 建库 {build_seconds:.2f}s ·
索引 {retrieval.stats()['index_mb']} MB · 源文件 <code>{source}</code></p>
<table><thead><tr><th>配置</th><th>Recall@10</th><th>MRR@10</th><th>nDCG@10</th><th>P50 (ms)</th><th>P95 (ms)</th></tr></thead>
<tbody>{rows}</tbody></table>
{significance}
<h2>口径与局限</h2>
<p class="note">查询集一类是小节标题（一条查询对应整节多个正例），一类是从块里抽的原句（与原文措辞重合，对 BM25 有利）。
小语料上 BM25 本身很强，混合检索的优势通常要在更大语料、更口语化的提问上才显现；这张表按实际跑出的数字展示，不做修饰。</p>
</main></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
