import calendar
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from db import get_connection, SCHEMA_PATH, BASE_DIR
import agreements as agr

FINANCE_SCHEMA_PATH = BASE_DIR / "database" / "finance_schema.sql"


def ensure_finance_schema(conn: Optional[sqlite3.Connection] = None):
    sql = FINANCE_SCHEMA_PATH.read_text(encoding="utf-8")
    own = False
    if conn is None:
        conn = get_connection()
        own = True
    try:
        _migrate(conn)
        conn.executescript(sql)
        conn.commit()
    finally:
        if own:
            conn.close()


def _migrate(conn):
    """Add columns introduced after the first release (safe to run on every start)."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(employee_placements)").fetchall()]
    if cols and "flow_mode" not in cols:
        conn.execute("ALTER TABLE employee_placements ADD COLUMN flow_mode TEXT NOT NULL DEFAULT 'direct' "
                     "CHECK (flow_mode IN ('direct', 'via_company'))")
        conn.commit()
    for table in ("placement_contractors", "placement_representatives"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if cols and "notes" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN notes TEXT")
            conn.commit()


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def month_range(month_ref: str):
    y, m = map(int, month_ref.split("-"))
    first = date(y, m, 1)
    last_day = calendar.monthrange(y, m)[1]
    last = date(y, m, last_day)
    return first, last, last_day


def _overlap_days(a_start: date, a_end: Optional[date], b_start: date, b_end: date) -> int:
    start = max(a_start, b_start)
    end = min(a_end or b_end, b_end)
    if end < start:
        return 0
    return (end - start).days + 1


def _active_days_for_placement(placement: dict, month_ref: str) -> int:
    m_start, m_end, month_days = month_range(month_ref)
    p_start = _parse(placement["start_date"])
    p_end = _parse(placement["end_date"]) if placement.get("end_date") else None
    # if placement marked ended/suspended, end_date should be respected; if missing, treat as not active beyond no info
    if placement.get("status") in ("ended", "suspended") and p_end is None:
        # without stop date, cannot attribute active days safely
        return 0
    return _overlap_days(p_start, p_end, m_start, m_end)


def _is_agreement_active_in_month(start_s: str, end_s: Optional[str], month_ref: str) -> bool:
    m_start, m_end, _ = month_range(month_ref)
    a_start = _parse(start_s)
    a_end = _parse(end_s) if end_s else None
    return _overlap_days(a_start, a_end, m_start, m_end) > 0


def _is_agreement_active_on_period(start_s: str, end_s: Optional[str], period_start: date, period_end: date) -> bool:
    a_start = _parse(start_s)
    a_end = _parse(end_s) if end_s else None
    return _overlap_days(a_start, a_end, period_start, period_end) > 0


def calculate_month(month_ref: str) -> List[Dict[str, Any]]:
    """
    Calculate monthly financial results per employee placement.
    - Entitlements are prorated by active days in month (supports mid-month start/stop).
    - Amounts with review_status='pending_review' are tracked separately and excluded from company margin/profit.
    - Bank transfers and recorded wages/refunds are separated by category in totals.
    """
    ensure_finance_schema()
    m_start, m_end, month_days = month_range(month_ref)
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        placements = [dict(r) for r in conn.execute(
            """SELECT p.*, e.full_name as employee_name, c.name as company_name
               FROM employee_placements p
               JOIN employees e ON e.id=p.employee_id
               JOIN companies c ON c.id=p.company_id
               WHERE date(p.start_date) <= date(?)
                 AND (p.end_date IS NULL OR date(p.end_date) >= date(?))
               ORDER BY p.id""",
            (m_end.isoformat(), m_start.isoformat())
        ).fetchall()]

        results = []
        live_placements = [p for p in placements if _active_days_for_placement(p, month_ref) > 0]
        fin_agreements = agr.load_active(conn, m_start, m_end)
        elig = agr.eligibility(fin_agreements, live_placements, m_start, m_end)
        for p in placements:
            active_days = _active_days_for_placement(p, month_ref)
            if active_days <= 0:
                continue
            ratio = active_days / month_days

            # Aggregate ledger totals for this placement/month
            tx_rows = [dict(r) for r in conn.execute(
                """SELECT category, review_status, amount FROM financial_transactions
                   WHERE month_ref=? AND placement_id=?""",
                (month_ref, p["id"])
            ).fetchall()]

            def sum_cat(cat, approved_only=False, pending_only=False):
                total = 0.0
                for t in tx_rows:
                    if t["category"] != cat:
                        continue
                    rs = t["review_status"]
                    if approved_only and rs != "approved":
                        continue
                    if pending_only and rs != "pending_review":
                        continue
                    total += float(t["amount"] or 0)
                return round(total, 2)

            client_agreed_total = sum_cat("client_agreed_amount", approved_only=True)
            recorded_wages_total = sum_cat("recorded_wage", approved_only=True)
            bank_transfers_actual_total = sum_cat("bank_transfer_actual", approved_only=True)
            refunds_returned_total = sum_cat("refund_returned", approved_only=True)
            external_expenses_total = sum_cat("external_expense", approved_only=True)
            pending_review_total = round(sum(float(t["amount"] or 0) for t in tx_rows if t["review_status"] == "pending_review"), 2)

            # Contractor entitlements based on active agreements in month, prorated by active days
            contractor_entitlements_total = 0.0
            contractor_lines = []
            pc_rows = [dict(r) for r in conn.execute(
                """SELECT * FROM placement_contractors WHERE placement_id=?""", (p["id"],)
            ).fetchall()]
            for pc in pc_rows:
                if pc.get("status") == "ended" and not pc.get("agreement_end"):
                    continue
                if not _is_agreement_active_on_period(pc["agreement_start"], pc.get("agreement_end"), m_start, m_end):
                    continue
                # overlap with placement active period inside month
                a_start = _parse(pc["agreement_start"])
                a_end = _parse(pc["agreement_end"]) if pc.get("agreement_end") else None
                p_start = _parse(p["start_date"])
                p_end = _parse(p["end_date"]) if p.get("end_date") else None
                eff_days = _overlap_days(max(a_start, p_start), min(a_end, p_end) if (a_end and p_end) else (a_end or p_end), m_start, m_end)
                if eff_days <= 0:
                    continue
                base = client_agreed_total if client_agreed_total > 0 else recorded_wages_total
                if pc["commission_type"] == "fixed":
                    due = float(pc["commission_value"]) * (eff_days / month_days)
                else:  # percentage
                    due = base * (float(pc["commission_value"]) / 100.0) * (eff_days / month_days)
                due = round(due, 2)
                contractor_entitlements_total += due
                contractor_lines.append({"contractor_id": pc["contractor_id"], "amount": due, "days": eff_days, "source": "placement_contractors",
                                         "source_id": pc["id"], "detail": f"اتفاق التعيين: {pc['commission_value']:g}{'%' if pc['commission_type'] == 'percentage' else ' ريال'} × {eff_days}/{month_days} يوم"})

            # Representative entitlements based on active agreements in month and (if linked) active company-rep relationship
            representative_entitlements_total = 0.0
            representative_lines = []
            pr_rows = [dict(r) for r in conn.execute(
                """SELECT pr.*, cr.relationship_start AS cr_start, cr.relationship_end AS cr_end, cr.status AS cr_status
                   FROM placement_representatives pr
                   LEFT JOIN company_representatives cr ON cr.id = pr.company_representative_id
                   WHERE pr.placement_id=?""", (p["id"],)
            ).fetchall()]
            for pr in pr_rows:
                if pr.get("status") == "ended" and not pr.get("agreement_end"):
                    continue
                if not _is_agreement_active_on_period(pr["agreement_start"], pr.get("agreement_end"), m_start, m_end):
                    continue
                # if linked to company_representative relationship, respect its end (no new entitlements after relationship end)
                rel_end = pr.get("cr_end")
                rel_start = pr.get("cr_start")
                if rel_start and not _is_agreement_active_on_period(rel_start, rel_end, m_start, m_end):
                    continue
                a_start = _parse(pr["agreement_start"])
                a_end = _parse(pr["agreement_end"]) if pr.get("agreement_end") else None
                p_start = _parse(p["start_date"])
                p_end = _parse(p["end_date"]) if p.get("end_date") else None
                # cap by company relationship end if present
                caps = [d for d in [a_end, p_end, _parse(rel_end) if rel_end else None] if d is not None]
                eff_end = min(caps) if caps else None
                eff_days = _overlap_days(max(a_start, p_start, _parse(rel_start) if rel_start else a_start), eff_end, m_start, m_end)
                if eff_days <= 0:
                    continue
                base = client_agreed_total if client_agreed_total > 0 else recorded_wages_total
                if pr["commission_type"] == "fixed":
                    due = float(pr["commission_value"]) * (eff_days / month_days)
                else:
                    due = base * (float(pr["commission_value"]) / 100.0) * (eff_days / month_days)
                due = round(due, 2)
                representative_entitlements_total += due
                representative_lines.append({"representative_id": pr["representative_id"], "amount": due, "days": eff_days, "source": "placement_representatives",
                                             "source_id": pr["id"], "detail": f"اتفاق التعيين: {pr['commission_value']:g}{'%' if pr['commission_type'] == 'percentage' else ' ريال'} × {eff_days}/{month_days} يوم"})

            # Approved company revenue basis: explicit approved revenue entries, else approved client agreed amounts minus refunds
            explicit_approved_revenue = sum_cat("approved_company_revenue", approved_only=True)
            approved_company_revenue_total = explicit_approved_revenue if explicit_approved_revenue > 0 else round(max(client_agreed_total - refunds_returned_total, 0), 2)

            # Flexible agreements (client / employee / group scope): fixed, per-employee or percentage
            bases = {"agreed": client_agreed_total, "after_refund": approved_company_revenue_total,
                     "surplus": round(approved_company_revenue_total - recorded_wages_total, 2),
                     "wage": recorded_wages_total,
                     "margin": round(approved_company_revenue_total - recorded_wages_total - external_expenses_total, 2)}
            for ln in agr.lines_for_placement(fin_agreements, elig, p, bases, month_ref):
                if ln["beneficiary_type"] == "contractor":
                    contractor_entitlements_total += ln["amount"]
                    contractor_lines.append(dict(ln, contractor_id=ln["beneficiary_id"]))
                else:
                    representative_entitlements_total += ln["amount"]
                    representative_lines.append(dict(ln, representative_id=ln["beneficiary_id"]))

            contractor_entitlements_total = round(contractor_entitlements_total, 2)
            representative_entitlements_total = round(representative_entitlements_total, 2)

            # Company margin excludes pending_review amounts entirely (not profit)
            company_margin = round(
                approved_company_revenue_total
                - recorded_wages_total
                - external_expenses_total
                - contractor_entitlements_total
                - representative_entitlements_total,
                2,
            )

            result = {
                "month_ref": month_ref,
                "employee_id": p["employee_id"],
                "employee_name": p.get("employee_name"),
                "company_id": p["company_id"],
                "company_name": p.get("company_name"),
                "placement_id": p["id"],
                "active_days": active_days,
                "month_days": month_days,
                "client_agreed_total": client_agreed_total,
                "recorded_wages_total": recorded_wages_total,
                "bank_transfers_actual_total": bank_transfers_actual_total,
                "refunds_returned_total": refunds_returned_total,
                "external_expenses_total": external_expenses_total,
                "contractor_entitlements_total": contractor_entitlements_total,
                "representative_entitlements_total": representative_entitlements_total,
                "approved_company_revenue_total": approved_company_revenue_total,
                "pending_review_total": pending_review_total,
                "company_margin": company_margin,
                "contractor_lines": contractor_lines,
                "representative_lines": representative_lines,
                "notes": "الحسابات حسب الاتفاقات الفعلية وتواريخ النشاط/التوقف؛ مبالغ قيد المراجعة مستبعدة من هامش/ربح الشركة."
            }
            results.append(result)

            # Per-party dues snapshot (kept in step with the monthly account; frozen when the month is approved)
            dues = {}
            def _add(pt, pid, amt):
                dues[(pt, pid)] = round(dues.get((pt, pid), 0.0) + float(amt), 2)
            if (p.get("flow_mode") or "direct") == "direct":
                # the client pays the employee directly: the employee owes the company the surplus (negative due),
                # and the company owes the client the refund (negative due = owed TO the client)
                _add("company", p["company_id"], -refunds_returned_total)
                _add("employee", p["employee_id"], recorded_wages_total - client_agreed_total)
            else:
                _add("company", p["company_id"], client_agreed_total - refunds_returned_total)
                _add("employee", p["employee_id"], recorded_wages_total)
            for ln in contractor_lines:
                _add("contractor", ln["contractor_id"], ln["amount"])
            for ln in representative_lines:
                _add("representative", ln["representative_id"], ln["amount"])

            # Upsert monthly result snapshot
            conn.execute(
                """INSERT INTO monthly_employee_accounts(
                    month_ref, employee_id, company_id, placement_id, active_days, month_days,
                    client_agreed_total, recorded_wages_total, bank_transfers_actual_total, refunds_returned_total,
                    external_expenses_total, contractor_entitlements_total, representative_entitlements_total,
                    approved_company_revenue_total, pending_review_total, company_margin, status, calculation_note, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'calculated', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(month_ref, placement_id) DO UPDATE SET
                    employee_id=excluded.employee_id, company_id=excluded.company_id, active_days=excluded.active_days, month_days=excluded.month_days,
                    client_agreed_total=excluded.client_agreed_total, recorded_wages_total=excluded.recorded_wages_total,
                    bank_transfers_actual_total=excluded.bank_transfers_actual_total, refunds_returned_total=excluded.refunds_returned_total,
                    external_expenses_total=excluded.external_expenses_total, contractor_entitlements_total=excluded.contractor_entitlements_total,
                    representative_entitlements_total=excluded.representative_entitlements_total, approved_company_revenue_total=excluded.approved_company_revenue_total,
                    pending_review_total=excluded.pending_review_total, company_margin=excluded.company_margin, calculation_note=excluded.calculation_note, updated_at=CURRENT_TIMESTAMP
                WHERE monthly_employee_accounts.status != 'approved'
                """,
                (
                    month_ref, p["employee_id"], p["company_id"], p["id"], active_days, month_days,
                    client_agreed_total, recorded_wages_total, bank_transfers_actual_total, refunds_returned_total,
                    external_expenses_total, contractor_entitlements_total, representative_entitlements_total,
                    approved_company_revenue_total, pending_review_total, company_margin, result["notes"]
                )
            )
            acct = conn.execute("SELECT status FROM monthly_employee_accounts WHERE month_ref=? AND placement_id=?",
                                (month_ref, p["id"])).fetchone()
            frozen = acct is not None and acct["status"] == "approved"
            if not frozen:
                conn.execute("DELETE FROM party_dues WHERE month_ref=? AND placement_id=?", (month_ref, p["id"]))
            for (pt, pid), amt in dues.items():
                # frozen month: only fill lines that never existed (one-time backfill), never overwrite
                conn.execute("INSERT OR IGNORE INTO party_dues(month_ref, placement_id, party_type, party_id, amount) VALUES (?,?,?,?,?)",
                             (month_ref, p["id"], pt, pid, amt))
            # how each commission number was reached (kept as history; rewritten only while the month is open)
            if not frozen:
                conn.execute("DELETE FROM agreement_calc_log WHERE month_ref=? AND placement_id=?", (month_ref, p["id"]))
            if not conn.execute("SELECT 1 FROM agreement_calc_log WHERE month_ref=? AND placement_id=? LIMIT 1", (month_ref, p["id"])).fetchone():
                for kind, lines in (("contractor", contractor_lines), ("representative", representative_lines)):
                    for ln in lines:
                        conn.execute(
                            "INSERT INTO agreement_calc_log(month_ref, placement_id, source, source_id, beneficiary_type, beneficiary_id, amount, detail) VALUES (?,?,?,?,?,?,?,?)",
                            (month_ref, p["id"], ln.get("source"), ln.get("source_id"), kind, ln[f"{kind}_id"], ln["amount"], ln.get("detail")))

        conn.commit()
        return results
    finally:
        conn.close()


def get_party_statement(party_type: str, party_id: int, month_ref: Optional[str] = None) -> List[Dict[str, Any]]:
    """Independent statement per party from ledger transactions."""
    ensure_finance_schema()
    conn = get_connection()
    try:
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM financial_transactions WHERE 1=1"
        params = []
        if party_type == "employee":
            q += " AND employee_id=?"
            params.append(party_id)
        elif party_type == "contractor":
            q += " AND contractor_id=?"
            params.append(party_id)
        elif party_type == "representative":
            q += " AND representative_id=?"
            params.append(party_id)
        elif party_type == "company":
            q += " AND company_id=?"
            params.append(party_id)
        else:
            q += " AND party_type=? AND party_id=?"
            params.extend([party_type, party_id])
        if month_ref:
            q += " AND month_ref=?"
            params.append(month_ref)
        q += " ORDER BY tx_date, id"
        rows = conn.execute(q, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
