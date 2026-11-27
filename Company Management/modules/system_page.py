import streamlit as st
import security
from modules import access_settings, settings_page, users, backup_page, audit_log


def render(page="الإعدادات"):
    me = security.current_user()
    if not me:
        st.stop()
    access_message = st.session_state.pop("_access_flash", None)
    if access_message:
        st.toast(access_message, icon="✅")
    allowed = security.allowed_pages(me["role"])
    direct_sections = {
        "حسابي والمستخدمون": users.render,
        "النسخ الاحتياطي والاستعادة": backup_page.render,
        "سجل التدقيق": audit_log.render,
    }
    if page != "الإعدادات":
        if page not in allowed or page not in direct_sections:
            st.info("لا توجد أقسام متاحة لهذه الصفحة.")
            return
        direct_sections[page]()
        return

    sections = []
    if "الإعدادات" in allowed and me["role"] == "admin":
        sections.extend([
            ("الإعدادات العامة", settings_page.render),
            ("صلاحيات الوظائف", access_settings.render),
        ])
    if "حسابي والمستخدمون" in allowed:
        sections.append(("حسابي" if me["role"] != "admin" else "المستخدمون وحسابي", users.render))
    if "النسخ الاحتياطي والاستعادة" in allowed:
        sections.append(("النسخ الاحتياطي", backup_page.render))
    if "سجل التدقيق" in allowed:
        sections.append(("سجل التدقيق", audit_log.render))
    if not sections:
        st.info("لا توجد أقسام إعدادات متاحة لهذا الحساب.")
        return
    tabs = st.tabs([label for label, _ in sections])
    for tab, (_, render_section) in zip(tabs, sections):
        with tab:
            render_section()
