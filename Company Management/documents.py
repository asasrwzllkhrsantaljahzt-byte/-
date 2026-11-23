"""Documents register: expiry dates + optional file for employees, clients, contractors, representatives.
Document numbers are deliberately NOT stored (they are sensitive); only type, title, dates, notes and the scanned file.
"""
from datetime import date, datetime, timedelta

import app_settings
from audit import log_audit, _current_username
from db import get_connection, query_all, query_one

OWNER_AR = {"employee": "موظف", "company": "شركة عميلة", "contractor": "متعهد", "representative": "مندوب"}
OWNER_TABLE = {"employee": ("employees", "full_name"), "company": ("companies", "name"),
               "contractor": ("contractors", "name"), "representative": ("representatives", "name")}
DOC_TYPES = {
    "employee": ["هوية وطنية", "شهادة التأمينات الاجتماعية", "تأمين طبي", "عقد عمل", "شهادة بنكية (آيبان)", "شهادة صحية", "أخرى"],
    "company": ["سجل تجاري", "شهادة ضريبية", "شهادة الزكاة", "عضوية الغرفة التجارية", "عقد", "أخرى"],
    "contractor": ["هوية", "سجل تجاري", "عقد", "أخرى"],
    "representative": ["هوية", "عقد", "أخرى"],
}
MAX_FILE = 5 * 1024 * 1024
ALLOWED_EXT = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

DOCUMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('employee','company','contractor','representative')),
    owner_id INTEGER NOT NULL,
    doc_type TEXT NOT NULL,
    title TEXT,
    issue_date TEXT,
    expiry_date TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
    notes TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (expiry_date IS NULL OR issue_date IS NULL OR expiry_date >= issue_date)
);
CREATE TABLE IF NOT EXISTS document_files (
    document_id INTEGER PRIMARY KEY,
    file_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    data BLOB NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_documents_owner ON documents(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS ix_documents_expiry ON documents(status, expiry_date);

CREATE TRIGGER IF NOT EXISTS trg_documents_owner_exists BEFORE INSERT ON documents
WHEN NOT (
    (NEW.owner_type='employee' AND EXISTS (SELECT 1 FROM employees WHERE id=NEW.owner_id)) OR
    (NEW.owner_type='company' AND EXISTS (SELECT 1 FROM companies WHERE id=NEW.owner_id)) OR
    (NEW.owner_type='contractor' AND EXISTS (SELECT 1 FROM contractors WHERE id=NEW.owner_id)) OR
    (NEW.owner_type='representative' AND EXISTS (SELECT 1 FROM representatives WHERE id=NEW.owner_id)))
BEGIN SELECT RAISE(ABORT, 'صاحب الوثيقة غير موجود في النظام.'); END;

CREATE TRIGGER IF NOT EXISTS trg_documents_no_delete BEFORE DELETE ON documents
BEGIN SELECT RAISE(ABORT, 'لا تُحذف الوثائق. أرشفها بدلاً من ذلك.'); END;

CREATE TRIGGER IF NOT EXISTS trg_documents_owner_fixed BEFORE UPDATE ON documents
WHEN NEW.owner_type != OLD.owner_type OR NEW.owner_id != OLD.owner_id
BEGIN SELECT RAISE(ABORT, 'لا يمكن نقل الوثيقة إلى صاحب آخر.'); END;
"""


def ensure_documents_schema():
    conn = get_connection()
    try:
        conn.executescript(DOCUMENTS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _iso(d):
    if d in (None, ""):
        return None
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)


def _to_date(s):
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def owner_name(owner_type, owner_id):
    t = OWNER_TABLE[owner_type]
    r = query_one(f"SELECT {t[1]} AS n FROM {t[0]} WHERE id=?", (owner_id,))
    return r["n"] if r else "(محذوف)"


def validate(owner_type, owner_id, doc_type, issue, expiry, file=None):
    if owner_type not in OWNER_TABLE:
        raise ValueError("نوع صاحب الوثيقة غير صحيح.")
    if not owner_id:
        raise ValueError("اختر صاحب الوثيقة.")
    if doc_type not in DOC_TYPES[owner_type]:
        raise ValueError("نوع الوثيقة غير صحيح.")
    if issue and expiry and _iso(expiry) < _iso(issue):
        raise ValueError("تاريخ الانتهاء قبل تاريخ الإصدار.")
    if file:
        name, data = file[0], file[1]
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        if ext not in ALLOWED_EXT:
            raise ValueError("نوع الملف غير مسموح. المسموح: PDF أو JPG أو PNG.")
        if len(data) > MAX_FILE:
            raise ValueError("حجم الملف أكبر من 5 ميغابايت.")
        if not data:
            raise ValueError("الملف فارغ.")


def _save_file(conn, doc_id, file):
    name, data = file[0], file[1]
    ext = "." + name.rsplit(".", 1)[-1].lower()
    conn.execute("INSERT OR REPLACE INTO document_files(document_id, file_name, mime, data) VALUES (?,?,?,?)",
                 (doc_id, name, ALLOWED_EXT[ext], data))


def add_document(owner_type, owner_id, doc_type, title=None, issue=None, expiry=None, notes=None, file=None) -> int:
    validate(owner_type, owner_id, doc_type, issue, expiry, file)
    conn = get_connection()
    try:
        cur = conn.execute("""INSERT INTO documents(owner_type, owner_id, doc_type, title, issue_date, expiry_date, notes, created_by)
                              VALUES (?,?,?,?,?,?,?,?)""",
                           (owner_type, owner_id, doc_type, (title or "").strip() or None, _iso(issue), _iso(expiry),
                            (notes or "").strip() or None, _current_username()))
        did = cur.lastrowid
        if file:
            _save_file(conn, did, file)
        conn.commit()
    finally:
        conn.close()
    log_audit("documents", did, "INSERT", None, {"owner_type": owner_type, "owner_id": owner_id, "doc_type": doc_type,
                                                  "expiry_date": _iso(expiry), "has_file": bool(file)})
    return did


def update_document(doc_id, title=None, issue=None, expiry=None, notes=None, file=None) -> str:
    old = query_one("SELECT * FROM documents WHERE id=?", (doc_id,))
    if not old:
        raise ValueError("الوثيقة غير موجودة.")
    if old["status"] == "archived":
        raise ValueError("الوثيقة مؤرشفة ولا تُعدَّل.")
    validate(old["owner_type"], old["owner_id"], old["doc_type"], issue, expiry, file)
    conn = get_connection()
    try:
        conn.execute("UPDATE documents SET title=?, issue_date=?, expiry_date=?, notes=? WHERE id=?",
                     ((title or "").strip() or None, _iso(issue), _iso(expiry), (notes or "").strip() or None, doc_id))
        if file:
            _save_file(conn, doc_id, file)
        conn.commit()
    finally:
        conn.close()
    log_audit("documents", doc_id, "UPDATE", {"expiry_date": old["expiry_date"], "issue_date": old["issue_date"]},
              {"expiry_date": _iso(expiry), "issue_date": _iso(issue), "file_replaced": bool(file)})
    return "تم حفظ التعديل."


def archive_document(doc_id) -> str:
    old = query_one("SELECT * FROM documents WHERE id=?", (doc_id,))
    if not old:
        raise ValueError("الوثيقة غير موجودة.")
    conn = get_connection()
    try:
        conn.execute("UPDATE documents SET status='archived' WHERE id=?", (doc_id,))
        conn.commit()
    finally:
        conn.close()
    log_audit("documents", doc_id, "STATUS_CHANGE", {"status": "active"}, {"status": "archived"})
    return "تمت أرشفة الوثيقة."


def get_file(doc_id):
    return query_one("SELECT file_name, mime, data FROM document_files WHERE document_id=?", (doc_id,))


def list_documents(owner_type=None, status="active"):
    sql = "SELECT d.*, (SELECT 1 FROM document_files f WHERE f.document_id=d.id) AS has_file FROM documents d WHERE 1=1"
    params = []
    if owner_type:
        sql += " AND d.owner_type=?"; params.append(owner_type)
    if status:
        sql += " AND d.status=?"; params.append(status)
    rows = query_all(sql + " ORDER BY (d.expiry_date IS NULL), d.expiry_date, d.id", tuple(params))
    for r in rows:
        r["owner_name"] = owner_name(r["owner_type"], r["owner_id"])
    return rows


def state_of(r, today=None, days=None):
    """expired / soon / valid / none (no expiry date)."""
    today = today or date.today()
    days = days or app_settings.get_int("doc_alert_days")
    if not r["expiry_date"]:
        return "none"
    e = _to_date(r["expiry_date"])
    if e < today:
        return "expired"
    return "soon" if e <= today + timedelta(days=days) else "valid"


def expiry_alerts(today=None, days=None) -> dict:
    today = today or date.today()
    days = days or app_settings.get_int("doc_alert_days")
    expired, soon = [], []
    for r in list_documents():
        s = state_of(r, today, days)
        if s == "expired":
            expired.append(r)
        elif s == "soon":
            soon.append(r)
    return {"expired": expired, "soon": soon, "days": days}
