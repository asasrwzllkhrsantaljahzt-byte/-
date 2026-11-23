import streamlit as st
import pandas as pd
from datetime import date
from db import query_all, query_one, execute
from audit import log_audit
from ui import flash_set, show_flash, form_ver, friendly_error, number_field, norm_month, MONTH_EXAMPLE
from finance_engine import ensure_finance_schema


CATEGORIES = [
    ("مبلغ متفق عليه مع العميل (مستحق على العميل)", "client_agreed_amount", "in"),
    ("إيراد معتمد للشركة", "approved_company_revenue", "in"),
    ("أجر الموظف المسجل (مستحق للموظف)", "recorded_wage", "out"),
    ("حوالة بنكية فعلية مدفوعة", "bank_transfer_actual", "out"),
    ("مبلغ مردود / معاد", "refund_returned", "out"),
    ("مصروف خارجي", "external_expense", "out"),
    ("أخرى", "other", "in"),
]
CATEGORY_AR = {c[1]: c[0] for c in CATEGORIES}
DIRECTION_AR = {"in": "داخل (إيراد/مستحق لنا)", "out": "خارج (التزام/مصروف)"}
REVIEW_AR = {"approved": "معتمدة", "pending_review": "قيد المراجعة", "rejected": "مرفوضة"}


def readable_transactions(rows) -> pd.DataFrame:
    """Arabic, human-readable table of ledger rows (names instead of ids, no None)."""
    names = {}
    for key, table, col in (("employee_id", "employees", "full_name"), ("company_id", "companies", "name"),
                            ("contractor_id", "contractors", "name"), ("representative_id", "representatives", "name")):
        names[key] = {r["id"]: r["n"] for r in query_all(f"SELECT id, {col} AS n FROM {table}")}
    out = []
    for r in rows:
        out.append({"الرقم": r["id"], "التاريخ": r["tx_date"], "الشهر": r["month_ref"],
                    "النوع": CATEGORY_AR.get(r["category"], r["category"]), "الاتجاه": DIRECTION_AR.get(r["direction"], r["direction"]),
                    "المبلغ": float(r["amount"]), "الحالة": REVIEW_AR.get(r["review_status"], r["review_status"]),
                    "الموظف": names["employee_id"].get(r.get("employee_id"), ""), "الشركة": names["company_id"].get(r.get("company_id"), ""),
                    "المتعهد": names["contractor_id"].get(r.get("contractor_id"), ""),
                    "المندوب": names["representative_id"].get(r.get("representative_id"), ""),
                    "البيان": r.get("description") or ""})
    return pd.DataFrame(out)


def _options(sql, label_fmt):
    rows = query_all(sql)
    opts = {"(غير محدد)": None}
    for r in rows:
        opts[label_fmt(r)] = r["id"]
    return opts


def render():
    ensure_finance_schema()
    show_flash()
    with st.expander("ℹ️ ما الفرق بين «الحركة المالية» و«الإذن»؟", expanded=False):
        st.markdown(
            "- **الحركة المالية (هذه الصفحة):** قيد محاسبي يُبنى عليه احتساب الشهر، مثل: المبلغ المتفق عليه مع العميل، "
            "أجر الموظف المسجل، المصروف الخارجي. هي التي تصنع «المستحقات» لكل جهة.\n"
            "- **إذن الاستلام / الصرف (صفحة «السندات»):** مال تحرّك فعلاً (نقداً أو حوالة أو شيك) لجهة معيّنة، "
            "وهو الذي يُنقص رصيدها المستحق.\n"
            "- مثال: اتفقت مع شركة على 5000 ريال (حركة) ← استلمت منها 2000 (إذن استلام) ← المتبقي عليها 3000.")
    st.caption("سجّل هنا ما يدخل في احتساب الشهر. لتسجيل مبلغ استلمته أو صرفته فعلاً استخدم صفحة «السندات».")

    @st.dialog("تسجيل حركة مالية", width="large")
    def _tx_dialog():
        with st.form(f"tx_form_{form_ver('tx_ver')}"):
            c1, c2, c3 = st.columns(3)
            with c1:
                tx_date = st.date_input("تاريخ الحركة", value=date.today())
                month_ref = st.text_input("الشهر المرجعي (مثل 2026-03)", value=tx_date.strftime("%Y-%m"))
            with c2:
                cat_label = st.selectbox("نوع الحركة", [c[0] for c in CATEGORIES])
                review = st.selectbox("حالة المراجعة", ["approved", "pending_review", "rejected"], format_func=lambda x: {"approved":"معتمدة","pending_review":"قيد المراجعة (لا تُحسب كربح)","rejected":"مرفوضة"}[x])
            with c3:
                amount = number_field("المبلغ (SAR)", "tx_amount")

            st.markdown("**الربط (اختياري حسب الحركة)**")
            e_opts = _options("SELECT id, full_name FROM employees ORDER BY full_name", lambda r: f"{r['id']} - {r['full_name']}")
            c_opts = _options("SELECT id, name FROM companies ORDER BY name", lambda r: f"{r['id']} - {r['name']}")
            p_opts = _options("SELECT p.id, e.full_name, c.name, p.start_date FROM employee_placements p JOIN employees e ON e.id=p.employee_id JOIN companies c ON c.id=p.company_id ORDER BY p.id DESC", lambda r: f"{r['id']} - {r['full_name']} / {r['name']} ({r['start_date']})")
            co_opts = _options("SELECT id, name FROM contractors ORDER BY name", lambda r: f"{r['id']} - {r['name']}")
            r_opts = _options("SELECT id, name FROM representatives ORDER BY name", lambda r: f"{r['id']} - {r['name']}")

            a,b = st.columns(2)
            with a:
                employee_id = e_opts[st.selectbox("الموظف", list(e_opts.keys()))]
                company_id = c_opts[st.selectbox("الشركة العميلة", list(c_opts.keys()))]
                placement_id = p_opts[st.selectbox("التعيين (موظف/شركة)", list(p_opts.keys()))]
            with b:
                contractor_id = co_opts[st.selectbox("المتعهد (إن وجد)", list(co_opts.keys()))]
                representative_id = r_opts[st.selectbox("المندوب (إن وجد)", list(r_opts.keys()))]
                doc_ref = st.text_input("رقم المستند/المرجع")

            description = st.text_area("الوصف/ملاحظات")
            submitted = st.form_submit_button("حفظ الحركة", type="primary")

        if submitted:
            if not amount or amount <= 0:
                st.error("المبلغ يجب أن يكون أكبر من صفر.")
            elif not norm_month(month_ref):
                st.error(f"الشهر المرجعي غير صحيح. اكتب السنة ثم الشهر، مثال: {MONTH_EXAMPLE}")
            else:
                cat = next(c for c in CATEGORIES if c[0] == cat_label)
                try:
                    payload = {
                        "tx_date": tx_date.strftime("%Y-%m-%d"), "month_ref": norm_month(month_ref), "placement_id": placement_id,
                        "employee_id": employee_id, "company_id": company_id, "contractor_id": contractor_id,
                        "representative_id": representative_id, "category": cat[1], "direction": cat[2], "amount": float(amount),
                        "review_status": review, "description": description.strip() or None, "document_ref": doc_ref.strip() or None,
                    }
                    new_id = execute(
                        """INSERT INTO financial_transactions(tx_date, month_ref, placement_id, employee_id, company_id, contractor_id, representative_id, category, direction, amount, currency, review_status, source_type, description, document_ref)
                           VALUES (?,?,?,?,?,?,?,?,?,?, 'SAR', ?, 'manual', ?, ?)""",
                        (payload["tx_date"], payload["month_ref"], payload["placement_id"], payload["employee_id"], payload["company_id"], payload["contractor_id"], payload["representative_id"], payload["category"], payload["direction"], payload["amount"], payload["review_status"], payload["description"], payload["document_ref"])
                    )
                    log_audit("financial_transactions", new_id, "INSERT", None, payload, note="تسجيل حركة مالية")
                    flash_set("تم حفظ الحركة المالية وتسجيلها في سجل التدقيق.", "tx_ver")
                    st.rerun()
                except Exception as e:
                    st.error(friendly_error(e, "تعذر حفظ الحركة"))

    if st.button("➕ تسجيل حركة مالية", type="primary", key="tx_add_btn"):
        _tx_dialog()
    with st.container():
        month_f = st.text_input("تصفية بالشهر (مثل 2026-03)", value="", key="tx_month_f")
        cat_f = st.selectbox("تصفية بالتصنيف", ["الكل"] + [c[1] for c in CATEGORIES], key="tx_cat_f")
        q = ("SELECT id, tx_date, month_ref, category, direction, amount, review_status, employee_id, company_id, placement_id, "
             "contractor_id, representative_id, description FROM financial_transactions WHERE 1=1")
        params = []
        if month_f.strip():
            q += " AND month_ref=?"; params.append(norm_month(month_f) or month_f.strip())
        if cat_f != "الكل":
            q += " AND category=?"; params.append(dict((c[0], c[1]) for c in CATEGORIES)[cat_f])
        q += " ORDER BY tx_date DESC, id DESC LIMIT 500"
        rows = query_all(q, tuple(params))
        if rows:
            from ui import excel_button
            df = readable_transactions(rows)
            excel_button(df, "transactions", "tx_xl")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"عدد النتائج: {len(rows)}")
        else:
            st.info("لا توجد حركات مطابقة.")
