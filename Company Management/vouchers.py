"""Receipt / payment vouchers (إذن استلام / إذن صرف) for every kind of party + the per-party account.

A voucher records money that actually moved. An issued voucher is never edited or deleted (enforced by the
database); a mistake is fixed by voiding it with a written reason and issuing a new one.
Party account: due (live from the monthly engine, `hub_accounts`) minus what was settled by vouchers.
"""
import html
from datetime import date

import app_settings
from audit import log_audit, _current_username
from db import get_connection, query_all, query_one

KIND_AR = {"receipt": "إذن استلام", "payment": "إذن صرف"}
KIND_PREFIX = {"receipt": "RCV", "payment": "PAY"}
PARTY_AR = {"company": "شركة عميلة", "contractor": "متعهد", "representative": "مندوب", "employee": "موظف", "other": "جهة أخرى"}
PARTY_TABLE = {"company": ("companies", "name"), "contractor": ("contractors", "name"),
               "representative": ("representatives", "name"), "employee": ("employees", "full_name")}
METHOD_AR = {"cash": "نقداً", "transfer": "حوالة بنكية", "cheque": "شيك", "other": "أخرى"}
STATUS_AR = {"issued": "سارٍ", "void": "ملغى"}
ENTRY_CATEGORY_AR = {
    "settlement": "تسوية مستحقات",
    "operating_expense": "مصروف تشغيلي",
    "owner_draw": "مسحوبات صاحب الشركة",
}

VOUCHERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS vouchers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_no TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('receipt','payment')),
    voucher_date TEXT NOT NULL,
    party_type TEXT NOT NULL CHECK (party_type IN ('company','contractor','representative','employee','other')),
    party_id INTEGER,
    party_name TEXT NOT NULL,
    amount NUMERIC NOT NULL CHECK (amount > 0),
    method TEXT NOT NULL DEFAULT 'cash' CHECK (method IN ('cash','transfer','cheque','other')),
    reference TEXT,
    month_ref TEXT,
    description TEXT,
    entry_category TEXT NOT NULL DEFAULT 'settlement'
        CHECK (entry_category IN ('settlement','operating_expense','owner_draw')),
    status TEXT NOT NULL DEFAULT 'issued' CHECK (status IN ('issued','void')),
    void_reason TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((party_type = 'other' AND party_id IS NULL) OR (party_type != 'other' AND party_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_vouchers_party ON vouchers(party_type, party_id, status);

CREATE TRIGGER IF NOT EXISTS trg_vouchers_party_exists BEFORE INSERT ON vouchers
WHEN NEW.party_type != 'other' AND NOT (
    (NEW.party_type='company' AND EXISTS (SELECT 1 FROM companies WHERE id=NEW.party_id)) OR
    (NEW.party_type='contractor' AND EXISTS (SELECT 1 FROM contractors WHERE id=NEW.party_id)) OR
    (NEW.party_type='representative' AND EXISTS (SELECT 1 FROM representatives WHERE id=NEW.party_id)) OR
    (NEW.party_type='employee' AND EXISTS (SELECT 1 FROM employees WHERE id=NEW.party_id)))
BEGIN SELECT RAISE(ABORT, 'الجهة المحددة غير موجودة في النظام.'); END;

CREATE TRIGGER IF NOT EXISTS trg_vouchers_no_delete BEFORE DELETE ON vouchers
BEGIN SELECT RAISE(ABORT, 'لا تُحذف الإذون. ألغِ الإذن بسبب مكتوب وأصدر بدلاً منه إذناً جديداً.'); END;

CREATE TRIGGER IF NOT EXISTS trg_vouchers_only_void BEFORE UPDATE ON vouchers
WHEN NOT (OLD.status = 'issued' AND NEW.status = 'void' AND TRIM(COALESCE(NEW.void_reason,'')) != ''
          AND NEW.voucher_no = OLD.voucher_no AND NEW.kind = OLD.kind AND NEW.voucher_date = OLD.voucher_date
          AND NEW.party_type = OLD.party_type AND COALESCE(NEW.party_id,0) = COALESCE(OLD.party_id,0)
          AND NEW.party_name = OLD.party_name AND NEW.amount = OLD.amount AND NEW.method = OLD.method)
BEGIN SELECT RAISE(ABORT, 'الإذن الصادر لا يُعدَّل. يمكن فقط إلغاؤه مع كتابة السبب.'); END;
"""


def ensure_vouchers_schema():
    conn = get_connection()
    try:
        conn.executescript(VOUCHERS_SCHEMA)
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(vouchers)").fetchall()}
        if "entry_category" not in columns:
            conn.execute("ALTER TABLE vouchers ADD COLUMN entry_category TEXT NOT NULL DEFAULT 'settlement'")
        conn.commit()
    finally:
        conn.close()


def _iso(d):
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)


def party_name(party_type, party_id):
    t = PARTY_TABLE.get(party_type)
    if not t:
        return None
    r = query_one(f"SELECT {t[1]} AS n FROM {t[0]} WHERE id=?", (party_id,))
    return r["n"] if r else None


def _next_number(conn, kind, year):
    prefix = f"{KIND_PREFIX[kind]}-{year}-"
    r = conn.execute("SELECT MAX(CAST(SUBSTR(voucher_no, ?) AS INTEGER)) AS n FROM vouchers WHERE voucher_no LIKE ?",
                     (len(prefix) + 1, prefix + "%")).fetchone()
    return f"{prefix}{int(r['n'] or 0) + 1:04d}"


def issue_voucher(kind, voucher_date, party_type, party_id, amount, method="cash", reference=None, month_ref=None,
                  description=None, other_name=None, entry_category="settlement") -> int:
    if kind not in KIND_AR:
        raise ValueError("نوع الإذن غير صحيح.")
    if party_type not in PARTY_AR:
        raise ValueError("نوع الجهة غير صحيح.")
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("المبلغ غير صحيح.")
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر.")
    if method not in METHOD_AR:
        raise ValueError("طريقة الدفع غير صحيحة.")
    if entry_category not in ENTRY_CATEGORY_AR:
        raise ValueError("تصنيف البند غير صحيح.")
    if kind != "payment" or party_type != "other":
        entry_category = "settlement"
    if party_type == "other":
        name, party_id = (other_name or "").strip(), None
        if not name:
            raise ValueError("اكتب اسم الجهة.")
    else:
        name = party_name(party_type, party_id)
        if not name:
            raise ValueError("اختر الجهة.")
    month_ref = (month_ref or "").strip() or None
    if month_ref and (len(month_ref) != 7 or month_ref[4] != "-" or not (month_ref[:4] + month_ref[5:]).isdigit()):
        raise ValueError("الشهر بصيغة YYYY-MM.")
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        no = _next_number(conn, kind, voucher_date.year)
        cur = conn.execute(
            """INSERT INTO vouchers(voucher_no, kind, voucher_date, party_type, party_id, party_name, amount, method, reference,
                                    month_ref, description, entry_category, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (no, kind, _iso(voucher_date), party_type, party_id, name, amount, method, (reference or "").strip() or None,
             month_ref, (description or "").strip() or None, entry_category, _current_username()))
        vid = cur.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log_audit("vouchers", vid, "INSERT", None, {"voucher_no": no, "kind": kind, "party_type": party_type, "party_id": party_id,
                                                 "amount": amount, "entry_category": entry_category}, note=f"{KIND_AR[kind]} {no}")
    return vid


def replace_voucher(voucher_id, voucher_date, amount, method, reference, month_ref, description, entry_category, reason,
                    other_name=None):
    old = query_one("SELECT * FROM vouchers WHERE id=?", (voucher_id,))
    if not old:
        raise ValueError("الإذن غير موجود.")
    if old["status"] != "issued":
        raise ValueError("لا يمكن تعديل إذن ملغى.")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("سبب التعديل مطلوب.")
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("المبلغ غير صحيح.")
    if amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر.")
    if method not in METHOD_AR:
        raise ValueError("طريقة الدفع غير صحيحة.")
    if entry_category not in ENTRY_CATEGORY_AR:
        raise ValueError("تصنيف البند غير صحيح.")
    if old["kind"] != "payment" or old["party_type"] != "other":
        entry_category = "settlement"
    name = ((other_name if other_name is not None else old["party_name"]) or "").strip() if old["party_type"] == "other" else party_name(old["party_type"], old["party_id"])
    if not name:
        raise ValueError("الجهة المحددة غير موجودة.")
    month_ref = (month_ref or "").strip() or None
    if month_ref and (len(month_ref) != 7 or month_ref[4] != "-" or not (month_ref[:4] + month_ref[5:]).isdigit()):
        raise ValueError("الشهر بصيغة YYYY-MM.")

    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM vouchers WHERE id=?", (voucher_id,)).fetchone()
        if not current or current["status"] != "issued":
            raise ValueError("تغيّر الإذن أثناء التعديل. حدّث الصفحة ثم أعد المحاولة.")
        conn.execute("UPDATE vouchers SET status='void', void_reason=? WHERE id=?", (reason, voucher_id))
        no = _next_number(conn, old["kind"], voucher_date.year)
        cur = conn.execute(
            """INSERT INTO vouchers(voucher_no, kind, voucher_date, party_type, party_id, party_name, amount, method, reference,
                                    month_ref, description, entry_category, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (no, old["kind"], _iso(voucher_date), old["party_type"], old["party_id"], name, amount, method,
             (reference or "").strip() or None, month_ref, (description or "").strip() or None, entry_category,
             _current_username()))
        new_id = cur.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log_audit("vouchers", voucher_id, "STATUS_CHANGE", {"status": "issued"},
              {"status": "void", "void_reason": reason}, note=f"تصحيح {KIND_AR[old['kind']]} {old['voucher_no']}")
    log_audit("vouchers", new_id, "INSERT", None, {"voucher_no": no, "kind": old["kind"],
              "party_type": old["party_type"], "party_id": old["party_id"], "amount": amount,
              "entry_category": entry_category}, note=f"بديل {old['voucher_no']}")
    return new_id


def void_voucher(voucher_id, reason) -> str:
    v = query_one("SELECT * FROM vouchers WHERE id=?", (voucher_id,))
    if not v:
        raise ValueError("الإذن غير موجود.")
    if v["status"] == "void":
        raise ValueError("الإذن ملغى بالفعل.")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("سبب الإلغاء مطلوب.")
    conn = get_connection()
    try:
        conn.execute("UPDATE vouchers SET status='void', void_reason=? WHERE id=?", (reason, voucher_id))
        conn.commit()
    finally:
        conn.close()
    log_audit("vouchers", voucher_id, "STATUS_CHANGE", {"status": "issued"}, {"status": "void", "void_reason": reason},
              note=f"إلغاء {KIND_AR[v['kind']]} {v['voucher_no']}")
    return f"تم إلغاء {v['voucher_no']}."


def list_vouchers(kind=None, party_type=None, party_id=None, status=None, month_ref=None):
    sql, params = "SELECT * FROM vouchers WHERE 1=1", []
    for col, v in (("kind", kind), ("party_type", party_type), ("party_id", party_id), ("status", status), ("month_ref", month_ref)):
        if v:
            sql += f" AND {col}=?"
            params.append(v)
    return query_all(sql + " ORDER BY voucher_date DESC, id DESC", tuple(params))


# ------------------------------------------------------------------ party account (live from the monthly engine)
# company  : the company owes the client the REFUND            -> settled by payment vouchers
# employee : the employee owes the company what she returns     -> settled by receipt vouchers
# others   : the company owes the contractor / external / rep   -> settled by payment vouchers
def inbound_kind(party_type) -> str:
    return "receipt" if party_type == "employee" else "payment"


def voucher_month(v) -> str:
    return (v["month_ref"] or "").strip() or (v["voucher_date"] or "")[:7]


def other_payment_totals() -> dict:
    totals = {}
    rows = query_all("""SELECT * FROM vouchers WHERE kind='payment' AND party_type='other' AND status='issued'""")
    for row in rows:
        month = voucher_month(row)
        bucket = totals.setdefault(month, {"operating_expense": 0.0, "owner_draw": 0.0})
        category = row["entry_category"] or "settlement"
        if category in bucket:
            bucket[category] += float(row["amount"])
    return {month: {key: round(value, 2) for key, value in values.items()} for month, values in totals.items()}


def balance_phrase(party_type, balance) -> str:
    b = round(float(balance or 0), 2)
    a = f"{abs(b):,.2f}"
    if abs(b) < 0.005:
        return "مسدَّد — لا رصيد"
    if party_type == "company":
        return f"للعميل {a} (مردود مستحق له على الشركة)" if b > 0 else f"صُرف للعميل زيادة {a}"
    if party_type == "employee":
        return f"على الموظفة {a} تعيدها للشركة" if b > 0 else f"استُلم منها زيادة {a}"
    return f"له {a} على الشركة" if b > 0 else f"صُرف له زيادة {a}"


def _settled(vs, party_type) -> float:
    inb = inbound_kind(party_type)
    return round(sum(float(v["amount"]) for v in vs if v["kind"] == inb)
                 - sum(float(v["amount"]) for v in vs if v["kind"] != inb), 2)


def party_account(party_type, party_id) -> dict:
    import hub_accounts as HA
    if party_type not in PARTY_TABLE:
        raise ValueError("الحساب متاح للشركات والموظفين والمتعهدين والمندوبين فقط.")
    dues = HA.dues_of(party_type, party_id)
    due_rows = [{"month_ref": m, "due": d} for m, d in sorted(dues.items()) if abs(d) > 0.004]
    vs = query_all("SELECT * FROM vouchers WHERE party_type=? AND party_id=? AND status='issued' ORDER BY voucher_date, id",
                   (party_type, party_id))
    settled = _settled(vs, party_type)
    due = round(sum(r["due"] for r in due_rows), 2)
    labels = HA.LABELS[party_type]
    return {"party_type": party_type, "party_id": party_id, "due": due, "settled": settled, "balance": round(due - settled, 2),
            "by_month": due_rows, "vouchers": vs, "note": balance_phrase(party_type, round(due - settled, 2)),
            "due_label": labels[0], "settled_label": labels[1], "balance_label": labels[2]}


def statement_rows(party_type, party_id) -> list:
    acc = party_account(party_type, party_id)
    ev = []
    for r in acc["by_month"]:
        ev.append((r["month_ref"] + "-99", 0, f"مستحق شهر {r['month_ref']}", float(r["due"]), 0.0))
    inb = inbound_kind(party_type)
    for v in acc["vouchers"]:
        sign = 1 if v["kind"] == inb else -1
        ev.append((v["voucher_date"], 1, f"{KIND_AR[v['kind']]} {v['voucher_no']}", 0.0, sign * float(v["amount"])))
    ev.sort(key=lambda e: (e[0], e[1]))
    out, bal = [], 0.0
    for d, _, text, due, paid in ev:
        bal = round(bal + due - paid, 2)
        out.append({"التاريخ": d[:10] if not d.endswith("-99") else d[:7], "البيان": text, "مستحق": due or None, "مسدد": paid or None, "الرصيد": bal})
    return out


def relations(party_type, party_id) -> list:
    """Who this party is linked to (company hub: placements, contractor/external, representative terms)."""
    out = []
    def add(kind, name, rel, since, until, status):
        out.append({"النوع": kind, "الجهة": name, "العلاقة": rel, "من": since or "", "إلى": until or "مفتوح", "الحالة": status})
    P = {"active": "نشط", "ended": "مستبعد/منتهٍ", "suspended": "موقوف"}
    if party_type == "company":
        for r in query_all("""SELECT e.full_name n, p.start_date s, p.end_date e, p.status st FROM employee_placements p
                              JOIN employees e ON e.id=p.employee_id WHERE p.company_id=? ORDER BY p.id DESC""", (party_id,)):
            add("موظف", r["n"], "يعمل لديها", r["s"], r["e"], P.get(r["st"], r["st"]))
        for r in query_all("""SELECT r.name n, t.start_date s, t.end_date e, t.percent pc FROM company_rep_terms t
                              JOIN representatives r ON r.id=t.representative_id WHERE t.company_id=? ORDER BY t.start_date DESC""", (party_id,)):
            add("مندوب", r["n"], f"مندوبها ({float(r['pc']):g}% من صافيها)", r["s"], r["e"], "ساري" if not r["e"] else "منتهٍ")
    elif party_type == "employee":
        for r in query_all("""SELECT c.name n, p.start_date s, p.end_date e, p.status st FROM employee_placements p
                              JOIN companies c ON c.id=p.company_id WHERE p.employee_id=? ORDER BY p.id DESC""", (party_id,)):
            add("شركة عميلة", r["n"], "تعمل لديها", r["s"], r["e"], P.get(r["st"], r["st"]))
    elif party_type == "contractor":
        for r in query_all("""SELECT e.full_name en, c.name cn, p.start_date s, p.end_date e, p.status st, p.contractor_commission v
                              FROM employee_placements p JOIN employees e ON e.id=p.employee_id JOIN companies c ON c.id=p.company_id
                              WHERE p.contractor_id=?""", (party_id,)):
            add("موظف", r["en"], f"عمولة ثابتة {float(r['v'] or 0):g} — لدى {r['cn']}", r["s"], r["e"], P.get(r["st"], r["st"]))
        for r in query_all("""SELECT e.full_name en, c.name cn, p.start_date s, p.end_date e, p.status st, p.external_commission v
                              FROM employee_placements p JOIN employees e ON e.id=p.employee_id JOIN companies c ON c.id=p.company_id
                              WHERE p.external_id=?""", (party_id,)):
            add("موظف", r["en"], f"عمولة خارجية {float(r['v'] or 0):g} — لدى {r['cn']}", r["s"], r["e"], P.get(r["st"], r["st"]))
    elif party_type == "representative":
        for r in query_all("""SELECT c.name n, t.start_date s, t.end_date e, t.percent pc FROM company_rep_terms t
                              JOIN companies c ON c.id=t.company_id WHERE t.representative_id=? ORDER BY t.start_date DESC""", (party_id,)):
            add("شركة عميلة", r["n"], f"يمثّلها ({float(r['pc']):g}% من صافيها)", r["s"], r["e"], "ساري" if not r["e"] else "منتهٍ")
    if query_one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fin_agreements'"):
        import agreements as agr

        if party_type == "company":
            rows = query_all("""SELECT DISTINCT a.*, COALESCE(r.name, c.name) AS beneficiary_name
                               FROM fin_agreements a
                               LEFT JOIN representatives r ON a.beneficiary_type='representative' AND r.id=a.beneficiary_id
                               LEFT JOIN contractors c ON a.beneficiary_type='contractor' AND c.id=a.beneficiary_id
                               WHERE (a.scope_type='client' AND a.company_id=?)
                                  OR (a.scope_type='placement' AND a.placement_id IN
                                      (SELECT id FROM employee_placements WHERE company_id=?))
                                  OR (a.scope_type='group' AND EXISTS
                                      (SELECT 1 FROM fin_agreement_members m JOIN employee_placements p ON p.id=m.placement_id
                                       WHERE m.agreement_id=a.id AND p.company_id=?))""", (party_id, party_id, party_id))
        elif party_type == "employee":
            rows = query_all("""SELECT DISTINCT a.*, COALESCE(r.name, c.name) AS beneficiary_name
                               FROM fin_agreements a
                               LEFT JOIN representatives r ON a.beneficiary_type='representative' AND r.id=a.beneficiary_id
                               LEFT JOIN contractors c ON a.beneficiary_type='contractor' AND c.id=a.beneficiary_id
                               WHERE (a.scope_type='client' AND a.company_id IN
                                      (SELECT company_id FROM employee_placements WHERE employee_id=?))
                                  OR (a.scope_type='placement' AND a.placement_id IN
                                      (SELECT id FROM employee_placements WHERE employee_id=?))
                                  OR (a.scope_type='group' AND EXISTS
                                      (SELECT 1 FROM fin_agreement_members m JOIN employee_placements p ON p.id=m.placement_id
                                       WHERE m.agreement_id=a.id AND p.employee_id=?))""", (party_id, party_id, party_id))
        elif party_type in ("contractor", "representative"):
            rows = query_all("""SELECT * FROM fin_agreements WHERE beneficiary_type=? AND beneficiary_id=?""",
                             (party_type, party_id))
        else:
            rows = []
        for r in rows:
            agreement = dict(r)
            amount = agr.describe(agreement)
            scope = agr.scope_label(agreement)
            beneficiary = agreement.get("beneficiary_name")
            if party_type in ("company", "employee"):
                add(agr.BENEFICIARY_AR[agreement["beneficiary_type"]], beneficiary,
                    f"اتفاق مالي — {amount}", agreement["start_date"], agreement["end_date"],
                    agr.STATUS_AR.get(agreement["status"], agreement["status"]))
            else:
                add("شركة عميلة" if agreement["scope_type"] == "client" else "موظف/مجموعة",
                    scope, f"اتفاق مالي — {amount}", agreement["start_date"], agreement["end_date"],
                    agr.STATUS_AR.get(agreement["status"], agreement["status"]))
    return out


# ------------------------------------------------------------------ printable voucher
def voucher_html(voucher_id) -> str:
    v = query_one("SELECT * FROM vouchers WHERE id=?", (voucher_id,))
    e = lambda x: html.escape(str(x if x is not None else ""))
    org = app_settings.get("org_name")
    void = f"<div class=void>ملغى — {e(v['void_reason'])}</div>" if v["status"] == "void" else ""
    import branding
    logo = branding.logo_img_html(48) + " "
    who = "استلمنا من" if v["kind"] == "receipt" else "صرفنا إلى"
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{e(v['voucher_no'])}</title>
<style>body{{font-family:Tahoma,Arial,sans-serif;margin:32px;color:#111}}.box{{border:2px solid #333;padding:20px;max-width:720px}}
h1{{margin:0 0 8px}}table{{width:100%;border-collapse:collapse;margin-top:12px}}td{{border:1px solid #999;padding:8px}}td.k{{background:#eee;width:28%}}
.amt{{font-size:24px;font-weight:bold}}.void{{color:#b00;font-weight:bold;font-size:20px;border:3px solid #b00;display:inline-block;padding:2px 10px}}
.sig{{display:flex;justify-content:space-between;margin-top:48px}}</style></head><body><div class=box>
<div>{logo}{e(org)}</div><h1>{KIND_AR[v['kind']]}</h1>{void}
<table><tr><td class=k>رقم الإذن</td><td>{e(v['voucher_no'])}</td><td class=k>التاريخ</td><td>{e(v['voucher_date'])}</td></tr>
<tr><td class=k>{who}</td><td colspan=3>{e(v['party_name'])} ({PARTY_AR[v['party_type']]})</td></tr>
<tr><td class=k>المبلغ</td><td colspan=3 class=amt>{float(v['amount']):,.2f} ر.س</td></tr>
<tr><td class=k>طريقة الدفع</td><td>{METHOD_AR[v['method']]}</td><td class=k>المرجع</td><td>{e(v['reference'] or '—')}</td></tr>
<tr><td class=k>الشهر المتعلق</td><td>{e(v['month_ref'] or '—')}</td><td class=k>التصنيف</td><td>{e(ENTRY_CATEGORY_AR.get(v['entry_category'], '—'))}</td></tr>
<tr><td class=k>البيان</td><td colspan=3>{e(v['description'] or '—')}</td></tr></table>
<div class=sig><div>المستلم: ____________</div><div>المحاسب: ____________</div></div></div></body></html>"""


def party_balances(party_type, month_ref=None) -> list:
    """One row per party of this type: due / settled / balance (optionally for one work month)."""
    import hub_accounts as HA
    t, col = PARTY_TABLE[party_type]
    dues = HA.all_dues().get(party_type, {})
    vs = {}
    for r in query_all("SELECT * FROM vouchers WHERE party_type=? AND status='issued'", (party_type,)):
        if month_ref and voucher_month(r) != month_ref:
            continue
        vs.setdefault(r["party_id"], []).append(r)
    out = []
    for r in query_all(f"SELECT id, {col} AS name, status FROM {t} ORDER BY {col}"):
        pd_ = dues.get(r["id"], {})
        d = round(pd_.get(month_ref, 0.0) if month_ref else sum(pd_.values()), 2)
        s = _settled(vs.get(r["id"], []), party_type)
        out.append({"id": r["id"], "name": r["name"], "status": r["status"], "due": d, "settled": s, "balance": round(d - s, 2)})
    return out
