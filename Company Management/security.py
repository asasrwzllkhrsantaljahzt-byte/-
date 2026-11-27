"""Authentication, roles and sensitive-data helpers (stdlib only)."""
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone

from db import get_connection, query_all, query_one, execute
from audit import log_audit

ITERATIONS = 600_000          # PBKDF2-HMAC-SHA256 work factor (tests lower it for speed)
MAX_FAILED = 5                # failed logins before a temporary lock
LOCK_MINUTES = 5

ROLES = {"admin": "مدير النظام", "accountant": "محاسب", "viewer": "مطّلع (قراءة فقط)"}

PAGES = [
    "لوحة التحكم",
    "المساعد",
    "الشركات والموظفون",
    "المتعهدون",
    "المندوبون",
    "العقود",
    "الوثائق",
    "التحويلات والحساب الشهري",
    "التقارير المالية والإدارية",
    "كشوف الحسابات",
    "مراجعة وإقفال الشهر",
    "فواتير العملاء",
    "النسخ الاحتياطي والاستعادة",
    "سجل التدقيق",
    "الإعدادات",
    "حسابي والمستخدمون",
]
_ACCOUNTANT_EXCLUDED = {"النسخ الاحتياطي والاستعادة", "سجل التدقيق", "الإعدادات"}
_VIEWER_PAGES = ["لوحة التحكم", "المساعد", "التقارير المالية والإدارية", "كشوف الحسابات", "حسابي والمستخدمون"]
REPORT_SECTIONS = {
    "monthly_summary": "ملخص الشهر",
    "employee_details": "تفصيل الموظفات",
    "balances": "الأرصدة والمستحقات",
    "annual": "التقرير السنوي",
}

SENSITIVE_KEYS = ("national_id", "id_number", "bank_name", "iban")

_WEAK = {"12345678", "123456789", "1234567890", "password", "password1", "11111111", "qwertyui", "abcd1234", "00000000"}
GENERIC_LOGIN_ERROR = "اسم المستخدم أو كلمة المرور غير صحيحة."

SECURITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'accountant', 'viewer')),
    password_hash TEXT NOT NULL,
    can_view_sensitive INTEGER NOT NULL DEFAULT 0 CHECK (can_view_sensitive IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_login TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS role_page_permissions (
    role TEXT NOT NULL CHECK (role IN ('admin', 'accountant', 'viewer')),
    page TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (role, page)
);

CREATE TABLE IF NOT EXISTS role_report_permissions (
    role TEXT NOT NULL CHECK (role IN ('admin', 'accountant', 'viewer')),
    section TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (role, section)
);

CREATE TRIGGER IF NOT EXISTS trg_users_no_delete
BEFORE DELETE ON users
BEGIN
    SELECT RAISE(ABORT, 'لا يجوز حذف المستخدمين. أوقف الحساب بدلاً من ذلك.');
END;

CREATE TRIGGER IF NOT EXISTS trg_users_keep_admin
BEFORE UPDATE ON users
WHEN OLD.role = 'admin' AND OLD.is_active = 1 AND (NEW.role != 'admin' OR NEW.is_active = 0)
     AND (SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1 AND id != OLD.id) = 0
BEGIN
    SELECT RAISE(ABORT, 'لا يمكن إيقاف أو تخفيض آخر مدير نشط في النظام.');
END;
"""


# ----------------------------------------------------------------- schema
def ensure_security_schema() -> None:
    conn = get_connection()
    try:
        conn.executescript(SECURITY_SCHEMA)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------- passwords
def hash_password(password: str, iterations: int = None) -> str:
    iters = iterations or ITERATIONS
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    return f"pbkdf2_sha256${iters}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:  # noqa: BLE001
        return False


def validate_password(password: str, username: str = "") -> str:
    """Returns an Arabic error message, or '' when the password is acceptable."""
    if len(password) < 8:
        return "كلمة المرور يجب ألا تقل عن 8 أحرف."
    if password.isdigit():
        return "كلمة المرور لا يجوز أن تكون أرقاماً فقط."
    if password.lower() in _WEAK:
        return "كلمة المرور شائعة وضعيفة. اختر غيرها."
    if username and password.lower() == username.lower():
        return "كلمة المرور لا يجوز أن تطابق اسم المستخدم."
    return ""


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


def validate_username(username: str) -> str:
    if not _USERNAME_RE.match(username or ""):
        return "اسم المستخدم من 3 إلى 32 حرفاً إنجليزياً أو أرقاماً أو (_ . -) بدون مسافات."
    return ""


# ------------------------------------------------------------------ helpers
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def has_users() -> bool:
    return query_one("SELECT COUNT(*) AS n FROM users")["n"] > 0


def get_user(user_id: int):
    return query_one("SELECT * FROM users WHERE id=?", (user_id,))


def list_users():
    return query_all("""SELECT id, username, display_name, role, can_view_sensitive, is_active, last_login, created_at
                        FROM users ORDER BY id""")


def session_user(row: dict) -> dict:
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"],
            "role": row["role"], "can_view_sensitive": bool(row["can_view_sensitive"]) or row["role"] == "admin"}


# ------------------------------------------------------------------ users CRUD
def create_user(username: str, display_name: str, password: str, role: str, can_view_sensitive: bool = False) -> int:
    username = (username or "").strip()
    display_name = (display_name or "").strip()
    err = validate_username(username) or validate_password(password, username)
    if err:
        raise ValueError(err)
    if not display_name:
        raise ValueError("الاسم الظاهر مطلوب.")
    if role not in ROLES:
        raise ValueError("الدور غير صحيح.")
    if query_one("SELECT id FROM users WHERE username=? COLLATE NOCASE", (username,)):
        raise ValueError("اسم المستخدم مستخدم من قبل.")
    flag = 1 if (can_view_sensitive or role == "admin") else 0
    uid = execute("""INSERT INTO users(username, display_name, role, password_hash, can_view_sensitive)
                     VALUES (?,?,?,?,?)""", (username, display_name, role, hash_password(password), flag))
    log_audit("users", uid, "INSERT", None,
              {"username": username, "role": role, "can_view_sensitive": bool(flag)}, note="إنشاء مستخدم")
    return uid


def update_user_access(user_id: int, role: str, can_view_sensitive: bool, is_active: bool) -> None:
    if role not in ROLES:
        raise ValueError("الدور غير صحيح.")
    old = get_user(user_id)
    if not old:
        raise ValueError("المستخدم غير موجود.")
    flag = 1 if (can_view_sensitive or role == "admin") else 0
    execute("UPDATE users SET role=?, can_view_sensitive=?, is_active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (role, flag, 1 if is_active else 0, user_id))
    log_audit("users", user_id, "UPDATE",
              {"role": old["role"], "can_view_sensitive": bool(old["can_view_sensitive"]), "is_active": bool(old["is_active"])},
              {"role": role, "can_view_sensitive": bool(flag), "is_active": bool(is_active)}, note="تعديل صلاحيات مستخدم")


def reset_password(user_id: int, new_password: str) -> None:
    old = get_user(user_id)
    if not old:
        raise ValueError("المستخدم غير موجود.")
    err = validate_password(new_password, old["username"])
    if err:
        raise ValueError(err)
    execute("""UPDATE users SET password_hash=?, failed_attempts=0, locked_until=NULL, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""", (hash_password(new_password), user_id))
    log_audit("users", user_id, "UPDATE", None, None, note=f"إعادة تعيين كلمة مرور المستخدم {old['username']}")


def change_own_password(user_id: int, current_password: str, new_password: str) -> None:
    row = get_user(user_id)
    if not row or not verify_password(current_password, row["password_hash"]):
        raise ValueError("كلمة المرور الحالية غير صحيحة.")
    if verify_password(new_password, row["password_hash"]):
        raise ValueError("كلمة المرور الجديدة مطابقة للحالية.")
    err = validate_password(new_password, row["username"])
    if err:
        raise ValueError(err)
    execute("UPDATE users SET password_hash=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (hash_password(new_password), user_id))
    log_audit("users", user_id, "UPDATE", None, None, note="تغيير كلمة المرور من المستخدم نفسه")


# ------------------------------------------------------------------ login
_DUMMY_HASH = None


def _burn_time(password: str) -> None:
    """Hash once for unknown accounts so response time does not reveal whether a username exists."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing")
    verify_password(password, _DUMMY_HASH)


def authenticate(username: str, password: str):
    """Returns (session_user_dict | None, arabic_message)."""
    username = (username or "").strip()
    row = query_one("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)) if username else None
    if not row:
        _burn_time(password or "")
        log_audit("users", 0, "STATUS_CHANGE", None, None, changed_by=username[:32] or None,
                  note="محاولة دخول فاشلة: مستخدم غير معروف")
        return None, GENERIC_LOGIN_ERROR

    now = _now()
    if row["locked_until"] and row["locked_until"] > _fmt(now):
        until = datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        mins = max(1, int((until - now).total_seconds() // 60) + 1)
        return None, f"الحساب مقفل مؤقتاً بسبب محاولات خاطئة متكررة. حاول بعد {mins} دقيقة."

    if not verify_password(password or "", row["password_hash"]):
        failed = int(row["failed_attempts"] or 0) + 1
        if failed >= MAX_FAILED:
            execute("UPDATE users SET failed_attempts=0, locked_until=? WHERE id=?",
                    (_fmt(now + timedelta(minutes=LOCK_MINUTES)), row["id"]))
            log_audit("users", row["id"], "STATUS_CHANGE", None, None, changed_by=row["username"],
                      note=f"قفل الحساب {LOCK_MINUTES} دقائق بعد {MAX_FAILED} محاولات فاشلة")
            return None, f"تم قفل الحساب {LOCK_MINUTES} دقائق بسبب محاولات خاطئة متكررة."
        execute("UPDATE users SET failed_attempts=? WHERE id=?", (failed, row["id"]))
        log_audit("users", row["id"], "STATUS_CHANGE", None, None, changed_by=row["username"],
                  note=f"محاولة دخول فاشلة ({failed}/{MAX_FAILED})")
        return None, GENERIC_LOGIN_ERROR

    if not row["is_active"]:
        return None, "هذا الحساب موقوف. راجع مدير النظام."

    execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=? WHERE id=?", (_fmt(now), row["id"]))
    log_audit("users", row["id"], "STATUS_CHANGE", None, None, changed_by=row["username"], note="تسجيل دخول ناجح")
    return session_user(get_user(row["id"])), ""


# ------------------------------------------------------- session / permissions
def current_user():
    try:
        import streamlit as st
        return st.session_state.get("auth_user")
    except Exception:  # noqa: BLE001
        return None


def allowed_pages(role: str) -> list:
    default_pages = set(_default_pages(role))
    if not default_pages:
        return []
    overrides = {row["page"]: bool(row["enabled"]) for row in query_all(
        "SELECT page, enabled FROM role_page_permissions WHERE role=?", (role,))}
    pages = [page for page in PAGES if overrides.get(page, page in default_pages)]
    if role != "admin":
        pages = [page for page in pages if page != "الإعدادات"]
    if role == "admin":
        for required in ("الإعدادات", "حسابي والمستخدمون"):
            if required not in pages:
                pages.append(required)
    return pages


def _default_pages(role: str) -> list:
    if role == "admin":
        return list(PAGES)
    if role == "accountant":
        return [page for page in PAGES if page not in _ACCOUNTANT_EXCLUDED]
    if role == "viewer":
        return list(_VIEWER_PAGES)
    return []


def allowed_report_sections(role: str) -> list:
    if "التقارير المالية والإدارية" not in allowed_pages(role):
        return []
    overrides = {row["section"]: bool(row["enabled"]) for row in query_all(
        "SELECT section, enabled FROM role_report_permissions WHERE role=?", (role,))}
    return [key for key in REPORT_SECTIONS if overrides.get(key, True)]


def save_role_permissions(role: str, enabled_pages, enabled_reports) -> None:
    if role not in ROLES:
        raise ValueError("الدور غير صحيح.")
    pages = set(enabled_pages)
    reports = set(enabled_reports)
    if pages - set(PAGES) or reports - set(REPORT_SECTIONS):
        raise ValueError("تم اختيار وظيفة أو تقرير غير معروف.")
    if role == "admin":
        pages.update(("الإعدادات", "حسابي والمستخدمون"))
    else:
        pages.discard("الإعدادات")

    conn = get_connection()
    try:
        conn.executemany(
            """INSERT INTO role_page_permissions(role, page, enabled, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(role, page) DO UPDATE SET enabled=excluded.enabled,
                   updated_at=CURRENT_TIMESTAMP""",
            [(role, page, int(page in pages)) for page in PAGES],
        )
        conn.executemany(
            """INSERT INTO role_report_permissions(role, section, enabled, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(role, section) DO UPDATE SET enabled=excluded.enabled,
                   updated_at=CURRENT_TIMESTAMP""",
            [(role, section, int(section in reports)) for section in REPORT_SECTIONS],
        )
        conn.commit()
    finally:
        conn.close()
    log_audit("role_permissions", 0, "UPDATE", None,
              {"role": role, "pages": sorted(pages), "reports": sorted(reports)},
              note=f"تعديل صلاحيات واجهة وتقارير دور {ROLES[role]}")


def can_write() -> bool:
    u = current_user()
    return bool(u) and u["role"] in ("admin", "accountant")


def can_view_sensitive() -> bool:
    u = current_user()
    return bool(u) and (u["role"] == "admin" or bool(u.get("can_view_sensitive")))


# ------------------------------------------------------------ sensitive data
def mask(value) -> str:
    if not value:
        return ""
    s = str(value)
    return "•" * max(len(s) - 4, 4) + s[-4:] if len(s) > 4 else "••••"


def sensitive_input(label: str, value, key: str = None) -> str:
    """Text input for a sensitive field: real value for authorised users, masked and disabled for the rest."""
    import streamlit as st
    if can_view_sensitive():
        return st.text_input(label, value=value or "", key=key)
    st.text_input(label, value=mask(value), disabled=True, key=key,
                  help="ليست لديك صلاحية عرض أو تعديل البيانات الحساسة.")
    return value or ""


def keep_sensitive(payload: dict, existing) -> dict:
    """Users without permission can never change sensitive columns: keep what is stored."""
    if can_view_sensitive():
        return payload
    existing = existing or {}
    for k in SENSITIVE_KEYS:
        if k in payload:
            payload[k] = existing.get(k)
    return payload
