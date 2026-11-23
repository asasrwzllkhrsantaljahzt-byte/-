CFG = {
    "key": "emp", "table": "employees", "singular": "موظف", "name_field": "full_name",
    "name_label": "اسم الموظف", "statuses": {"active": "نشط", "inactive": "غير نشط", "suspended": "موقوف"},
    "search": ["full_name", "national_id", "phone", "email"],
    "search_hint": "🔍 ابحث بالاسم أو الهوية أو الهاتف أو البريد",
    "dup_check": True,
    "fields": [
        {"name": "full_name", "label": "الاسم الكامل *"},
        {"name": "national_id", "label": "رقم الهوية (حساس)", "kind": "sensitive"},
        {"name": "phone", "label": "الهاتف"},
        {"name": "bank_name", "label": "اسم البنك (حساس)", "kind": "sensitive"},
        {"name": "email", "label": "البريد الإلكتروني"},
        {"name": "iban", "label": "الآيبان (حساس)", "kind": "sensitive"},
        {"name": "notes", "label": "ملاحظات", "kind": "area"},
    ],
    "quick_fields": ["full_name", "phone", "national_id"],
    "list_sql": """SELECT t.*, (SELECT c.name FROM employee_placements p JOIN companies c ON c.id=p.company_id
                   WHERE p.employee_id=t.id AND p.status='active' AND p.end_date IS NULL ORDER BY p.id DESC LIMIT 1) AS current_company
                   FROM employees t""",
    "columns": [("id", "الرقم"), ("full_name", "الموظف"), ("current_company", "الشركة الحالية"), ("phone", "الهاتف"),
                ("email", "البريد"), ("status", "الحالة")],
}

