"""Excel templates and validated imports for transfers and employee receipts."""
import io
import math
import sqlite3
from datetime import date, datetime

import pandas as pd

import hub_engine as E
import vouchers as V
from db import query_all, query_one

TRANSFER_COLUMNS = ["الشركة", "شهر العمل", "اسم الموظف", "المبلغ المحول", "تاريخ التحويل", "ملاحظات"]
RECEIPT_COLUMNS = ["اسم الموظف", "الشركة", "المبلغ", "التاريخ", "طريقة الدفع", "المرجع", "شهر العمل", "البيان"]
_COLUMNS = {"transfer": TRANSFER_COLUMNS, "employee_receipt": RECEIPT_COLUMNS}
MAX_IMPORT_ROWS = 50
_REQUIRED = {
    "transfer": ["الشركة", "شهر العمل", "اسم الموظف", "المبلغ المحول", "تاريخ التحويل"],
    "employee_receipt": ["اسم الموظف", "المبلغ", "التاريخ"],
}
_ARABIC_NUMBERS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")


def template_bytes(operation: str) -> bytes:
    if operation not in _COLUMNS:
        raise ValueError("نوع الحركة غير مدعوم للاستيراد.")

    instructions = [
        "أدخل كل حركة في صف مستقل بورقة «الحركات»، واترك الصفوف الفارغة كما هي.",
        f"الحد الأقصى {MAX_IMPORT_ROWS} حركة في الملف الواحد.",
        "لا تغيّر أسماء الأعمدة. المبلغ يجب أن يكون أكبر من صفر، والتاريخ بصيغة YYYY-MM-DD.",
        "استخدم أسماء الشركة والموظف كما تظهر في ورقة «المرجع» والنظام.",
    ]
    if operation == "transfer":
        instructions.append("شهر العمل بصيغة YYYY-MM. أدخل اسم الشركة واسم الموظف في عموديهما.")
        reference = pd.DataFrame(query_all("""
            SELECT c.name AS 'الشركة', e.full_name AS 'اسم الموظف',
                   p.start_date AS 'بداية التعيين', COALESCE(p.end_date, '') AS 'نهاية التعيين',
                   CASE WHEN p.status='active' THEN 'نشط' ELSE 'منتهي' END AS 'الحالة'
            FROM employee_placements p
            JOIN companies c ON c.id=p.company_id
            JOIN employees e ON e.id=p.employee_id
            ORDER BY c.name, e.full_name, p.start_date, p.id
        """))
        reference_columns = ["الشركة", "اسم الموظف", "بداية التعيين", "نهاية التعيين", "الحالة"]
    else:
        instructions.extend([
            "طريقة الدفع: نقداً، حوالة بنكية، شيك، أو أخرى. إذا تُركت فارغة فستُسجل نقداً.",
            "شهر العمل اختياري، ويُكتب بصيغة YYYY-MM.",
            "الشركة اختيارية، واستخدمها إذا تكرر اسم الموظف في النظام.",
        ])
        reference = pd.DataFrame(query_all(
            """SELECT DISTINCT e.full_name AS 'اسم الموظف', c.name AS 'الشركة'
               FROM employees e
               LEFT JOIN employee_placements p ON p.employee_id=e.id
               LEFT JOIN companies c ON c.id=p.company_id
               ORDER BY e.full_name, c.name"""
        ))
        reference_columns = ["اسم الموظف", "الشركة"]

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        pd.DataFrame(columns=_COLUMNS[operation]).to_excel(writer, sheet_name="الحركات", index=False)
        pd.DataFrame({"تعليمات": instructions}).to_excel(writer, sheet_name="تعليمات", index=False)
        reference.reindex(columns=reference_columns).to_excel(writer, sheet_name="المرجع", index=False)
        for sheet in writer.sheets.values():
            sheet.sheet_view.rightToLeft = True
            for column in sheet.columns:
                sheet.column_dimensions[column[0].column_letter].width = 24
        writer.sheets["تعليمات"].column_dimensions["A"].width = 88
    return out.getvalue()


def read_sheet(data: bytes, operation: str) -> pd.DataFrame:
    if operation not in _COLUMNS:
        raise ValueError("نوع الحركة غير مدعوم للاستيراد.")
    try:
        workbook = pd.ExcelFile(io.BytesIO(data))
    except Exception as ex:  # noqa: BLE001
        raise ValueError("تعذرت قراءة الملف. استخدم ملف Excel (xlsx) من القالب المناسب.") from ex
    if "الحركات" not in workbook.sheet_names:
        raise ValueError("الملف لا يحتوي ورقة «الحركات». نزّل القالب المناسب.")
    try:
        frame = pd.read_excel(io.BytesIO(data), sheet_name="الحركات", dtype=object)
    except Exception as ex:  # noqa: BLE001
        raise ValueError("تعذرت قراءة ورقة «الحركات». نزّل القالب المناسب وأعد تعبئته.") from ex

    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [column for column in _REQUIRED[operation] if column not in frame.columns]
    if missing:
        legacy_identifier = {"transfer": "رقم التعيين", "employee_receipt": "رقم الموظف"}[operation]
        if legacy_identifier in frame.columns:
            raise ValueError(
                f"هذا قالب قديم يعتمد «{legacy_identifier}». نزّل القالب الحالي وأدخل أسماء الشركة والموظف."
            )
        raise ValueError("أعمدة ناقصة: " + "، ".join(missing) + ". نزّل القالب المناسب.")
    for column in _COLUMNS[operation]:
        if column not in frame.columns:
            frame[column] = None
    _ensure_row_limit(frame)
    return frame


def _blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text(value) -> str:
    return "" if _blank(value) else str(value).strip()


def _ensure_row_limit(frame: pd.DataFrame):
    row_count = sum(not all(_blank(value) for value in row.values()) for row in frame.to_dict("records"))
    if row_count > MAX_IMPORT_ROWS:
        raise ValueError(f"الحد الأقصى {MAX_IMPORT_ROWS} حركة في الملف الواحد؛ الملف يحتوي {row_count} حركة.")


def _amount(value) -> float:
    text = _text(value).translate(_ARABIC_NUMBERS).replace(",", "")
    try:
        amount = float(text)
    except ValueError as ex:
        raise ValueError("المبلغ غير صحيح.") from ex
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من صفر.")
    return round(amount, 2)


def _date(value, label) -> date:
    if isinstance(value, (datetime, date)):
        return value.date() if isinstance(value, datetime) else value
    text = _text(value)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as ex:
        raise ValueError(f"«{label}» مطلوب بصيغة YYYY-MM-DD.") from ex


def _month(value, required=False):
    if _blank(value):
        if required:
            raise ValueError("شهر العمل مطلوب بصيغة YYYY-MM.")
        return None
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m")
    text = _text(value)
    try:
        return datetime.strptime(text, "%Y-%m").strftime("%Y-%m")
    except ValueError as ex:
        raise ValueError("شهر العمل بصيغة YYYY-MM.") from ex


def plan(frame: pd.DataFrame, operation: str) -> list:
    """Validate uploaded rows without writing; return one add/error item per non-empty row."""
    if operation not in _COLUMNS:
        raise ValueError("نوع الحركة غير مدعوم للاستيراد.")
    missing = [column for column in _REQUIRED[operation] if column not in frame.columns]
    if missing:
        raise ValueError("أعمدة ناقصة: " + "، ".join(missing) + ". نزّل القالب المناسب.")
    _ensure_row_limit(frame)

    items, seen = [], {}
    methods = {label: key for key, label in V.METHOD_AR.items()}
    for row_number, row in enumerate(frame.to_dict("records"), start=2):
        if all(_blank(value) for value in row.values()):
            continue
        item = {"row": row_number, "action": "error", "error": ""}
        try:
            if operation == "transfer":
                company_name = _text(row.get("الشركة"))
                employee_name = _text(row.get("اسم الموظف"))
                if not company_name or not employee_name:
                    raise ValueError("اسم الشركة واسم الموظف مطلوبان.")
                month = _month(row.get("شهر العمل"), required=True)
                transfer_date = _date(row.get("تاريخ التحويل"), "تاريخ التحويل")
                amount = _amount(row.get("المبلغ المحول"))
                candidates = query_all("""
                    SELECT p.id, c.name AS company_name, e.full_name
                    FROM employee_placements p
                    JOIN companies c ON c.id=p.company_id
                    JOIN employees e ON e.id=p.employee_id
                    WHERE TRIM(c.name)=? AND TRIM(e.full_name)=?
                    ORDER BY p.id
                """, (company_name, employee_name))
                if not candidates:
                    raise ValueError(f"لم يُعثر على الموظف «{employee_name}» في الشركة «{company_name}».")
                valid_candidates, transfer_errors = [], []
                for candidate in candidates:
                    try:
                        E._check_transfer(candidate["id"], month, transfer_date, amount)
                        valid_candidates.append(candidate)
                    except ValueError as ex:
                        transfer_errors.append(str(ex))
                if not valid_candidates:
                    raise ValueError(transfer_errors[0] if transfer_errors else "لا يوجد تعيين صالح لهذا الشهر.")
                if len(valid_candidates) > 1:
                    raise ValueError(
                        f"يوجد أكثر من تعيين صالح للموظف «{employee_name}» في الشركة «{company_name}» لهذا الشهر."
                    )
                placement = valid_candidates[0]
                details = {
                    "placement_id": placement["id"],
                    "month": month,
                    "date": transfer_date,
                    "amount": amount,
                    "notes": _text(row.get("ملاحظات")),
                    "company": placement["company_name"],
                    "employee": placement["full_name"],
                }
                duplicate_key = ("transfer", placement["id"], month, transfer_date, amount, details["notes"])
            else:
                employee_name = _text(row.get("اسم الموظف"))
                company_name = _text(row.get("الشركة"))
                if not employee_name:
                    raise ValueError("اسم الموظف مطلوب.")
                sql = """SELECT DISTINCT e.id, e.full_name
                         FROM employees e
                         LEFT JOIN employee_placements p ON p.employee_id=e.id
                         LEFT JOIN companies c ON c.id=p.company_id
                         WHERE TRIM(e.full_name)=?"""
                params = [employee_name]
                if company_name:
                    sql += " AND TRIM(c.name)=?"
                    params.append(company_name)
                employees = query_all(sql, tuple(params))
                if not employees:
                    if company_name:
                        raise ValueError(f"لم يُعثر على الموظف «{employee_name}» في الشركة «{company_name}».")
                    raise ValueError(f"الموظف «{employee_name}» غير مسجل.")
                if len(employees) > 1:
                    raise ValueError(f"اسم الموظف «{employee_name}» مكرر؛ اكتب اسم الشركة للتمييز.")
                employee = employees[0]
                voucher_date = _date(row.get("التاريخ"), "التاريخ")
                amount = _amount(row.get("المبلغ"))
                method_text = _text(row.get("طريقة الدفع"))
                method = methods.get(method_text, method_text or "cash")
                if method not in V.METHOD_AR:
                    raise ValueError("طريقة الدفع: نقداً، حوالة بنكية، شيك، أو أخرى.")
                month = _month(row.get("شهر العمل"))
                details = {
                    "employee_id": employee["id"],
                    "employee": employee["full_name"],
                    "company": company_name,
                    "date": voucher_date,
                    "amount": amount,
                    "method": method,
                    "reference": _text(row.get("المرجع")),
                    "month": month,
                    "description": _text(row.get("البيان")),
                }
                duplicate_key = ("employee_receipt", employee["id"], voucher_date, amount, method,
                                 details["reference"], month, details["description"])

            item.update(details)
            if duplicate_key in seen:
                raise ValueError(f"الحركة مطابقة للحركة الموجودة في صف Excel رقم {seen[duplicate_key]}.")
            seen[duplicate_key] = row_number
            item["action"] = "add"
        except ValueError as ex:
            item["action"] = "error"
            item["error"] = str(ex)
        items.append(item)
    return items


def apply(items: list, operation: str) -> dict:
    """Create valid rows and return row-level failures and transfer warnings."""
    if operation not in _COLUMNS:
        raise ValueError("نوع الحركة غير مدعوم للاستيراد.")
    result = {"added": 0, "failed": [], "warnings": []}
    for item in items:
        if item["action"] == "error":
            result["failed"].append((item["row"], item["error"]))
            continue
        try:
            if operation == "transfer":
                _, _, warnings = E.add_transfer(
                    item["placement_id"], item["month"], item["date"], item["amount"], item["notes"]
                )
                result["warnings"].extend((item["row"], warning) for warning in warnings)
            else:
                V.issue_voucher(
                    "receipt", item["date"], "employee", item["employee_id"], item["amount"],
                    item["method"], item["reference"], item["month"], item["description"],
                )
            result["added"] += 1
        except (ValueError, sqlite3.Error) as ex:
            result["failed"].append((item["row"], str(ex)))
    return result
