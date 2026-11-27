"""Party accounts + collections on the new engine. Run: py -3 tests\\test_hub_accounts.py"""
import sys, tempfile
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / "tests"))
from test_company_hub import _St, boot, raises, D


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_acc_"))
    db, fe = boot(tmp)
    db.init_db()
    import company_hub as H, hub_engine as E, vouchers as V, hub_accounts as HA
    H.ensure_hub_schema(); E.ensure_engine_schema(); V.ensure_vouchers_schema()

    co, _ = H.save_company(None, {"name": "المروة", "work_start_date": D(2026, 1, 1)})
    con = db.execute("INSERT INTO contractors(name) VALUES ('صفاء')")
    ext = db.execute("INSERT INTO contractors(name, kind) VALUES ('أبو سعد','external')")
    rep = db.execute("INSERT INTO representatives(name) VALUES ('مندوب')")
    H.set_rep(co, rep, 10, D(2026, 1, 1))
    terms = {"basic_salary": 2000, "actual_cost": 1700, "bonus": 1000, "contractor_id": con, "contractor_commission": 100,
             "external_id": ext, "external_commission": 50, "start_date": D(2026, 10, 1), "status": "active"}
    pid, _ = H.add_employee(co, {"full_name": "منال"}, terms)
    eid = H.get_placement(pid)["employee_id"]

    # no transfer: nothing due
    assert V.party_account("employee", eid)["due"] == 0
    # transfer 2000 for October: refund 300; returns 1000; contractor 100; external 50; net 550; rep 55
    E.add_transfer(pid, "2026-10", D(2026, 11, 2), 2000)
    a = V.party_account("company", co); assert a["due"] == 300 and a["balance"] == 300
    a = V.party_account("employee", eid); assert a["due"] == 1000 and a["balance"] == 1000
    assert V.party_account("contractor", con)["due"] == 100 and V.party_account("contractor", ext)["due"] == 50
    assert V.party_account("representative", rep)["due"] == 55

    # collections screen rows
    rows = HA.collection_rows("2026-10")
    assert len(rows) == 1 and rows[0]["owed"] == 1000 and rows[0]["collected"] == 0 and rows[0]["diff"] == 1000
    V.issue_voucher("receipt", D(2026, 11, 5), "employee", eid, 600, "cash", "", "2026-10", "", None)
    rows = HA.collection_rows("2026-10")
    assert rows[0]["collected"] == 600 and rows[0]["diff"] == 400
    a = V.party_account("employee", eid); assert a["settled"] == 600 and a["balance"] == 400
    assert "400.00" in V.balance_phrase("employee", a["balance"])
    # a receipt without a month counts in the month of its date -> not in October
    V.issue_voucher("receipt", D(2026, 11, 6), "employee", eid, 100, "cash", "", "", "", None)
    assert HA.collection_rows("2026-10")[0]["collected"] == 600

    # payments reduce what we owe
    V.issue_voucher("payment", D(2026, 11, 7), "contractor", con, 100, "transfer", "", "2026-10", "", None)
    assert V.party_account("contractor", con)["balance"] == 0
    V.issue_voucher("payment", D(2026, 11, 7), "company", co, 100, "transfer", "", "2026-10", "", None)
    assert V.party_account("company", co)["balance"] == 200
    # void removes it from the account
    vid = V.list_vouchers(party_type="company")[0]["id"]
    V.void_voucher(vid, "خطأ"); assert V.party_account("company", co)["balance"] == 300

    # party_balances by month
    b = {x["id"]: x for x in V.party_balances("contractor", "2026-10")}
    assert b[con]["due"] == 100 and b[con]["balance"] == 0 and b[ext]["balance"] == 50
    assert {x["id"]: x for x in V.party_balances("representative")}[rep]["due"] == 55

    # statement is chronological with a running balance
    st = V.statement_rows("employee", eid)
    assert st[0]["البيان"].startswith("مستحق شهر 2026-10") and st[-1]["الرصيد"] == 300, st

    # relations without the old agreement tables
    assert V.relations("company", co) and V.relations("contractor", con) and V.relations("representative", rep) and V.relations("employee", eid)
    print("test_hub_accounts: OK")


if __name__ == "__main__":
    main()
