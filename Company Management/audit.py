import json
from db import get_connection

# Values of these keys are never written to the (permanent, append-only) audit log.
SENSITIVE_KEYS = {"national_id", "id_number", "iban", "bank_name", "password_hash"}
REDACTED = "[محجوب]"


def _redact(obj):
    if hasattr(obj, "keys") and not isinstance(obj, dict):
        obj = dict(obj)
    if isinstance(obj, dict):
        return {k: (REDACTED if k in SENSITIVE_KEYS and v not in (None, "") else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redact(x) for x in obj]
    return obj


def _current_username():
    try:
        import streamlit as st
        user = st.session_state.get("auth_user")
        return user["username"] if user else None
    except Exception:  # noqa: BLE001
        return None


def log_audit(table_name: str, record_id: int, action: str, old_values=None, new_values=None, changed_by: str = None, note: str = None):
    changed_by = changed_by or _current_username()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO audit_log(table_name, record_id, action, old_values, new_values, changed_by, note)
               VALUES (?,?,?,?,?,?,?)""",
            (
                table_name,
                int(record_id) if record_id is not None else 0,
                action,
                json.dumps(_redact(old_values), ensure_ascii=False) if old_values is not None else None,
                json.dumps(_redact(new_values), ensure_ascii=False) if new_values is not None else None,
                changed_by,
                note,
            ),
        )
        conn.commit()
    finally:
        conn.close()
