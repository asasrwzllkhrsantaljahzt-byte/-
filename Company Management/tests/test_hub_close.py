"""Month review, closing/reopening, reports datasets, PDF. Run: py -3 tests\\test_hub_close.py"""
import sys, tempfile
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / "tests"))
from test_company_hub import _St, boot, raises, D


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_close_"))
    db, fe = boot(tmp)
    db.init_db()
    import company_hub as H, hub_engine as E, vouchers as V, hub_close as C, exports as X
    H.ensure_hub_schema(); E.ensure_engine_schema(); E.ensure_engine_schema(); V.ensure_vouchers_schema()
    co, _ = H.save_company(None, {"name": "المروة", "work_start_date": D(2026, 1, 1)})
    con = db.execute("INSERT INTO contractors(name) VALUES ('صفاء')")
    rep = db.execute("INSERT INTO representatives(name) VALUES ('مندوب')")
    H.set_rep(co, rep, 10, D(2026, 1, 1))
    terms = {"basic_salary": 2000, "actual_cost": 1700, "bonus": 1000, "contractor_id": con, "contractor_commission": 100,
             "start_date": D(2026, 10, 1), "status": "active"}
    p1, _ = H.add_employee(co, {"full_name": "منال"}, terms)
    p2, _ = H.add_employee(co, {"full_name": "نورة"}, terms)

    raises("لا توجد بيانات", lambda: E.close_month("2026-09"))
    rv = C.review("2026-10")
    assert not rv["blocking"] and sum(1 for l, _ in rv["items"] if l == "warn") == 2        # both without transfers
    E.add_transfer(p1, "2026-10", D(2026, 11, 1), 1000)       # ratio 1000/1700
    E.add_transfer(p2, "2026-10", D(2026, 11, 1), 2000)
    live = E.compute_month("2026-10")
    assert live["closed"] is False
    net_live = live["totals"]["net"]

    msg = E.close_month("2026-10")
    assert E.is_closed("2026-10")
    raises("مقفل", lambda: E.close_month("2026-10"))
    raises("مقفل", lambda: E.add_transfer(p1, "2026-10", D(2026, 11, 2), 100))
    tid = db.query_one("SELECT id FROM client_transfers LIMIT 1")["id"]
    raises("مقفل", lambda: E.void_transfer(tid, "x"))
    raises("مقفل", lambda: E.update_transfer(tid, "2026-10", D(2026, 11, 2), 5))
    raises("مقفل", lambda: E.add_bulk("2026-10", D(2026, 11, 2), {p1: 10}))

    # frozen: changing the employee's terms afterwards does not move the closed month
    H.update_employee(p1, {"full_name": "منال"}, {**terms, "bonus": 500})
    snap = E.compute_month("2026-10")
    assert snap["closed"] and snap["totals"]["net"] == net_live
    assert E.compute_month("2026-10", co)["totals"]["net"] == net_live and E.compute_month("2026-10", 999)["totals"]["net"] == 0
    # accounts use the snapshot too
    import hub_accounts as HA
    assert HA.dues_of("representative", rep)["2026-10"] == snap["companies"][0]["rep_due"]
    # other months still live and open
    E.add_transfer(p1, "2026-11", D(2026, 11, 20), 100)

    raises("سبب", lambda: E.reopen_month("2026-10", " "))
    E.reopen_month("2026-10", "تصحيح")
    assert not E.is_closed("2026-10") and E.compute_month("2026-10")["totals"]["net"] != net_live   # bonus 500 now counts
    assert [r["action"] for r in E.closure_log("2026-10")] == ["reopen", "close"]
    raises("غير مقفل", lambda: E.reopen_month("2026-10", "x"))
    E.add_transfer(p1, "2026-10", D(2026, 11, 3), 10)

    # report datasets
    res = E.compute_month("2026-10")
    assert len(C.companies_df(res)) == 1 and len(C.employees_df(res)) == 2 and len(C.totals_df(res)) == 11
    assert C.year_df(2026)["الشهر"].tolist() == ["2026-10", "2026-11"]
    V.issue_voucher("payment", D(2026, 11, 5), "other", None, 50, other_name="مصروف تشغيل",
                    entry_category="operating_expense")
    V.issue_voucher("payment", D(2026, 11, 5), "other", None, 20, other_name="مسحوبات المالك",
                    entry_category="owner_draw")
    annual = C.year_df(2026).set_index("الشهر")
    assert annual.loc["2026-11", "المصروفات التشغيلية"] == 50
    assert annual.loc["2026-11", "مسحوبات المالك (تسوية سنوية)"] == 20
    assert annual.loc["2026-11", "صافي الربح بعد المصروفات"] == round(annual.loc["2026-11", "هامش الشركة قبل المصروفات"] - 50, 2)
    from modules import dashboard
    dashboard._months_chart("2026-11")
    V.issue_voucher("payment", D(2026, 11, 5), "contractor", con, 50)
    bal = C.balances_df("2026-10")
    assert not bal.empty and set(bal.columns) == {"النوع", "الاسم", "المستحق", "المسدَّد", "المتبقي"}
    assert X.export_excel({"أ": C.companies_df(res)})[:2] == b"PK"
    ok, why = X.pdf_available()
    if ok:
        assert X.table_pdf("تقرير", [("الشركات", C.companies_df(res)), ("الموظفات", C.employees_df(res))], "شهر 2026-10")[:4] == b"%PDF"
    print("test_hub_close: OK", "(pdf skipped: %s)" % why if not ok else "")


if __name__ == "__main__":
    main()
