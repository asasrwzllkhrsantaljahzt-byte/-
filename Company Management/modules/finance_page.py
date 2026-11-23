"""Single entry point for financial pages, preserving each page's existing behavior."""
import streamlit as st

from ui import FINANCE_GROUPS


_DESCRIPTIONS = {
    "التحويلات والحساب الشهري": "تسجيل تحويلات العملاء ومراجعة الحساب الفعلي لكل شهر.",
    "مراجعة وإقفال الشهر": "مراجعة النتائج وتثبيت الشهر أو إعادة فتحه بسبب مسجل.",
    "التحصيل والمدفوعات والسندات": "متابعة الأرصدة والتحصيل والصرف، مع سجل موحد لإذون الاستلام والصرف.",
    "كشوف الحسابات": "عرض وتصدير كشف تفصيلي لحساب جهة محددة.",
    "فواتير العملاء": "إصدار فواتير العملاء ومراجعة الفواتير السابقة.",
    "التقارير المالية والإدارية": "عرض التقارير الشهرية والسنوية والأرصدة.",
}


def _render_settlements(allowed: list):
    views = [
        ("متابعة التحصيل والمدفوعات", "التحصيل والمدفوعات"),
        ("سجل السندات", "السندات"),
    ]
    options = [label for label, page in views if page in allowed]
    if st.session_state.get("_finance_cash_view") not in options:
        st.session_state["_finance_cash_view"] = options[0]
    view = st.radio("العرض", options, horizontal=True, key="_finance_cash_view")
    if view == "متابعة التحصيل والمدفوعات":
        from modules import collections_page
        collections_page.render()
    else:
        from modules import vouchers_page
        vouchers_page.render()


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

    if selected == "التحويلات والحساب الشهري":
        from modules import monthly_page
        monthly_page.render()
    elif selected == "مراجعة وإقفال الشهر":
        from modules import month_close_page
        month_close_page.render()
    elif selected == "التحصيل والمدفوعات والسندات":
        _render_settlements(allowed)
    elif selected == "كشوف الحسابات":
        from modules import statements
        statements.render()
    elif selected == "فواتير العملاء":
        from modules import invoices_page
        invoices_page.render()
    elif selected == "التقارير المالية والإدارية":
        from modules import reports
        reports.render()
