"""Flexible financial agreements.

An agreement says: *this beneficiary (representative or contractor) earns this much, on this basis,
for this scope (a whole client company, one placement, or a chosen group of placements), during this period*.

Any number of agreements may exist for the same client, beneficiary and month. The monthly engine
(finance_engine.calculate_month) calls `lines_for_placement` for every placement and adds the result to the
beneficiary dues; nothing here writes to the ledger, so re-running a month never duplicates a commission.
"""
from datetime import date, datetime
import calendar

from db import query_all, query_one, execute, get_connection
from audit import log_audit

BENEFICIARY_AR = {"representative": "مندوب", "contractor": "متعهد"}
SCOPE_AR = {"client": "كل موظفي شركة عميلة", "placement": "موظف معيّن", "group": "مجموعة موظفين"}
METHOD_AR = {"fixed_monthly": "مبلغ ثابت شهري", "per_employee": "مبلغ عن كل موظف", "percent": "نسبة مئوية"}
BASIS_AR = {
    "agreed": "المبلغ المتفق عليه مع العميل",
    "after_refund": "إيراد الشركة بعد المردود",
    "surplus": "الفائض لدى الشركة (بعد المردود وأجر الموظف)",
    "wage": "أجر الموظف",
    "margin": "الهامش قبل العمولات (بعد المصروفات)",
}
STATUS_AR = {"active": "ساري", "ended": "منتهٍ"}
PARTY_TABLE = {"representative": ("representatives", "name"), "contractor": ("contractors", "name")}


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _month(month_ref):
    y, m = map(int, month_ref.split("-"))
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last), last


def _days(start, end, m_start, m_end):
    """Days of [start, end(None=open)] that fall inside [m_start, m_end]."""
    s = max(start, m_start)
    e = min(end, m_end) if end else m_end
    return 0 if e < s else (e - s).days + 1


def _window_days(a, p_start, p_end, m_start, m_end):
    s = max(_d(a["start_date"]), p_start, m_start)
    ends = [m_end] + [x for x in (_d(a["end_date"]) if a.get("end_date") else None, p_end) if x]
    e = min(ends)
    return 0 if e < s else (e - s).days + 1


def _live(a):
    return not (a.get("status") == "ended" and not a.get("end_date"))


# ------------------------------------------------------------------ describing
def describe(a) -> str:
    v = float(a["value"])
    if a["method"] == "percent":
        core = f"{v:g}% من {BASIS_AR.get(a.get('percent_basis'), '')}"
    elif a["method"] == "per_employee":
        core = f"{v:g} ريال شهرياً عن كل موظف"
    else:
        core = f"{v:g} ريال شهرياً"
    return core


def scope_label(a) -> str:
    if a["scope_type"] == "client":
        r = query_one("SELECT name FROM companies WHERE id=?", (a["company_id"],))
        return f"كل موظفي {r['name'] if r else '#' + str(a['company_id'])}"
    if a["scope_type"] == "placement":
        r = query_one("""SELECT e.full_name n, c.name cn FROM employee_placements p JOIN employees e ON e.id=p.employee_id
                         JOIN companies c ON c.id=p.company_id WHERE p.id=?""", (a["placement_id"],))
        return f"{r['n']} ({r['cn']})" if r else f"تعيين #{a['placement_id']}"
    n = query_one("SELECT COUNT(*) c FROM fin_agreement_members WHERE agreement_id=?", (a["id"],))
    return f"مجموعة من {n['c']} موظف"


def beneficiary_name(btype, bid) -> str:
    t, col = PARTY_TABLE[btype]
    r = query_one(f"SELECT {col} AS n FROM {t} WHERE id=?", (bid,))
    return r["n"] if r else f"#{bid}"


# ------------------------------------------------------------------ monthly engine hooks
def load_active(conn, m_start, m_end):
    """All agreements that overlap the month, with their member placement ids."""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM fin_agreements WHERE date(start_date) <= date(?) AND (end_date IS NULL OR date(end_date) >= date(?)) ORDER BY id",
        (m_end.isoformat(), m_start.isoformat())).fetchall()]
    out = []
    for a in rows:
        if not _live(a):
            continue
        a["members"] = [r[0] for r in conn.execute("SELECT placement_id FROM fin_agreement_members WHERE agreement_id=?", (a["id"],)).fetchall()]
        out.append(a)
    return out


def _in_scope(a, p):
    if a["scope_type"] == "client":
        return p["company_id"] == a["company_id"]
    if a["scope_type"] == "placement":
        return p["id"] == a["placement_id"]
    return p["id"] in a["members"]


def eligibility(agreements, placements, m_start, m_end):
    """{agreement_id: sorted [placement ids]} that are in scope and share at least one day with the agreement."""
    out = {}
    for a in agreements:
        ids = []
        for p in placements:
            if not _in_scope(a, p):
                continue
            p_start = _d(p["start_date"]); p_end = _d(p["end_date"]) if p.get("end_date") else None
            if _window_days(a, p_start, p_end, m_start, m_end) > 0:
                ids.append(p["id"])
        out[a["id"]] = sorted(ids)
    return out


def lines_for_placement(agreements, elig, p, bases, month_ref):
    """Commission lines this placement generates in the month.

    bases = {"agreed", "after_refund", "surplus", "wage", "margin"} (month totals of this placement).
    """
    m_start, m_end, month_days = _month(month_ref)
    p_start = _d(p["start_date"]); p_end = _d(p["end_date"]) if p.get("end_date") else None
    lines = []
    for a in agreements:
        ids = elig.get(a["id"], [])
        if p["id"] not in ids:
            continue
        eff = _window_days(a, p_start, p_end, m_start, m_end)
        v = float(a["value"])
        pr = bool(a.get("prorate", 1))
        ratio = (eff / month_days) if pr else 1.0
        if a["method"] == "fixed_monthly" and a["scope_type"] != "placement":
            a_days = _days(_d(a["start_date"]), _d(a["end_date"]) if a.get("end_date") else None, m_start, m_end)
            total = round(v * ((a_days / month_days) if pr else 1.0), 2)
            n = len(ids)
            share = round(total / n, 2)
            amount = round(total - share * (n - 1), 2) if ids[0] == p["id"] else share
            detail = f"{v:g} ريال شهرياً تُقسَّم بالتساوي على {n} موظف = {total:,.2f}؛ حصة هذا الموظف {amount:,.2f}"
        elif a["method"] == "percent":
            basis = float(bases.get(a["percent_basis"], 0) or 0)
            amount = round(basis * v / 100.0 * ratio, 2)
            detail = f"{v:g}% × {basis:,.2f} ({BASIS_AR[a['percent_basis']]})"
            if pr and eff != month_days:
                detail += f" × {eff}/{month_days} يوم"
        else:  # per_employee, or fixed on a single placement
            amount = round(v * ratio, 2)
            detail = f"{v:g} ريال" + (f" × {eff}/{month_days} يوم" if pr and eff != month_days else "")
        lines.append({"beneficiary_type": a["beneficiary_type"], "beneficiary_id": a["beneficiary_id"], "amount": amount,
                      "days": eff, "source": "fin_agreements", "source_id": a["id"], "detail": detail})
    return lines


# ------------------------------------------------------------------ validation + CRUD
def _validate(d, members=None):
    if d["beneficiary_type"] not in BENEFICIARY_AR:
        raise ValueError("نوع المستفيد غير صحيح.")
    t, col = PARTY_TABLE[d["beneficiary_type"]]
    if not query_one(f"SELECT 1 FROM {t} WHERE id=?", (d["beneficiary_id"],)):
        raise ValueError("المستفيد غير موجود.")
    if d["scope_type"] not in SCOPE_AR or d["method"] not in METHOD_AR:
        raise ValueError("النطاق أو طريقة الحساب غير صحيحة.")
    if d["scope_type"] == "client" and not d.get("company_id"):
        raise ValueError("اختر الشركة العميلة.")
    if d["scope_type"] == "placement" and not d.get("placement_id"):
        raise ValueError("اختر الموظف (التعيين).")
    if d["scope_type"] == "group" and not members:
        raise ValueError("اختر موظفاً واحداً على الأقل للمجموعة.")
    v = float(d.get("value") or 0)
    if v <= 0:
        raise ValueError("القيمة يجب أن تكون أكبر من صفر.")
    if d["method"] == "percent":
        if d.get("percent_basis") not in BASIS_AR:
            raise ValueError("اختر أساس حساب النسبة.")
        if v > 100:
            raise ValueError("النسبة لا يمكن أن تتجاوز 100%.")
    if d.get("end_date") and d["end_date"] < d["start_date"]:
        raise ValueError("تاريخ النهاية لا يسبق تاريخ البداية.")


def _clean(d):
    c = dict(d)
    c["value"] = float(c["value"])
    if c["method"] != "percent":
        c["percent_basis"] = None
    if c["scope_type"] != "client":
        c["company_id"] = None
    if c["scope_type"] != "placement":
        c["placement_id"] = None
    c["prorate"] = 1 if c.get("prorate", 1) else 0
    c["notes"] = (c.get("notes") or "").strip() or None
    c["end_date"] = c.get("end_date") or None
    return c


def _duplicate_of(d, members, ignore_id=None):
    """An identical live agreement (same beneficiary, scope, rule, value) with an overlapping period = almost surely a double entry."""
    far = "9999-12-31"
    for o in query_all("SELECT * FROM fin_agreements WHERE beneficiary_type=? AND beneficiary_id=? AND scope_type=? AND method=?",
                       (d["beneficiary_type"], d["beneficiary_id"], d["scope_type"], d["method"])):
        if o["id"] == ignore_id or (o["status"] == "ended" and not o["end_date"]):
            continue
        same = (float(o["value"]) == float(d["value"]) and o["percent_basis"] == d["percent_basis"]
                and o["company_id"] == d["company_id"] and o["placement_id"] == d["placement_id"] and bool(o["prorate"]) == bool(d["prorate"]))
        if same and d["scope_type"] == "group":
            same = set(members_of(o["id"])) == set(members or [])
        if same and (o["end_date"] or far) >= d["start_date"] and (d["end_date"] or far) >= o["start_date"]:
            return o
    return None


def create_agreement(d, members=None) -> int:
    d = _clean(d)
    _validate(d, members)
    dup = _duplicate_of(d, members)
    if dup:
        raise ValueError(f"يوجد اتفاق مطابق تماماً (رقم {dup['id']}) في الفترة نفسها، ولن تُحسب العمولة مرتين. عدّل الاتفاق الموجود أو غيّر شرطاً في هذا الاتفاق.")
    aid = execute(
        """INSERT INTO fin_agreements(beneficiary_type, beneficiary_id, scope_type, company_id, placement_id, method, value,
           percent_basis, prorate, start_date, end_date, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d["beneficiary_type"], d["beneficiary_id"], d["scope_type"], d["company_id"], d["placement_id"], d["method"], d["value"],
         d["percent_basis"], d["prorate"], d["start_date"], d["end_date"], d["notes"]))
    if d["scope_type"] == "group":
        for pid in sorted(set(members)):
            execute("INSERT INTO fin_agreement_members(agreement_id, placement_id) VALUES (?,?)", (aid, pid))
    log_audit("fin_agreements", aid, "INSERT", None, dict(d, members=sorted(set(members or []))), note="إنشاء اتفاق مالي")
    return aid


def update_agreement(aid, d, members=None) -> str:
    old = query_one("SELECT * FROM fin_agreements WHERE id=?", (aid,))
    if not old:
        raise ValueError("الاتفاق غير موجود.")
    d = _clean(d)
    _validate(d, members)
    dup = _duplicate_of(d, members, ignore_id=aid)
    if dup:
        raise ValueError(f"يوجد اتفاق مطابق تماماً (رقم {dup['id']}) في الفترة نفسها.")
    used = query_one("SELECT 1 FROM agreement_calc_log WHERE source='fin_agreements' AND source_id=? LIMIT 1", (aid,))
    if used and (old["start_date"] != d["start_date"]):
        raise ValueError("لا يمكن تغيير تاريخ بداية اتفاق دخل في حسابات سابقة. أنهِه وأنشئ اتفاقاً جديداً.")
    execute("""UPDATE fin_agreements SET beneficiary_type=?, beneficiary_id=?, scope_type=?, company_id=?, placement_id=?, method=?,
               value=?, percent_basis=?, prorate=?, start_date=?, end_date=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (d["beneficiary_type"], d["beneficiary_id"], d["scope_type"], d["company_id"], d["placement_id"], d["method"], d["value"],
             d["percent_basis"], d["prorate"], d["start_date"], d["end_date"], d["notes"], aid))
    execute("DELETE FROM fin_agreement_members WHERE agreement_id=?", (aid,))
    if d["scope_type"] == "group":
        for pid in sorted(set(members)):
            execute("INSERT INTO fin_agreement_members(agreement_id, placement_id) VALUES (?,?)", (aid, pid))
    log_audit("fin_agreements", aid, "UPDATE", dict(old), dict(d, members=sorted(set(members or []))), note="تعديل اتفاق مالي")
    return f"تم تحديث الاتفاق رقم {aid}. الأشهر المعتمدة لا تتغير؛ الأشهر المفتوحة تُحتسب بالشروط الجديدة عند إعادة الاحتساب."


def end_agreement(aid, end_d) -> str:
    a = query_one("SELECT * FROM fin_agreements WHERE id=?", (aid,))
    if not a:
        raise ValueError("الاتفاق غير موجود.")
    e = end_d.strftime("%Y-%m-%d")
    if e < a["start_date"]:
        raise ValueError("تاريخ الإنهاء لا يسبق بداية الاتفاق.")
    execute("UPDATE fin_agreements SET end_date=?, status='ended', updated_at=CURRENT_TIMESTAMP WHERE id=?", (e, aid))
    log_audit("fin_agreements", aid, "STATUS_CHANGE", {"status": a["status"], "end_date": a["end_date"]},
              {"status": "ended", "end_date": e}, note="إنهاء اتفاق مالي")
    return f"تم إنهاء الاتفاق رقم {aid} بتاريخ {e}."


def delete_agreement(aid) -> str:
    a = query_one("SELECT * FROM fin_agreements WHERE id=?", (aid,))
    if not a:
        raise ValueError("الاتفاق غير موجود.")
    try:
        execute("DELETE FROM fin_agreements WHERE id=?", (aid,))
    except Exception as ex:  # noqa: BLE001
        if "ولا يُحذف" in str(ex):
            raise ValueError("هذا الاتفاق دخل في حسابات سابقة ولا يُحذف. أنهِه بتاريخ انتهاء بدلاً من ذلك.")
        raise
    log_audit("fin_agreements", aid, "STATUS_CHANGE", dict(a), {"deleted": True}, note="حذف اتفاق مالي لم يُستخدم")
    return f"تم حذف الاتفاق رقم {aid}."


def list_agreements(beneficiary_type=None, beneficiary_id=None, company_id=None, status=None):
    q, p = "SELECT * FROM fin_agreements WHERE 1=1", []
    if beneficiary_type:
        q += " AND beneficiary_type=?"; p.append(beneficiary_type)
    if beneficiary_id:
        q += " AND beneficiary_id=?"; p.append(beneficiary_id)
    if status:
        q += " AND status=?"; p.append(status)
    rows = query_all(q + " ORDER BY id DESC", tuple(p))
    if company_id:
        keep = []
        for a in rows:
            if a["scope_type"] == "client":
                ok = a["company_id"] == company_id
            elif a["scope_type"] == "placement":
                r = query_one("SELECT company_id FROM employee_placements WHERE id=?", (a["placement_id"],))
                ok = bool(r) and r["company_id"] == company_id
            else:
                r = query_one("""SELECT 1 FROM fin_agreement_members m JOIN employee_placements p ON p.id=m.placement_id
                                 WHERE m.agreement_id=? AND p.company_id=?""", (a["id"], company_id))
                ok = bool(r)
            if ok:
                keep.append(a)
        rows = keep
    return rows


def members_of(aid):
    return [r["placement_id"] for r in query_all("SELECT placement_id FROM fin_agreement_members WHERE agreement_id=?", (aid,))]


# ------------------------------------------------------------------ preview (no writes)
def preview(d, members, month_ref, sample_bases=None):
    """What would this agreement pay in `month_ref`? Uses real placements and, if given, real month figures."""
    d = _clean(dict(d, id=0, status="active"))
    _validate(d, members)
    m_start, m_end, _ = _month(month_ref)
    d["members"] = list(members or [])
    conn = get_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        pls = [dict(r) for r in conn.execute("SELECT * FROM employee_placements WHERE status IN ('active','ended','suspended')").fetchall()]
        accts = {r["placement_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM monthly_employee_accounts WHERE month_ref=?", (month_ref,)).fetchall()}
    finally:
        conn.close()
    pls = [p for p in pls if not (p["status"] in ("ended", "suspended") and not p.get("end_date"))]
    elig = eligibility([d], pls, m_start, m_end)
    rows, total = [], 0.0
    for p in pls:
        if p["id"] not in elig[0]:
            continue
        acct = accts.get(p["id"])
        if acct:
            agreed = float(acct["client_agreed_total"]); after = float(acct["approved_company_revenue_total"])
            wage = float(acct["recorded_wages_total"]); exp = float(acct["external_expenses_total"])
        else:
            agreed = after = wage = exp = 0.0
        bases = (sample_bases or {}) or {"agreed": agreed, "after_refund": after, "surplus": after - wage, "wage": wage, "margin": after - wage - exp}
        for ln in lines_for_placement([d], elig, p, bases, month_ref):
            e = query_one("SELECT e.full_name n, c.name cn FROM employee_placements p JOIN employees e ON e.id=p.employee_id JOIN companies c ON c.id=p.company_id WHERE p.id=?", (p["id"],))
            rows.append({"الموظف": e["n"], "الشركة": e["cn"], "المبلغ": ln["amount"], "طريقة الحساب": ln["detail"]})
            total += ln["amount"]
    return {"rows": rows, "total": round(total, 2), "no_figures": d["method"] == "percent" and not any(accts.get(p["id"]) for p in pls if p["id"] in elig[0]) and not sample_bases}


# ------------------------------------------------------------------ audit trail of numbers
def calc_log(month_ref=None, beneficiary_type=None, beneficiary_id=None, placement_id=None):
    q = """SELECT l.*, e.full_name AS employee, c.name AS company FROM agreement_calc_log l
           JOIN employee_placements p ON p.id=l.placement_id JOIN employees e ON e.id=p.employee_id JOIN companies c ON c.id=p.company_id
           WHERE 1=1"""
    p = []
    for col, val in (("l.month_ref", month_ref), ("l.beneficiary_type", beneficiary_type), ("l.beneficiary_id", beneficiary_id),
                     ("l.placement_id", placement_id)):
        if val:
            q += f" AND {col}=?"; p.append(val)
    return query_all(q + " ORDER BY l.month_ref DESC, l.id", tuple(p))
