"""Security tests: login, lockout, roles, last-admin guard, audit redaction, sensitive-data masking.
Run:  py -3 tests\\test_security.py
"""
import sys, types, tempfile, shutil, sqlite3
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


SESSION, MSGS, CALLS = {}, [], []


def install(inputs, submit):
    st = types.ModuleType("streamlit")
    st.session_state = SESSION

    def val(label, key, default):
        if key in inputs:
            return inputs[key]
        if label in inputs:
            return inputs[label]
        return default
    def text_input(label, value="", key=None, type=None, disabled=False, help=None, **k):
        CALLS.append((label, value, disabled))
        return val(label, key, value)
    def selectbox(label, options, index=0, key=None, format_func=None, disabled=False, **k):
        options = list(options)
        want = inputs.get(key)
        if want is not None:
            for o in options:
                if str(want) in str(o):
                    return o
            raise AssertionError(f"option '{want}' not found for {key}: {options}")
        return options[index or 0] if options else None
    st.text_input = text_input
    st.text_area = lambda label, value="", key=None, **k: val(label, key, value)
    st.selectbox = selectbox
    st.checkbox = lambda label, value=False, key=None, **k: val(label, key, value)
    st.form_submit_button = lambda label, *a, **k: label == submit
    st.button = lambda label, *a, **k: label == submit
    st.columns = lambda spec, *a, **k: [Fake() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs = lambda names: [Fake() for _ in names]
    st.form = lambda *a, **k: Fake()
    st.toast = lambda m, *a, **k: MSGS.append(("success", m))

    def stop():
        raise Stop()
    st.stop = stop
    st.rerun = stop
    for n in ("success", "error", "warning", "info"):
        setattr(st, n, (lambda nn: (lambda m, *a, **k: MSGS.append((nn, m))))(n))
    for n in ("markdown", "caption", "dataframe", "subheader", "write", "metric", "json", "code", "image"):
        setattr(st, n, lambda *a, **k: Fake())
    sys.modules["streamlit"] = st


def run(fn, inputs=None, submit=None, modules=()):
    MSGS.clear(); CALLS.clear()
    install(inputs or {}, submit)
    for m in modules:
        sys.modules.pop(m, None)
    try:
        return fn()
    except Stop:
        return "STOPPED"


def has(kind, text):
    return any(k == kind and text in m for k, m in MSGS)


def raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    return False


def main():
    install({}, None)                       # keep the real streamlit out of this test
    tmp = Path(tempfile.mkdtemp(prefix="cm_sec_"))
    (tmp / "database").mkdir()
    for f in ("schema.sql",):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db, security as sec
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    db.init_db(); sec.ensure_security_schema(); sec.ensure_security_schema()
    sec.ITERATIONS = 2000                   # fast hashing for tests only

    # ---------- passwords
    h1, h2 = sec.hash_password("Secret#2026"), sec.hash_password("Secret#2026")
    assert h1 != h2 and h1.startswith("pbkdf2_sha256$2000$")
    assert sec.verify_password("Secret#2026", h1) and not sec.verify_password("secret#2026", h1)
    assert not sec.verify_password("x", "garbage") and "Secret" not in h1
    assert sec.validate_password("short1", "u") and sec.validate_password("12345678", "u") and sec.validate_password("password1", "u")
    assert sec.validate_password("Owner-Name", "owner-name") and sec.validate_password("Good#Pass9", "u") == ""
    assert sec.validate_username("ab") and sec.validate_username("ali baba") and sec.validate_username("ali.b-1") == ""

    # ---------- first-run setup through the UI gate
    import modules.auth_ui as _  # noqa: F401  (imported fresh inside run)
    gate = lambda: __import__("modules.auth_ui", fromlist=["gate"]).gate()
    mods = ("modules.auth_ui",)
    assert not sec.has_users()
    assert run(gate, modules=mods) == "STOPPED" and "auth_user" not in SESSION          # setup screen, nobody logged in
    run(gate, {"setup_user": "owner", "setup_display": "المالك", "setup_pw1": "Owner#Pass1", "setup_pw2": "Different#1"},
        "إنشاء حساب المدير وبدء الاستخدام", mods)
    assert has("error", "غير متطابقتين") and not sec.has_users()
    run(gate, {"setup_user": "owner", "setup_display": "المالك", "setup_pw1": "password1", "setup_pw2": "password1"},
        "إنشاء حساب المدير وبدء الاستخدام", mods)
    assert has("error", "شائعة") and not sec.has_users()
    run(gate, {"setup_user": "owner", "setup_display": "المالك", "setup_pw1": "Owner#Pass1", "setup_pw2": "Owner#Pass1"},
        "إنشاء حساب المدير وبدء الاستخدام", mods)
    assert sec.has_users() and SESSION["auth_user"]["role"] == "admin"
    SESSION.clear()

    # ---------- users + roles
    acc = sec.create_user("acc1", "المحاسب", "Acc#Pass123", "accountant")
    view = sec.create_user("view1", "مطّلع", "View#Pass123", "viewer")
    assert raises(ValueError, lambda: sec.create_user("OWNER", "x", "Another#Pass1", "viewer"))       # case-insensitive duplicate
    assert raises(ValueError, lambda: sec.create_user("bad", "x", "Another#Pass1", "root"))
    assert sec.get_user(acc)["can_view_sensitive"] == 0 and sec.get_user(1)["can_view_sensitive"] == 1
    assert len(sec.allowed_pages("admin")) == 19 and len(sec.allowed_pages("accountant")) == 16 and "العقود" in sec.allowed_pages("accountant") and "الإعدادات" not in sec.allowed_pages("accountant") and "العقود" not in sec.allowed_pages("viewer")
    ap, vp = sec.allowed_pages("accountant"), sec.allowed_pages("viewer")
    assert "التحويلات والحساب الشهري" in ap and "النسخ الاحتياطي والاستعادة" not in ap and "سجل التدقيق" not in ap
    assert "التحويلات والحساب الشهري" not in vp and "لوحة التحكم" in vp and sec.allowed_pages("x") == []

    # ---------- login, wrong password, lockout
    u, msg = sec.authenticate("owner", "Owner#Pass1")
    assert u and u["role"] == "admin" and not msg
    u, m1 = sec.authenticate("ACC1", "Acc#Pass123")                                   # username is case-insensitive
    assert u and u["username"] == "acc1"
    _, m_unknown = sec.authenticate("nobody", "whatever1")
    _, m_wrong = sec.authenticate("acc1", "wrong-password")
    assert m_unknown == m_wrong == sec.GENERIC_LOGIN_ERROR                              # no user enumeration
    for _ in range(3):
        sec.authenticate("acc1", "wrong-password")
    assert sec.get_user(acc)["failed_attempts"] == 4
    u, msg = sec.authenticate("acc1", "wrong-password")                                  # 5th failure -> lock
    assert not u and "قفل" in msg
    u, msg = sec.authenticate("acc1", "Acc#Pass123")                                     # correct password but locked
    assert not u and "مقفل" in msg
    db.execute("UPDATE users SET locked_until='2000-01-01 00:00:00' WHERE id=?", (acc,))  # lock expires
    u, msg = sec.authenticate("acc1", "Acc#Pass123")
    assert u and sec.get_user(acc)["failed_attempts"] == 0 and sec.get_user(acc)["last_login"]

    # ---------- deactivated account, last-admin guard, no deletes
    old = sec.create_user("old1", "قديم", "Old#Pass1234", "accountant")
    sec.update_user_access(old, "accountant", False, False)
    u, msg = sec.authenticate("old1", "Old#Pass1234")
    assert not u and "موقوف" in msg
    _, msg = sec.authenticate("old1", "bad-password")
    assert msg == sec.GENERIC_LOGIN_ERROR
    assert raises(sqlite3.IntegrityError, lambda: sec.update_user_access(1, "accountant", False, True))   # only admin
    assert raises(sqlite3.IntegrityError, lambda: sec.update_user_access(1, "admin", True, False))
    assert raises(sqlite3.IntegrityError, lambda: db.execute("DELETE FROM users WHERE id=?", (acc,)))
    own2 = sec.create_user("owner2", "مدير ثان", "Owner2#Pass1", "admin")
    sec.update_user_access(1, "accountant", False, True)                                  # allowed once another admin exists
    sec.update_user_access(1, "admin", True, True)
    assert raises(ValueError, lambda: sec.change_own_password(acc, "wrong", "New#Pass12345"))
    sec.change_own_password(acc, "Acc#Pass123", "New#Pass12345")
    assert sec.authenticate("acc1", "New#Pass12345")[0] and not sec.authenticate("acc1", "Acc#Pass123")[0]
    sec.reset_password(acc, "Reset#Pass123")
    assert sec.authenticate("acc1", "Reset#Pass123")[0]

    # ---------- revalidation: a deactivated user is thrown out on the next run
    SESSION.clear(); SESSION["auth_user"] = sec.session_user(sec.get_user(old))
    sec.update_user_access(old, "accountant", False, True)
    SESSION["auth_user"] = sec.session_user(sec.get_user(old))
    assert run(gate, modules=mods)["username"] == "old1"
    sec.update_user_access(old, "accountant", False, False)
    assert run(gate, modules=mods) == "STOPPED" and "auth_user" not in SESSION

    # ---------- login screen through the UI
    SESSION.clear()
    run(gate, {"login_user": "acc1", "login_pw": "nope"}, "دخول", mods)
    assert has("error", sec.GENERIC_LOGIN_ERROR) and "auth_user" not in SESSION
    run(gate, {"login_user": "acc1", "login_pw": "Reset#Pass123"}, "دخول", mods)
    assert SESSION["auth_user"]["username"] == "acc1" and sec.can_view_sensitive() is False

    # ---------- sensitive data: employee form + audit log
    RAW_ID, RAW_IBAN = "1234567890", "SA0380000000608010167519"
    ent_mods = ("modules.entities", "modules.employees")
    def ent_call(fn):
        def go():
            import modules.entities as ent, modules.employees as emp_page
            return fn(ent, emp_page.CFG)
        return go

    SESSION.clear(); SESSION["auth_user"] = sec.session_user(sec.get_user(1))           # admin creates employee
    assert sec.can_view_sensitive()
    run(ent_call(lambda ent, cfg: ent.save_record(cfg, None, {"full_name": "موظف س", "national_id": RAW_ID, "iban": RAW_IBAN, "bank_name": "الراجحي"})),
        modules=ent_mods)
    e = db.query_one("SELECT * FROM employees")
    assert e["national_id"] == RAW_ID and e["iban"] == RAW_IBAN
    # duplicate national id -> friendly Arabic message, not the raw SQL error
    try:
        run(ent_call(lambda ent, cfg: ent.save_record(cfg, None, {"full_name": "اسم آخر", "national_id": RAW_ID})), modules=ent_mods)
        raise AssertionError("duplicate national id accepted")
    except ValueError as ex:
        assert "مسجل مسبقاً" in str(ex) and "UNIQUE" not in str(ex), ex

    SESSION.clear(); SESSION["auth_user"] = sec.session_user(sec.get_user(acc))         # accountant WITHOUT permission
    assert not sec.can_view_sensitive()
    run(ent_call(lambda ent, cfg: ent._fields(cfg, db.query_one("SELECT * FROM employees WHERE id=1"), "e1")), modules=ent_mods)
    shown = [c for c in CALLS if c[0] == "الآيبان (حساس)"]
    assert shown and shown[-1][2] is True and shown[-1][1].endswith("7519") and shown[-1][1] != RAW_IBAN, shown
    run(ent_call(lambda ent, cfg: ent.save_record(cfg, 1, {"full_name": "موظف س معدل", "national_id": "HACK", "iban": "HACK", "bank_name": "HACK"})),
        modules=ent_mods)
    e = db.query_one("SELECT * FROM employees")
    assert e["full_name"] == "موظف س معدل", e                                          # allowed field changed
    assert e["national_id"] == RAW_ID and e["iban"] == RAW_IBAN and e["bank_name"] == "الراجحي", e   # sensitive untouched
    rows = " ".join((r["old_values"] or "") + (r["new_values"] or "") for r in db.query_all("SELECT * FROM audit_log"))
    assert RAW_ID not in rows and "SA0380" not in rows and "الراجحي" not in rows, "sensitive data leaked into audit log"
    assert "pbkdf2" not in rows and "[محجوب]" in rows
    upd = db.query_one("SELECT changed_by FROM audit_log WHERE table_name='employees' AND action='UPDATE'")
    assert upd["changed_by"] == "acc1"                                                  # actor recorded automatically

    # defence in depth: even a tampered payload cannot change sensitive columns without permission
    tampered = sec.keep_sensitive({"full_name": "x", "iban": "HACK", "national_id": "HACK", "bank_name": "HACK", "id_number": "HACK"},
                                  {"iban": "A", "national_id": "B", "bank_name": "C", "id_number": "D"})
    assert tampered == {"full_name": "x", "iban": "A", "national_id": "B", "bank_name": "C", "id_number": "D"}, tampered
    assert sec.keep_sensitive({"iban": "NEW"}, None) == {"iban": None}                   # new record by unauthorised user: empty
    sec.update_user_access(acc, "accountant", True, True)                               # admin grants permission
    SESSION["auth_user"] = sec.session_user(sec.get_user(acc))
    assert sec.can_view_sensitive()
    run(ent_call(lambda ent, cfg: ent.save_record(cfg, 1, {"full_name": "موظف س معدل", "iban": "SA9999999999999999999999"})), modules=ent_mods)
    assert db.query_one("SELECT iban FROM employees")["iban"] == "SA9999999999999999999999"

    # direct audit redaction unit check
    from audit import log_audit
    log_audit("employees", 9, "UPDATE", {"national_id": "5555555555", "full_name": "اسم", "iban": None}, {"iban": "SA11"})
    last = db.query_one("SELECT old_values o, new_values n FROM audit_log ORDER BY id DESC LIMIT 1")
    assert "5555555555" not in last["o"] and "اسم" in last["o"] and "SA11" not in last["n"]

    # ---------- user management page
    SESSION.clear(); SESSION["auth_user"] = sec.session_user(sec.get_user(1))
    users_page = lambda: __import__("modules.users", fromlist=["render"]).render()
    run(users_page, {"ua_user": "newbie", "ua_display": "جديد", "ua_role": "viewer", "ua_pw1": "Newbie#Pass1", "ua_pw2": "Newbie#Pass1"},
        "إضافة المستخدم", ("modules.users",))
    assert db.query_one("SELECT role FROM users WHERE username='newbie'")["role"] == "viewer"
    run(users_page, {"um_sel": "owner2"}, "حفظ التعديلات", ("modules.users",))        # editing another admin is fine
    SESSION["auth_user"] = sec.session_user(sec.get_user(acc))                          # non-admin sees only the account tab
    run(users_page, {"pw_cur": "wrong", "pw_new1": "Fresh#Pass1234", "pw_new2": "Fresh#Pass1234"}, "تغيير كلمة المرور", ("modules.users",))
    assert has("error", "غير صحيحة")

    # ---------- emergency reset script: works even while the account is locked
    db.execute("UPDATE users SET locked_until='2999-01-01 00:00:00', failed_attempts=3 WHERE id=1")
    assert not sec.authenticate("owner", "Owner#Pass1")[0]
    import reset_password
    assert reset_password.reset("OWNER", "Recovered#Pass1") == "owner"
    assert sec.authenticate("owner", "Recovered#Pass1")[0] and not sec.authenticate("owner", "Owner#Pass1")[0]
    assert raises(ValueError, lambda: reset_password.reset("ghost", "Recovered#Pass1"))
    assert raises(ValueError, lambda: reset_password.reset("owner", "123"))

    # ---------- notes: nothing sensitive stored in plaintext in users table
    assert all(r["password_hash"].startswith("pbkdf2_sha256$") for r in db.query_all("SELECT password_hash FROM users"))
    n_events = db.query_one("SELECT COUNT(*) c FROM audit_log WHERE note LIKE '%دخول%'")["c"]
    assert n_events >= 6

    print("SECURITY_TESTS_PASSED")
    print("- passwords: salted PBKDF2, weak/short/numeric/same-as-username rejected")
    print("- first-run setup creates the admin; login is case-insensitive; unknown user == wrong password message")
    print("- lockout after 5 failures (even a correct password is refused), expires, counter resets")
    print("- deactivated user refused and thrown out on the next page run; last active admin cannot be removed; users cannot be deleted")
    print("- roles: admin 19 pages, accountant 16 (no backup/audit/settings), viewer 5")
    print("- accountant without permission sees masked IBAN, cannot overwrite it, edits other fields normally")
    print("- audit log never contains ID/IBAN/bank/password hashes, and records who did what")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
