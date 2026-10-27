"""存储层基准：对比 JSON / SQLite 两种后端的读路径耗时（P2 · S4）。

用法（在项目根目录执行）：
    python scripts/bench_store.py
    EDU_STORE=json python scripts/bench_store.py

输出每个集合 list_items / load_item 的 p50、p95（毫秒）。
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import store  # noqa: E402

ROUNDS = int(os.environ.get("EDU_BENCH_ROUNDS", "50"))


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(ratio * (len(ordered) - 1))))
    return ordered[index]


def main() -> int:
    print(f"后端：{store.backend()}    轮数：{ROUNDS}\n")
    print(f"{'collection':<12} {'items':>6} {'list p50':>9} {'list p95':>9} {'load p50':>9} {'load p95':>9}")
    for name in store.COLLECTIONS:
        items = store.list_items(name)
        if not items:
            continue
        sample = items[0]["id"]
        list_times: list[float] = []
        load_times: list[float] = []
        for _ in range(ROUNDS):
            started = time.perf_counter()
            store.list_items(name)
            list_times.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            store.load_item(name, sample)
            load_times.append((time.perf_counter() - started) * 1000)
        print(
            f"{name:<12} {len(items):>6} "
            f"{statistics.median(list_times):>8.2f}ms {_percentile(list_times, 0.95):>8.2f}ms "
            f"{statistics.median(load_times):>8.2f}ms {_percentile(load_times, 0.95):>8.2f}ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
