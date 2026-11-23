import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from db import get_db_path, BASE_DIR, init_db, SCHEMA_PATH

BACKUP_DIR = BASE_DIR / "backups"


def ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def create_backup(note: str = "") -> Path:
    ensure_backup_dir()
    db_path = get_db_path()
    if not db_path.exists():
        init_db()
        db_path = get_db_path()
    name = f"backup_{_timestamp()}.db"
    dest = BACKUP_DIR / name
    # Use sqlite backup API for consistency
    src_conn = sqlite3.connect(str(db_path))
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    if note:
        (BACKUP_DIR / f"{name}.txt").write_text(note, encoding="utf-8")
    return dest


def list_backups() -> List[Dict]:
    ensure_backup_dir()
    items = []
    for p in sorted(BACKUP_DIR.glob("backup_*.db"), reverse=True):
        note_path = p.with_suffix(p.suffix + ".txt")
        items.append({
            "name": p.name,
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "note": note_path.read_text(encoding="utf-8").strip() if note_path.exists() else "",
        })
    return items


def restore_backup(backup_path: str) -> Path:
    src = Path(backup_path)
    if not src.exists():
        raise FileNotFoundError(f"ملف النسخة الاحتياطية غير موجود: {src}")
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # create safety backup of current before restore
    if db_path.exists():
        ensure_backup_dir()
        safety = BACKUP_DIR / f"pre_restore_{_timestamp()}.db"
        sconn = sqlite3.connect(str(db_path))
        try:
            dconn = sqlite3.connect(str(safety))
            try:
                sconn.backup(dconn)
            finally:
                dconn.close()
        finally:
            sconn.close()
    # restore by copying bytes (replace)
    shutil.copy2(src, db_path)
    # ensure schemas exist (forward compat)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path
