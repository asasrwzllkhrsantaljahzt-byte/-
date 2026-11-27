import streamlit as st

import security
from db import query_all


def render():
    st.caption("يُطبّق الإخفاء على الواجهة والتحقق من الوصول معاً. يحتفظ المدير دائماً بإمكانية فتح الإعدادات وحسابه.")
    roles = list(security.ROLES)
    role_tabs = st.tabs([security.ROLES[role] for role in roles])
    for role, tab in zip(roles, role_tabs):
        with tab:
            current_pages = set(security.allowed_pages(role))
            report_rows = {
                row["section"]: bool(row["enabled"])
                for row in query_all(
                    "SELECT section, enabled FROM role_report_permissions WHERE role=?", (role,))
            }
            current_reports = {
                section for section in security.REPORT_SECTIONS
                if report_rows.get(section, True)
            }
            with st.form(f"role_permissions_{role}"):
                st.markdown("**الوظائف والصفحات**")
                cols = st.columns(3)
                enabled_pages = set()
                for index, page in enumerate(security.PAGES):
                    required = role == "admin" and page in ("الإعدادات", "حسابي والمستخدمون")
                    admin_only = page == "الإعدادات" and role != "admin"
                    label = "الحركات المالية" if page == "التحويلات والحساب الشهري" else page
                    enabled = cols[index % len(cols)].checkbox(
                        label,
                        value=(page in current_pages or required) and not admin_only,
                        key=f"access_{role}_{index}",
                        disabled=required or admin_only,
                    )
                    if enabled:
                        enabled_pages.add(page)

                st.markdown("**أقسام التقارير**")
                report_cols = st.columns(2)
                enabled_reports = set()
                for index, (section, label) in enumerate(security.REPORT_SECTIONS.items()):
                    if report_cols[index % len(report_cols)].checkbox(
                        label,
                        value=section in current_reports,
                        key=f"report_access_{role}_{section}",
                    ):
                        enabled_reports.add(section)
                submitted = st.form_submit_button("حفظ صلاحيات هذا الدور", type="primary")
            if submitted:
                try:
                    security.save_role_permissions(role, enabled_pages, enabled_reports)
                    st.session_state["_access_flash"] = f"تم حفظ صلاحيات {security.ROLES[role]}."
                    st.rerun()
                except ValueError as ex:
                    st.error(str(ex))
