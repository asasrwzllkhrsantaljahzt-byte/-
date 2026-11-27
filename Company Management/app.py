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
from ui import apply_rtl_style, page_header, set_page
from modules import dashboard, auth_ui, contracts, documents_page, assistant_page, system_page

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
    items = [a for a in ss["_alerts"] if a["page"] in allowed or a.get("system_error")]
    icon = {"high": "🔴", "mid": "🟠", "low": "🔵"}
    with st.popover(
        f"🔔 التنبيهات ({len(items)})" if items else "🔔 لا تنبيهات",
        key="toolbar_bell",
        use_container_width=True,
    ):
        if not items:
            st.caption("كل شيء على ما يرام ✅")
        for i, a in enumerate(items):
            if a.get("system_error"):
                st.warning(a["text"])
                continue
            st.markdown(f"{icon[a['level']]} {a['text']}")
            st.button("فتح ←", key=f"bell_{i}", on_click=set_page, args=(a["page"],))


def _render_toolbar():
    st.markdown(
        """
        <style>
        header[data-testid="stHeader"] { display: none !important; }
        .stApp:has(section[data-testid="stSidebar"][aria-expanded="true"]) {
            --toolbar-sidebar-offset: 21rem;
        }
        .stApp:has(section[data-testid="stSidebar"][aria-expanded="false"]),
        .stApp:has(section[data-testid="stSidebar"][data-collapsed="true"]) {
            --toolbar-sidebar-offset: 0px;
        }
        div[data-testid="stHorizontalBlock"]:has(.st-key-toolbar_menu) {
            position: fixed; top: 0; left: 0; right: var(--toolbar-sidebar-offset, 0px);
            z-index: 10000 !important; direction: ltr; align-items: center; box-sizing: border-box;
            background: #fff !important; opacity: 1 !important;
            margin: 0; padding: .65rem 2.2rem;
            border-bottom: 1px solid #b8c7d1;
            box-shadow: 0 3px 12px rgba(23,43,58,.12);
        }
        .block-container { padding-top: 5rem !important; }
        .st-key-toolbar_menu button, .st-key-toolbar_bell button,
        .st-key-toolbar_assistant button {
            min-height: 2.8rem; border-radius: 999px; opacity: 1 !important;
            background: #f0f6f7 !important; color: #17364b !important;
            border: 1px solid #9aadb8 !important;
            box-shadow: 0 2px 5px rgba(23,43,58,.12);
        }
        .st-key-toolbar_menu button, .st-key-toolbar_bell button {
            min-width: 3rem; font-size: 1.15rem;
        }
        .st-key-toolbar_assistant button {
            background: #0f766e !important; border-color: #0f766e !important;
            color: #fff !important;
        }
        .st-key-toolbar_back button {
            min-height: 2.8rem; border-radius: 999px; opacity: 1 !important;
            background: #f3bb4e !important; border: 1px solid #a56a00 !important;
            color: #172b3a !important; font-weight: 700;
            box-shadow: 0 2px 6px rgba(23,43,58,.16);
        }
        @media (max-width: 768px) {
            .stApp:has(section[data-testid="stSidebar"][aria-expanded="true"]) {
                --toolbar-sidebar-offset: 0px;
            }
            div[data-testid="stHorizontalBlock"]:has(.st-key-toolbar_menu) {
                padding: .45rem .8rem;
            }
            .block-container { padding-top: 4.5rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    menu, bell, assistant, back, _ = st.columns([0.75, 0.75, 1.45, 1.8, 8], gap="small")
    with menu:
        with st.popover("☰", key="toolbar_menu", help="المستخدم والإعدادات", use_container_width=True):
            st.markdown(f"**{user['display_name']}**")
            st.caption(security.ROLES[user["role"]])
            if "الإعدادات" in allowed:
                st.button(
                    "⚙️ الإعدادات",
                    key="header_settings",
                    use_container_width=True,
                    on_click=set_page,
                    args=("الإعدادات",),
                )
            if "حسابي والمستخدمون" in allowed:
                st.button(
                    "👤 حسابي والمستخدمون" if user["role"] == "admin" else "👤 حسابي",
                    key="header_account",
                    use_container_width=True,
                    on_click=set_page,
                    args=("حسابي والمستخدمون",),
                )
            auth_ui.logout_button()
            if user["role"] == "admin":
                check = _release_check()
                st.caption(f"قاعدة البيانات: {db.get_db_path()}")
                if check.get("no_manifest"):
                    st.caption("الإصدار: غير معروف (ملف release_manifest.json غير موجود)")
                elif check["ok"]:
                    st.caption(f"✅ الإصدار {check['build']} — كل الملفات محدّثة")
                else:
                    st.warning(f"⚠️ الإصدار المطلوب {check['build']}")
                    for missing in check["missing"]:
                        st.caption(f"❌ ناقص: {missing}")
                    for different in check["different"]:
                        st.caption(f"⚠️ مختلف: {different}")
    with bell:
        _render_bell(allowed)
    if "المساعد" in allowed:
        with assistant:
            st.button(
                "المساعد",
                icon=":material/support_agent:",
                key="toolbar_assistant",
                help="فتح مساعد خدمة العملاء",
                on_click=set_page,
                args=("المساعد",),
                use_container_width=True,
            )
    if st.session_state.get("_page", "العرض") not in ("التسجيل", "العرض"):
        with back:
            return_page = st.session_state.get("_return_page", "العرض")
            st.button(
                "↩ العودة للقائمة",
                key="toolbar_back",
                help="العودة إلى قائمة التسجيل أو العرض",
                on_click=set_page,
                args=(return_page,),
                use_container_width=True,
            )


with st.sidebar:
    if branding.logo_path():
        st.image(branding.logo_path(), width=90)
    st.markdown(f"## {app_settings.get('org_name')}")
    st.button("📝 التسجيل", key="sidebar_registration", use_container_width=True,
              on_click=set_page, args=("التسجيل",))
    st.button("📊 العرض", key="sidebar_view", use_container_width=True,
              on_click=set_page, args=("العرض",))

_render_toolbar()
menu_pages = ("التسجيل", "العرض")
page = st.session_state.get("_page", "العرض")


def _page_allowed(target):
    if target == "العقود والوثائق":
        return any(item in allowed for item in ("العقود", "الوثائق"))
    return target in allowed


if page not in menu_pages and not _page_allowed(page):
    page = "العرض"
    st.session_state["_page"] = page

if not page:
    st.stop()
if page not in menu_pages and not _page_allowed(page):
    st.error("ليست لديك صلاحية الوصول إلى هذه الصفحة.")
    st.stop()

if page == "التسجيل":
    page_header("التسجيل", "اختر وظيفة لإدخال البيانات أو تحديثها.")
    dashboard.render_action_menu(allowed, dashboard.REGISTRATION_ACTIONS)
elif page == "العرض":
    page_header("العرض", "اختر لوحة التحكم أو أحد التقارير والصفحات المعروضة.")
    dashboard.render_action_menu(allowed, dashboard.VIEW_ACTIONS)
elif page == "لوحة التحكم":
    page_header("لوحة التحكم", "مؤشرات أداء الشهر والحسابات.")
    dashboard.render()
elif page == "المساعد":
    page_header("المساعد", "اسأل عن طريقة العمل أو عن أرقامك")
    assistant_page.render()
elif page == "الشركات والموظفون":
    page_header("الشركات والموظفون", "إدارة الشركات وموظفيها وتفاصيل العمل من شاشة الشركة.")
    from modules import company_hub_page
    company_hub_page.render()
elif page == "المتعهدون":
    page_header("المتعهدون", "إدارة بيانات المتعهدين والعمولات الخارجية.")
    from modules import contractors
    contractors.render()
elif page == "المندوبون":
    page_header("المندوبون", "إدارة بيانات المندوبين وعلاقاتهم بالشركات.")
    from modules import representatives
    representatives.render()
elif page in ("العقود والوثائق", "العقود", "الوثائق"):
    page_header("العقود والوثائق", "إدارة العقود والوثائق ومتابعة تواريخ انتهائها.")
    sections = []
    if "العقود" in allowed:
        sections.append(("📄 العقود", contracts.render))
    if "الوثائق" in allowed:
        sections.append(("🪪 الوثائق", documents_page.render))
    if len(sections) == 2:
        contract_tab, document_tab = st.tabs([label for label, _ in sections])
        with contract_tab:
            sections[0][1]()
        with document_tab:
            sections[1][1]()
    elif sections:
        sections[0][1]()
    else:
        st.info("ليست لديك صلاحية الوصول إلى العقود أو الوثائق.")
elif page == "التحويلات والحساب الشهري":
    page_header("الحركات المالية", "تسجيل ومراجعة تحويلات العملاء والاستلام والصرف.")
    from modules import financial_activity_page
    financial_activity_page.render(allowed)
elif page == "مراجعة وإقفال الشهر":
    page_header(page, "مراجعة نتائج الشهر وإقفاله.")
    from modules import month_close_page
    month_close_page.render()
elif page == "كشوف الحسابات":
    page_header(page, "عرض وتصدير كشوف حسابات الجهات.")
    from modules import statements
    statements.render()
elif page == "فواتير العملاء":
    page_header(page, "إصدار ومراجعة فواتير العملاء.")
    from modules import invoices_page
    invoices_page.render()
elif page == "التقارير المالية والإدارية":
    page_header(page, "التقارير الشهرية والسنوية والأرصدة.")
    from modules import reports
    reports.render()
elif page == "الإعدادات":
    page_header("الإعدادات", "بيانات المنشأة والتنبيهات والصلاحيات.")
    system_page.render(page)
elif page in ("النسخ الاحتياطي والاستعادة", "سجل التدقيق", "حسابي والمستخدمون"):
    page_header(page, "إدارة الحساب وإعدادات النظام والنسخ الاحتياطية.")
    system_page.render(page)
