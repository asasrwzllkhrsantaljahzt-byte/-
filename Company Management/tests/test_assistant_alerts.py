"""Offline assistant + notification bell. Run: py -3 tests\\test_assistant_alerts.py"""
import sys, tempfile
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / "tests"))
from test_company_hub import _St, boot, raises, D


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_ast_"))
    db, fe = boot(tmp)
    db.init_db()
    import company_hub as H, hub_engine as E, vouchers as V, assistant as A, alerts as AL, app_settings as aps, security as sec
    aps.ensure_settings_schema(); H.ensure_hub_schema(); E.ensure_engine_schema(); V.ensure_vouchers_schema()
    co, _ = H.save_company(None, {"name": "المروة", "work_start_date": D(2026, 1, 1)})
    con = db.execute("INSERT INTO contractors(name) VALUES ('صفاء')")
    rep = db.execute("INSERT INTO representatives(name) VALUES ('خالد')")
    H.set_rep(co, rep, 10, D(2026, 1, 1))
    terms = {"basic_salary": 2000, "actual_cost": 1700, "bonus": 1000, "contractor_id": con, "contractor_commission": 100,
             "start_date": D(2026, 10, 1), "status": "active"}
    p1, _ = H.add_employee(co, {"full_name": "منال"}, terms)
    p2, _ = H.add_employee(co, {"full_name": "نورة"}, terms)
    E.add_transfer(p1, "2026-10", D(2026, 11, 3), 1000)
    today = D(2026, 11, 18)

    assert A.parse_month("صافي اكتوبر", today) == "2026-10" and A.parse_month("2026-9", today) == "2026-09"
    assert A.parse_month("الشهر الماضي", today) == "2026-10" and A.parse_month("هذا الشهر", today) == "2026-11"
    a = A.answer("كم صافي أكتوبر؟", today)
    assert "352.94" in a and "317.65" in a, a                       # the user's example numbers
    assert "منال" in A.answer("كم تعيد منال في 2026-10", today) and "411.76" in A.answer("كم تعيد منال في 2026-10", today)
    assert "نورة" in A.answer("مين لم يحول لها اكتوبر", today) and "منال" not in A.answer("مين لم يحول لها اكتوبر", today)
    assert "المروة" in A.answer("كم هامش المروة في اكتوبر", today)
    assert "100.00" in A.answer("كم مستحق صفاء", today) or "58.82" in A.answer("كم مستحق صفاء", today)
    assert "إغلاق" not in A.answer("كيف اقفل الشهر", today) and "مراجعة وإقفال" in A.answer("كيف اقفل الشهر", today)
    assert "استيراد" in A.answer("كيف اضيف موظفين بالاكسل", today)
    assert "النسبة" in A.answer("كيف يحسب الشهر", today)
    assert "لم أفهم" in A.answer("طقس اليوم", today) and A.answer("   ", today)
    n_emp = A.answer("كم عدد الموظفات", today); assert "2" in n_emp
    before = db.query_one("SELECT COUNT(*) c FROM client_transfers")["c"]; A.answer("سجل تحويل", today)
    assert db.query_one("SELECT COUNT(*) c FROM client_transfers")["c"] == before            # never acts

    # bell
    items = AL.collect(today)
    texts = " | ".join(i["text"] for i in items)
    assert any(i["page"] == "مراجعة وإقفال الشهر" for i in items), texts                    # October not closed
    assert any("بلا أي تحويل" in i["text"] for i in items), texts                           # Norah has none
    assert any(i["page"] == "النسخ الاحتياطي والاستعادة" for i in items)
    assert not any(i["page"] == "التحصيل والمدفوعات" for i in items)                         # too early
    assert any(i["page"] == "التحصيل والمدفوعات" for i in AL.collect(D(2026, 12, 5)))      # >30 days after month end
    E.close_month("2026-10")
    assert not any(i["page"] == "مراجعة وإقفال الشهر" for i in AL.collect(today))
    # contract + document alerts
    from modules import contracts as C
    db.execute("INSERT INTO contracts(contract_type, party_type, party_id, start_date, end_date, status) VALUES ('client','company',?,?,?,'active')",
               (co, "2026-01-01", "2026-11-25"))
    assert any(i["page"] == "العقود" for i in AL.collect(today))
    print("test_assistant_alerts: OK")


if __name__ == "__main__":
    main()
