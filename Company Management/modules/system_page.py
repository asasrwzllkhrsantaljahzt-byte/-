import streamlit as st
import security
from modules import settings_page, users, backup_page, audit_log


def render():
    me = security.current_user()
    if not me:
        st.stop()

    if me["role"] == "admin":
        tabs = st.tabs(["الإعدادات العامة", "المستخدمون وحسابي", "النسخ الاحتياطي", "سجل التدقيق"])
        with tabs[0]:
            settings_page.render()
        with tabs[1]:
            users.render()
        with tabs[2]:
            backup_page.render()
        with tabs[3]:
            audit_log.render()
    else:
        tab = st.tabs(["حسابي"])[0]
        with tab:
            users.render()
