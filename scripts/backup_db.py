"""SQLite 热备份 + 过期清理。

为什么用 sqlite3 的 backup API 而不是 cp：
- 服务运行时直接复制文件可能拿到写了一半的页（数据库损坏）
- backup API 会正确处理锁与事务，属于官方推荐的热备方式

用法（宿主机执行，容器里有数据）：
    docker exec contract-agent python scripts/backup_db.py

参数：
    --db     数据库路径（默认取 CLAUSEGUARD_DB，否则 /data/clauseguard.sqlite3）
    --out    备份目录（默认 /data/backups，随数据卷持久化）
    --keep   保留份数（默认 7）

配合 crontab：
    0 3 * * * docker exec contract-agent python scripts/backup_db.py >> ~/cg-backup.log 2>&1
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_DB = os.environ.get("CLAUSEGUARD_DB") or "/data/clauseguard.sqlite3"
DEFAULT_OUT = "/data/backups"
DEFAULT_KEEP = 7


def backup(db_path: Path, out_dir: Path) -> Path:
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"clauseguard-{stamp}.sqlite3"

    source = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
            destination.execute("PRAGMA integrity_check").fetchone()
        finally:
            destination.close()
    finally:
        source.close()
    return target


def prune(out_dir: Path, keep: int) -> list[Path]:
    files = sorted(out_dir.glob("clauseguard-*.sqlite3"), key=lambda item: item.name)
    removed: list[Path] = []
    for path in files[: max(0, len(files) - keep)]:
        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            print(f"清理失败 {path.name}：{exc}", file=sys.stderr)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite 热备份")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    out_dir = Path(args.out)
    target = backup(db_path, out_dir)
    size_mb = target.stat().st_size / 1024 / 1024
    print(f"备份完成：{target}（{size_mb:.2f} MB）")

    removed = prune(out_dir, max(1, args.keep))
    if removed:
        print(f"已清理 {len(removed)} 份过期备份（保留最近 {args.keep} 份）")
    remaining = len(list(out_dir.glob("clauseguard-*.sqlite3")))
    print(f"当前共 {remaining} 份备份")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
