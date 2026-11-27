"""Import / update employees of client companies from an Excel sheet."""
import io
from datetime import date, datetime

import pandas as pd

import company_hub as H
from db import query_all, query_one

COLS = ["الشركة", "اسم الموظف", "رقم الهوية", "الهاتف", "البنك", "الآيبان", "الراتب الأساسي", "التكلفة الفعلية", "المكافأة",
        "المتعهد", "عمولة المتعهد", "جهة العمولة الخارجية", "العمولة الخارجية", "تاريخ البداية", "الحالة", "تاريخ الاستبعاد", "سبب الاستبعاد"]
REQUIRED = ["الشركة", "اسم الموظف", "الراتب الأساسي", "التكلفة الفعلية", "تاريخ البداية"]
MAX_IMPORT_ROWS = 50
STATUS_IN = {"نشط": "active", "active": "active", "": "active", "مستبعد": "ended", "ended": "ended", "موقوف": "ended"}


def _existing_rows(company_id) -> list:
    rows = []
    for r in H.company_employees(company_id, "all"):
        cname = query_one("SELECT name FROM companies WHERE id=?", (company_id,))["name"]
        rows.append({"الشركة": cname, "اسم الموظف": r["full_name"], "رقم الهوية": r["national_id"] or "", "الهاتف": r["phone"] or "",
                     "البنك": r["bank_name"] or "", "الآيبان": r["iban"] or "", "الراتب الأساسي": r["basic_salary"] or 0,
                     "التكلفة الفعلية": r["actual_cost"] or 0, "المكافأة": r["bonus"] or 0, "المتعهد": r["contractor_name"] or "",
                     "عمولة المتعهد": r["contractor_commission"] or 0, "جهة العمولة الخارجية": r["external_name"] or "",
                     "العمولة الخارجية": r["external_commission"] or 0, "تاريخ البداية": r["start_date"] or "",
                     "الحالة": "نشط" if r["status"] == "active" else "مستبعد", "تاريخ الاستبعاد": r["end_date"] or "",
                     "سبب الاستبعاد": r["stop_reason"] or ""})
    return rows


def template_bytes(company_id=None) -> bytes:
    """Empty template, or (with company_id) the company's current employees ready to edit and re-upload."""
    cos = [r["name"] for r in query_all("SELECT name FROM companies ORDER BY name")]
    existing = _existing_rows(company_id) if company_id else []
    sample = pd.DataFrame(existing or [{
        "الشركة": cos[0] if cos else "اسم الشركة كما هو في النظام", "اسم الموظف": "منال محمد", "رقم الهوية": "1000000001", "الهاتف": "0500000000",
        "البنك": "", "الآيبان": "", "الراتب الأساسي": 2000, "التكلفة الفعلية": 1700, "المكافأة": 1000, "المتعهد": "", "عمولة المتعهد": 0,
        "جهة العمولة الخارجية": "", "العمولة الخارجية": 0, "تاريخ البداية": "2026-01-01", "الحالة": "نشط", "تاريخ الاستبعاد": "", "سبب الاستبعاد": ""}], columns=COLS)
    help_rows = [
        "املأ شيت «الموظفات» (احذف الصف التجريبي). الأعمدة المطلوبة: الشركة، اسم الموظف، الراتب الأساسي، التكلفة الفعلية، تاريخ البداية.",
        f"الحد الأقصى {MAX_IMPORT_ROWS} موظفاً في الملف الواحد.",
        "اسم الشركة والمتعهد وجهة العمولة يجب أن يطابقوا ما هو مسجل في النظام تماماً (سجّلهم أولاً).",
        "التواريخ بصيغة 2026-01-31. الحالة: نشط أو مستبعد (والمستبعد يحتاج تاريخ استبعاد).",
        "إن كان الموظف موجوداً (بنفس رقم الهوية، أو الاسم داخل نفس الشركة) فسيُحدَّث بدل أن يتكرر.",
        "الأعمدة الاختيارية يمكن تركها فارغة. المبالغ أرقام فقط.",
    ]
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        sample.to_excel(w, sheet_name="الموظفات", index=False)
        pd.DataFrame({"تعليمات": help_rows}).to_excel(w, sheet_name="تعليمات", index=False)
        pd.DataFrame({"الشركات المسجلة": cos}).to_excel(w, sheet_name="الشركات", index=False)
        for ws in w.sheets.values():
            ws.sheet_view.rightToLeft = True
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = 22
        w.sheets["تعليمات"].column_dimensions["A"].width = 120
    return out.getvalue()


def _s(v):
    if _blank(v):
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def _blank(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _ensure_row_limit(df):
    row_count = sum(not all(_blank(value) for value in row.values()) for row in df.to_dict("records"))
    if row_count > MAX_IMPORT_ROWS:
        raise ValueError(f"الحد الأقصى {MAX_IMPORT_ROWS} موظفاً في الملف الواحد؛ الملف يحتوي {row_count} موظفاً.")


def _num(v, name):
    t = _s(v).replace(",", "")
    if t == "":
        return 0.0
    try:
        return float(t)
    except ValueError as ex:
        raise ValueError(f"«{name}» ليس رقماً: {t}") from ex


def _date(v, name):
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d") if not isinstance(v, pd.Timestamp) or not pd.isna(v) else None
    t = _s(v)
    if not t:
        return None
    try:
        return datetime.strptime(t[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as ex:
        raise ValueError(f"«{name}» تاريخ غير صحيح ({t}). الصيغة: 2026-01-31") from ex


def read_sheet(data: bytes) -> pd.DataFrame:
    try:
        xl = pd.ExcelFile(io.BytesIO(data))
        df = xl.parse("الموظفات" if "الموظفات" in xl.sheet_names else xl.sheet_names[0], dtype=object)
    except Exception as ex:  # noqa: BLE001
        raise ValueError("تعذرت قراءة الملف. استخدم ملف Excel (xlsx) من القالب.") from ex
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError("أعمدة ناقصة: " + "، ".join(missing) + ". نزّل القالب واستخدمه.")
    for c in COLS:
        if c not in df.columns:
            df[c] = None
    df = df.dropna(how="all")
    _ensure_row_limit(df)
    return df


def _lookup(table, name, kind=None):
    sql, params = f"SELECT id FROM {table} WHERE TRIM(name)=?", [name]
    if kind:
        sql += " AND COALESCE(kind,'contractor')=?"
        params.append(kind)
    r = query_all(sql, tuple(params))
    return r[0]["id"] if r else None


def plan(df: pd.DataFrame, company_id=None) -> list:
    """One dict per row: {row, name, company, action: add|update|error, error, emp, terms, cid, pid, eid}. Writes nothing."""
    _ensure_row_limit(df)
    out, seen = [], set()
    for i, r in enumerate(df.to_dict("records"), start=2):
        item = {"row": i, "name": _s(r.get("اسم الموظف")), "company": _s(r.get("الشركة")), "action": "error", "error": ""}
        try:
            if company_id and not item["company"]:
                item["company"] = query_one("SELECT name FROM companies WHERE id=?", (company_id,))["name"]
            if not item["company"] or not item["name"]:
                raise ValueError("الشركة واسم الموظف مطلوبان.")
            cid = _lookup("companies", item["company"])
            if company_id and cid and cid != company_id:
                raise ValueError(f"الصف لشركة أخرى («{item['company']}»). هذا الشيت خاص بهذه الشركة فقط.")
            if not cid:
                raise ValueError(f"الشركة «{item['company']}» غير مسجلة.")
            con_n, ext_n = _s(r.get("المتعهد")), _s(r.get("جهة العمولة الخارجية"))
            con_id = _lookup("contractors", con_n, "contractor") if con_n else None
            ext_id = _lookup("contractors", ext_n, "external") if ext_n else None
            if con_n and not con_id:
                raise ValueError(f"المتعهد «{con_n}» غير مسجل (أو ليس من نوع متعهد).")
            if ext_n and not ext_id:
                raise ValueError(f"جهة العمولة الخارجية «{ext_n}» غير مسجلة (أو ليست من نوع عمولة خارجية).")
            status = STATUS_IN.get(_s(r.get("الحالة")))
            if status is None:
                raise ValueError("الحالة: نشط أو مستبعد.")
            terms = {"basic_salary": _num(r.get("الراتب الأساسي"), "الراتب الأساسي"), "actual_cost": _num(r.get("التكلفة الفعلية"), "التكلفة الفعلية"),
                     "bonus": _num(r.get("المكافأة"), "المكافأة"), "contractor_id": con_id,
                     "contractor_commission": _num(r.get("عمولة المتعهد"), "عمولة المتعهد"), "external_id": ext_id,
                     "external_commission": _num(r.get("العمولة الخارجية"), "العمولة الخارجية"),
                     "start_date": _date(r.get("تاريخ البداية"), "تاريخ البداية"), "status": status,
                     "end_date": _date(r.get("تاريخ الاستبعاد"), "تاريخ الاستبعاد"), "stop_reason": _s(r.get("سبب الاستبعاد"))}
            if not terms["start_date"]:
                raise ValueError("تاريخ البداية مطلوب.")
            probs = H.terms_problems({**terms, "start_date": date.fromisoformat(terms["start_date"])}) if hasattr(H, "terms_problems") else []
            if probs:
                raise ValueError(probs[0])
            emp = {"full_name": item["name"], "national_id": _s(r.get("رقم الهوية")), "phone": _s(r.get("الهاتف")),
                   "bank_name": _s(r.get("البنك")), "iban": _s(r.get("الآيبان"))}
            eid = pid = None
            if emp["national_id"]:
                e = query_one("SELECT id FROM employees WHERE national_id=?", (emp["national_id"],))
                eid = e["id"] if e else None
            if eid is None:
                e = query_one("""SELECT e.id FROM employees e JOIN employee_placements p ON p.employee_id=e.id
                                 WHERE e.full_name=? AND p.company_id=? ORDER BY p.id DESC""", (item["name"], cid))
                eid = e["id"] if e else None
            if eid:
                pl = query_one("SELECT id FROM employee_placements WHERE employee_id=? AND company_id=? ORDER BY (status='active') DESC, id DESC", (eid, cid))
                pid = pl["id"] if pl else None
            key = (cid, emp["national_id"] or item["name"])
            if key in seen:
                raise ValueError("الموظف مكرر في الملف.")
            seen.add(key)
            item.update(action="update" if pid else "add", cid=cid, eid=eid, pid=pid, emp=emp, terms=terms)
        except ValueError as ex:
            item["error"] = str(ex)
        out.append(item)
    return out


def apply(items: list) -> dict:
    """Runs the valid rows. Returns {'added','updated','failed':[(row, msg)]}."""
    res = {"added": 0, "updated": 0, "failed": []}
    for it in items:
        if it["action"] == "error":
            res["failed"].append((it["row"], it["error"]))
            continue
        t = dict(it["terms"])
        for k in ("start_date", "end_date"):
            t[k] = date.fromisoformat(t[k]) if t.get(k) else None
        try:
            if it["action"] == "update":
                H.update_employee(it["pid"], it["emp"], t)
                res["updated"] += 1
            else:
                H.add_employee(it["cid"], it["emp"] if not it["eid"] else {}, t, existing_employee_id=it["eid"])
                res["added"] += 1
        except ValueError as ex:
            res["failed"].append((it["row"], str(ex)))
    return res
