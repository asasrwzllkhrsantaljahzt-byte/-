import streamlit as st
import pandas as pd
from db import query_all


def render():
    st.caption("سجل التعديلات والعمليات المسجلة (إضافة/تحديث/عمليات نظام) بما في ذلك الحركات المالية.")

    c1, c2 = st.columns(2)
    with c1:
        table_f = st.text_input("تصفية باسم الجدول", value="")
    with c2:
        action_f = st.selectbox("الإجراء", ["الكل", "INSERT", "UPDATE", "DELETE_ATTEMPT", "STATUS_CHANGE"])

    q = "SELECT id, table_name, record_id, action, changed_at, changed_by, note FROM audit_log WHERE 1=1"
    params = []
    if table_f.strip():
        q += " AND table_name LIKE ?"; params.append(f"%{table_f.strip()}%")
    if action_f != "الكل":
        q += " AND action=?"; params.append(action_f)
    q += " ORDER BY id DESC LIMIT 500"
    rows = query_all(q, tuple(params))
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد سجلات تدقيق بعد.")

    if rows:
        sel = st.selectbox("عرض تفاصيل سجل (ID)", [r['id'] for r in rows])
        detail = next((r for r in query_all("SELECT * FROM audit_log WHERE id=?", (sel,))), None)
        if detail:
            st.json({k: detail[k] for k in detail.keys()})
