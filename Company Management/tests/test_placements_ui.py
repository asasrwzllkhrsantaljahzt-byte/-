"""Placements & agreements: business rules used by the placements page, checked against the finance engine.
Run:  py -3 tests\\test_placements_ui.py
"""
import sys, types, tempfile, shutil, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.dont_write_bytecode = True


class _St(types.ModuleType):
    """Minimal Streamlit stand-in: the page module only needs to import (dialog decorator) here."""
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
    def dialog(self, *a, **k):
        return lambda f: f
    def __getattr__(self, name):
        return lambda *a, **k: None


def raises(msg, fn):
    try:
        fn()
    except ValueError as ex:
        assert msg in str(ex), (msg, str(ex))
        return True
    raise AssertionError(f"expected ValueError containing '{msg}'")


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_pl_"))
    (tmp / "database").mkdir()
    for f in ("schema.sql", "finance_schema.sql"):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db, finance_engine as fe
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    fe.BASE_DIR = tmp; fe.FINANCE_SCHEMA_PATH = tmp / "database/finance_schema.sql"
    db.init_db(); fe.ensure_finance_schema()
    import modules.placements as P
    D = datetime.date

    co = db.execute("INSERT INTO companies(name) VALUES ('شركة اختبار')")
    emp = db.execute("INSERT INTO employees(full_name) VALUES ('موظف اختبار')")
    emp2 = db.execute("INSERT INTO employees(full_name) VALUES ('موظف ثاني')")
    ct = db.execute("INSERT INTO contractors(name) VALUES ('متعهد اختبار')")
    rp = db.execute("INSERT INTO representatives(name) VALUES ('مندوب اختبار')")

    # 1) placements: add, and one open placement per employee
    pid = P.add_placement(emp, co, D(2026, 3, 1), "ملاحظة")
    raises("تعيين نشط مفتوح", lambda: P.add_placement(emp, co, D(2026, 4, 1)))
    assert db.query_one("SELECT COUNT(*) c FROM employee_placements")["c"] == 1
    pid2 = P.add_placement(emp2, co, D(2026, 3, 1))

    # 2) contractor agreement: validation, saved fixed 300, duplicate open blocked
    raises("أكبر من صفر", lambda: P.add_agreement("contractor", pid, ct, D(2026, 3, 1), "fixed", 0))
    raises("تجاوز 100", lambda: P.add_agreement("representative", pid, rp, D(2026, 3, 1), "percentage", 150))
    aid, warn = P.add_agreement("contractor", pid, ct, D(2026, 3, 1), "fixed", 300)
    row = db.query_one("SELECT * FROM placement_contractors")
    assert row["commission_type"] == "fixed" and float(row["commission_value"]) == 300.0 and warn is None
    raises("اتفاق نشط مفتوح", lambda: P.add_agreement("contractor", pid, ct, D(2026, 3, 1), "fixed", 250))
    assert db.query_one("SELECT COUNT(*) c FROM placement_contractors")["c"] == 1

    # 3) representative agreement without a relationship -> saved unlinked + warning
    raid, warn = P.add_agreement("representative", pid, rp, D(2026, 3, 1), "percentage", 10)
    r = db.query_one("SELECT * FROM placement_representatives WHERE id=?", (raid,))
    assert r["company_representative_id"] is None and warn and "علاقة" in warn

    # 4) relationship: add, duplicate blocked; new agreement on 2nd placement is auto-linked
    crid = P.add_relation(co, rp, D(2026, 3, 1))
    raises("علاقة نشطة مفتوحة", lambda: P.add_relation(co, rp, D(2026, 3, 1)))
    raid2, warn2 = P.add_agreement("representative", pid2, rp, D(2026, 3, 1), "percentage", 10)
    assert warn2 is None and db.query_one("SELECT company_representative_id x FROM placement_representatives WHERE id=?", (raid2,))["x"] == crid

    # 5) engine uses what the page created
    for cat, amt, d in (("client_agreed_amount", 5000, "in"), ("recorded_wage", 3000, "out")):
        for e_, p_ in ((emp, pid), (emp2, pid2)):
            db.execute("""INSERT INTO financial_transactions(tx_date,month_ref,placement_id,employee_id,company_id,category,direction,amount,review_status,source_type)
                          VALUES ('2026-03-05','2026-03',?,?,?,?,?,?,'approved','manual')""", (p_, e_, co, cat, d, amt))
    res = {r["employee_name"]: r for r in fe.calculate_month("2026-03")}
    a = res["موظف اختبار"]
    assert a["contractor_entitlements_total"] == 300.0 and a["representative_entitlements_total"] == 500.0, a
    assert a["company_margin"] == 5000 - 3000 - 300 - 500, a
    assert res["موظف ثاني"]["representative_entitlements_total"] == 500.0

    # 6) end the relationship on 15 Mar -> linked rep commission prorated 15/31
    raises("لا يمكن أن يسبق", lambda: P.end_relation(crid, D(2026, 2, 1)))
    P.end_relation(crid, D(2026, 3, 15))
    raises("منتهية بالفعل", lambda: P.end_relation(crid, D(2026, 3, 20)))
    b = {r["employee_name"]: r for r in fe.calculate_month("2026-03")}["موظف ثاني"]
    assert b["representative_entitlements_total"] == round(500 * 15 / 31, 2), b

    # 7) editing a placement: start date locks once monthly accounts exist, notes stay editable
    assert P.placement_has_accounts(pid)
    raises("حسابات شهرية", lambda: P.update_placement(pid, D(2026, 3, 5), "x"))
    P.update_placement(pid, D(2026, 3, 1), "ملاحظة جديدة")
    assert db.query_one("SELECT notes n FROM employee_placements WHERE id=?", (pid,))["n"] == "ملاحظة جديدة"
    emp3 = db.execute("INSERT INTO employees(full_name) VALUES ('موظف ثالث')")
    pid3 = P.add_placement(emp3, co, D(2026, 5, 1))
    assert not P.placement_has_accounts(pid3)
    P.update_placement(pid3, D(2026, 5, 10), None)
    assert db.query_one("SELECT start_date s FROM employee_placements WHERE id=?", (pid3,))["s"] == "2026-05-10"

    # 8) end a placement: date must be >= start; 20 Mar -> prorated; ended placements are closed
    raises("لا يمكن أن يسبق", lambda: P.end_placement(pid, "ended", D(2026, 2, 1)))
    P.end_placement(pid, "ended", D(2026, 3, 20), "استقالة")
    p1 = db.query_one("SELECT * FROM employee_placements WHERE id=?", (pid,))
    assert p1["status"] == "ended" and p1["end_date"] == "2026-03-20" and p1["stop_reason"] == "استقالة"
    raises("منتهٍ ومغلق", lambda: P.end_placement(pid, "ended", D(2026, 3, 25)))
    a = {r["employee_name"]: r for r in fe.calculate_month("2026-03")}["موظف اختبار"]
    assert a["active_days"] == 20 and a["contractor_entitlements_total"] == round(300 * 20 / 31, 2), a
    # a placement can be added again for the employee after the old one ended (history kept)
    P.add_placement(emp, co, D(2026, 4, 1))
    assert db.query_one("SELECT COUNT(*) c FROM employee_placements WHERE employee_id=?", (emp,))["c"] == 2

    # 9) ending an agreement
    P.end_agreement("contractor", aid, D(2026, 3, 31))
    raises("منتهٍ بالفعل", lambda: P.end_agreement("contractor", aid, D(2026, 4, 5)))

    # 10) everything audited
    kinds = {r["table_name"] for r in db.query_all("SELECT DISTINCT table_name FROM audit_log")}
    assert {"employee_placements", "placement_contractors", "placement_representatives", "company_representatives"} <= kinds, kinds
    acts = {r["action"] for r in db.query_all("SELECT DISTINCT action FROM audit_log")}
    assert {"INSERT", "STATUS_CHANGE", "UPDATE"} <= acts, acts

    print("PLACEMENTS_UI_TESTS_PASSED")
    print("- placements: one open per employee, edit (start locked after accounts), end with date check, history kept")
    print("- agreements: validation, duplicate block, unlinked warning, auto-link to relationship, end")
    print("- engine uses the data: margin 1200; relationship end 15/03 -> 241.94; placement end 20/03 -> 193.55")
    print("- audit log has all 4 tables")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
