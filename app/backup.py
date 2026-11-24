"""Utilitas pencadangan (backup) basis data SQLite secara aman (NFR-010).

Jalankan:
    python -m app.backup
"""
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Optional

from app.config import BASE_DIR, DATABASE_PATH


def create_backup(db_path: Optional[Path] = None, backup_dir: Optional[Path] = None) -> Path:
    source = db_path or DATABASE_PATH
    if not source.exists():
        raise FileNotFoundError(f"File database tidak ditemukan: {source}")

    target_dir = backup_dir or (BASE_DIR / "backups")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = target_dir / f"local_thrift_{stamp}.db"

    with sqlite3.connect(str(source)) as src_conn, sqlite3.connect(str(dest)) as dst_conn:
        src_conn.backup(dst_conn)
    return dest


if __name__ == "__main__":
    out = create_backup()
    print(f"Backup basis data berhasil disimpan di: {out}")
