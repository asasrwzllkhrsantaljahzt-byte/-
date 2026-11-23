"""Removes tables of the old agreement-based accounting engine (replaced by the company hub + monthly engine).
Only EMPTY tables are dropped, so nothing the user may still want is ever lost."""
from db import get_connection

LEGACY_TABLES = ["agreement_calc_log", "fin_agreement_members", "fin_agreements", "party_dues", "monthly_employee_accounts",
                 "financial_transactions", "placement_representatives", "placement_contractors", "company_representatives"]


def drop_legacy_tables() -> dict:
    """Returns {'dropped': [...], 'kept': [(table, rows)]}."""
    conn = get_connection()
    out = {"dropped": [], "kept": []}
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in LEGACY_TABLES:
            if t not in have:
                continue
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if n:
                out["kept"].append((t, n))
            else:
                conn.execute(f'DROP TABLE "{t}"')
                out["dropped"].append(t)
        conn.commit()
    finally:
        conn.close()
    return out
