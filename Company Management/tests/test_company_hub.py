"""Company hub: company data, representative terms, employees with financial terms, reset script.
Run:  py -3 tests\\test_company_hub.py
"""
import sys, types, tempfile, shutil, subprocess, sqlite3, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.dont_write_bytecode = True
D = datetime.date


class _St(types.ModuleType):
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
        return
    raise AssertionError(f"expected ValueError containing '{msg}'")


def boot(tmp):
    (tmp / "database").mkdir(exist_ok=True)
    for f in ("schema.sql",):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    return db, None


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_hub_"))
    db, fe = boot(tmp)
    db.init_db()
    import company_hub as H
    H.ensure_hub_schema()
    H.ensure_hub_schema()                      # idempotent

    # columns exist
    cols = {r["name"] for r in db.query_all("PRAGMA table_info(employee_placements)")}
    assert {"basic_salary", "actual_cost", "bonus", "contractor_id", "external_id"} <= cols
    assert "kind" in {r["name"] for r in db.query_all("PRAGMA table_info(contractors)")}

    # pure calc: the user's example 2000 / 1700 / 1000 / 100 / 50
    c = H.calc(2000, 1700, 1000, 100, 50)
    assert c == {"refund": 300.0, "net": 550.0}, c

    # ---- company
    raises("اسم الشركة مطلوب", lambda: H.save_company(None, {"name": " "}))
    raises("لا يسبق", lambda: H.save_company(None, {"name": "س", "work_start_date": D(2026, 5, 1), "work_end_date": D(2026, 4, 1)}))
    co, _ = H.save_company(None, {"name": "العلياء", "tax_number": "3000", "work_start_date": D(2026, 1, 1)})
    raises("بهذا الاسم", lambda: H.save_company(None, {"name": "العلياء"}))
    H.save_company(co, {"name": "العلياء", "tax_number": "3001", "phone": "055", "work_start_date": D(2026, 1, 1)})
    assert db.query_one("SELECT tax_number, phone FROM companies WHERE id=?", (co,)) == {"tax_number": "3001", "phone": "055"}

    # ---- contractors / external / reps
    con = db.execute("INSERT INTO contractors(name) VALUES ('صفاء')")                       # default kind
    ext = db.execute("INSERT INTO contractors(name, kind) VALUES ('أبو سعد', 'external')")
    assert db.query_one("SELECT kind FROM contractors WHERE id=?", (con,))["kind"] == "contractor"
    r1 = db.execute("INSERT INTO representatives(name) VALUES ('مندوب أ')")
    r2 = db.execute("INSERT INTO representatives(name) VALUES ('مندوب ب')")
    assert [x["id"] for x in H.contractors_of_kind("contractor")] == [con]
    assert [x["id"] for x in H.contractors_of_kind("external")] == [ext]

    # ---- representative terms: one at a time, history kept
    assert H.current_rep(co) is None
    raises("اختر المندوب", lambda: H.set_rep(co, None, 10, D(2026, 1, 1)))
    raises("بين 0 و100", lambda: H.set_rep(co, r1, 150, D(2026, 1, 1)))
    H.set_rep(co, r1, 10, D(2026, 1, 1))
    assert H.current_rep(co)["rep_name"] == "مندوب أ" and H.current_rep(co)["percent"] == 10
    H.set_rep(co, r2, 8, D(2026, 6, 1))                                   # replaces: A ends 31 May
    assert H.current_rep(co, D(2026, 5, 31))["rep_name"] == "مندوب أ"      # past month keeps the old rep and percent
    assert H.current_rep(co, D(2026, 6, 1))["rep_name"] == "مندوب ب"
    raises("أحدث", lambda: H.set_rep(co, r1, 5, D(2026, 6, 1)))
    assert sum(1 for t in H.rep_terms(co) if t["end_date"] is None) == 1
    H.end_rep(co, D(2026, 9, 30), "استقال")
    assert H.current_rep(co, D(2026, 10, 1)) is None
    raises("لا يوجد مندوب سارٍ", lambda: H.end_rep(co, D(2026, 10, 5)))
    H.set_rep(co, r1, 10, D(2026, 11, 1))

    # ---- employees
    good = {"basic_salary": 2000, "actual_cost": 1700, "bonus": 1000, "contractor_id": con, "contractor_commission": 100,
            "external_id": ext, "external_commission": 50, "start_date": D(2026, 10, 1), "status": "active"}
    emp = {"full_name": "منال", "phone": "0500", "national_id": "1000000001"}
    raises("اسم الموظف مطلوب", lambda: H.add_employee(co, {"full_name": ""}, good))
    raises("التكلفة الفعلية لا يمكن أن تزيد", lambda: H.add_employee(co, emp, {**good, "actual_cost": 2100}))
    raises("الراتب الأساسي", lambda: H.add_employee(co, emp, {**good, "basic_salary": 0}))
    raises("اختر المتعهد", lambda: H.add_employee(co, emp, {**good, "contractor_id": None}))
    raises("اختر جهة العمولة", lambda: H.add_employee(co, emp, {**good, "external_id": None}))
    raises("النوع الصحيح", lambda: H.add_employee(co, emp, {**good, "contractor_id": ext}))
    raises("النوع الصحيح", lambda: H.add_employee(co, emp, {**good, "external_id": con}))
    raises("تاريخ الاستبعاد", lambda: H.add_employee(co, emp, {**good, "status": "ended"}))
    raises("تسبق بداية عمل الشركة", lambda: H.add_employee(co, emp, {**good, "start_date": D(2025, 12, 1)}))
    assert db.query_one("SELECT COUNT(*) c FROM employees")["c"] == 0, "failed adds must not leave employees behind"
    pid, _ = H.add_employee(co, emp, good)
    raises("مسجل مسبقاً", lambda: H.add_employee(co, {"full_name": "ثانية", "national_id": "1000000001"}, good))
    raises("نشط حالياً", lambda: H.add_employee(co, {"full_name": "منال ٢"}, good, existing_employee_id=db.query_one("SELECT employee_id e FROM employee_placements WHERE id=?", (pid,))["e"]))
    rows = H.company_employees(co)
    assert len(rows) == 1 and rows[0]["refund"] == 300 and rows[0]["net"] == 550
    assert rows[0]["contractor_name"] == "صفاء" and rows[0]["external_name"] == "أبو سعد"

    # commission without a person is dropped; no contractor -> 0
    p2, _ = H.add_employee(co, {"full_name": "نورة"}, {**good, "contractor_id": None, "contractor_commission": 0,
                                                       "external_id": None, "external_commission": 0, "bonus": 1000})
    r2row = H.get_placement(p2)
    assert r2row["contractor_commission"] == 0 and H.calc(2000, 1700, 1000, 0, 0)["net"] == 700
    p3, _ = H.add_employee(co, {"full_name": "هند"}, good)

    # expected totals: 550 + 700 + 550 = 1800, rep 10% = 180, margin 1620
    ex = H.company_expected(co)
    assert ex["employees"] == 3 and ex["net"] == 1800 and ex["rep_amount"] == 180 and ex["margin"] == 1620, ex
    assert ex["refund"] == 900 and ex["revenue"] == 5100 and ex["contractors"] == 200 and ex["external"] == 100

    # warning for negative net
    assert H.terms_warnings({**good, "bonus": 1700})

    # ---- update + exclude
    H.update_employee(pid, {"full_name": "منال المحمد", "phone": "0511", "national_id": "1000000001"}, {**good, "bonus": 900})
    assert H.get_placement(pid)["full_name"] == "منال المحمد" and H.get_placement(pid)["bonus"] == 900
    raises("لا يسبق", lambda: H.exclude_employee(pid, D(2026, 9, 1)))
    H.exclude_employee(pid, D(2026, 10, 20), "استقالة")
    r = H.get_placement(pid)
    assert r["status"] == "ended" and r["end_date"] == "2026-10-20"
    assert H.company_expected(co)["employees"] == 2                         # excluded one leaves the expected totals
    assert len(H.company_employees(co, "ended")) == 1 and len(H.company_employees(co, "active")) == 2

    # excluded employee can be placed again elsewhere (existing employee)
    co2, _ = H.save_company(None, {"name": "المروة"})
    eid = r["employee_id"]
    assert eid in [x["id"] for x in H.available_employees()]
    p4, _ = H.add_employee(co2, {}, {**good, "start_date": D(2026, 11, 1)}, existing_employee_id=eid)
    assert db.query_one("SELECT COUNT(*) c FROM employee_placements WHERE employee_id=?", (eid,))["c"] == 2

    # ---- delete rules
    import hub_engine as _E
    _E.ensure_engine_schema()
    _E.add_transfer(p3, "2026-10", D(2026, 11, 2), 100)
    raises("لا يمكن الحذف", lambda: H.delete_employee_placement(p3))
    H.delete_employee_placement(p2)
    assert H.get_placement(p2) is None
    assert db.query_one("SELECT COUNT(*) c FROM employees WHERE full_name='نورة'")["c"] == 0
    raises("لا يمكن حذف الشركة", lambda: H.delete_company(co))
    co3, _ = H.save_company(None, {"name": "فارغة"})
    H.delete_company(co3)
    assert db.query_one("SELECT 1 FROM companies WHERE name='فارغة'") is None

    # ---- reset script: wipes the test data, keeps users + settings, triggers come back
    import security, app_settings, invoicing, documents, vouchers
    from modules import contracts
    security.ensure_security_schema(); app_settings.ensure_settings_schema()
    db.execute("INSERT INTO users(username, display_name, password_hash, role) VALUES ('hani','هاني','x','admin')")
    before_users = db.query_one("SELECT COUNT(*) c FROM users")["c"]
    shutil.copy2(BASE / "تصفير_بيانات_التجربة.py", tmp / "reset.py")
    out = subprocess.run([sys.executable, "-I", str(tmp / "reset.py"), "--yes"], capture_output=True, text=True, cwd=str(tmp))
    assert out.returncode == 0, out.stdout + out.stderr
    for t in ("companies", "employees", "employee_placements", "client_transfers", "contractors", "representatives",
              "company_rep_terms", "audit_log"):
        assert db.query_one(f"SELECT COUNT(*) c FROM {t}")["c"] == 0, t
    assert db.query_one("SELECT COUNT(*) c FROM users")["c"] == before_users
    assert list((tmp / "database").glob("app_قبل_التصفير_*.db")), "backup missing"
    contracts.ensure_contracts_schema(); invoicing.ensure_invoice_schema(); H.ensure_hub_schema(); _E.ensure_engine_schema()
    documents.ensure_documents_schema(); vouchers.ensure_vouchers_schema()
    trg = {r["name"] for r in db.query_all("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert "trg_ct_no_delete" in trg and "trg_vouchers_no_delete" in trg, "protections not restored"
    # and the app works again from empty
    c9, _ = H.save_company(None, {"name": "جديدة"})
    assert c9 == 1

    print("test_company_hub: OK")


if __name__ == "__main__":
    main()
