"""Single entry point for financial pages."""
import streamlit as st

from ui import FINANCE_GROUPS


_DESCRIPTIONS = {
    "الحركات المالية": "تسجيل التحويلات والتحصيل والمدفوعات ومراجعة الحساب الشهري.",
    "مراجعة وإقفال الشهر": "مراجعة النتائج وتثبيت الشهر أو إعادة فتحه بسبب مسجل.",
    "كشوف الحسابات": "عرض وتصدير كشف تفصيلي لحساب جهة محددة.",
    "فواتير العملاء": "إصدار فواتير العملاء ومراجعة الفواتير السابقة.",
    "التقارير المالية والإدارية": "عرض التقارير الشهرية والسنوية والأرصدة.",
}


def render(allowed: list):
    options = [
        title for title, source_pages in FINANCE_GROUPS
        if any(page in allowed for page in source_pages)
    ]
    current = st.session_state.get("_finance_section")
    if current not in options:
        st.session_state["_finance_section"] = options[0]
    selected = st.selectbox("القسم المالي", options, key="_finance_section")
    st.caption(_DESCRIPTIONS[selected])

    if selected == "الحركات المالية":
        from modules import financial_activity_page
        financial_activity_page.render(allowed)
    elif selected == "مراجعة وإقفال الشهر":
        from modules import month_close_page
        month_close_page.render()
    elif selected == "كشوف الحسابات":
        from modules import statements
        statements.render()
    elif selected == "فواتير العملاء":
        from modules import invoices_page
        invoices_page.render()
    elif selected == "التقارير المالية والإدارية":
        from modules import reports
        reports.render()
