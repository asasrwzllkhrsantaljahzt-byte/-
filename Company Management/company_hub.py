"""Company hub: one place for a client company, its representative, and its employees with their financial terms.

Per employee (placement) the user records:
    basic_salary   الراتب الأساسي   = what the client company transfers to the employee
    actual_cost    التكلفة الفعلية  = what was agreed between us and the client (our revenue)
    bonus          مكافأة الموظف    = what the employee keeps
    contractor     متعهد واحد + عمولة ثابتة شهرياً
    external       جهة عمولة خارجية واحدة + عمولة ثابتة شهرياً
Derived (never typed):
    refund = basic_salary - actual_cost            (returned to the client)
    net    = actual_cost - bonus - contractor_commission - external_commission

The representative belongs to the company (one at a time) with a fixed percentage of the company's total net.
Rep terms are kept as dated periods so past months keep the percentage that applied then.
"""
import sqlite3
from datetime import date, datetime, timedelta

from db import get_connection, query_all, query_one
from audit import log_audit

STATUS_AR = {"active": "نشط", "ended": "مستبعد", "suspended": "موقوف"}

_PLACEMENT_COLS = {
    "basic_salary": "REAL",
    "actual_cost": "REAL",
    "bonus": "REAL NOT NULL DEFAULT 0",
    "contractor_id": "INTEGER",
    "contractor_commission": "REAL NOT NULL DEFAULT 0",
    "external_id": "INTEGER",
    "external_commission": "REAL NOT NULL DEFAULT 0",
}
_COMPANY_COLS = {"work_start_date": "TEXT", "work_end_date": "TEXT"}
_CONTRACTOR_COLS = {"kind": "TEXT NOT NULL DEFAULT 'contractor'"}

_REP_TABLE = """
CREATE TABLE IF NOT EXISTS company_rep_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    representative_id INTEGER NOT NULL,
    percent REAL NOT NULL CHECK (percent >= 0 AND percent <= 100),
    start_date TEXT NOT NULL,
    end_date TEXT,
    end_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (representative_id) REFERENCES representatives(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CHECK (end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS idx_rep_terms_company ON company_rep_terms(company_id, start_date);
"""


def ensure_hub_schema(conn=None):
    own = conn is None
    if own:
        conn = get_connection()
    try:
        for table, cols in (("employee_placements", _PLACEMENT_COLS), ("companies", _COMPANY_COLS),
                            ("contractors", _CONTRACTOR_COLS)):
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for name, decl in cols.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        conn.executescript(_REP_TABLE)
        conn.commit()
    finally:
        if own:
            conn.close()


# ------------------------------------------------------------------ helpers
def _d(v):
    if v in (None, ""):
        return None
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    datetime.strptime(str(v), "%Y-%m-%d")
    return str(v)


def _money(v):
    return round(float(v or 0), 2)


def _clean(v):
    return (v or "").strip() or None


def calc(basic, cost, bonus, contractor_commission, external_commission) -> dict:
    """The two derived figures. Pure function, used by the page for the live preview too."""
    basic, cost = _money(basic), _money(cost)
    return {
        "refund": round(basic - cost, 2),
        "net": round(cost - _money(bonus) - _money(contractor_commission) - _money(external_commission), 2),
    }


def terms_problems(t: dict) -> list:
    """Hard errors (block saving). Empty list = valid."""
    errs = []
    basic, cost = _money(t.get("basic_salary")), _money(t.get("actual_cost"))
    if basic <= 0:
        errs.append("الراتب الأساسي يجب أن يكون أكبر من صفر.")
    if cost <= 0:
        errs.append("التكلفة الفعلية يجب أن تكون أكبر من صفر.")
    if basic > 0 and cost > basic:
        errs.append("التكلفة الفعلية لا يمكن أن تزيد عن الراتب الأساسي (الاسترداد يصبح سالباً).")
    for k, lbl in (("bonus", "مكافأة الموظف"), ("contractor_commission", "عمولة المتعهد"),
                   ("external_commission", "العمولة الخارجية")):
        if _money(t.get(k)) < 0:
            errs.append(f"{lbl} لا يمكن أن تكون سالبة.")
    if _money(t.get("contractor_commission")) > 0 and not t.get("contractor_id"):
        errs.append("اختر المتعهد لأن له عمولة.")
    if _money(t.get("external_commission")) > 0 and not t.get("external_id"):
        errs.append("اختر جهة العمولة الخارجية لأن لها عمولة.")
    for k, kind, lbl in (("contractor_id", "contractor", "المتعهد"), ("external_id", "external", "جهة العمولة الخارجية")):
        if t.get(k):
            r = query_one("SELECT kind FROM contractors WHERE id=?", (t[k],))
            if not r:
                errs.append(f"{lbl} غير موجود.")
            elif (r["kind"] or "contractor") != kind:
                errs.append(f"{lbl} المختار ليس من النوع الصحيح (غيّر نوعه من صفحة المتعهدين).")
    return errs


def terms_warnings(t: dict) -> list:
    out = []
    c = calc(t.get("basic_salary"), t.get("actual_cost"), t.get("bonus"), t.get("contractor_commission"),
             t.get("external_commission"))
    if c["net"] < 0:
        out.append(f"الصافي سالب ({c['net']:,.2f}): المكافأة والعمولات أكبر من التكلفة الفعلية.")
    return out


# ------------------------------------------------------------------ company
def save_company(cid, d: dict) -> tuple:
    """Insert/update a company's data. Returns (id, message)."""
    name = _clean(d.get("name"))
    if not name:
        raise ValueError("اسم الشركة مطلوب.")
    ws, we = _d(d.get("work_start_date")), _d(d.get("work_end_date"))
    if ws and we and we < ws:
        raise ValueError("تاريخ توقف الشركة لا يسبق تاريخ بداية عملها.")
    status = d.get("status") or "active"
    if status not in ("active", "inactive"):
        raise ValueError("الحالة غير صحيحة.")
    payload = {"name": name, "commercial_register": _clean(d.get("commercial_register")),
               "tax_number": _clean(d.get("tax_number")), "contact_person": _clean(d.get("contact_person")),
               "phone": _clean(d.get("phone")), "email": _clean(d.get("email")), "address": _clean(d.get("address")),
               "notes": _clean(d.get("notes")), "work_start_date": ws, "work_end_date": we, "status": status}
    conn = get_connection()
    try:
        old = conn.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone() if cid else None
        if cid and not old:
            raise ValueError("الشركة غير موجودة.")
        try:
            if cid:
                conn.execute("UPDATE companies SET " + ", ".join(f"{k}=?" for k in payload) +
                             ", updated_at=CURRENT_TIMESTAMP WHERE id=?", tuple(payload.values()) + (cid,))
            else:
                cur = conn.execute("INSERT INTO companies(" + ",".join(payload) + ") VALUES (" +
                                   ",".join("?" * len(payload)) + ")", tuple(payload.values()))
                cid_new = cur.lastrowid
            conn.commit()
        except sqlite3.IntegrityError as ex:
            if "companies.name" in str(ex):
                raise ValueError("يوجد شركة بهذا الاسم مسجلة مسبقاً.") from ex
            raise
    finally:
        conn.close()
    if cid:
        log_audit("companies", cid, "UPDATE", dict(old), payload, note="تعديل بيانات الشركة")
        return cid, f"تم تحديث بيانات الشركة: {name}"
    log_audit("companies", cid_new, "INSERT", None, payload, note="إضافة شركة")
    return cid_new, f"تمت إضافة الشركة: {name}"


def company_links(cid) -> dict:
    out = {}
    n = lambda sql, *a: _safe_count(sql, a)
    out["موظفون"] = n("SELECT COUNT(*) c FROM employee_placements WHERE company_id=?", cid)
    out["فواتير"] = n("SELECT COUNT(*) c FROM invoices WHERE company_id=?", cid)
    out["مندوب"] = n("SELECT COUNT(*) c FROM company_rep_terms WHERE company_id=?", cid)
    out["تحويلات"] = n("SELECT COUNT(*) c FROM client_transfers t JOIN employee_placements p ON p.id=t.placement_id WHERE p.company_id=?", cid)
    out["إذون"] = n("SELECT COUNT(*) c FROM vouchers WHERE party_type='company' AND party_id=?", cid)
    return {k: v for k, v in out.items() if v}


def _safe_count(sql, params):
    try:
        return query_one(sql, tuple(params))["c"]
    except sqlite3.Error:
        return 0


def delete_company(cid) -> str:
    row = query_one("SELECT * FROM companies WHERE id=?", (cid,))
    if not row:
        raise ValueError("الشركة غير موجودة.")
    links = company_links(cid)
    if links:
        raise ValueError("لا يمكن حذف الشركة لأنها مرتبطة بسجلات (" + "، ".join(f"{k}: {v}" for k, v in links.items()) +
                         "). غيّر حالتها إلى «غير نشط» وضع تاريخ توقفها ليبقى تاريخها.")
    conn = get_connection()
    try:
        conn.execute("DELETE FROM companies WHERE id=?", (cid,))
        conn.commit()
    finally:
        conn.close()
    log_audit("companies", cid, "STATUS_CHANGE", row, {"deleted": True}, note="حذف شركة")
    return f"تم حذف الشركة: {row['name']}"


# ------------------------------------------------------------------ representative
def rep_terms(cid) -> list:
    return query_all("""SELECT t.*, r.name AS rep_name FROM company_rep_terms t
                        JOIN representatives r ON r.id=t.representative_id
                        WHERE t.company_id=? ORDER BY t.start_date DESC, t.id DESC""", (cid,))


def current_rep(cid, on: date = None):
    """The rep term in force on a date (today by default) or None."""
    d = (on or date.today()).strftime("%Y-%m-%d")
    return query_one("""SELECT t.*, r.name AS rep_name FROM company_rep_terms t
                        JOIN representatives r ON r.id=t.representative_id
                        WHERE t.company_id=? AND t.start_date<=? AND (t.end_date IS NULL OR t.end_date>=?)
                        ORDER BY t.start_date DESC, t.id DESC LIMIT 1""", (cid, d, d))


def set_rep(cid, representative_id, percent, start) -> str:
    """Give the company a rep (one at a time). An open term is closed the day before `start`."""
    if not query_one("SELECT 1 FROM companies WHERE id=?", (cid,)):
        raise ValueError("الشركة غير موجودة.")
    rep = query_one("SELECT * FROM representatives WHERE id=?", (representative_id,))
    if not rep:
        raise ValueError("اختر المندوب.")
    p = _money(percent)
    if not (0 <= p <= 100):
        raise ValueError("النسبة بين 0 و100.")
    s = _d(start)
    if not s:
        raise ValueError("تاريخ بداية المندوب مطلوب.")
    openterm = query_one("SELECT * FROM company_rep_terms WHERE company_id=? AND end_date IS NULL", (cid,))
    later = query_one("SELECT 1 FROM company_rep_terms WHERE company_id=? AND start_date>=?", (cid, s))
    if later:
        raise ValueError("يوجد مندوب بدأ في هذا التاريخ أو بعده. اختر تاريخاً أحدث.")
    conn = get_connection()
    try:
        if openterm:
            prev_end = (datetime.strptime(s, "%Y-%m-%d").date() - timedelta(days=1)).strftime("%Y-%m-%d")
            if prev_end < openterm["start_date"]:
                raise ValueError("تاريخ البداية يسبق بداية المندوب الحالي.")
            conn.execute("UPDATE company_rep_terms SET end_date=?, end_reason='استبدال بمندوب آخر' WHERE id=?",
                         (prev_end, openterm["id"]))
        cur = conn.execute("INSERT INTO company_rep_terms(company_id, representative_id, percent, start_date) VALUES (?,?,?,?)",
                           (cid, representative_id, p, s))
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()
    log_audit("company_rep_terms", new_id, "INSERT", None,
              {"company_id": cid, "representative_id": representative_id, "percent": p, "start_date": s},
              note="تعيين مندوب للشركة")
    return f"تم تعيين المندوب {rep['name']} بنسبة {p:g}% اعتباراً من {s}."


def end_rep(cid, end, reason=None) -> str:
    t = query_one("SELECT * FROM company_rep_terms WHERE company_id=? AND end_date IS NULL", (cid,))
    if not t:
        raise ValueError("لا يوجد مندوب سارٍ لهذه الشركة.")
    e = _d(end)
    if not e:
        raise ValueError("تاريخ الإنهاء مطلوب.")
    if e < t["start_date"]:
        raise ValueError("تاريخ الإنهاء لا يسبق بداية المندوب.")
    conn = get_connection()
    try:
        conn.execute("UPDATE company_rep_terms SET end_date=?, end_reason=? WHERE id=?", (e, _clean(reason), t["id"]))
        conn.commit()
    finally:
        conn.close()
    log_audit("company_rep_terms", t["id"], "UPDATE", t, {"end_date": e, "end_reason": reason}, note="إنهاء مندوب الشركة")
    return f"تم إنهاء نسبة المندوب بتاريخ {e}."


# ------------------------------------------------------------------ employees (placements)
_PL_SELECT = """SELECT p.*, e.full_name, e.phone, e.national_id, e.iban, e.bank_name,
                       c1.name AS contractor_name, c2.name AS external_name
                FROM employee_placements p
                JOIN employees e ON e.id=p.employee_id
                LEFT JOIN contractors c1 ON c1.id=p.contractor_id
                LEFT JOIN contractors c2 ON c2.id=p.external_id"""


def company_employees(cid, status="all") -> list:
    sql, params = _PL_SELECT + " WHERE p.company_id=?", [cid]
    if status != "all":
        sql += " AND p.status=?"
        params.append(status)
    rows = query_all(sql + " ORDER BY (p.status='active') DESC, e.full_name", tuple(params))
    for r in rows:
        if r["basic_salary"] is None or r["actual_cost"] is None:
            r["refund"], r["net"] = None, None
        else:
            c = calc(r["basic_salary"], r["actual_cost"], r["bonus"], r["contractor_commission"], r["external_commission"])
            r["refund"], r["net"] = c["refund"], c["net"]
    return rows


def get_placement(pid):
    rows = query_all(_PL_SELECT + " WHERE p.id=?", (pid,))
    return rows[0] if rows else None


def company_expected(cid) -> dict:
    """Expected monthly figures if the client pays in full (active employees only)."""
    emps = [r for r in company_employees(cid, "active") if r["net"] is not None]
    total_net = round(sum(r["net"] for r in emps), 2)
    rep = current_rep(cid)
    pct = rep["percent"] if rep else 0.0
    rep_amt = round(total_net * pct / 100.0, 2)
    return {"employees": len(emps), "revenue": round(sum(r["actual_cost"] for r in emps), 2),
            "refund": round(sum(r["refund"] for r in emps), 2), "bonus": round(sum(r["bonus"] for r in emps), 2),
            "contractors": round(sum(r["contractor_commission"] for r in emps), 2),
            "external": round(sum(r["external_commission"] for r in emps), 2),
            "net": total_net, "rep_percent": pct, "rep_amount": rep_amt, "margin": round(total_net - rep_amt, 2),
            "rep_name": rep["rep_name"] if rep else None}


def _employee_payload(e: dict) -> dict:
    name = _clean(e.get("full_name"))
    if not name:
        raise ValueError("اسم الموظف مطلوب.")
    return {"full_name": name, "phone": _clean(e.get("phone")), "national_id": _clean(e.get("national_id")),
            "iban": _clean(e.get("iban")), "bank_name": _clean(e.get("bank_name")),
            "email": _clean(e.get("email"))}


def _terms_payload(t: dict) -> dict:
    out = {"basic_salary": _money(t.get("basic_salary")), "actual_cost": _money(t.get("actual_cost")),
           "bonus": _money(t.get("bonus")), "contractor_id": t.get("contractor_id") or None,
           "contractor_commission": _money(t.get("contractor_commission")), "external_id": t.get("external_id") or None,
           "external_commission": _money(t.get("external_commission"))}
    if not out["contractor_id"]:
        out["contractor_commission"] = 0.0
    if not out["external_id"]:
        out["external_commission"] = 0.0
    return out


def _dates_payload(t: dict) -> dict:
    s = _d(t.get("start_date"))
    if not s:
        raise ValueError("تاريخ بداية العمل مطلوب.")
    status = t.get("status") or "active"
    if status not in ("active", "ended"):
        raise ValueError("الحالة: نشط أو مستبعد.")
    e = _d(t.get("end_date"))
    if status == "ended" and not e:
        raise ValueError("اكتب تاريخ الاستبعاد (آخر يوم عمل) ليُحسب الشهر الأخير بالأيام الفعلية.")
    if status == "active":
        e = None
    if e and e < s:
        raise ValueError("تاريخ النهاية لا يسبق تاريخ البداية.")
    return {"start_date": s, "end_date": e, "status": status, "stop_reason": _clean(t.get("stop_reason")),
            "notes": _clean(t.get("notes"))}


def add_employee(cid, emp: dict, terms: dict, existing_employee_id=None) -> tuple:
    """Create (or reuse) the employee and place him/her in the company with the given terms."""
    company = query_one("SELECT * FROM companies WHERE id=?", (cid,))
    if not company:
        raise ValueError("الشركة غير موجودة.")
    errs = terms_problems(terms)
    if errs:
        raise ValueError(errs[0])
    t, dts = _terms_payload(terms), _dates_payload(terms)
    if company["work_start_date"] and dts["start_date"] < company["work_start_date"]:
        raise ValueError(f"بداية عمل الموظف تسبق بداية عمل الشركة ({company['work_start_date']}).")
    conn = get_connection()
    try:
        if existing_employee_id:
            e_row = conn.execute("SELECT * FROM employees WHERE id=?", (existing_employee_id,)).fetchone()
            if not e_row:
                raise ValueError("الموظف المختار غير موجود.")
            eid, ename = existing_employee_id, e_row["full_name"]
        else:
            ep = _employee_payload(emp)
            try:
                if ep["national_id"] and conn.execute("SELECT 1 FROM employees WHERE national_id=?", (ep["national_id"],)).fetchone():
                    raise ValueError("رقم الهوية هذا مسجل مسبقاً لموظف آخر. اختر «موظف موجود».")
                cur = conn.execute("INSERT INTO employees(full_name, phone, national_id, iban, bank_name, email) VALUES (?,?,?,?,?,?)",
                                   (ep["full_name"], ep["phone"], ep["national_id"], ep["iban"], ep["bank_name"], ep["email"]))
            except sqlite3.IntegrityError as ex:
                raise ValueError("تعذر حفظ بيانات الموظف (قيمة مكررة).") from ex
            eid, ename = cur.lastrowid, ep["full_name"]
        busy = conn.execute("""SELECT c.name FROM employee_placements p JOIN companies c ON c.id=p.company_id
                               WHERE p.employee_id=? AND p.status='active' AND p.end_date IS NULL""", (eid,)).fetchone()
        if busy and dts["status"] == "active":
            raise ValueError(f"الموظف نشط حالياً في شركة «{busy['name']}». استبعده منها أولاً.")
        cols = {**t, **dts, "employee_id": eid, "company_id": cid, "flow_mode": "direct"}
        cur = conn.execute("INSERT INTO employee_placements(" + ",".join(cols) + ") VALUES (" + ",".join("?" * len(cols)) + ")",
                           tuple(cols.values()))
        pid = cur.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log_audit("employee_placements", pid, "INSERT", None, {**cols}, note="إضافة موظف إلى شركة")
    return pid, f"تمت إضافة الموظف {ename} إلى الشركة."


def update_employee(pid, emp: dict, terms: dict) -> str:
    cur_row = get_placement(pid)
    if not cur_row:
        raise ValueError("التعيين غير موجود.")
    errs = terms_problems(terms)
    if errs:
        raise ValueError(errs[0])
    t, dts = _terms_payload(terms), _dates_payload(terms)
    ep = _employee_payload(emp)
    conn = get_connection()
    try:
        if ep["national_id"] and conn.execute("SELECT 1 FROM employees WHERE national_id=? AND id<>?",
                                              (ep["national_id"], cur_row["employee_id"])).fetchone():
            raise ValueError("رقم الهوية هذا مسجل مسبقاً لموظف آخر.")
        if dts["status"] == "active" and conn.execute(
                """SELECT 1 FROM employee_placements WHERE employee_id=? AND id<>? AND status='active' AND end_date IS NULL""",
                (cur_row["employee_id"], pid)).fetchone():
            raise ValueError("للموظف تعيين نشط آخر مفتوح.")
        conn.execute("UPDATE employees SET full_name=?, phone=?, national_id=?, iban=?, bank_name=?, email=?, "
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (ep["full_name"], ep["phone"], ep["national_id"], ep["iban"], ep["bank_name"], ep["email"],
                      cur_row["employee_id"]))
        cols = {**t, **dts}
        conn.execute("UPDATE employee_placements SET " + ", ".join(f"{k}=?" for k in cols) +
                     ", updated_at=CURRENT_TIMESTAMP WHERE id=?", tuple(cols.values()) + (pid,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    log_audit("employee_placements", pid, "UPDATE", cur_row, {**cols, **{k: v for k, v in ep.items()}},
              note="تعديل بيانات وشروط موظف")
    return f"تم تحديث بيانات الموظف {ep['full_name']}."


def exclude_employee(pid, end, reason=None) -> str:
    """Mark as excluded (مستبعد) with the last working day. Past months keep their figures."""
    p = get_placement(pid)
    if not p:
        raise ValueError("التعيين غير موجود.")
    e = _d(end)
    if not e:
        raise ValueError("تاريخ الاستبعاد مطلوب.")
    if e < p["start_date"]:
        raise ValueError("تاريخ الاستبعاد لا يسبق بداية العمل.")
    conn = get_connection()
    try:
        conn.execute("UPDATE employee_placements SET status='ended', end_date=?, stop_reason=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (e, _clean(reason), pid))
        conn.commit()
    finally:
        conn.close()
    log_audit("employee_placements", pid, "STATUS_CHANGE", p, {"status": "ended", "end_date": e, "reason": reason},
              note="استبعاد موظف")
    return f"تم استبعاد {p['full_name']} اعتباراً من {e}. آخر شهر يُحسب بالأيام الفعلية."


def placement_links(pid) -> dict:
    n = lambda sql: _safe_count(sql, (pid,))
    out = {"تحويلات": n("SELECT COUNT(*) c FROM client_transfers WHERE placement_id=?")}
    return {k: v for k, v in out.items() if v}


def delete_employee_placement(pid) -> str:
    p = get_placement(pid)
    if not p:
        raise ValueError("التعيين غير موجود.")
    links = placement_links(pid)
    if links:
        raise ValueError("لا يمكن الحذف لأن له سجلات مالية (" + "، ".join(f"{k}: {v}" for k, v in links.items()) +
                         "). استبعده بدلاً من ذلك ليبقى تاريخه.")
    conn = get_connection()
    try:
        conn.execute("DELETE FROM employee_placements WHERE id=?", (pid,))
        others = conn.execute("SELECT 1 FROM employee_placements WHERE employee_id=?", (p["employee_id"],)).fetchone()
        removed_emp = False
        if not others:
            try:
                conn.execute("DELETE FROM employees WHERE id=?", (p["employee_id"],))
                removed_emp = True
            except sqlite3.IntegrityError:
                pass
        conn.commit()
    finally:
        conn.close()
    log_audit("employee_placements", pid, "STATUS_CHANGE", p, {"deleted": True, "employee_removed": removed_emp},
              note="حذف موظف من الشركة")
    return f"تم حذف {p['full_name']} من الشركة."


def available_employees() -> list:
    """Existing employees that are not active anywhere (can be placed in another company)."""
    return query_all("""SELECT e.id, e.full_name, e.phone FROM employees e
                        WHERE NOT EXISTS (SELECT 1 FROM employee_placements p WHERE p.employee_id=e.id
                                          AND p.status='active' AND p.end_date IS NULL)
                        ORDER BY e.full_name""")


def contractors_of_kind(kind) -> list:
    return query_all("SELECT id, name FROM contractors WHERE COALESCE(kind,'contractor')=? AND status='active' ORDER BY name",
                     (kind,))
