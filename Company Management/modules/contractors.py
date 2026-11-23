from modules import entities

CFG = {
    "key": "con", "table": "contractors", "singular": "متعهد", "name_field": "name",
    "name_label": "اسم متعهد", "statuses": {"active": "نشط", "inactive": "غير نشط"}, "dup_check": True,
    "search": ["name", "id_number", "phone", "email"],
    "search_hint": "🔍 ابحث بالاسم أو الهوية/السجل أو الهاتف أو البريد",
    "fields": [
        {"name": "name", "label": "الاسم *"},
        {"name": "kind", "label": "النوع", "kind": "select", "options": {"contractor": "متعهد", "external": "عمولة خارجية"}},
        {"name": "id_number", "label": "رقم الهوية/السجل (حساس)", "kind": "sensitive"},
        {"name": "phone", "label": "الهاتف"},
        {"name": "bank_name", "label": "اسم البنك (حساس)", "kind": "sensitive"},
        {"name": "email", "label": "البريد الإلكتروني"},
        {"name": "iban", "label": "الآيبان (حساس)", "kind": "sensitive"},
        {"name": "notes", "label": "ملاحظات", "kind": "area"},
    ],
    "quick_fields": ["name", "kind", "phone"],
    "list_sql": """SELECT t.*, (SELECT COUNT(*) FROM employee_placements x WHERE (x.contractor_id=t.id OR x.external_id=t.id) AND x.status='active') AS active_agreements
                   FROM contractors t""",
    "columns": [("id", "الرقم"), ("name", "الاسم"), ("kind", "النوع"), ("phone", "الهاتف"), ("email", "البريد"),
                ("active_agreements", "موظفون نشطون"), ("status", "الحالة")],
}


def render():
    entities.render(CFG)
