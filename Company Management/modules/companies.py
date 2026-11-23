CFG = {
    "key": "co", "table": "companies", "singular": "شركة", "masculine": False, "name_field": "name",
    "name_label": "اسم الشركة", "statuses": {"active": "نشط", "inactive": "غير نشط"},
    "search": ["name", "commercial_register", "tax_number", "contact_person", "phone"],
    "search_hint": "🔍 ابحث بالاسم أو السجل التجاري أو الرقم الضريبي أو المسؤول أو الهاتف",
    "fields": [
        {"name": "name", "label": "اسم الشركة *"},
        {"name": "commercial_register", "label": "السجل التجاري"},
        {"name": "tax_number", "label": "الرقم الضريبي"},
        {"name": "contact_person", "label": "الشخص المسؤول"},
        {"name": "phone", "label": "الهاتف"},
        {"name": "email", "label": "البريد الإلكتروني"},
        {"name": "address", "label": "العنوان", "kind": "area"},
        {"name": "notes", "label": "ملاحظات", "kind": "area"},
    ],
    "quick_fields": ["name", "phone"],
    "list_sql": """SELECT t.*, (SELECT COUNT(DISTINCT p.employee_id) FROM employee_placements p
                   WHERE p.company_id=t.id AND p.status='active' AND p.end_date IS NULL) AS active_emps
                   FROM companies t""",
    "columns": [("id", "الرقم"), ("name", "الشركة"), ("active_emps", "الموظفون النشطون"), ("contact_person", "المسؤول"),
                ("phone", "الهاتف"), ("commercial_register", "السجل التجاري"), ("tax_number", "الرقم الضريبي"), ("status", "الحالة")],
}

