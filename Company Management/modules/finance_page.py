"""Single entry point for financial pages, preserving each page's existing behavior."""
import streamlit as st

from ui import FINANCE_GROUPS


_DESCRIPTIONS = {
    "الحركات المالية": "تسجيل التحويلات والتحصيل والمدفوعات ومراجعة الحساب الشهري.",
    "مراجعة وإقفال الشهر": "مراجعة النتائج وتثبيت الشهر أو إعادة فتحه بسبب مسجل.",
    "كشوف الحسابات": "عرض وتصدير كشف تفصيلي لحساب جهة محددة.",
    "فواتير العملاء": "إصدار فواتير العملاء ومراجعة الفواتير السابقة.",
    "التقارير المالية والإدارية": "عرض التقارير الشهرية والسنوية والأرصدة.",
}


def _render_activity(allowed: list):
    from modules import collections_page, monthly_page, vouchers_page
    import security

    views = [
        ("الحساب الشهري والتحويلات", "التحويلات والحساب الشهري"),
        ("التحصيل والمدفوعات", "التحصيل والمدفوعات"),
        ("سجل السندات", "السندات"),
    ]
    views = [view for view in views if view[1] in allowed]
    tabs = st.tabs([label for label, _ in views])
    can = security.can_write()
    for tab, (_, page) in zip(tabs, views):
        with tab:
            if page == "التحويلات والحساب الشهري":
                monthly_page.show_flash()
                sub_tabs = st.tabs(["الحساب الشهري", "تحويلات العميل"])
                with sub_tabs[0]:
                    monthly_page._tab_monthly()
                with sub_tabs[1]:
                    monthly_page._tab_transfers(can)
            elif page == "التحصيل والمدفوعات":
                sub_tabs = st.tabs(["التحصيل من الموظفين", "المدفوعات والمستحقات"])
                with sub_tabs[0]:
                    collections_page._collect_tab(can)
                with sub_tabs[1]:
                    collections_page._pay_tab(can)
            else:
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

    if selected == "الحركات المالية":
        _render_activity(allowed)
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
