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

    q = "SELECT table_name, action, changed_at, changed_by, note FROM audit_log WHERE 1=1"
    params = []
    if table_f.strip():
        q += " AND table_name LIKE ?"; params.append(f"%{table_f.strip()}%")
    if action_f != "الكل":
        q += " AND action=?"; params.append(action_f)
    q += " ORDER BY id DESC LIMIT 500"
    rows = query_all(q, tuple(params))
    if rows:
        table_names = {
            "users": "المستخدمون", "companies": "الشركات", "employees": "الموظفون",
            "employee_placements": "تعيينات الموظفين", "client_transfers": "تحويلات العملاء",
            "vouchers": "الحركات المالية", "contracts": "العقود", "invoices": "الفواتير",
            "documents": "الوثائق", "representatives": "المناديب", "contractors": "المتعهدون",
        }
        action_names = {"INSERT": "إضافة", "UPDATE": "تعديل", "DELETE_ATTEMPT": "محاولة حذف",
                        "STATUS_CHANGE": "تغيير الحالة"}
        df = pd.DataFrame(rows).rename(columns={
            "table_name": "القسم",
            "action": "العملية",
            "changed_at": "التاريخ والوقت",
            "changed_by": "المستخدم",
            "note": "البيان",
        })
        df["القسم"] = df["القسم"].map(lambda value: table_names.get(value, value))
        df["العملية"] = df["العملية"].map(lambda value: action_names.get(value, value))
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد سجلات تدقيق بعد.")
