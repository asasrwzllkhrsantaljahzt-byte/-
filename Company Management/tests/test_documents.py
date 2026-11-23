"""Tests for the documents register. Run: py -3 tests\\test_documents.py"""
import sys, types, tempfile, shutil, datetime, sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.dont_write_bytecode = True


class _St(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.dialog = lambda *a, **k: (lambda f: f)


def raises(exc, text, fn):
    try:
        fn()
    except exc as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError("no error: " + text)


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_doc_"))
    (tmp / "database").mkdir()
    for f in ("schema.sql",):
        shutil.copy2(BASE / "database" / f, tmp / "database" / f)
    import db, security as sec, app_settings as aps, documents as D
    db.BASE_DIR = tmp; db.SCHEMA_PATH = tmp / "database/schema.sql"; db.DB_PATH = tmp / "database/app.db"
    db.init_db(); sec.ensure_security_schema(); aps.ensure_settings_schema()
    D.ensure_documents_schema(); D.ensure_documents_schema()
    d = datetime.date; today = d.today(); day = lambda n: today + datetime.timedelta(days=n)
    e = db.execute("INSERT INTO employees(full_name) VALUES ('موظف')")
    co = db.execute("INSERT INTO companies(name) VALUES ('شركة')")

    a = D.add_document("employee", e, "هوية وطنية", "هوية", day(-300), day(-5), file=("id.pdf", b"%PDF-1"))
    b = D.add_document("company", co, "سجل تجاري", None, None, day(10))
    c = D.add_document("employee", e, "تأمين طبي", None, None, day(200))
    n = D.add_document("employee", e, "أخرى", None, None, None)
    al = D.expiry_alerts()
    assert [r["id"] for r in al["expired"]] == [a] and [r["id"] for r in al["soon"]] == [b]
    assert al["days"] == 30 and D.expiry_alerts(days=300)["soon"].__len__() == 2
    assert D.state_of(db.query_one("SELECT * FROM documents WHERE id=?", (n,))) == "none"
    assert bytes(D.get_file(a)["data"]) == b"%PDF-1" and D.get_file(b) is None

    raises(ValueError, "غير صحيح", lambda: D.add_document("employee", e, "سجل تجاري"))
    raises(ValueError, "قبل تاريخ الإصدار", lambda: D.add_document("employee", e, "عقد عمل", None, day(5), day(1)))
    raises(ValueError, "غير مسموح", lambda: D.add_document("employee", e, "عقد عمل", file=("x.exe", b"1")))
    raises(ValueError, "5 ميغابايت", lambda: D.add_document("employee", e, "عقد عمل", file=("x.pdf", b"0" * (D.MAX_FILE + 1))))
    def bad(sql, args=()):
        try:
            db.execute(sql, args)
        except sqlite3.IntegrityError:
            return True
        return False
    assert bad("INSERT INTO documents(owner_type, owner_id, doc_type) VALUES ('employee', 999, 'x')")
    assert bad("DELETE FROM documents WHERE id=?", (a,))
    assert bad("UPDATE documents SET owner_id=? WHERE id=?", (999, a))

    D.update_document(a, "هوية مجددة", day(-5), day(1000), None, file=("new.png", b"\x89PNG"))   # renewal
    assert D.get_file(a)["file_name"] == "new.png" and not D.expiry_alerts()["expired"]
    D.archive_document(b)
    assert len(D.list_documents()) == 3 and len(D.list_documents(status="archived")) == 1
    raises(ValueError, "مؤرشفة", lambda: D.update_document(b, "x", None, None, None))
    assert not D.expiry_alerts()["soon"]
    aud = db.query_all("SELECT old_values, new_values FROM audit_log WHERE table_name='documents'")
    assert len(aud) == 4 + 2 and not any("%PDF" in (r["new_values"] or "") for r in aud)
    assert aps.get_int("doc_alert_days") == 30
    print("DOCUMENTS_TESTS_PASSED")


if __name__ == "__main__":
    main()
