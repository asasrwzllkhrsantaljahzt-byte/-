"""Single entry point for basic-data pages, preserving existing permissions and behavior."""
import streamlit as st

from ui import MASTER_DATA_GROUPS


_DESCRIPTIONS = {
    "الشركات والموظفون": "إدارة الشركات وموظفيها وتفاصيل العمل من شاشة الشركة.",
    "المتعهدون": "إدارة بيانات المتعهدين والعمولات الخارجية.",
    "المندوبون": "إدارة بيانات المندوبين وعلاقاتهم بالشركات.",
}


def render(allowed: list):
    options = [
        title for title, source_pages in MASTER_DATA_GROUPS
        if any(page in allowed for page in source_pages)
    ]
    current = st.session_state.get("_master_data_section")
    if current not in options:
        st.session_state["_master_data_section"] = options[0]
    selected = st.selectbox("القسم", options, key="_master_data_section")
    st.caption(_DESCRIPTIONS[selected])

    if selected == "الشركات والموظفون":
        from modules import company_hub_page
        company_hub_page.render()
    elif selected == "المتعهدون":
        from modules import contractors
        contractors.render()
    elif selected == "المندوبون":
        from modules import representatives
        representatives.render()
