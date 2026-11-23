import os
import sqlite3
import tempfile
import shutil
from pathlib import Path
import sys
import pytest

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import db
import backup


def setup_temp_env():
    tmp = Path(tempfile.mkdtemp(prefix="cm_sys_"))
    # copy schemas
    (tmp / "database").mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE / "database" / "schema.sql", tmp / "database" / "schema.sql")
    return tmp


def patch_paths(tmp: Path):
    db.BASE_DIR = tmp
    db.SCHEMA_PATH = tmp / "database" / "schema.sql"
    db.DB_PATH = tmp / "database" / "app.db"
    backup.BASE_DIR = tmp
    backup.BACKUP_DIR = tmp / "backups"
    backup.SCHEMA_PATH = db.SCHEMA_PATH


@pytest.fixture(autouse=True)
def isolated_database(tmp_path):
    """Keep pytest runs separate from the real application database."""
    (tmp_path / "database").mkdir()
    shutil.copy2(BASE / "database" / "schema.sql", tmp_path / "database" / "schema.sql")
    patch_paths(tmp_path)
    db.init_db()
    yield


def test_save_and_persist():
    # CRUD save and persistence across connections
    emp_id = db.execute("INSERT INTO employees(full_name,status) VALUES (?,?)", ("موظف حفظ", "active"))
    comp_id = db.execute("INSERT INTO companies(name,status) VALUES (?,?)", ("شركة حفظ", "active"))
    assert emp_id and comp_id
    row = db.query_one("SELECT full_name FROM employees WHERE id=?", (emp_id,))
    assert row and row["full_name"] == "موظف حفظ"
    # new connection sees persisted data
    conn = db.get_connection()
    try:
        r = conn.execute("SELECT name FROM companies WHERE id=?", (comp_id,)).fetchone()
        assert r[0] == "شركة حفظ"
    finally:
        conn.close()
    return None


def test_backup_restore():
    db_path = db.get_db_path()
    # seed marker
    marker_id = db.execute("INSERT INTO contractors(name,status) VALUES (?,?)", ("متعهد قبل النسخ", "active"))
    bpath = backup.create_backup("test backup")
    assert bpath.exists() and bpath.stat().st_size > 0
    backups = backup.list_backups()
    assert any(b["name"] == bpath.name for b in backups)
    # mutate after backup
    db.execute("INSERT INTO contractors(name,status) VALUES (?,?)", ("متعهد بعد النسخ", "active"))
    assert db.query_one("SELECT COUNT(*) c FROM contractors")["c"] >= 2
    # restore
    restored = backup.restore_backup(str(bpath))
    assert Path(restored).exists()
    # after restore, post-backup row should be gone, pre-backup remains
    names = [r["name"] for r in db.query_all("SELECT name FROM contractors ORDER BY id")]
    assert "متعهد قبل النسخ" in names
    assert "متعهد بعد النسخ" not in names
    # safety backup created
    pre = list(backup.BACKUP_DIR.glob("pre_restore_*.db"))
    assert len(pre) >= 1
    return None


def test_accounts():
    """End to end on the monthly engine: the user's own example (2000 salary / 1700 cost / bonus 1000 / contractor 100)."""
    import datetime
    import company_hub as H, hub_engine as E, vouchers as V
    H.ensure_hub_schema(); E.ensure_engine_schema(); V.ensure_vouchers_schema()
    D = datetime.date
    co, _ = H.save_company(None, {"name": "شركة حسابات", "work_start_date": D(2026, 1, 1)})
    ct = db.execute("INSERT INTO contractors(name) VALUES (?)", ("متعهد حسابات",))
    rep = db.execute("INSERT INTO representatives(name) VALUES (?)", ("مندوب حسابات",))
    H.set_rep(co, rep, 10, D(2026, 1, 1))
    pid, _ = H.add_employee(co, {"full_name": "موظف حسابات"}, {"basic_salary": 2000, "actual_cost": 1700, "bonus": 1000, "contractor_id": ct,
                            "contractor_commission": 100, "start_date": D(2026, 4, 1), "status": "active"})
    E.add_transfer(pid, "2026-04", D(2026, 5, 2), 1000)
    t = E.compute_month("2026-04")["totals"]
    assert (t["net"], t["rep_due"], t["margin"]) == (352.94, 35.29, 317.65), t
    assert V.party_account("representative", rep)["due"] == 35.29
    # the old engine's tables are gone / dropped when empty
    import legacy
    db.execute("CREATE TABLE IF NOT EXISTS party_dues(id INTEGER PRIMARY KEY)")
    result = legacy.drop_legacy_tables()
    assert "party_dues" in result["dropped"] or any(t == "party_dues" for t, _ in result["kept"])
    return None


def main():
    tmp = setup_temp_env()
    try:
        patch_paths(tmp)
        db.init_db()
        test_save_and_persist()
        test_backup_restore()
        test_accounts()
        print("SYSTEM_TESTS_PASSED")
        print("save_persist=True")
        print("backup_restore=True")
        print("accounts=True")
        print(f"temp_env={tmp}")
        return 0
    finally:
        # keep temp for inspection? remove to be clean
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
