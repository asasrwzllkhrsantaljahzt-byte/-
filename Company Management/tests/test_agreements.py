"""Financial agreements + client->employee money cycle (مثال العربية). Run: py -3 tests\\test_agreements.py"""
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


def raises(text, fn):
    try:
        fn()
    except ValueError as e:
        assert text in str(e), (text, str(e)); return
    raise AssertionError("no error: " + text)


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_ag_"))
    (tmp / "database").mkdir()
    for f in ("schema.sql", "finance_schema.sql"):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db, finance_engine as fe, security as sec, app_settings as aps, vouchers as V, agreements as A
    import company_hub as H
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    fe.BASE_DIR = tmp; fe.FINANCE_SCHEMA_PATH = tmp / "database/finance_schema.sql"
    db.init_db(); fe.ensure_finance_schema(); fe.ensure_finance_schema(); sec.ensure_security_schema(); aps.ensure_settings_schema()
    H.ensure_hub_schema()
    V.ensure_vouchers_schema()
    D = datetime.date
    ar = db.execute("INSERT INTO companies(name) VALUES ('العربية')")
    other = db.execute("INSERT INTO companies(name) VALUES ('شركة أخرى')")
    hani = db.execute("INSERT INTO contractors(name) VALUES ('هاني')")
    must = db.execute("INSERT INTO contractors(name) VALUES ('مصطفى')")
    rep = db.execute("INSERT INTO representatives(name) VALUES ('المندوب')")
    pids, eids = [], []
    for i in (1, 2, 3):
        e = db.execute("INSERT INTO employees(full_name) VALUES (?)", (f"موظف {i}",)); eids.append(e)
        pids.append(db.execute("INSERT INTO employee_placements(employee_id,company_id,start_date,status) VALUES (?,?,'2026-03-01','active')", (e, ar)))
    for i, pid in enumerate(pids):
        for cat, d, amt, pt, ptid in (("client_agreed_amount", "in", 2000, "company", ar), ("recorded_wage", "out", 1000, "employee", eids[i]),
                                      ("refund_returned", "out", 300, "company", ar)):
            db.execute("""INSERT INTO financial_transactions(tx_date,month_ref,placement_id,employee_id,company_id,party_type,party_id,category,direction,amount,review_status,source_type)
                          VALUES ('2026-03-20','2026-03',?,?,?,?,?,?,?,?,'approved','manual')""", (pid, eids[i], ar, pt, ptid, cat, d, amt))

    # --- validation
    base = dict(beneficiary_type="contractor", beneficiary_id=hani, scope_type="group", method="per_employee", value=100, start_date="2026-03-01")
    raises("موظفاً واحداً", lambda: A.create_agreement(base, []))
    raises("أكبر من صفر", lambda: A.create_agreement(dict(base, value=0), [pids[0]]))
    raises("أساس", lambda: A.create_agreement(dict(base, method="percent"), [pids[0]]))
    raises("100%", lambda: A.create_agreement(dict(base, method="percent", percent_basis="agreed", value=101), [pids[0]]))
    raises("النهاية", lambda: A.create_agreement(dict(base, end_date="2026-02-01"), [pids[0]]))
    raises("المستفيد غير موجود", lambda: A.create_agreement(dict(base, beneficiary_id=999), [pids[0]]))

    # --- scenario 1: Hani 2 employees (100 each), Mustafa 1 (150), rep 50 per employee on the whole client
    a_h = A.create_agreement(base, [pids[0], pids[1]])
    a_m = A.create_agreement(dict(base, beneficiary_id=must, value=150), [pids[2]])
    a_r = A.create_agreement(dict(beneficiary_type="representative", beneficiary_id=rep, scope_type="client", company_id=ar,
                                  method="per_employee", value=50, start_date="2026-03-01"))
    raises("مطابق تماماً", lambda: A.create_agreement(dict(beneficiary_type="representative", beneficiary_id=rep, scope_type="client", company_id=ar,
                                                          method="per_employee", value=50, start_date="2026-03-15")))
    A.create_agreement(dict(beneficiary_type="representative", beneficiary_id=rep, scope_type="client", company_id=ar,
                            method="per_employee", value=75, start_date="2026-03-15", end_date="2026-03-20", notes="x"))   # different value is allowed
    db.execute("DELETE FROM fin_agreements WHERE value=75")
    res = {r["placement_id"]: r for r in fe.calculate_month("2026-03")}
    assert [res[p]["company_margin"] for p in pids] == [550, 550, 500], [res[p]["company_margin"] for p in pids]
    assert sum(r["company_margin"] for r in res.values()) == 1600
    n_log = len(db.query_all("SELECT * FROM agreement_calc_log"))
    fe.calculate_month("2026-03"); fe.calculate_month("2026-03")      # re-run: nothing duplicated
    assert len(db.query_all("SELECT * FROM agreement_calc_log")) == n_log == 6
    assert db.query_one("SELECT SUM(amount) s FROM party_dues WHERE party_type='contractor'")["s"] == 350
    assert db.query_one("SELECT SUM(amount) s FROM party_dues WHERE party_type='representative'")["s"] == 150
    assert "100 ريال" in db.query_one("SELECT detail FROM agreement_calc_log WHERE source_id=? AND source='fin_agreements'", (a_h,))["detail"]

    rel_c = [r["العلاقة"] for r in V.relations("company", ar)]
    assert any("اتفاق مالي" in x and "50" in x for x in rel_c), rel_c
    assert any("اتفاق مالي" in r["العلاقة"] for r in V.relations("representative", rep))
    assert any("اتفاق مالي" in r["العلاقة"] for r in V.relations("employee", eids[0]))
    import reporting as R
    cs = R.company_summary("2026-03")
    assert cs["revenue"] == 5100 and cs["refunds"] == 900 and cs["contractor_commissions"] == 350 and cs["representative_commissions"] == 150
    assert cs["net_margin"] == 1600 and cs["uncollected"] == 3000 and cs["unpaid"] == 350 + 150 + 900
    db.execute("""INSERT INTO financial_transactions(tx_date,month_ref,category,direction,amount,review_status,source_type)
                  VALUES ('2026-03-09','2026-03','external_expense','out',100,'approved','manual')""")
    assert R.company_summary("2026-03")["general_expenses"] == 100 and R.company_summary("2026-03")["net_margin"] == 1500
    # --- the money cycle: client paid the employee directly
    assert V.party_account("company", ar)["balance"] == -900            # we owe the client 3 x 300
    assert all(V.party_account("employee", e)["balance"] == -1000 for e in eids)   # each must return 1000
    V.issue_voucher("receipt", D(2026, 3, 28), "employee", eids[0], 1000, "cash")
    assert V.party_account("employee", eids[0])["balance"] == 0
    V.issue_voucher("payment", D(2026, 3, 29), "company", ar, 900, "transfer")
    assert V.party_account("company", ar)["balance"] == 0
    V.issue_voucher("payment", D(2026, 3, 30), "contractor", hani, 200, "cash")
    assert V.party_account("contractor", hani)["balance"] == 0

    # --- via_company flow keeps the old meaning (client owes us, we pay the employee)
    db.execute("UPDATE employee_placements SET flow_mode='via_company' WHERE id=?", (pids[1],))
    fe.calculate_month("2026-03")
    assert db.query_one("SELECT SUM(amount) s FROM party_dues WHERE party_type='employee' AND party_id=?", (eids[1],))["s"] == 1000
    db.execute("UPDATE employee_placements SET flow_mode='direct' WHERE id=?", (pids[1],))

    # --- scenario 2 (1 Hani + 2 Mustafa): margin 1550
    db.execute("UPDATE fin_agreements SET end_date=NULL, status='ended' WHERE id IN (?,?)", (a_h, a_m))
    A.create_agreement(dict(base, scope_type="placement", placement_id=pids[0]))
    A.create_agreement(dict(base, beneficiary_id=must, value=150, scope_type="group"), [pids[1], pids[2]])
    res = fe.calculate_month("2026-03")
    assert sum(r["company_margin"] for r in res) == 1550, sum(r["company_margin"] for r in res)

    # --- other methods: percent on surplus, client-level fixed split, no proration
    db.execute("UPDATE fin_agreements SET status='ended', end_date=NULL")
    a_p = A.create_agreement(dict(beneficiary_type="representative", beneficiary_id=rep, scope_type="client", company_id=ar,
                                  method="percent", percent_basis="surplus", value=10, start_date="2026-03-01"))
    r1 = {r["placement_id"]: r for r in fe.calculate_month("2026-03")}
    assert r1[pids[0]]["representative_entitlements_total"] == 70.0      # 10% of 700
    A.create_agreement(dict(beneficiary_type="contractor", beneficiary_id=hani, scope_type="client", company_id=ar,
                            method="fixed_monthly", value=100, start_date="2026-03-01"))
    r2 = fe.calculate_month("2026-03")
    assert round(sum(r["contractor_entitlements_total"] for r in r2), 2) == 100.0       # 100 split over 3 (33.34 + 33.33 + 33.33)
    # mid-month start is prorated by days; prorate=0 pays full month
    pm = db.execute("INSERT INTO employee_placements(employee_id,company_id,start_date,status) VALUES (?,?,'2026-03-16','active')", (eids[0], other))
    A.create_agreement(dict(beneficiary_type="contractor", beneficiary_id=must, scope_type="placement", placement_id=pm,
                            method="per_employee", value=310, start_date="2026-03-01"))
    r3 = {r["placement_id"]: r for r in fe.calculate_month("2026-03")}
    assert r3[pm]["contractor_entitlements_total"] == 160.0, r3[pm]       # 16/31 x 310
    db.execute("UPDATE fin_agreements SET prorate=0 WHERE scope_type='placement' AND placement_id=?", (pm,))
    assert {r["placement_id"]: r for r in fe.calculate_month("2026-03")}[pm]["contractor_entitlements_total"] == 310.0

    # --- preview, listing, history
    pv = A.preview(dict(beneficiary_type="representative", beneficiary_id=rep, scope_type="client", company_id=ar, method="per_employee",
                        value=25, start_date="2026-03-01"), [], "2026-03")
    assert pv["total"] == 75 and len(pv["rows"]) == 3
    assert len(A.list_agreements(beneficiary_type="representative", beneficiary_id=rep)) >= 2
    assert A.list_agreements(company_id=other)[0]["placement_id"] == pm
    assert A.calc_log("2026-03", "representative", rep)

    # --- history protection: used agreements cannot be deleted; unused can
    fe.calculate_month("2026-03")
    raises("ولا يُحذف", lambda: A.delete_agreement(a_p))
    fresh = A.create_agreement(dict(base, scope_type="placement", placement_id=pids[0], start_date="2027-01-01"))
    A.delete_agreement(fresh)
    raises("غير موجود", lambda: A.delete_agreement(fresh))
    pdict = dict(beneficiary_type="representative", beneficiary_id=rep, scope_type="client", company_id=ar,
                 method="percent", percent_basis="surplus", value=10, start_date="2026-03-01")
    raises("لا يمكن تغيير تاريخ بداية", lambda: A.update_agreement(a_p, dict(pdict, start_date="2026-02-01")))
    A.update_agreement(a_p, dict(pdict, value=12))
    A.end_agreement(a_p, D(2026, 3, 31))
    assert db.query_one("SELECT status FROM fin_agreements WHERE id=?", (a_p,))["status"] == "ended"

    # --- an approved month stays frozen when agreements change afterwards
    db.execute("UPDATE monthly_employee_accounts SET status='approved' WHERE month_ref='2026-03'")
    before = db.query_one("SELECT SUM(amount) s FROM party_dues WHERE month_ref='2026-03'")["s"]
    db.execute("UPDATE fin_agreements SET value=99 WHERE id=?", (a_p,))
    fe.calculate_month("2026-03")
    assert db.query_one("SELECT SUM(amount) s FROM party_dues WHERE month_ref='2026-03'")["s"] == before
    print("agreements tests OK")


if __name__ == "__main__":
    main()
