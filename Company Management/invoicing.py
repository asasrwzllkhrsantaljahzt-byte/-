"""Client invoices built from the monthly engine (revenue actually earned).

These are INTERNAL invoices (a register + printable copy + Excel). They are not submitted to ZATCA/Fatoora:
the official tax e-invoice must still be issued from the accounting system that is connected to ZATCA.
An issued invoice is never edited or deleted (the database enforces it); a mistake is fixed by voiding it
with a reason and issuing a new one.
"""
import html
import io
from datetime import date

import pandas as pd

import app_settings
from audit import log_audit
from db import get_connection, query_all, query_one

INVOICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_no TEXT NOT NULL UNIQUE,
    company_id INTEGER NOT NULL,
    month_ref TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    subtotal NUMERIC NOT NULL CHECK (subtotal > 0),
    vat_rate NUMERIC NOT NULL CHECK (vat_rate >= 0 AND vat_rate <= 100),
    vat_amount NUMERIC NOT NULL CHECK (vat_amount >= 0),
    total NUMERIC NOT NULL CHECK (total > 0),
    status TEXT NOT NULL DEFAULT 'issued' CHECK (status IN ('issued', 'void')),
    void_reason TEXT,
    notes TEXT,
    seller_name TEXT NOT NULL,
    seller_tax_number TEXT NOT NULL,
    buyer_name TEXT NOT NULL,
    buyer_tax_number TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    placement_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    active_days INTEGER NOT NULL,
    month_days INTEGER NOT NULL,
    amount NUMERIC NOT NULL CHECK (amount > 0),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE RESTRICT
);
-- one live (not void) invoice per client per month
CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_live ON invoices(company_id, month_ref) WHERE status = 'issued';

CREATE TRIGGER IF NOT EXISTS trg_invoices_no_delete BEFORE DELETE ON invoices
BEGIN SELECT RAISE(ABORT, 'لا يجوز حذف الفواتير. ألغِ الفاتورة بسبب مكتوب وأصدر بدلاً منها فاتورة جديدة.'); END;

-- the only allowed change: issued -> void with a reason; every other column stays as issued
CREATE TRIGGER IF NOT EXISTS trg_invoices_only_void BEFORE UPDATE ON invoices
WHEN NOT (OLD.status = 'issued' AND NEW.status = 'void' AND TRIM(COALESCE(NEW.void_reason, '')) != ''
          AND NEW.invoice_no = OLD.invoice_no AND NEW.company_id = OLD.company_id AND NEW.month_ref = OLD.month_ref
          AND NEW.issue_date = OLD.issue_date AND NEW.subtotal = OLD.subtotal AND NEW.vat_rate = OLD.vat_rate
          AND NEW.vat_amount = OLD.vat_amount AND NEW.total = OLD.total
          AND NEW.seller_name = OLD.seller_name AND NEW.seller_tax_number = OLD.seller_tax_number
          AND NEW.buyer_name = OLD.buyer_name AND COALESCE(NEW.buyer_tax_number, '') = COALESCE(OLD.buyer_tax_number, ''))
BEGIN SELECT RAISE(ABORT, 'الفاتورة الصادرة لا تُعدَّل. يمكن فقط إلغاؤها مع كتابة السبب.'); END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_lines_no_update BEFORE UPDATE ON invoice_lines
BEGIN SELECT RAISE(ABORT, 'بنود الفاتورة لا تُعدَّل.'); END;
CREATE TRIGGER IF NOT EXISTS trg_invoice_lines_no_delete BEFORE DELETE ON invoice_lines
BEGIN SELECT RAISE(ABORT, 'بنود الفاتورة لا تُحذف.'); END;
"""


def ensure_invoice_schema() -> None:
    conn = get_connection()
    try:
        conn.executescript(INVOICE_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _r2(x) -> float:
    return round(float(x or 0) + 1e-9, 2)


def vat_rate() -> float:
    try:
        return float(app_settings.get("vat_rate"))
    except (TypeError, ValueError):
        return float(app_settings.DEFAULTS["vat_rate"])


def months_with_accounts(company_id: int) -> list:
    import hub_engine as E
    out = []
    for m in E.month_options():
        if any(c["company_id"] == company_id and c["revenue"] > 0 for c in E.compute_month(m, company_id)["companies"]):
            out.append(m)
    return out


def preview(company_id: int, month_ref: str) -> dict:
    """Lines + totals this invoice would have: the revenue actually earned per employee (what the client really paid for)."""
    import hub_engine as E
    res = E.compute_month(month_ref, company_id)
    lines = []
    for co in res["companies"]:
        for r in co["employees"]:
            if r["revenue"] > 0:
                lines.append({"employee_id": r["employee_id"], "placement_id": r["placement_id"], "full_name": r["employee"],
                              "active_days": r["days"], "month_days": r["month_days"], "amount": r["revenue"]})
    lines.sort(key=lambda l: l["full_name"])
    rate = vat_rate()
    subtotal = _r2(sum(float(l["amount"]) for l in lines))
    vat = _r2(subtotal * rate / 100)
    return {"lines": lines, "subtotal": subtotal, "vat_rate": rate, "vat_amount": vat, "total": _r2(subtotal + vat),
            "month_closed": bool(res.get("closed"))}


def _next_number(conn, year: int) -> str:
    prefix = f"INV-{year}-"
    row = conn.execute("SELECT MAX(CAST(SUBSTR(invoice_no, ?) AS INTEGER)) AS n FROM invoices WHERE invoice_no LIKE ?",
                       (len(prefix) + 1, prefix + "%")).fetchone()
    return f"{prefix}{int(row['n'] or 0) + 1:04d}"


def issue_invoice(company_id: int, month_ref: str, issue_date: date, notes: str = None, require_closed: bool = False) -> int:
    seller_name, seller_tax = app_settings.get("org_name").strip(), app_settings.get("org_tax_number").strip()
    if not seller_tax:
        raise ValueError("أدخل الرقم الضريبي للمنشأة من صفحة «الإعدادات» أولاً.")
    company = query_one("SELECT * FROM companies WHERE id=?", (company_id,))
    if not company:
        raise ValueError("الشركة غير موجودة.")
    pv = preview(company_id, month_ref)
    if not pv["lines"]:
        raise ValueError("لا توجد إيرادات فعلية لهذه الشركة في هذا الشهر (سجّل تحويلات العميل أولاً).")
    if require_closed and not pv["month_closed"]:
        raise ValueError("الشهر غير مقفل. أقفله من «مراجعة وإقفال الشهر» أولاً.")
    if query_one("SELECT invoice_no FROM invoices WHERE company_id=? AND month_ref=? AND status='issued'", (company_id, month_ref)):
        ex = query_one("SELECT invoice_no FROM invoices WHERE company_id=? AND month_ref=? AND status='issued'", (company_id, month_ref))
        raise ValueError(f"توجد فاتورة سارية لهذه الشركة والشهر ({ex['invoice_no']}). ألغِها أولاً إن أردت إصدار بديلة.")
    from audit import _current_username
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        number = _next_number(conn, issue_date.year)
        cur = conn.execute(
            """INSERT INTO invoices(invoice_no, company_id, month_ref, issue_date, subtotal, vat_rate, vat_amount, total, notes,
                                    seller_name, seller_tax_number, buyer_name, buyer_tax_number, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (number, company_id, month_ref, issue_date.strftime("%Y-%m-%d"), pv["subtotal"], pv["vat_rate"], pv["vat_amount"],
             pv["total"], (notes or "").strip() or None, seller_name, seller_tax, company["name"], company["tax_number"],
             _current_username()))
        iid = cur.lastrowid
        for l in pv["lines"]:
            conn.execute(
                """INSERT INTO invoice_lines(invoice_id, employee_id, placement_id, description, active_days, month_days, amount)
                   VALUES (?,?,?,?,?,?,?)""",
                (iid, l["employee_id"], l["placement_id"], f"خدمات الموظف {l['full_name']} — {month_ref}",
                 l["active_days"], l["month_days"], _r2(l["amount"])))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log_audit("invoices", iid, "INSERT", None, {"invoice_no": number, "company_id": company_id, "month_ref": month_ref,
                                                 "total": pv["total"]}, note=f"إصدار فاتورة {number}")
    return iid


def void_invoice(invoice_id: int, reason: str) -> str:
    inv = query_one("SELECT * FROM invoices WHERE id=?", (invoice_id,))
    if not inv:
        raise ValueError("الفاتورة غير موجودة.")
    if inv["status"] == "void":
        raise ValueError("الفاتورة ملغاة بالفعل.")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("سبب الإلغاء مطلوب.")
    conn = get_connection()
    try:
        conn.execute("UPDATE invoices SET status='void', void_reason=? WHERE id=?", (reason, invoice_id))
        conn.commit()
    finally:
        conn.close()
    log_audit("invoices", invoice_id, "STATUS_CHANGE", {"status": "issued"}, {"status": "void", "void_reason": reason},
              note=f"إلغاء فاتورة {inv['invoice_no']}")
    return f"تم إلغاء الفاتورة {inv['invoice_no']}."


def list_invoices(company_id=None, month_ref=None, status=None) -> list:
    sql = "SELECT * FROM invoices WHERE 1=1"
    params = []
    for col, v in (("company_id", company_id), ("month_ref", month_ref), ("status", status)):
        if v:
            sql += f" AND {col}=?"
            params.append(v)
    return query_all(sql + " ORDER BY id DESC", tuple(params))


def invoice_lines(invoice_id: int) -> list:
    return query_all("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id", (invoice_id,))


def invoice_excel(invoice_id: int) -> bytes:
    inv = query_one("SELECT * FROM invoices WHERE id=?", (invoice_id,))
    lines = pd.DataFrame(invoice_lines(invoice_id))[["description", "active_days", "month_days", "amount"]]
    lines.columns = ["البيان", "أيام العمل", "أيام الشهر", "المبلغ"]
    head = pd.DataFrame([("رقم الفاتورة", inv["invoice_no"]), ("التاريخ", inv["issue_date"]), ("الشهر", inv["month_ref"]),
                         ("البائع", inv["seller_name"]), ("الرقم الضريبي للبائع", inv["seller_tax_number"]),
                         ("العميل", inv["buyer_name"]), ("الرقم الضريبي للعميل", inv["buyer_tax_number"] or ""),
                         ("الإجمالي قبل الضريبة", inv["subtotal"]), (f"ضريبة القيمة المضافة {inv['vat_rate']:g}%", inv["vat_amount"]),
                         ("الإجمالي شامل الضريبة", inv["total"]), ("الحالة", "ملغاة: " + inv["void_reason"] if inv["status"] == "void" else "سارية")],
                        columns=["الحقل", "القيمة"])
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        head.to_excel(w, sheet_name="الفاتورة", index=False)
        lines.to_excel(w, sheet_name="البنود", index=False)
    return out.getvalue()


def invoice_html(invoice_id: int) -> str:
    import branding
    logo = branding.logo_img_html(52)
    inv = query_one("SELECT * FROM invoices WHERE id=?", (invoice_id,))
    e = lambda v: html.escape(str(v if v is not None else ""))
    rows = "".join(
        f"<tr><td>{i}</td><td>{e(l['description'])}</td><td>{l['active_days']}/{l['month_days']}</td><td class=n>{float(l['amount']):,.2f}</td></tr>"
        for i, l in enumerate(invoice_lines(invoice_id), 1))
    void = f"<div class=void>ملغاة — {e(inv['void_reason'])}</div>" if inv["status"] == "void" else ""
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{e(inv['invoice_no'])}</title>
<style>body{{font-family:Tahoma,Arial,sans-serif;margin:32px;color:#111}}h1{{margin:0 0 4px}}table{{width:100%;border-collapse:collapse;margin-top:16px}}
th,td{{border:1px solid #999;padding:6px 8px;text-align:right}}th{{background:#eee}}td.n{{text-align:left}}.meta{{display:flex;justify-content:space-between;gap:24px;margin-top:12px}}
.tot{{width:50%;margin-right:auto}}.void{{color:#b00;font-size:22px;font-weight:bold;border:3px solid #b00;display:inline-block;padding:4px 12px;margin:8px 0}}
.note{{margin-top:24px;font-size:12px;color:#555}}</style></head><body>
<div>{logo}</div><h1>فاتورة ضريبية — نسخة داخلية</h1><div>رقم الفاتورة: <b>{e(inv['invoice_no'])}</b> &nbsp; التاريخ: {e(inv['issue_date'])} &nbsp; الشهر: {e(inv['month_ref'])}</div>{void}
<div class=meta><div><b>البائع</b><br>{e(inv['seller_name'])}<br>الرقم الضريبي: {e(inv['seller_tax_number'])}</div>
<div><b>العميل</b><br>{e(inv['buyer_name'])}<br>الرقم الضريبي: {e(inv['buyer_tax_number'] or '—')}</div></div>
<table><tr><th>#</th><th>البيان</th><th>أيام العمل</th><th>المبلغ (ر.س)</th></tr>{rows}</table>
<table class=tot><tr><td>الإجمالي قبل الضريبة</td><td class=n>{float(inv['subtotal']):,.2f}</td></tr>
<tr><td>ضريبة القيمة المضافة {float(inv['vat_rate']):g}%</td><td class=n>{float(inv['vat_amount']):,.2f}</td></tr>
<tr><th>الإجمالي شامل الضريبة</th><th class=n>{float(inv['total']):,.2f}</th></tr></table>
{f"<p>ملاحظات: {e(inv['notes'])}</p>" if inv['notes'] else ""}
<p class=note>هذه نسخة داخلية من سجل الفواتير ولا تُغني عن الفاتورة الإلكترونية المعتمدة من هيئة الزكاة والضريبة والجمارك، والتي تُصدر من النظام المحاسبي المرتبط بالهيئة.</p>
</body></html>"""
