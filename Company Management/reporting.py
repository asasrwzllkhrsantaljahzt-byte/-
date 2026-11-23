import io
from datetime import date
import pandas as pd
from db import query_all, query_one, get_connection
from finance_engine import ensure_finance_schema, calculate_month


def ensure_ready():
    ensure_finance_schema()


def _df(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def active_employees_count():
    ensure_ready()
    # employees with at least one active placement (end_date null or >= today and status active)
    row = query_one(
        """SELECT COUNT(DISTINCT e.id) AS c
           FROM employees e
           JOIN employee_placements p ON p.employee_id=e.id
           WHERE p.status='active' AND (p.end_date IS NULL OR date(p.end_date) >= date('now'))"""
    )
    return (row or {}).get("c", 0)


def employees_per_client():
    ensure_ready()
    rows = query_all(
        """SELECT c.id AS company_id, c.name AS company_name, COUNT(DISTINCT p.employee_id) AS active_employees
           FROM companies c
           LEFT JOIN employee_placements p ON p.company_id=c.id AND p.status='active' AND (p.end_date IS NULL OR date(p.end_date) >= date('now'))
           GROUP BY c.id, c.name
           ORDER BY active_employees DESC, c.name"""
    )
    return _df(rows)


def monthly_results(month_ref=None):
    ensure_ready()
    q = "SELECT m.*, e.full_name AS employee_name, c.name AS company_name FROM monthly_employee_accounts m JOIN employees e ON e.id=m.employee_id JOIN companies c ON c.id=m.company_id"
    params = []
    if month_ref:
        q += " WHERE m.month_ref=?"
        params.append(month_ref)
    q += " ORDER BY m.month_ref DESC, c.name, e.full_name"
    return _df(query_all(q, tuple(params)))


def monthly_summary(month_ref=None):
    ensure_ready()
    q = """
        SELECT month_ref,
               COUNT(*) AS records,
               COALESCE(SUM(active_days),0) AS active_days_sum,
               COALESCE(SUM(client_agreed_total),0) AS client_agreed_total,
               COALESCE(SUM(recorded_wages_total),0) AS recorded_wages_total,
               COALESCE(SUM(bank_transfers_actual_total),0) AS bank_transfers_actual_total,
               COALESCE(SUM(refunds_returned_total),0) AS refunds_returned_total,
               COALESCE(SUM(external_expenses_total),0) AS external_expenses_total,
               COALESCE(SUM(contractor_entitlements_total),0) AS contractor_entitlements_total,
               COALESCE(SUM(representative_entitlements_total),0) AS representative_entitlements_total,
               COALESCE(SUM(approved_company_revenue_total),0) AS approved_company_revenue_total,
               COALESCE(SUM(pending_review_total),0) AS pending_review_total,
               COALESCE(SUM(company_margin),0) AS company_margin
        FROM monthly_employee_accounts
    """
    params = []
    if month_ref:
        q += " WHERE month_ref=?"
        params.append(month_ref)
    q += " GROUP BY month_ref ORDER BY month_ref"
    return _df(query_all(q, tuple(params)))


def yearly_summary(year=None):
    df = monthly_summary()
    if df.empty:
        return df
    df["year"] = df["month_ref"].astype(str).str.slice(0,4)
    if year:
        df = df[df["year"] == str(year)]
    if df.empty:
        return df
    num_cols = [c for c in df.columns if c not in ("month_ref","year")]
    out = df.groupby("year", as_index=False)[num_cols].sum(numeric_only=True)
    return out


def entitlements_by_contractor(month_ref=None):
    ensure_ready()
    # prefer computed monthly results joined via placement_contractors proportions approximation not stored per line in snapshot,
    # so derive from transactions if present else from monthly accounts distributed is complex; use transactions + fallback note.
    q = """
        SELECT c.id AS contractor_id, c.name AS contractor_name,
               COALESCE(SUM(CASE WHEN ft.category='contractor_entitlement' AND ft.review_status='approved' THEN ft.amount ELSE 0 END),0) AS entitlement_tx,
               0 AS fallback
        FROM contractors c
        LEFT JOIN financial_transactions ft ON ft.contractor_id=c.id
    """
    params = []
    if month_ref:
        q += " AND ft.month_ref=?"
        params.append(month_ref)
    q += " GROUP BY c.id, c.name ORDER BY entitlement_tx DESC, c.name"
    df = _df(query_all(q, tuple(params)))
    # fallback from monthly aggregates proportionally not exact per contractor; supplement by total due context via placements
    return df


def entitlements_by_representative(month_ref=None):
    ensure_ready()
    q = """
        SELECT r.id AS representative_id, r.name AS representative_name,
               COALESCE(SUM(CASE WHEN ft.category='representative_entitlement' AND ft.review_status='approved' THEN ft.amount ELSE 0 END),0) AS entitlement_tx
        FROM representatives r
        LEFT JOIN financial_transactions ft ON ft.representative_id=r.id
    """
    params = []
    if month_ref:
        q += " AND ft.month_ref=?"
        params.append(month_ref)
    q += " GROUP BY r.id, r.name ORDER BY entitlement_tx DESC, r.name"
    return _df(query_all(q, tuple(params)))


def collections_payments_expenses(month_ref=None):
    ensure_ready()
    q = """
        SELECT month_ref,
          COALESCE(SUM(CASE WHEN review_status='approved' AND direction='in' AND category IN ('client_agreed_amount','approved_company_revenue','bank_transfer_actual','other') THEN amount ELSE 0 END),0) AS collected_in_approved,
          COALESCE(SUM(CASE WHEN review_status='approved' AND direction='out' AND category IN ('bank_transfer_actual','recorded_wage','external_expense','contractor_entitlement','representative_entitlement','refund_returned','other') THEN amount ELSE 0 END),0) AS paid_out_approved,
          COALESCE(SUM(CASE WHEN review_status='approved' AND category='external_expense' THEN amount ELSE 0 END),0) AS expenses_approved,
          COALESCE(SUM(CASE WHEN review_status='pending_review' THEN amount ELSE 0 END),0) AS pending_review
        FROM financial_transactions
    """
    params = []
    if month_ref:
        q += " WHERE month_ref=?"
        params.append(month_ref)
    q += " GROUP BY month_ref ORDER BY month_ref"
    return _df(query_all(q, tuple(params)))


def obligations_summary(month_ref=None):
    ms = monthly_summary(month_ref)
    if ms.empty:
        return ms
    cols = ["month_ref","contractor_entitlements_total","representative_entitlements_total","recorded_wages_total","external_expenses_total","pending_review_total","company_margin"]
    for c in cols:
        if c not in ms.columns:
            ms[c] = 0
    ms["total_obligations_est"] = ms["contractor_entitlements_total"].fillna(0)+ms["representative_entitlements_total"].fillna(0)+ms["recorded_wages_total"].fillna(0)+ms["external_expenses_total"].fillna(0)
    return ms[["month_ref","contractor_entitlements_total","representative_entitlements_total","recorded_wages_total","external_expenses_total","total_obligations_est","pending_review_total","company_margin"]]


def kpis(month_ref=None):
    ensure_ready()
    ms = monthly_summary(month_ref)
    if ms.empty:
        totals = {k:0 for k in ["approved_company_revenue_total","company_margin","contractor_entitlements_total","representative_entitlements_total","external_expenses_total","bank_transfers_actual_total","recorded_wages_total","pending_review_total"]}
    else:
        row = ms.sum(numeric_only=True)
        totals = {k: float(row.get(k,0) or 0) for k in ["approved_company_revenue_total","company_margin","contractor_entitlements_total","representative_entitlements_total","external_expenses_total","bank_transfers_actual_total","recorded_wages_total","pending_review_total"]}
    return {
        "active_employees": active_employees_count(),
        "approved_revenue": totals["approved_company_revenue_total"],
        "approved_margin": totals["company_margin"],
        "contractor_dues": totals["contractor_entitlements_total"],
        "representative_dues": totals["representative_entitlements_total"],
        "expenses": totals["external_expenses_total"],
        "actual_bank_transfers": totals["bank_transfers_actual_total"],
        "recorded_wages": totals["recorded_wages_total"],
        "pending_review": totals["pending_review_total"],
    }


def company_summary(month_ref=None):
    """Whole-company picture: revenue, refunds, commissions, expenses (linked and general), margin, uncollected, unpaid."""
    import vouchers as V
    ensure_ready()
    w, p = "", ()
    if month_ref:
        w, p = " WHERE month_ref=?", (month_ref,)
    from db import query_one as q1
    r = q1(f"""SELECT COALESCE(SUM(approved_company_revenue_total),0) rev, COALESCE(SUM(refunds_returned_total),0) refunds,
                      COALESCE(SUM(recorded_wages_total),0) wages,
                      COALESCE(SUM(contractor_entitlements_total),0) con, COALESCE(SUM(representative_entitlements_total),0) rep,
                      COALESCE(SUM(external_expenses_total),0) exp_linked, COALESCE(SUM(company_margin),0) margin
               FROM monthly_employee_accounts{w}""", p)
    gw = " AND month_ref=?" if month_ref else ""
    g = q1(f"""SELECT COALESCE(SUM(amount),0) s FROM financial_transactions WHERE category='external_expense' AND review_status='approved'
               AND placement_id IS NULL{gw}""", p)
    unc = liab = 0.0
    for pt in ("company", "employee", "contractor", "representative"):
        for b in V.party_balances(pt, month_ref):
            if pt == "company":
                unc += max(b["balance"], 0); liab += max(-b["balance"], 0)
            elif pt == "employee":
                unc += max(-b["balance"], 0); liab += max(b["balance"], 0)
            else:
                liab += max(b["balance"], 0)
    general = float(g["s"] or 0)
    return {"active_employees": active_employees_count(), "revenue": float(r["rev"]), "refunds": float(r["refunds"]), "wages": float(r["wages"]),
            "contractor_commissions": float(r["con"]), "representative_commissions": float(r["rep"]),
            "linked_expenses": float(r["exp_linked"]), "general_expenses": general,
            "margin_before_general": float(r["margin"]), "net_margin": round(float(r["margin"]) - general, 2),
            "uncollected": round(unc, 2), "unpaid": round(liab, 2)}


def export_excel(dfs: dict) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, df in dfs.items():
            safe = (name or "Sheet")[:31]
            (df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)).to_excel(writer, sheet_name=safe, index=False)
    return out.getvalue()


def try_export_pdf(title: str, df: pd.DataFrame) -> tuple[bytes | None, str | None]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
    except Exception as e:
        return None, str(e)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elems = [Paragraph(title, styles['Title']), Spacer(1, 8)]
    if df is None or df.empty:
        elems.append(Paragraph("No data", styles['Normal']))
    else:
        data = [list(df.columns)] + df.fillna("").astype(str).values.tolist()
        # limit columns/rows for readability
        data = [r[:12] for r in data[:60]]
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e5e7eb')),
            ('GRID',(0,0),(-1,-1),0.25,colors.grey),
            ('FONTSIZE',(0,0),(-1,-1),7),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
        ]))
        elems.append(table)
    doc.build(elems)
    return buf.getvalue(), None
