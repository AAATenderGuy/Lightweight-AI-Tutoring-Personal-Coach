"""把 data/ 下的 JSON 迁移进 SQLite（P2 · S4）。

用法：
    python scripts/migrate_json_to_sqlite.py                    # 只统计，不写入
    python scripts/migrate_json_to_sqlite.py --apply            # 写入（已存在的 id 跳过）
    python scripts/migrate_json_to_sqlite.py --apply --overwrite  # 覆盖已存在的 id

迁移是幂等的：重复执行只会跳过。写入后会逐条回读比对，任何一条不一致都会以
非零退出码报告，方便挂到 CI 或部署脚本里。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 关掉 store 的「首次启动自动导入」，否则 dry-run 会先被自动导入写脏。
os.environ["EDU_AUTO_IMPORT"] = "0"

from server import db, store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="JSON → SQLite 迁移")
    parser.add_argument("--apply", action="store_true", help="真正写入数据库（默认只统计）")
    parser.add_argument("--overwrite", action="store_true", help="覆盖数据库里已存在的 id")
    parser.add_argument("--data-dir", default=str(ROOT / "data"), help="JSON 数据目录，默认 data/")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser().resolve()
    stats = db.import_from_json(
        store.COLLECTIONS, store.SHARED_NAMES,
        data_dir=data_dir, apply=args.apply, overwrite=args.overwrite,
    )

    mode = "APPLY" if args.apply else "DRY-RUN（加 --apply 才写入）"
    print(f"\n模式：{mode}")
    print(f"数据库：{db.DB_PATH}")
    print(f"JSON 来源：{data_dir}\n")
    for name, count in stats["items"].items():
        print(f"  {name:<12} {count:>5} 条")
    for name, count in stats["shared"].items():
        print(f"  @{name:<11} {count:>5} 项")
    print(f"\n跳过（库里已有）：{stats['skipped']} 条")
    print(f"回读校验：{'通过' if stats['verified'] else '失败'}")
    if stats["errors"]:
        print(f"异常 {len(stats['errors'])} 条：")
        for line in stats["errors"][:10]:
            print(f"  - {line}")
    print()

    total = sum(stats["items"].values())
    if args.apply and total and db.count_items() < total:
        print("警告：库内记录数少于本次导入数，请检查 --overwrite 或重复 id。")
    return 0 if stats["verified"] and not stats["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
