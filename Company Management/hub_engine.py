"""Monthly calculation based on what the client ACTUALLY transferred (not on what was agreed).

For one employee (placement) and one work month:
    f           = active days in the month / days of the month  (first and last month are prorated by actual days)
    cost_eff    = actual_cost * f        bonus_eff = bonus * f     contractor_eff / external_eff likewise
    T           = sum of the client's active transfers booked to this work month
    if T < cost_eff:  ratio = T / cost_eff,  refund to client = 0
    else:             ratio = 1,             refund to client = T - cost_eff
    revenue     = min(T, cost_eff)
    bonus_due   = bonus_eff * ratio          (same for contractor and external commission)
    net         = revenue - bonus_due - contractor_due - external_due
    employee returns to the company = T - bonus_due
Per company and month:
    rep_due     = max(sum(net), 0) * rep_percent / 100        (rep term in force at the end of the month)
    margin      = sum(net) - rep_due
Everything is computed live from the data (no stale "calculate" button). Closing a month (phase 4) will freeze a snapshot.
"""
import calendar
import sqlite3
from datetime import date, datetime

import company_hub as hub
from audit import log_audit
from db import get_connection, query_all, query_one

_SCHEMA = """
CREATE TABLE IF NOT EXISTS client_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    placement_id INTEGER NOT NULL,
    work_month TEXT NOT NULL CHECK (work_month GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
    transfer_date TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','void')),
    void_reason TEXT,
    voided_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (placement_id) REFERENCES employee_placements(id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ct_placement_month ON client_transfers(placement_id, work_month);
CREATE INDEX IF NOT EXISTS idx_ct_month ON client_transfers(work_month);
CREATE TRIGGER IF NOT EXISTS trg_ct_no_delete BEFORE DELETE ON client_transfers
BEGIN SELECT RAISE(ABORT, 'تحويلات العميل لا تُحذف، تُلغى مع ذكر السبب'); END;

CREATE TABLE IF NOT EXISTS month_closures (
    month TEXT PRIMARY KEY, closed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, closed_by TEXT, snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS month_closure_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, month TEXT NOT NULL, action TEXT NOT NULL CHECK (action IN ('close','reopen')),
    reason TEXT, at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, by TEXT
);
"""


def ensure_engine_schema(conn=None):
    own = conn is None
    if own:
        conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        if own:
            conn.close()


# ------------------------------------------------------------------ dates
def norm_month(m) -> str:
    """Accepts 'YYYY-MM' (also date objects); raises ValueError otherwise."""
    if isinstance(m, (date, datetime)):
        return m.strftime("%Y-%m")
    s = str(m or "").strip()
    try:
        datetime.strptime(s, "%Y-%m")
    except ValueError as ex:
        raise ValueError("صيغة الشهر غير صحيحة، اكتبها مثل 2026-03.") from ex
    return s


def month_bounds(month):
    y, mo = int(month[:4]), int(month[5:7])
    days = calendar.monthrange(y, mo)[1]
    return date(y, mo, 1), date(y, mo, days), days


def _pd(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


def active_days(p, company, month) -> int:
    """Days in `month` during which the placement is active (inside its own period and the company's period)."""
    first, last, _ = month_bounds(month)
    start = max([d for d in (_pd(p["start_date"]), _pd(company["work_start_date"]), first) if d])
    ends = [last] + [d for d in (_pd(p["end_date"]), _pd(company["work_end_date"])) if d]
    end = min(ends)
    return max(0, (end - start).days + 1)


def month_options(extra=None) -> list:
    """Months from the earliest employee start (or transfer) to the current month, newest first."""
    ensure_engine_schema()
    r = query_one("SELECT MIN(start_date) m FROM employee_placements")
    r2 = query_one("SELECT MIN(work_month) m FROM client_transfers")
    today = date.today()
    cands = [x["m"][:7] for x in (r, r2) if x and x["m"]]
    first = min(cands) if cands else today.strftime("%Y-%m")
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while (y, m) <= (today.year, today.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    if extra and extra not in out:
        out.append(extra)
    return sorted(set(out), reverse=True)


# ------------------------------------------------------------------ the calculation
def _r(x):
    return round(float(x or 0) + 0.0, 2)


def employee_month(p, company, month, transferred) -> dict:
    """The calculation for one employee-month. Pure: no database access."""
    _, _, mdays = month_bounds(month)
    days = active_days(p, company, month)
    f = days / mdays
    cost_eff = float(p["actual_cost"] or 0) * f
    basic_eff = float(p["basic_salary"] or 0) * f
    bonus_eff = float(p["bonus"] or 0) * f
    con_eff = float(p["contractor_commission"] or 0) * f
    ext_eff = float(p["external_commission"] or 0) * f
    T = _r(transferred)
    if cost_eff <= 0:
        ratio, refund = 0.0, 0.0
    elif T < cost_eff:
        ratio, refund = T / cost_eff, 0.0
    else:
        ratio, refund = 1.0, T - cost_eff
    revenue = _r(min(T, cost_eff))
    bonus_due, con_due, ext_due = _r(bonus_eff * ratio), _r(con_eff * ratio), _r(ext_eff * ratio)
    return {
        "placement_id": p["id"], "employee_id": p["employee_id"], "employee": p["full_name"], "company_id": p["company_id"],
        "days": days, "month_days": mdays, "factor": f,
        "basic_eff": _r(basic_eff), "cost_eff": _r(cost_eff), "bonus_eff": _r(bonus_eff),
        "contractor_eff": _r(con_eff), "external_eff": _r(ext_eff),
        "contractor_name": p.get("contractor_name"), "external_name": p.get("external_name"),
        "contractor_id": p.get("contractor_id"), "external_id": p.get("external_id"),
        "transferred": T, "ratio": ratio, "revenue": revenue, "refund": _r(refund),
        "bonus_due": bonus_due, "contractor_due": con_due, "external_due": ext_due,
        "net": _r(revenue - bonus_due - con_due - ext_due),
        "employee_returns": _r(T - bonus_due),
        "expected_net": _r(cost_eff - bonus_eff - con_eff - ext_eff),
        "over_basic": T > _r(basic_eff) + 0.004 and basic_eff > 0,
    }


def rep_for_month(company, month):
    first, last, _ = month_bounds(month)
    ref = last
    if company["work_end_date"]:
        ref = min(ref, _pd(company["work_end_date"]))
    if ref < first:
        return None
    return hub.current_rep(company["id"], ref)


_LIVE_CACHE = {"ver": None, "data": {}}


def compute_live(month, company_id=None) -> dict:
    """Cached per database version: any write to the database invalidates it, so numbers are never stale."""
    import copy
    from db import data_version
    month = norm_month(month)
    ver = (data_version(), date.today())
    if _LIVE_CACHE["ver"] != ver:
        _LIVE_CACHE["ver"], _LIVE_CACHE["data"] = ver, {}
    key = (month, company_id)
    if key not in _LIVE_CACHE["data"]:
        _LIVE_CACHE["data"][key] = _compute_live(month, company_id)
    return copy.deepcopy(_LIVE_CACHE["data"][key])


def _compute_live(month, company_id=None) -> dict:
    month = norm_month(month)
    sql = hub._PL_SELECT + " WHERE p.basic_salary IS NOT NULL AND p.actual_cost IS NOT NULL"
    params = []
    if company_id:
        sql += " AND p.company_id=?"
        params.append(company_id)
    placements = query_all(sql, tuple(params))
    companies = {c["id"]: c for c in query_all("SELECT * FROM companies")}
    tr = {r["placement_id"]: r["s"] for r in query_all(
        "SELECT placement_id, SUM(amount) s FROM client_transfers WHERE work_month=? AND status='active' GROUP BY placement_id", (month,))}
    by_co, warnings = {}, []
    for p in placements:
        co = companies[p["company_id"]]
        row = employee_month(p, co, month, tr.get(p["id"], 0.0))
        if row["days"] == 0 and row["transferred"] == 0:
            continue                                     # not part of this month
        if row["days"] == 0:
            warnings.append(f"{p['full_name']}: يوجد تحويل لشهر لا عمل له فيه.")
        if row["over_basic"]:
            warnings.append(f"{p['full_name']}: المحوّل ({row['transferred']:,.2f}) أكبر من راتبه الأساسي لهذا الشهر ({row['basic_eff']:,.2f}).")
        by_co.setdefault(p["company_id"], []).append(row)
    out_cos, tot = [], {k: 0.0 for k in ("employees", "cost_eff", "transferred", "revenue", "refund", "bonus_due", "contractor_due",
                                         "external_due", "net", "rep_due", "margin", "employee_returns", "expected_net",
                                         "expected_rep", "expected_margin", "not_transferred")}
    for cid, rows in sorted(by_co.items(), key=lambda kv: companies[kv[0]]["name"]):
        co = companies[cid]
        rep = rep_for_month(co, month)
        pct = rep["percent"] if rep else 0.0
        net = _r(sum(r["net"] for r in rows))
        rep_due = _r(max(net, 0) * pct / 100.0)
        exp_net = _r(sum(r["expected_net"] for r in rows))
        exp_rep = _r(max(exp_net, 0) * pct / 100.0)
        agg = {"company_id": cid, "company": co["name"], "employees": rows, "rep_name": rep["rep_name"] if rep else None,
               "rep_percent": pct, "rep_id": rep["representative_id"] if rep else None,
               "cost_eff": _r(sum(r["cost_eff"] for r in rows)), "transferred": _r(sum(r["transferred"] for r in rows)),
               "revenue": _r(sum(r["revenue"] for r in rows)), "refund": _r(sum(r["refund"] for r in rows)),
               "bonus_due": _r(sum(r["bonus_due"] for r in rows)), "contractor_due": _r(sum(r["contractor_due"] for r in rows)),
               "external_due": _r(sum(r["external_due"] for r in rows)), "net": net, "rep_due": rep_due,
               "margin": _r(net - rep_due), "employee_returns": _r(sum(r["employee_returns"] for r in rows)),
               "expected_net": exp_net, "expected_rep": exp_rep, "expected_margin": _r(exp_net - exp_rep)}
        out_cos.append(agg)
        tot["employees"] += sum(1 for r in rows if r["days"] > 0)
        tot["not_transferred"] += sum(1 for r in rows if r["days"] > 0 and r["transferred"] == 0)
        for k in tot:
            if k in agg and k not in ("employees", "not_transferred"):
                tot[k] += agg[k]
    tot = {k: (int(v) if k in ("employees", "not_transferred") else _r(v)) for k, v in tot.items()}
    return {"month": month, "companies": out_cos, "totals": tot, "warnings": warnings}


# ------------------------------------------------------------------ closing
def closure(month):
    return query_one("SELECT * FROM month_closures WHERE month=?", (norm_month(month),))


def is_closed(month) -> bool:
    return closure(month) is not None


def _guard(month):
    if is_closed(month):
        raise ValueError(f"الشهر {norm_month(month)} مقفل. أعد فتحه (بسبب مكتوب) إن أردت التعديل.")


_SUM_KEYS = ("cost_eff", "transferred", "revenue", "refund", "bonus_due", "contractor_due", "external_due", "net", "rep_due",
             "margin", "employee_returns", "expected_net", "expected_rep", "expected_margin")


def compute_month(month, company_id=None) -> dict:
    """Live calculation, or the frozen snapshot when the month is closed."""
    import json
    month = norm_month(month)
    c = closure(month)
    if not c:
        res = compute_live(month, company_id)
        res["closed"] = False
        return res
    res = json.loads(c["snapshot"])
    if company_id:
        res["companies"] = [x for x in res["companies"] if x["company_id"] == company_id]
        tot = {k: 0.0 for k in res["totals"]}
        for co in res["companies"]:
            for k in tot:
                if k == "employees":
                    tot[k] += sum(1 for r in co["employees"] if r["days"] > 0)
                elif k == "not_transferred":
                    tot[k] += sum(1 for r in co["employees"] if r["days"] > 0 and r["transferred"] == 0)
                elif k in co:
                    tot[k] += co[k]
        res["totals"] = {k: (int(v) if k in ("employees", "not_transferred") else _r(v)) for k, v in tot.items()}
    res["closed"], res["closed_at"], res["closed_by"] = True, c["closed_at"], c["closed_by"]
    return res


def close_month(month) -> str:
    import json
    month = norm_month(month)
    if is_closed(month):
        raise ValueError("الشهر مقفل مسبقاً.")
    res = compute_live(month)
    if not res["companies"]:
        raise ValueError("لا توجد بيانات في هذا الشهر لإقفالها.")
    who = _who()
    conn = get_connection()
    try:
        conn.execute("INSERT INTO month_closures(month, closed_by, snapshot) VALUES (?,?,?)", (month, who, json.dumps(res, ensure_ascii=False)))
        conn.execute("INSERT INTO month_closure_log(month, action, by) VALUES (?, 'close', ?)", (month, who))
        conn.commit()
    finally:
        conn.close()
    log_audit("month_closures", None, "INSERT", None, {"month": month, "net": res["totals"]["net"], "margin": res["totals"]["margin"]},
              note=f"إقفال شهر {month}")
    return f"تم إقفال شهر {month}. الأرقام الآن مثبتة."


def reopen_month(month, reason) -> str:
    month = norm_month(month)
    if not is_closed(month):
        raise ValueError("الشهر غير مقفل.")
    if not (reason or "").strip():
        raise ValueError("اكتب سبب إعادة الفتح.")
    who = _who()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM month_closures WHERE month=?", (month,))
        conn.execute("INSERT INTO month_closure_log(month, action, reason, by) VALUES (?, 'reopen', ?, ?)", (month, reason.strip(), who))
        conn.commit()
    finally:
        conn.close()
    log_audit("month_closures", None, "STATUS_CHANGE", {"month": month, "state": "closed"}, {"state": "open"}, note=f"إعادة فتح شهر {month}: {reason.strip()}")
    return f"أُعيد فتح شهر {month}. الأرقام تُحتسب من جديد."


def closure_log(month=None) -> list:
    if month:
        return query_all("SELECT * FROM month_closure_log WHERE month=? ORDER BY id DESC", (norm_month(month),))
    return query_all("SELECT * FROM month_closure_log ORDER BY id DESC")


def _who() -> str:
    try:
        from audit import _current_username
        return _current_username()
    except Exception:  # noqa: BLE001
        return "system"


# ------------------------------------------------------------------ transfers
def _placement(pid):
    return hub.get_placement(pid)


def transferred_so_far(pid, month, exclude_id=None) -> float:
    sql, params = "SELECT COALESCE(SUM(amount),0) s FROM client_transfers WHERE placement_id=? AND work_month=? AND status='active'", [pid, month]
    if exclude_id:
        sql += " AND id<>?"
        params.append(exclude_id)
    return _r(query_one(sql, tuple(params))["s"])


def _check_transfer(pid, month, tdate, amount):
    p = _placement(pid)
    if not p:
        raise ValueError("اختر الموظف.")
    if p["basic_salary"] is None:
        raise ValueError("هذا الموظف بلا أرقام مالية. أكملها من شاشة الشركة أولاً.")
    month = norm_month(month)
    _guard(month)
    try:
        amt = _r(amount)
    except (TypeError, ValueError) as ex:
        raise ValueError("المبلغ غير صحيح.") from ex
    if amt <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر.")
    d = hub._d(tdate)
    if not d:
        raise ValueError("تاريخ التحويل مطلوب.")
    co = query_one("SELECT * FROM companies WHERE id=?", (p["company_id"],))
    if active_days(p, co, month) == 0:
        raise ValueError(f"الموظف {p['full_name']} لا عمل له في شهر {month} (خارج فترة تعيينه أو فترة الشركة).")
    return p, month, d, amt


def add_transfer(pid, month, tdate, amount, notes=None) -> tuple:
    p, month, d, amt = _check_transfer(pid, month, tdate, amount)
    conn = get_connection()
    try:
        cur = conn.execute("INSERT INTO client_transfers(placement_id, work_month, transfer_date, amount, notes) VALUES (?,?,?,?,?)",
                           (pid, month, d, amt, hub._clean(notes)))
        conn.commit()
        tid = cur.lastrowid
    finally:
        conn.close()
    log_audit("client_transfers", tid, "INSERT", None, {"placement_id": pid, "work_month": month, "transfer_date": d, "amount": amt},
              note=f"تحويل من العميل: {p['full_name']} شهر {month}")
    total = transferred_so_far(pid, month)
    co = query_one("SELECT * FROM companies WHERE id=?", (p["company_id"],))
    basic_eff = _r(float(p["basic_salary"]) * active_days(p, co, month) / month_bounds(month)[2])
    msg = f"تم تسجيل تحويل {amt:,.2f} للموظف {p['full_name']} عن شهر {month} (إجمالي المحوّل للشهر {total:,.2f})."
    warn = [f"المحوّل الإجمالي ({total:,.2f}) أكبر من الراتب الأساسي لهذا الشهر ({basic_eff:,.2f}). تأكد من المبلغ."] if total > basic_eff + 0.004 else []
    return tid, msg, warn


def add_bulk(month, tdate, amounts: dict, notes=None) -> tuple:
    """amounts = {placement_id: amount}. All-or-nothing: every row is validated before anything is written."""
    items = [(pid, a) for pid, a in amounts.items() if a not in (None, "") and _r(a) != 0]
    if not items:
        raise ValueError("لم تُدخل أي مبلغ.")
    checked = [_check_transfer(pid, month, tdate, a) for pid, a in items]
    conn = get_connection()
    ids = []
    try:
        for (p, m, d, amt) in checked:
            cur = conn.execute("INSERT INTO client_transfers(placement_id, work_month, transfer_date, amount, notes) VALUES (?,?,?,?,?)",
                               (p["id"], m, d, amt, hub._clean(notes)))
            ids.append((cur.lastrowid, p, m, d, amt))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for tid, p, m, d, amt in ids:
        log_audit("client_transfers", tid, "INSERT", None, {"placement_id": p["id"], "work_month": m, "transfer_date": d, "amount": amt},
                  note=f"تحويل من العميل (جماعي): {p['full_name']} شهر {m}")
    return len(ids), f"تم تسجيل {len(ids)} تحويلاً لشهر {checked[0][1]}."


def update_transfer(tid, month, tdate, amount, notes=None) -> str:
    old = query_one("SELECT * FROM client_transfers WHERE id=?", (tid,))
    if not old:
        raise ValueError("التحويل غير موجود.")
    if old["status"] != "active":
        raise ValueError("التحويل الملغى لا يُعدَّل. سجّل تحويلاً جديداً.")
    _guard(old["work_month"])
    p, month, d, amt = _check_transfer(old["placement_id"], month, tdate, amount)
    conn = get_connection()
    try:
        conn.execute("UPDATE client_transfers SET work_month=?, transfer_date=?, amount=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (month, d, amt, hub._clean(notes), tid))
        conn.commit()
    finally:
        conn.close()
    log_audit("client_transfers", tid, "UPDATE", old, {"work_month": month, "transfer_date": d, "amount": amt}, note="تعديل تحويل عميل")
    return "تم تعديل التحويل."


def void_transfer(tid, reason) -> str:
    old = query_one("SELECT * FROM client_transfers WHERE id=?", (tid,))
    if not old:
        raise ValueError("التحويل غير موجود.")
    if old["status"] == "void":
        raise ValueError("التحويل ملغى مسبقاً.")
    _guard(old["work_month"])
    if not (reason or "").strip():
        raise ValueError("اكتب سبب الإلغاء.")
    conn = get_connection()
    try:
        conn.execute("UPDATE client_transfers SET status='void', void_reason=?, voided_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (reason.strip(), tid))
        conn.commit()
    finally:
        conn.close()
    log_audit("client_transfers", tid, "STATUS_CHANGE", old, {"status": "void", "reason": reason}, note="إلغاء تحويل عميل")
    return "تم إلغاء التحويل."


def list_transfers(month=None, company_id=None, status="active") -> list:
    sql = """SELECT t.*, e.full_name, c.name AS company_name, c.id AS company_id
             FROM client_transfers t JOIN employee_placements p ON p.id=t.placement_id
             JOIN employees e ON e.id=p.employee_id JOIN companies c ON c.id=p.company_id WHERE 1=1"""
    params = []
    if month:
        sql += " AND t.work_month=?"; params.append(month)
    if company_id:
        sql += " AND p.company_id=?"; params.append(company_id)
    if status != "all":
        sql += " AND t.status=?"; params.append(status)
    return query_all(sql + " ORDER BY t.transfer_date DESC, t.id DESC", tuple(params))
