"""Tests for the contracts page and the settings page (stub Streamlit).
Run:  py -3 tests\\test_contracts_settings.py
"""
import sys, types, tempfile, shutil, datetime, sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.dont_write_bytecode = True


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
            if str(want) == str(o):
                return o
        for o in opts:
            if str(want) in str(o):
                return o
        raise AssertionError(f"option '{want}' not found for {key}: {opts}")
    st.selectbox = lambda label, options, *a, key=None, **k: pick(list(options), key)
    st.text_input = lambda label, *a, key=None, value="", **k: inputs.get(key, value)
    st.text_area = lambda label, *a, key=None, value="", **k: inputs.get(key, value)
    st.number_input = lambda label, *a, key=None, value=0, **k: inputs.get(key, value)
    st.checkbox = lambda label, *a, key=None, value=False, **k: inputs.get(key, value)
    st.date_input = lambda label, *a, key=None, value=None, **k: inputs.get(key, value)
    st.form_submit_button = lambda label, *a, **k: label == submit
    st.button = lambda *a, **k: False

    st.columns = lambda spec, *a, **k: [Fake() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs = lambda names: [Fake() for _ in names]
    st.form = lambda *a, **k: Fake()
    st.toast = lambda m, *a, **k: MSGS.append(("success", m))
    st.dialog = lambda *a, **k: (lambda f: f)

    def rerun():
        raise Stop()
    st.rerun = rerun
    for n in ("success", "error", "warning", "info"):
        setattr(st, n, (lambda nn: (lambda m, *a, **k: MSGS.append((nn, m))))(n))
    for n in ("markdown", "caption", "dataframe", "subheader", "write"):
        setattr(st, n, lambda *a, **k: Fake())
    sys.modules["streamlit"] = st


def act(module, inputs=None, submit=None):
    MSGS.clear()
    install(inputs or {}, submit)
    sys.modules.pop("ui", None)
    sys.modules.pop(module, None)
    mod = __import__(module, fromlist=["render"])
    try:
        if module == "modules.contracts":
            (mod._tab_add if any(k.startswith("ct_add") for k in (inputs or {})) else mod._tab_edit)()
        else:
            mod.render()
    except Stop:
        pass
    return list(MSGS) + [("flash", v) for k, v in SESSION.items() if k.endswith("_flash")]


def has(msgs, kind, text):
    return any(k == kind and text in m for k, m in msgs)


def raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    return False


def main():
    install({}, None)
    tmp = Path(tempfile.mkdtemp(prefix="cm_ct_"))
    (tmp / "database").mkdir()
    for f in ("schema.sql",):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db, security as sec, app_settings as aps
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    db.init_db(); sec.ensure_security_schema()
    aps.ensure_settings_schema(); aps.ensure_settings_schema()
    sec.ITERATIONS = 2000
    from modules import contracts as _c  # noqa: F401
    D, today = datetime.date, datetime.date.today()
    day = lambda n: today + datetime.timedelta(days=n)

    co = db.execute("INSERT INTO companies(name) VALUES ('شركة اختبار')")
    ct = db.execute("INSERT INTO contractors(name) VALUES ('متعهد اختبار')")
    rp = db.execute("INSERT INTO representatives(name) VALUES ('مندوب اختبار')")
    emp = db.execute("INSERT INTO employees(full_name) VALUES ('موظف اختبار')")
    admin = {"id": 1, "username": "admin", "display_name": "م", "role": "admin", "can_view_sensitive": True}
    SESSION["auth_user"] = admin

    # ---- database-level protection (cannot be bypassed by any screen)
    import modules.contracts as C
    C.ensure_contracts_schema(); C.ensure_contracts_schema()                         # idempotent
    ins = "INSERT INTO contracts(contract_type, party_type, party_id, start_date, status) VALUES (?,?,?,?,?)"
    assert raises(sqlite3.IntegrityError, lambda: db.execute(ins, ("client", "company", 999, "2026-01-01", "active")))
    assert raises(sqlite3.IntegrityError, lambda: db.execute(ins, ("client", "contractor", ct, "2026-01-01", "active")))
    assert raises(sqlite3.IntegrityError, lambda: db.execute(ins, ("other", "ghost", 1, "2026-01-01", "active")))
    assert raises(sqlite3.IntegrityError, lambda: db.execute(ins, ("client", "company", co, "2026-01-01", "ended")))  # ended needs end date

    # ---- add through the UI
    base = {"ct_add_type": "client", "ct_add_party": f"{co} -", "ct_add_start": day(-30), "ct_add_has_end": True,
            "ct_add_end": day(10), "ct_add_status": "active", "ct_add_doc": "DOC-1"}
    act("modules.contracts", base, "حفظ العقد")
    row = db.query_one("SELECT * FROM contracts")
    assert row and row["party_type"] == "company" and row["document_ref"] == "DOC-1" and row["status"] == "active"
    assert db.query_one("SELECT COUNT(*) c FROM audit_log WHERE table_name='contracts' AND action='INSERT'")["c"] == 1

    # overlapping active contract for the same party is blocked; a non-overlapping one is allowed
    msgs = act("modules.contracts", {**base, "ct_add_start": day(0), "ct_add_end": day(100)}, "حفظ العقد")
    assert has(msgs, "error", "متداخل") and db.query_one("SELECT COUNT(*) c FROM contracts")["c"] == 1
    act("modules.contracts", {**base, "ct_add_start": day(11), "ct_add_end": day(100), "ct_add_doc": "DOC-2"}, "حفظ العقد")
    assert db.query_one("SELECT COUNT(*) c FROM contracts")["c"] == 2
    # end before start / missing end for ended
    msgs = act("modules.contracts", {**base, "ct_add_start": day(5), "ct_add_end": day(1), "ct_add_party": f"{co} -",
                                      "ct_add_type": "other", "ct_add_ptype": "company"}, "حفظ العقد")
    assert has(msgs, "error", "لا يسبق")
    # typed contract must match party kind (service layer)
    assert raises(ValueError, lambda: C.add_contract("contractor", "company", co, None, today, None, "active", "", "", ""))
    # contractor + representative + employee contracts
    act("modules.contracts", {"ct_add_type": "contractor", "ct_add_party": f"{ct} -", "ct_add_start": today}, "حفظ العقد")
    act("modules.contracts", {"ct_add_type": "representative", "ct_add_party": f"{rp} -", "ct_add_start": today, "ct_add_company": f"{co} -"}, "حفظ العقد")
    act("modules.contracts", {"ct_add_type": "employee", "ct_add_party": f"{emp} -", "ct_add_start": today, "ct_add_status": "draft"}, "حفظ العقد")
    assert db.query_one("SELECT COUNT(*) c FROM contracts")["c"] == 5
    assert db.query_one("SELECT company_id FROM contracts WHERE contract_type='representative'")["company_id"] == co

    # ---- expiry alerts
    al = C.expiry_alerts(days=30)
    assert [r["document_ref"] for r in al["soon"]] == ["DOC-1"] and al["overdue"] == []
    assert C.expiry_alerts(today=day(20), days=5)["overdue"][0]["document_ref"] == "DOC-1"
    assert C.expiry_alerts(days=5)["soon"] == []                                          # 10 days away, threshold 5

    # ---- edit / end / freeze
    first = row["id"]
    assert raises(sqlite3.IntegrityError, lambda: db.execute("DELETE FROM contracts WHERE id=?", (first,)))
    assert raises(sqlite3.IntegrityError, lambda: db.execute("UPDATE contracts SET party_id=? WHERE id=?", (999, first)))
    assert raises(sqlite3.IntegrityError, lambda: db.execute("UPDATE contracts SET contract_type='other' WHERE id=?", (first,)))
    act("modules.contracts", {"ct_edit_sel": f"#{first} |", "ct_edit_start": day(-30), "ct_edit_has_end": True,
                              "ct_edit_end": day(-1), "ct_edit_status": "ended", "ct_edit_notes": "أُنهي"}, "حفظ التعديل")
    r1 = db.query_one("SELECT * FROM contracts WHERE id=?", (first,))
    assert r1["status"] == "ended" and r1["end_date"] == day(-1).isoformat()
    assert db.query_one("SELECT COUNT(*) c FROM audit_log WHERE table_name='contracts' AND action='STATUS_CHANGE'")["c"] == 1
    # closed: cannot reopen or move dates (database), UI only edits notes
    assert raises(sqlite3.IntegrityError, lambda: db.execute("UPDATE contracts SET status='active' WHERE id=?", (first,)))
    assert raises(sqlite3.IntegrityError, lambda: db.execute("UPDATE contracts SET end_date='2030-01-01' WHERE id=?", (first,)))
    act("modules.contracts", {"ct_edit_sel": f"#{first} |", "ct_edit_status": "active", "ct_edit_notes": "ملاحظة جديدة",
                              "ct_edit_has_end": False}, "حفظ التعديل")
    r1 = db.query_one("SELECT * FROM contracts WHERE id=?", (first,))
    assert r1["status"] == "ended" and r1["notes"] == "ملاحظة جديدة" and r1["end_date"] == (day(-1)).isoformat()
    assert first not in [r["id"] for r in C.expiry_alerts(days=365)["soon"] + C.expiry_alerts(days=365)["overdue"]]

    # ---- read-only role cannot add
    SESSION["auth_user"] = {**admin, "role": "viewer"}
    n = db.query_one("SELECT COUNT(*) c FROM contracts")["c"]
    msgs = act("modules.contracts", {**base, "ct_add_doc": "X"}, "حفظ العقد")
    assert db.query_one("SELECT COUNT(*) c FROM contracts")["c"] == n and has(msgs, "info", "صلاحية")
    SESSION["auth_user"] = admin

    # ---- settings
    assert aps.get("org_name") == aps.DEFAULTS["org_name"] and aps.get_int("contract_alert_days") == 30
    good = {"set_org_name": "أساسات روز", "set_cr": "1010", "set_tax": "3000", "set_phone": "05", "set_addr": "وادي الدواسر",
            "set_alert_days": 45, "set_bk_days": 3, "set_contract_alerts": False}
    act("modules.settings_page", good, "حفظ الإعدادات")
    assert aps.get("org_name") == "أساسات روز" and aps.get_int("contract_alert_days") == 45 and aps.get_int("backup_reminder_days") == 3
    assert not aps.get_bool("contract_alerts_enabled")
    assert C.expiry_alerts()["days"] == 45                                              # setting is really used
    aud = db.query_one("SELECT * FROM audit_log WHERE table_name='app_settings' ORDER BY id DESC LIMIT 1")
    assert aud and aud["changed_by"] == "admin" and "أساسات روز" in aud["new_values"]
    n_aud = db.query_one("SELECT COUNT(*) c FROM audit_log")["c"]
    act("modules.settings_page", good, "حفظ الإعدادات")                                   # no change -> no audit noise
    assert db.query_one("SELECT COUNT(*) c FROM audit_log")["c"] == n_aud
    msgs = act("modules.settings_page", {**good, "set_org_name": "  "}, "حفظ الإعدادات")
    assert has(msgs, "error", "اسم المنشأة") and aps.get("org_name") == "أساسات روز"
    msgs = act("modules.settings_page", {**good, "set_alert_days": 0}, "حفظ الإعدادات")
    assert has(msgs, "error", "عدد الأيام") and aps.get_int("contract_alert_days") == 45
    msgs = act("modules.settings_page", {**good, "set_bk_days": 9999}, "حفظ الإعدادات")
    assert has(msgs, "error", "عدد الأيام") and aps.get_int("backup_reminder_days") == 3
    assert raises(ValueError, lambda: aps.save({**{k: v for k, v in aps.get_all().items()}, "org_name": "x" * 500}))
    db.execute("UPDATE app_settings SET value='abc' WHERE key='contract_alert_days'")      # corrupt value -> safe default
    assert aps.get_int("contract_alert_days") == 30
    # non-admin refused and nothing changes
    SESSION["auth_user"] = {**admin, "role": "accountant"}
    msgs = act("modules.settings_page", {**good, "set_org_name": "اختراق"}, "حفظ الإعدادات")
    assert has(msgs, "error", "لمدير النظام") and aps.get("org_name") == "أساسات روز"

    print("CONTRACTS_SETTINGS_TESTS_PASSED")
    print("- database triggers: missing/mismatched party, ended-without-date, delete, party change, reopen ended")
    print("- contracts UI: add 4 types, overlap blocked, date validation, end + freeze, audit rows")
    print("- expiry alerts: soon/overdue, honour the configurable threshold")
    print("- viewer cannot add; settings: save, validate, audited once, used by alerts, admin only")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
