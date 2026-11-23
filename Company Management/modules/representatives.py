from modules import entities

CFG = {
    "key": "rep", "table": "representatives", "singular": "مندوب", "name_field": "name",
    "name_label": "اسم مندوب", "statuses": {"active": "نشط", "inactive": "غير نشط"}, "dup_check": True,
    "search": ["name", "id_number", "phone", "email"],
    "search_hint": "🔍 ابحث بالاسم أو الهوية/السجل أو الهاتف أو البريد",
    "fields": [
        {"name": "name", "label": "اسم مندوب *"},
        {"name": "id_number", "label": "رقم الهوية/السجل (حساس)", "kind": "sensitive"},
        {"name": "phone", "label": "الهاتف"},
        {"name": "bank_name", "label": "اسم البنك (حساس)", "kind": "sensitive"},
        {"name": "email", "label": "البريد الإلكتروني"},
        {"name": "iban", "label": "الآيبان (حساس)", "kind": "sensitive"},
        {"name": "notes", "label": "ملاحظات", "kind": "area"},
    ],
    "quick_fields": ["name", "phone"],
    "list_sql": """SELECT t.*, (SELECT COUNT(*) FROM company_rep_terms x WHERE x.representative_id=t.id AND x.end_date IS NULL) AS active_agreements
                   FROM representatives t""",
    "columns": [("id", "الرقم"), ("name", "المندوب"), ("phone", "الهاتف"), ("email", "البريد"),
                ("active_agreements", "شركات سارية"), ("status", "الحالة")],
}


def render():
    entities.render(CFG)
