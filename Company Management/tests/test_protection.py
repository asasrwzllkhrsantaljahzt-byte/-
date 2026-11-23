"""Protection tests: approved transactions, month closing, append-only audit log.
Run:  py -3 tests\\test_protection.py
"""
import sys, types, tempfile, shutil, datetime, sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.dont_write_bytecode = True
D = datetime.date


class Stop(Exception):
    pass


class Fake:
    def __getattr__(self, n):
        return lambda *a, **k: Fake()
    def __iter__(self):
        return iter([])
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


SESSION, MSGS = {}, []


def install(inputs, submit):
    st = types.ModuleType("streamlit")
    st.session_state = SESSION

    def pick(opts, key):
        want = inputs.get(key)
        if want is None:
            return opts[0] if opts else None
        for o in opts:
            if str(want) in str(o):
                return o
        raise AssertionError(f"option '{want}' not found for {key}: {opts}")
    st.selectbox = lambda label, options, *a, key=None, **k: pick(list(options), key)
    st.text_input = lambda label, *a, key=None, **k: inputs.get(key, k.get("value", ""))
    st.checkbox = lambda label, *a, key=None, **k: inputs.get(key, False)
    st.button = lambda label, *a, **k: label == submit
    st.form_submit_button = lambda label, *a, **k: label == submit
    st.columns = lambda spec, *a, **k: [Fake() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs = lambda names: [Fake() for _ in names]
    st.form = lambda *a, **k: Fake()
    st.toast = lambda m, *a, **k: MSGS.append(("success", m))

    def rerun():
        raise Stop()
    st.rerun = rerun
    for n in ("success", "error", "warning", "info"):
        setattr(st, n, (lambda nn: (lambda m, *a, **k: MSGS.append((nn, m))))(n))
    for n in ("markdown", "caption", "dataframe", "subheader", "write", "metric"):
        setattr(st, n, lambda *a, **k: Fake())
    sys.modules["streamlit"] = st


def act(inputs=None, submit=None):
    MSGS.clear()
    install(inputs or {}, submit)
    for m in ("modules.review_close", "modules.transactions"):
        sys.modules.pop(m, None)
    import modules.review_close as rc
    try:
        rc.render()
    except Stop:
        pass
    return list(MSGS)


def has(msgs, kind, text):
    return any(k == kind and text in m for k, m in msgs)


def blocked(fn):
    try:
        fn()
    except sqlite3.IntegrityError:
        return True
    return False


def main():
    tmp = Path(tempfile.mkdtemp(prefix="cm_prot_"))
    (tmp / "database").mkdir()
    for f in ("schema.sql", "finance_schema.sql"):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db, finance_engine as fe
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    fe.BASE_DIR = tmp; fe.FINANCE_SCHEMA_PATH = tmp / "database/finance_schema.sql"
    db.init_db(); fe.ensure_finance_schema()

    co = db.execute("INSERT INTO companies(name) VALUES ('شركة')")
    emp = db.execute("INSERT INTO employees(full_name) VALUES ('موظف')")
    ct = db.execute("INSERT INTO contractors(name) VALUES ('متعهد')")
    rp = db.execute("INSERT INTO representatives(name) VALUES ('مندوب')")
    pid = db.execute("INSERT INTO employee_placements(employee_id,company_id,start_date,status) VALUES (?,?,?,?)", (emp, co, "2026-03-01", "active"))
    db.execute("INSERT INTO placement_contractors(placement_id,contractor_id,agreement_start,commission_type,commission_value) VALUES (?,?,?,?,?)", (pid, ct, "2026-03-01", "fixed", 300))
    db.execute("INSERT INTO placement_representatives(placement_id,representative_id,agreement_start,commission_type,commission_value) VALUES (?,?,?,?,?)", (pid, rp, "2026-03-01", "percentage", 10))

    def tx(month, cat, amt, status="approved", direction="in", date_="2026-03-05"):
        return db.execute("""INSERT INTO financial_transactions(tx_date,month_ref,placement_id,employee_id,company_id,category,direction,amount,review_status,source_type)
                             VALUES (?,?,?,?,?,?,?,?,?,'manual')""", (date_, month, pid, emp, co, cat, direction, amt, status))
    t_client = tx("2026-03", "client_agreed_amount", 5000)
    t_wage = tx("2026-03", "recorded_wage", 3000, direction="out")
    t_pend = tx("2026-03", "external_expense", 100, status="pending_review", direction="out")
    t_pend2 = tx("2026-03", "external_expense", 50, status="pending_review", direction="out")

    def margin():
        return {r["employee_name"]: r for r in fe.calculate_month("2026-03")}["موظف"]["company_margin"]
    assert margin() == 1200.0                                   # pending expense excluded

    # ---- DB-level protection of approved transactions
    assert blocked(lambda: db.execute("DELETE FROM financial_transactions WHERE id=?", (t_client,))), "approved delete allowed!"
    assert blocked(lambda: db.execute("UPDATE financial_transactions SET amount=1 WHERE id=?", (t_client,))), "approved amount edit allowed!"
    assert blocked(lambda: db.execute("UPDATE financial_transactions SET month_ref='2026-04' WHERE id=?", (t_client,)))
    assert blocked(lambda: db.execute("UPDATE financial_transactions SET review_status='pending_review' WHERE id=?", (t_client,)))
    db.execute("UPDATE financial_transactions SET description='ملاحظة' WHERE id=?", (t_client,))       # harmless text is allowed
    db.execute("UPDATE financial_transactions SET amount=120 WHERE id=?", (t_pend,))                    # pending can be edited
    db.execute("UPDATE financial_transactions SET amount=100 WHERE id=?", (t_pend,))
    assert db.query_one("SELECT COUNT(*) c FROM financial_transactions")["c"] == 4

    # ---- audit log is append-only
    db.execute("INSERT INTO audit_log(table_name,record_id,action) VALUES ('x',1,'INSERT')")
    assert blocked(lambda: db.execute("UPDATE audit_log SET note='x'"))
    assert blocked(lambda: db.execute("DELETE FROM audit_log"))

    # ---- UI: approve / reject / cancel
    m = act({"rc_tx_sel": f"#{t_pend} |", "rc_action": "approve"}, "تنفيذ الإجراء")
    assert db.query_one("SELECT review_status s FROM financial_transactions WHERE id=?", (t_pend,))["s"] == "approved"
    assert margin() == 1100.0                                   # approved expense now counts
    m = act({"rc_tx_sel": f"#{t_pend2} |", "rc_action": "reject", "rc_reason": ""}, "تنفيذ الإجراء")
    assert has(m, "error", "سبب") and db.query_one("SELECT review_status s FROM financial_transactions WHERE id=?", (t_pend2,))["s"] == "pending_review"
    m = act({"rc_tx_sel": f"#{t_pend2} |", "rc_action": "reject", "rc_reason": "مكرر"}, "تنفيذ الإجراء")
    assert db.query_one("SELECT review_status s FROM financial_transactions WHERE id=?", (t_pend2,))["s"] == "rejected"
    m = act({"rc_status_filter": "معتمدة", "rc_tx_sel": f"#{t_pend} |", "rc_action": "cancel", "rc_reason": ""}, "تنفيذ الإجراء")
    assert has(m, "error", "سبب")
    m = act({"rc_status_filter": "معتمدة", "rc_tx_sel": f"#{t_pend} |", "rc_action": "cancel", "rc_reason": "إدخال خاطئ"}, "تنفيذ الإجراء")
    row = db.query_one("SELECT review_status s, description d FROM financial_transactions WHERE id=?", (t_pend,))
    assert row["s"] == "rejected" and "إدخال خاطئ" in row["d"]
    assert margin() == 1200.0                                   # cancelled -> excluded again
    assert db.query_one("SELECT COUNT(*) c FROM financial_transactions")["c"] == 4   # nothing deleted
    aud = db.query_all("SELECT note FROM audit_log WHERE table_name='financial_transactions' AND action='STATUS_CHANGE'")
    assert len(aud) >= 3 and any("إدخال خاطئ" in (a["note"] or "") for a in aud)

    # ---- month closing
    m = act({"rc_close_month": "2026-03", "rc_close_confirm": False}, "اعتماد وإقفال الشهر")
    assert has(m, "error", "خانة التأكيد")
    assert db.query_one("SELECT COUNT(*) c FROM monthly_employee_accounts WHERE status='approved'")["c"] == 0
    m = act({"rc_close_month": "2026-03", "rc_close_confirm": True}, "اعتماد وإقفال الشهر")
    assert db.query_one("SELECT COUNT(*) c FROM monthly_employee_accounts WHERE status='approved'")["c"] == 1
    m = act({"rc_close_month": "2026-03"})
    assert has(m, "success", "تم اعتماد وإقفال")

    # closed month rejects everything
    assert blocked(lambda: tx("2026-03", "external_expense", 10)), "insert into closed month allowed!"
    assert blocked(lambda: db.execute("UPDATE financial_transactions SET description='x' WHERE id=?", (t_client,)))
    assert blocked(lambda: db.execute("UPDATE monthly_employee_accounts SET company_margin=999"))
    assert blocked(lambda: db.execute("DELETE FROM monthly_employee_accounts"))
    m = act({"rc_status_filter": "معتمدة", "rc_tx_sel": f"#{t_wage} |", "rc_action": "cancel", "rc_reason": "تجربة"}, "تنفيذ الإجراء")
    assert has(m, "error", "رفضت قاعدة البيانات"), m
    assert db.query_one("SELECT review_status s FROM financial_transactions WHERE id=?", (t_wage,))["s"] == "approved"
    tx("2026-04", "client_agreed_amount", 10, date_="2026-04-02")                     # other months stay open

    # recalculation must not overwrite the frozen month, even if agreements change
    db.execute("UPDATE placement_contractors SET commission_value=999")
    res = fe.calculate_month("2026-03")
    stored = db.query_one("SELECT company_margin m, status s FROM monthly_employee_accounts WHERE month_ref='2026-03'")
    assert stored["s"] == "approved" and float(stored["m"]) == 1200.0, stored
    assert res[0]["company_margin"] == 501.0

    # reopen
    m = act({"rc_close_month": "2026-03", "rc_reopen_reason": ""}, "إعادة فتح الشهر")
    assert has(m, "error", "سبب")
    m = act({"rc_close_month": "2026-03", "rc_reopen_reason": "تصحيح العمولة"}, "إعادة فتح الشهر")
    assert db.query_one("SELECT status s FROM monthly_employee_accounts WHERE month_ref='2026-03'")["s"] == "calculated"
    fe.calculate_month("2026-03")
    assert float(db.query_one("SELECT company_margin m FROM monthly_employee_accounts WHERE month_ref='2026-03'")["m"]) == 501.0
    tx("2026-03", "external_expense", 10)                                              # allowed again
    notes = [r["note"] for r in db.query_all("SELECT note FROM audit_log WHERE table_name='monthly_employee_accounts'")]
    assert any("اعتماد وإقفال" in n for n in notes) and any("تصحيح العمولة" in n for n in notes)

    print("PROTECTION_TESTS_PASSED")
    print("- approved transaction: delete/edit/move/un-approve all blocked by the database")
    print("- pending review: editable; approve/reject/cancel via UI, reasons required, nothing deleted")
    print("- audit log: append-only (update and delete blocked)")
    print("- month close: needs confirmation; closed month rejects inserts/updates/deletes")
    print("- frozen month survives recalculation (stored 1200.0 vs live 501.0 after agreement change)")
    print("- reopen needs a reason, then recalculation and new entries work again")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
