"""SQLite 热备份（P2 · S4）。

走 sqlite3 的 backup API，服务运行中也能安全执行；备份文件默认放在
data/backups/，只保留最近 N 份。

用法：
    python scripts/backup.py                # 备份一次，保留最近 10 份
    python scripts/backup.py --keep 30      # 保留 30 份
    python scripts/backup.py --out D:/bk    # 指定输出目录
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Edu SQLite 备份")
    parser.add_argument("--keep", type=int, default=10, help="保留最近几份，默认 10")
    parser.add_argument("--out", default=str(db.BACKUP_DIR), help="备份目录")
    args = parser.parse_args()

    source = db.DB_PATH
    if not source.is_file():
        print(f"数据库不存在：{source}")
        return 1

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"edu-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"

    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)

    size = target.stat().st_size / 1024
    print(f"已备份：{target}（{size:.1f} KB）")

    backups = sorted(out_dir.glob("edu-*.sqlite3"))
    for stale in backups[: max(0, len(backups) - args.keep)]:
        stale.unlink()
        print(f"清理旧备份：{stale.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
