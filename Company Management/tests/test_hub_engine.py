"""Calculation on actual client transfers. Run: py -3 tests\\test_hub_engine.py"""
import sys, types, tempfile, sqlite3
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / "tests"))
from test_company_hub import _St, boot, raises, D


def near(a, b, tol=0.011):
    assert abs(a - b) <= tol, (a, b)


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_eng_"))
    db, fe = boot(tmp)
    db.init_db()
    import company_hub as H, hub_engine as E
    H.ensure_hub_schema(); E.ensure_engine_schema()

    co, _ = H.save_company(None, {"name": "المروة", "work_start_date": D(2026, 1, 1)})
    con = db.execute("INSERT INTO contractors(name) VALUES ('صفاء')")
    rep = db.execute("INSERT INTO representatives(name) VALUES ('مندوب')")
    H.set_rep(co, rep, 10, D(2026, 1, 1))
    terms = {"basic_salary": 2000, "actual_cost": 1700, "bonus": 1000, "contractor_id": con, "contractor_commission": 100,
             "start_date": D(2026, 10, 1), "status": "active"}
    pid, _ = H.add_employee(co, {"full_name": "منال"}, terms)

    # nothing transferred -> everything zero but the month exists
    m = E.compute_month("2026-10")
    row = m["companies"][0]["employees"][0]
    assert row["transferred"] == 0 and row["net"] == 0 and row["ratio"] == 0 and m["totals"]["not_transferred"] == 1
    assert row["cost_eff"] == 1700 and row["expected_net"] == 600

    # the user's example: client transferred 1000 of a 1700 cost
    E.add_transfer(pid, "2026-10", D(2026, 11, 3), 1000)
    c = E.compute_month("2026-10")["companies"][0]
    r = c["employees"][0]
    near(r["ratio"], 1000 / 1700, 1e-6)
    assert r["refund"] == 0
    near(r["revenue"], 1000); near(r["bonus_due"], 588.24); near(r["contractor_due"], 58.82)
    near(r["net"], 352.94); near(r["employee_returns"], 411.76)
    near(c["rep_due"], 35.29); near(c["margin"], 317.65)           # 10% of net, rest is the company's profit

    # second installment: totals accumulate on the same work month, paid late, different date
    E.add_transfer(pid, "2026-10", D(2026, 12, 20), 1000)         # total 2000 > cost 1700 -> refund 300
    c = E.compute_month("2026-10")["companies"][0]
    r = c["employees"][0]
    assert r["ratio"] == 1 and r["refund"] == 300 and r["revenue"] == 1700
    assert r["bonus_due"] == 1000 and r["contractor_due"] == 100 and r["net"] == 600 and r["employee_returns"] == 1000
    assert c["rep_due"] == 60 and c["margin"] == 540

    # transfers between cost and basic: refund is just the surplus
    pid2, _ = H.add_employee(co, {"full_name": "نورة"}, {**terms})
    _, _, w = E.add_transfer(pid2, "2026-10", D(2026, 10, 25), 1850)
    assert not w
    r2 = [x for x in E.compute_month("2026-10")["companies"][0]["employees"] if x["placement_id"] == pid2][0]
    assert r2["refund"] == 150 and r2["net"] == 600
    # over the basic salary -> warning but allowed
    _, _, w = E.add_transfer(pid2, "2026-10", D(2026, 10, 26), 300)
    assert w and any("أكبر من راتبه" in x for x in E.compute_month("2026-10")["warnings"])

    # validation
    raises("أكبر من صفر", lambda: E.add_transfer(pid, "2026-10", D(2026, 10, 1), 0))
    raises("صيغة الشهر", lambda: E.add_transfer(pid, "10-2026", D(2026, 10, 1), 10))
    raises("لا عمل له", lambda: E.add_transfer(pid, "2026-09", D(2026, 10, 1), 10))     # before his start
    raises("اختر الموظف", lambda: E.add_transfer(None, "2026-10", D(2026, 10, 1), 10))

    # void needs a reason, voided money no longer counts, never deleted
    tid = E.list_transfers("2026-10", co)[0]["id"]
    raises("اكتب سبب", lambda: E.void_transfer(tid, " "))
    E.void_transfer(tid, "خطأ في المبلغ")
    raises("ملغى مسبقاً", lambda: E.void_transfer(tid, "x"))
    try:
        db.execute("DELETE FROM client_transfers WHERE id=?", (tid,)); raise AssertionError("delete must be blocked")
    except sqlite3.IntegrityError as ex:
        assert "لا تُحذف" in str(ex)
    assert len(E.list_transfers("2026-10", co, "void")) == 1
    raises("الملغى لا يُعدَّل", lambda: E.update_transfer(tid, "2026-10", D(2026, 10, 1), 5))

    # update
    live = [t for t in E.list_transfers("2026-10", co) if t["placement_id"] == pid][0]
    E.update_transfer(live["id"], "2026-10", D(2026, 11, 4), 500, "تعديل")
    assert E.transferred_so_far(pid, "2026-10") == sum(t["amount"] for t in E.list_transfers("2026-10", co) if t["placement_id"] == pid)

    # bulk is all-or-nothing
    pid3, _ = H.add_employee(co, {"full_name": "هند"}, terms)
    before = len(E.list_transfers(None, co, "all"))
    raises("لا عمل له", lambda: E.add_bulk("2026-09", D(2026, 10, 1), {pid3: 500}))
    raises("لم تُدخل", lambda: E.add_bulk("2026-10", D(2026, 10, 1), {pid3: 0, pid: None}))
    n, _ = E.add_bulk("2026-10", D(2026, 10, 30), {pid3: 1700})
    assert n == 1 and len(E.list_transfers(None, co, "all")) == before + 1

    # proration: starts mid month / is excluded mid month (actual days of the month)
    pid4, _ = H.add_employee(co, {"full_name": "جود"}, {**terms, "start_date": D(2026, 11, 16)})   # 15 of 30 days
    E.add_transfer(pid4, "2026-11", D(2026, 11, 30), 850)
    r4 = [x for x in E.compute_month("2026-11")["companies"][0]["employees"] if x["placement_id"] == pid4][0]
    assert r4["days"] == 15 and r4["month_days"] == 30
    near(r4["cost_eff"], 850); near(r4["bonus_eff"], 500); near(r4["contractor_eff"], 50)
    assert r4["ratio"] == 1 and r4["refund"] == 0 and r4["net"] == 300
    H.exclude_employee(pid3, D(2026, 10, 10), "استقالة")                                    # 10 of 31 days in October
    r3 = [x for x in E.compute_month("2026-10")["companies"][0]["employees"] if x["placement_id"] == pid3][0]
    assert r3["days"] == 10
    near(r3["cost_eff"], 1700 * 10 / 31)
    assert r3["refund"] > 0                                                                  # 1700 paid for a 548.39 cost -> surplus to client
    assert not [x for x in E.compute_month("2026-11")["companies"][0]["employees"] if x["placement_id"] == pid3]   # gone after exclusion

    # rep changes: past months keep the old percentage
    H.set_rep(co, rep, 20, D(2026, 11, 1))
    assert E.compute_month("2026-10")["companies"][0]["rep_percent"] == 10
    assert E.compute_month("2026-11")["companies"][0]["rep_percent"] == 20
    H.end_rep(co, D(2026, 11, 30), "استقال")
    assert E.compute_month("2026-12") ["companies"] == [] or E.compute_month("2026-12")["companies"][0]["rep_percent"] == 0

    # company stops working: its employees stop counting that month
    co2, _ = H.save_company(None, {"name": "قصيرة", "work_end_date": D(2026, 10, 15)})
    p5, _ = H.add_employee(co2, {"full_name": "ريم"}, {**terms, "contractor_id": None, "contractor_commission": 0})
    r5 = [x for x in E.compute_month("2026-10")["companies"] if x["company_id"] == co2][0]["employees"][0]
    assert r5["days"] == 15
    assert not [x for x in E.compute_month("2026-11")["companies"] if x["company_id"] == co2]

    # negative company net never produces a negative commission
    co3, _ = H.save_company(None, {"name": "خاسرة"})
    H.set_rep(co3, rep, 10, D(2026, 1, 1))
    p6, _ = H.add_employee(co3, {"full_name": "وفاء"}, {**terms, "bonus": 1700, "contractor_commission": 100})
    E.add_transfer(p6, "2026-10", D(2026, 10, 30), 1700)
    c6 = [x for x in E.compute_month("2026-10")["companies"] if x["company_id"] == co3][0]
    assert c6["net"] == -100 and c6["rep_due"] == 0 and c6["margin"] == -100

    # filter by company + month options
    assert [c["company_id"] for c in E.compute_month("2026-10", co3)["companies"]] == [co3]
    assert "2026-10" in E.month_options() and E.month_options()[0] >= "2026-10"
    print("test_hub_engine: OK")


if __name__ == "__main__":
    main()
