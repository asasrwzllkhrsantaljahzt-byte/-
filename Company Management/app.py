import streamlit as st

import db
import security
import app_settings
import invoicing
import documents
import vouchers
import integrity
import branding
import company_hub
import hub_engine
import legacy
from ui import apply_rtl_style, page_header, sidebar_nav, grouped_entry_allowed
from modules import dashboard, backup_page, audit_log, auth_ui, users, contracts, settings_page, documents_page, assistant_page, finance_page, master_data_page, system_page

st.set_page_config(
    page_title="نظام إدارة شركة التوظيف",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

@st.cache_resource(show_spinner=False)
def _setup_database():
    """Creates / upgrades the schema once per server run (not on every click). Cleared after a backup restore."""
    db.init_db()
    legacy.drop_legacy_tables()
    company_hub.ensure_hub_schema()
    hub_engine.ensure_engine_schema()
    security.ensure_security_schema()
    app_settings.ensure_settings_schema()
    contracts.ensure_contracts_schema()
    invoicing.ensure_invoice_schema()
    documents.ensure_documents_schema()
    vouchers.ensure_vouchers_schema()
    return True


_setup_database()


@st.cache_data(ttl=300, show_spinner=False)
def _release_check():
    return integrity.check()


apply_rtl_style()

user = auth_ui.gate()          # login / first-time setup; stops the script when not signed in
allowed = security.allowed_pages(user["role"])

def _render_bell(allowed):
    import time
    import alerts
    from ui import set_page
    ss = st.session_state
    if time.time() - ss.get("_alerts_ts", 0) > 60 or "_alerts" not in ss:
        ss["_alerts"], ss["_alerts_ts"] = alerts.collect(), time.time()
    items = [a for a in ss["_alerts"] if a["page"] in allowed]
    icon = {"high": "🔴", "mid": "🟠", "low": "🔵"}
    with st.popover(f"🔔 التنبيهات ({len(items)})" if items else "🔔 لا تنبيهات", use_container_width=True):
        if not items:
            st.caption("كل شيء على ما يرام ✅")
        for i, a in enumerate(items):
            st.markdown(f"{icon[a['level']]} {a['text']}")
            st.button("فتح ←", key=f"bell_{i}", on_click=set_page, args=(a["page"],))


with st.sidebar:
    if branding.logo_path():
        st.image(branding.logo_path(), width=90)
    st.markdown(f"## {app_settings.get('org_name')}")
    st.caption("واجهة عربية RTL - متصلة بقاعدة بيانات SQLite")
    _render_bell(allowed)
    page = sidebar_nav(allowed)
    st.markdown("---")
    st.caption(f"المستخدم: {user['display_name']} — {security.ROLES[user['role']]}")
    auth_ui.logout_button()
    if user["role"] == "admin":
        _chk = _release_check()
        with st.expander("ℹ️ معلومات النظام", expanded=False):
            st.caption("مكان قاعدة البيانات:")
            st.caption(str(db.get_db_path()))
            if _chk.get("no_manifest"):
                st.caption("الإصدار: غير معروف (ملف release_manifest.json غير موجود)")
            elif _chk["ok"]:
                st.caption(f"✅ الإصدار {_chk['build']} — كل الملفات محدّثة")
            else:
                st.caption(f"⚠️ الإصدار المطلوب {_chk['build']}")
                for f in _chk["missing"]:
                    st.caption(f"❌ ناقص: {f}")
                for f in _chk["different"]:
                    st.caption(f"⚠️ مختلف: {f}")
        if not _chk.get("no_manifest") and not _chk["ok"]:
            st.warning(f"بعض ملفات البرنامج ({len(_chk['missing']) + len(_chk['different'])}) غير محدّثة، وقد تظهر أخطاء أو ميزات ناقصة. افتح «ℹ️ معلومات النظام» لترى أيها، أو شغّل فحص_التحديث.py.")

if page not in allowed and not grouped_entry_allowed(page, allowed):
    st.error("ليست لديك صلاحية الوصول إلى هذه الصفحة.")
    st.stop()

if page == "لوحة التحكم":
    page_header("لوحة التحكم الرئيسية", "متابعة سريعة لمؤشرات النظام الأساسية")
    dashboard.render()
elif page == "المساعد":
    page_header("المساعد", "اسأل عن طريقة العمل أو عن أرقامك")
    assistant_page.render()
elif page == "البيانات الأساسية":
    page_header("البيانات الأساسية", "الشركات والموظفون والمتعهدون والمندوبون وملفات الجهات في مدخل واحد.")
    master_data_page.render(allowed)
elif page == "المالية":
    page_header("المالية", "جميع الأقسام المالية في مدخل واحد. اختر القسم المطلوب من القائمة.")
    finance_page.render(allowed)
elif page == "النسخ الاحتياطي والاستعادة":
    page_header("النسخ الاحتياطي والاستعادة", "حفظ واستعادة قاعدة البيانات بأمان")
    backup_page.render()
elif page == "سجل التدقيق":
    page_header("سجل التدقيق", "متابعة التعديلات والحركات والعمليات المسجلة")
    audit_log.render()
elif page == "حسابي والمستخدمون":
    page_header("حسابي والمستخدمون", "إدارة كلمة المرور وصلاحيات المستخدمين")
    users.render()
elif page == "العقود":
    page_header("العقود", "توثيق عقود العملاء والمتعهدين والمندوبين والموظفين ومتابعة انتهائها")
    contracts.render()
elif page == "الوثائق":
    page_header("الوثائق", "سجل وثائق الموظفين والعملاء والمتعهدين والمندوبين وتواريخ انتهائها")
    documents_page.render()
elif page == "الإعدادات":
    page_header("الإعدادات", "بيانات المنشأة وحدود التنبيهات")
    settings_page.render()
elif page == "الإعدادات والنظام":
    page_header("الإعدادات والنظام", "إدارة إعدادات المنشأة والمستخدمين والنسخ الاحتياطية وسجل التدقيق")
    system_page.render()
