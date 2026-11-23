"""Tests for client invoices. Run: py -3 tests\\test_invoicing.py"""
import sys, types, tempfile, shutil, datetime, sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.dont_write_bytecode = True


class _St(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.dialog = lambda *a, **k: (lambda f: f)


def raises(exc, text, fn):
    try:
        fn()
    except exc as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError(f"no {exc.__name__}: {text}")


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_inv_"))
    (tmp / "database").mkdir()
    for f in ("schema.sql",):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db, security as sec, app_settings as aps, invoicing as I
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    db.init_db(); sec.ensure_security_schema(); aps.ensure_settings_schema()
    I.ensure_invoice_schema(); I.ensure_invoice_schema()
    import company_hub as H, hub_engine as E
    H.ensure_hub_schema(); E.ensure_engine_schema()
    D = datetime.date

    assert aps.get("vat_rate") == "15" and I.vat_rate() == 15.0
    co, _ = H.save_company(None, {"name": "شركة اختبار", "tax_number": "300111222333444", "work_start_date": D(2026, 1, 1)})
    t = lambda amt: {"basic_salary": amt, "actual_cost": amt, "bonus": 0, "start_date": D(2026, 3, 1), "status": "active"}
    p1, _ = H.add_employee(co, {"full_name": "موظف أ"}, t(5000)); p2, _ = H.add_employee(co, {"full_name": "موظف ب"}, t(3100))
    assert I.months_with_accounts(co) == []
    E.add_transfer(p1, "2026-03", D(2026, 3, 28), 5000); E.add_transfer(p2, "2026-03", D(2026, 3, 28), 3100)
    assert I.months_with_accounts(co) == ["2026-03"]
    pv = I.preview(co, "2026-03")
    assert pv["subtotal"] == 8100.0 and pv["vat_amount"] == 1215.0 and pv["total"] == 9315.0 and len(pv["lines"]) == 2

    # needs seller tax number
    raises(ValueError, "الرقم الضريبي", lambda: I.issue_invoice(co, "2026-03", D(2026, 4, 1)))
    aps.save({"org_name": "منشأتي", "org_tax_number": "300999888777666"}) if "org_tax_number" in aps.DEFAULTS else None
    iid = I.issue_invoice(co, "2026-03", D(2026, 4, 1), "ملاحظة")
    inv = db.query_one("SELECT * FROM invoices WHERE id=?", (iid,))
    assert inv["invoice_no"] == "INV-2026-0001" and float(inv["total"]) == 9315.0 and inv["buyer_tax_number"] == "300111222333444"
    assert len(I.invoice_lines(iid)) == 2
    raises(ValueError, "فاتورة سارية", lambda: I.issue_invoice(co, "2026-03", D(2026, 4, 2)))
    assert b"INV-2026-0001" in I.invoice_html(iid).encode() and len(I.invoice_excel(iid)) > 1000

    # database-level protection
    def bad(sql, args=()):
        try:
            db.execute(sql, args)
        except sqlite3.IntegrityError:
            return True
        return False
    assert bad("DELETE FROM invoices WHERE id=?", (iid,))
    assert bad("UPDATE invoices SET total=1 WHERE id=?", (iid,))
    assert bad("UPDATE invoices SET status='void' WHERE id=?", (iid,))           # no reason
    assert bad("UPDATE invoice_lines SET amount=1 WHERE invoice_id=?", (iid,))
    assert bad("DELETE FROM invoice_lines WHERE invoice_id=?", (iid,))

    # void then re-issue -> next number, old kept
    raises(ValueError, "سبب", lambda: I.void_invoice(iid, " "))
    I.void_invoice(iid, "خطأ في المبلغ")
    raises(ValueError, "ملغاة", lambda: I.void_invoice(iid, "x"))
    assert bad("UPDATE invoices SET status='issued' WHERE id=?", (iid,))
    iid2 = I.issue_invoice(co, "2026-03", D(2026, 4, 3))
    assert db.query_one("SELECT invoice_no n FROM invoices WHERE id=?", (iid2,))["n"] == "INV-2026-0002"
    assert db.query_one("SELECT COUNT(*) c FROM invoices")["c"] == 2
    assert db.query_one("SELECT COUNT(*) c FROM audit_log WHERE table_name='invoices'")["c"] == 3
    raises(ValueError, "لا توجد إيرادات", lambda: I.issue_invoice(co, "2026-04", D(2026, 5, 1)))
    print("INVOICING_TESTS_PASSED")


if __name__ == "__main__":
    main()
