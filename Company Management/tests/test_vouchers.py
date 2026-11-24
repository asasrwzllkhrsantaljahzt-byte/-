"""Tests for vouchers, per-party accounts and relationships. Run: py -3 tests\\test_vouchers.py"""
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


def raises(text, fn):
    try:
        fn()
    except ValueError as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError("no error: " + text)


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_vo_"))
    (tmp / "database").mkdir()
    for f in ("schema.sql",):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db, security as sec, app_settings as aps, vouchers as V
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    db.init_db(); sec.ensure_security_schema(); aps.ensure_settings_schema()
    V.ensure_vouchers_schema(); V.ensure_vouchers_schema()
    import company_hub as H, hub_engine as E
    H.ensure_hub_schema(); E.ensure_engine_schema()
    D = datetime.date
    co, _ = H.save_company(None, {"name": "شركة العميل", "work_start_date": D(2026, 1, 1)})
    ct = db.execute("INSERT INTO contractors(name) VALUES ('متعهد')")
    rp = db.execute("INSERT INTO representatives(name) VALUES ('مندوب')")
    H.set_rep(co, rp, 10, D(2026, 1, 1))
    pid, _ = H.add_employee(co, {"full_name": "موظف"}, {"basic_salary": 2000, "actual_cost": 1700, "bonus": 1000, "contractor_id": ct,
                            "contractor_commission": 100, "start_date": D(2026, 3, 1), "status": "active"})
    emp = H.get_placement(pid)["employee_id"]
    E.add_transfer(pid, "2026-03", D(2026, 4, 1), 2000)       # refund 300, returns 1000, contractor 100, net 600, rep 60

    a = V.party_account("company", co)
    assert a["due"] == 300 and a["settled"] == 0 and a["balance"] == 300
    r1 = V.issue_voucher("payment", D(2026, 4, 2), "company", co, 100, "transfer", "REF1", "2026-03", "مردود")
    assert db.query_one("SELECT voucher_no n FROM vouchers WHERE id=?", (r1,))["n"] == "PAY-2026-0001"
    assert V.party_account("company", co)["balance"] == 200
    p1 = V.issue_voucher("receipt", D(2026, 4, 3), "employee", emp, 400, month_ref="2026-03")
    p2 = V.issue_voucher("payment", D(2026, 4, 3), "contractor", ct, 100)
    assert db.query_one("SELECT voucher_no n FROM vouchers WHERE id=?", (p2,))["n"] == "PAY-2026-0002"
    assert V.party_account("employee", emp)["balance"] == 600 and V.party_account("contractor", ct)["balance"] == 0
    oth = V.issue_voucher("payment", D(2026, 4, 5), "other", None, 50, other_name="مصروف ضيافة")
    st = V.statement_rows("employee", emp)
    assert st[-1]["الرصيد"] == 600 and len(st) == 2

    # validation
    raises("أكبر من صفر", lambda: V.issue_voucher("receipt", D(2026, 4, 2), "company", co, 0))
    raises("اختر الجهة", lambda: V.issue_voucher("receipt", D(2026, 4, 2), "company", 999, 10))
    raises("اسم الجهة", lambda: V.issue_voucher("receipt", D(2026, 4, 2), "other", None, 10))
    raises("YYYY-MM", lambda: V.issue_voucher("receipt", D(2026, 4, 2), "company", co, 10, month_ref="2026/03"))
    raises("غير صحيح", lambda: V.issue_voucher("x", D(2026, 4, 2), "company", co, 10))

    # protection
    def bad(sql, args=()):
        try:
            db.execute(sql, args)
        except sqlite3.IntegrityError:
            return True
        return False
    assert bad("DELETE FROM vouchers WHERE id=?", (r1,))
    assert bad("UPDATE vouchers SET amount=1 WHERE id=?", (r1,))
    assert bad("UPDATE vouchers SET status='void' WHERE id=?", (r1,))
    raises("سبب", lambda: V.void_voucher(r1, " "))
    V.void_voucher(r1, "أُدخل خطأً")
    assert V.party_account("company", co)["settled"] == 0 and V.party_account("company", co)["balance"] == 300
    raises("ملغى", lambda: V.void_voucher(r1, "x"))
    assert b"PAY-2026-0002" in V.voucher_html(p2).encode()
    assert db.query_one("SELECT COUNT(*) c FROM audit_log WHERE table_name='vouchers'")["c"] == 5

    expense = V.issue_voucher("payment", D(2026, 4, 5), "other", None, 75, other_name="مصروف تشغيل",
                               entry_category="operating_expense")
    V.issue_voucher("payment", D(2026, 4, 5), "other", None, 20, other_name="مسحوبات المالك",
                    entry_category="owner_draw")
    replacement = V.replace_voucher(expense, D(2026, 4, 6), 80, "cash", "", "2026-04", "تصحيح",
                                    "operating_expense", "تصحيح المبلغ", "مصروف تشغيل معدل")
    assert db.query_one("SELECT status FROM vouchers WHERE id=?", (expense,))["status"] == "void"
    updated = db.query_one("SELECT amount, party_name FROM vouchers WHERE id=?", (replacement,))
    assert updated == {"amount": 80, "party_name": "مصروف تشغيل معدل"}
    assert V.other_payment_totals()["2026-04"] == {"operating_expense": 80.0, "owner_draw": 20.0}
    reassigned = V.replace_voucher(p2, D(2026, 4, 7), 100, "transfer", "", None, "تغيير المستفيد",
                                   "settlement", "تصحيح الجهة", party_type="representative", party_id=rp)
    assert db.query_one("SELECT status FROM vouchers WHERE id=?", (p2,))["status"] == "void"
    assert db.query_one("SELECT party_type, party_id FROM vouchers WHERE id=?", (reassigned,)) == {
        "party_type": "representative", "party_id": rp}
    from modules import financial_activity_page as activity
    movements = activity._collect_rows(["التحويلات والحساب الشهري", "التحصيل والمدفوعات", "السندات"])
    operations = {row["operation"] for row in movements}
    assert {"transfer", "employee_receipt", "settlement", "operating_expense", "owner_draw"} <= operations
    assert "نوع الحركة" in activity._display_frame(movements).columns

    pb = {r["name"]: r for r in V.party_balances("company")}
    assert pb["شركة العميل"]["due"] == 300 and pb["شركة العميل"]["balance"] == 300
    assert V.party_balances("company", "2026-04")[0]["due"] == 0
    import ui
    assert ui.parse_number("1,500.50") == 1500.5 and ui.parse_number("١٥٠٠") == 1500 and ui.parse_number(" ") is None
    for bad_text in ("abc", "1e999", "nan"):
        try:
            ui.parse_number(bad_text)
        except ValueError:
            pass
        else:
            raise AssertionError(bad_text)
    print("VOUCHERS_TESTS_PASSED")


if __name__ == "__main__":
    main()
