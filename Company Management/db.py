import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"
DB_PATH = BASE_DIR / "database" / "app.db"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> Path:
    global DB_PATH
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    # Try primary path, fallback to root path if unicode/path issues occur
    try:
        conn = _connect(DB_PATH)
    except sqlite3.OperationalError:
        fallback = BASE_DIR / "app.db"
        conn = _connect(fallback)
        DB_PATH = fallback
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
    return DB_PATH


def get_db_path() -> Path:
    return DB_PATH


def data_version() -> tuple:
    """Changes whenever anything is written to the database file (used to cache heavy calculations safely)."""
    out = []
    for suffix in ("", "-wal", "-journal"):
        try:
            st = os.stat(str(DB_PATH) + suffix)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def get_connection() -> sqlite3.Connection:
    global DB_PATH
    db_path = DB_PATH
    if not db_path.exists():
        # try fallback existence
        fallback = BASE_DIR / "app.db"
        if fallback.exists():
            db_path = fallback
            DB_PATH = fallback
        else:
            init_db()
            db_path = get_db_path()
    try:
        return _connect(db_path)
    except sqlite3.OperationalError:
        # if primary fails now, init/create fallback
        fallback = BASE_DIR / "app.db"
        conn = _connect(fallback)
        DB_PATH = fallback
        # ensure schema
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        conn.commit()
        return conn


def query_all(sql: str, params: tuple = ()): 
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_one(sql: str, params: tuple = ()):
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()): 
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def execute_many(sql: str, seq_of_params):
    conn = get_connection()
    try:
        cur = conn.executemany(sql, seq_of_params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
