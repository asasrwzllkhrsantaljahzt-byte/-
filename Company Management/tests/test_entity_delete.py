"""Safe deletion of parties. Run: py -3 tests\\test_entity_delete.py"""
import sys, types, tempfile, shutil, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.dont_write_bytecode = True


class _St(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.dialog = lambda *a, **k: (lambda f: f)


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_del_"))
    (tmp / "database").mkdir()
    for f in ("schema.sql",):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db, security as sec, app_settings as aps, documents as DOC, vouchers as V, invoicing as I
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    db.init_db(); sec.ensure_security_schema(); aps.ensure_settings_schema()
    DOC.ensure_documents_schema(); V.ensure_vouchers_schema(); I.ensure_invoice_schema()
    from modules import entities as E, employees, companies, contractors, representatives
    D = datetime.date
    free = db.execute("INSERT INTO employees(full_name) VALUES ('حر')")
    busy = db.execute("INSERT INTO employees(full_name) VALUES ('مرتبط')")
    co = db.execute("INSERT INTO companies(name) VALUES ('ش')")
    db.execute("INSERT INTO employee_placements(employee_id, company_id, start_date, status) VALUES (?,?,?,'active')", (busy, co, '2026-03-01'))
    assert "تم حذف" in E.delete_record(employees.CFG, free)
    assert db.query_one("SELECT COUNT(*) c FROM employees WHERE id=?", (free,))["c"] == 0
    assert db.query_one("SELECT COUNT(*) c FROM audit_log WHERE table_name='employees' AND action='STATUS_CHANGE'")["c"] == 1
    for cfg, rid in ((employees.CFG, busy), (companies.CFG, co)):
        try:
            E.delete_record(cfg, rid)
        except ValueError as e:
            assert "تعيينات" in str(e) and "غير نشط" in str(e)
        else:
            raise AssertionError("deleted a linked record")
    # only a voucher / only a document also blocks
    ct = db.execute("INSERT INTO contractors(name) VALUES ('م')")
    V.issue_voucher("payment", D(2026, 4, 1), "contractor", ct, 10)
    try:
        E.delete_record(contractors.CFG, ct)
    except ValueError as e:
        assert "إذون" in str(e)
    else:
        raise AssertionError("voucher link ignored")
    rp = db.execute("INSERT INTO representatives(name) VALUES ('ر')")
    DOC.add_document("representative", rp, "هوية")
    try:
        E.delete_record(representatives.CFG, rp)
    except ValueError as e:
        assert "وثائق" in str(e)
    else:
        raise AssertionError("document link ignored")
    print("ENTITY_DELETE_TESTS_PASSED")


if __name__ == "__main__":
    main()
