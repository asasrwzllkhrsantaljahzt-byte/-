"""System settings stored in the database (key/value). Read by the sidebar, dashboard and contracts page."""
from db import get_connection, query_all, query_one
from audit import log_audit

DEFAULTS = {
    "org_name": "نظام إدارة شركة التوظيف",
    "org_commercial_register": "",
    "org_tax_number": "",
    "org_phone": "",
    "org_address": "",
    "contract_alert_days": "30",     # warn when an active contract ends within this many days
    "contract_alerts_enabled": "1",
    "backup_reminder_days": "7",     # warn when the last backup is older than this
    "backup_alerts_enabled": "1",
    "doc_alert_days": "30",          # warn when a document expires within this many days
    "doc_alerts_enabled": "1",
    "dues_alert_days": "30",         # warn about dues still unpaid this many days after the month ended
    "dues_alerts_enabled": "1",
    "month_alerts_enabled": "1",
    "vat_rate": "15",                # VAT % used on client invoices
}
LIMITS = {"contract_alert_days": (1, 365), "backup_reminder_days": (1, 90), "vat_rate": (0, 100), "doc_alert_days": (1, 365), "dues_alert_days": (1, 365)}
MAX_TEXT = 200

SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def ensure_settings_schema() -> None:
    conn = get_connection()
    try:
        conn.executescript(SETTINGS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_all() -> dict:
    out = dict(DEFAULTS)
    try:
        for r in query_all("SELECT key, value FROM app_settings"):
            if r["key"] in DEFAULTS:
                out[r["key"]] = r["value"]
    except Exception:  # noqa: BLE001  (table not created yet)
        pass
    return out


def get(key: str) -> str:
    return get_all()[key]


def get_int(key: str) -> int:
    lo, hi = LIMITS[key]
    try:
        v = int(get(key))
    except (TypeError, ValueError):
        v = int(DEFAULTS[key])
    return min(max(v, lo), hi)


def get_bool(key: str) -> bool:
    if key not in DEFAULTS or DEFAULTS[key] not in ("0", "1"):
        raise KeyError(key)
    value = get(key)
    if value not in ("0", "1"):
        raise ValueError(f"قيمة إعداد التنبيه غير صالحة: {key}")
    return value == "1"


def validate(values: dict) -> list:
    """Returns a list of Arabic error messages (empty when valid)."""
    errors = []
    if not str(values.get("org_name", "")).strip():
        errors.append("اسم المنشأة مطلوب.")
    for k in ("org_name", "org_commercial_register", "org_tax_number", "org_phone", "org_address"):
        if len(str(values.get(k, ""))) > MAX_TEXT:
            errors.append(f"النص طويل جداً (الحد {MAX_TEXT} حرفاً).")
            break
    for k, (lo, hi) in LIMITS.items():
        if k not in values:
            continue
        try:
            n = int(values[k])
            if not lo <= n <= hi:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            errors.append(f"قيمة غير صالحة: يجب أن يكون عدد الأيام بين {lo} و{hi}.")
    for k in ("contract_alerts_enabled", "backup_alerts_enabled", "doc_alerts_enabled",
              "dues_alerts_enabled", "month_alerts_enabled"):
        if k in values and str(values[k]) not in ("0", "1"):
            errors.append("قيمة إعداد التنبيه غير صالحة.")
    return errors


def save(values: dict) -> dict:
    """Validates and saves; returns {key: (old, new)} of what actually changed. Raises ValueError on bad input."""
    clean = {
        k: ("1" if values[k] else "0") if isinstance(values[k], bool) else str(values[k]).strip()
        for k in DEFAULTS if k in values
    }
    errors = validate(clean)
    if errors:
        raise ValueError(" ".join(errors))
    current = get_all()
    changed = {k: (current[k], v) for k, v in clean.items() if current[k] != v}
    if not changed:
        return {}
    conn = get_connection()
    try:
        for k, (_, new) in changed.items():
            conn.execute(
                """INSERT INTO app_settings(key, value, updated_at) VALUES (?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP""",
                (k, new),
            )
        conn.commit()
    finally:
        conn.close()
    log_audit("app_settings", 0, "UPDATE",
              {k: o for k, (o, _) in changed.items()}, {k: n for k, (_, n) in changed.items()},
              note="تعديل إعدادات النظام")
    return changed
