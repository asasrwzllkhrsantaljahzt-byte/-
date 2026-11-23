"""التحصيل والمدفوعات: what employees actually return vs what is owed, and what the company owes others."""
import pandas as pd
import streamlit as st

import hub_engine as E
from hub_accounts import collection_rows
import vouchers as V
import security
from db import query_all
from modules import vouchers_page
from ui import select_table, toast_flash, excel_button, row_action_bar

_PAY_TYPES = [("contractor", "المتعهدون وعمولات خارجية"), ("representative", "المناديب"), ("company", "العملاء (المردود)")]


def _collect_tab(can):
    months = E.month_options()
    c1, c2 = st.columns(2)
    month = c1.selectbox("شهر العمل", months, key="col_m")
    cos = {"كل الشركات": None}
    cos.update({r["name"]: r["id"] for r in query_all("SELECT id, name FROM companies ORDER BY name")})
    cid = cos[c2.selectbox("الشركة", list(cos), key="col_c")]
    rows = collection_rows(month, cid)
    if not rows:
        st.info("لا يوجد موظفون لهذا الشهر. سجّل تحويلات العميل أولاً من «التحويلات والحساب الشهري».")
        return
    owed = sum(r["owed"] for r in rows); got = sum(r["collected"] for r in rows)
    m1, m2, m3 = st.columns(3)
    m1.metric("المطلوب تحصيله من الموظفات", f"{owed:,.2f}")
    m2.metric("المحصَّل فعلاً", f"{got:,.2f}")
    m3.metric("الفرق (المتبقي)", f"{owed - got:,.2f}")
    df = pd.DataFrame([{"الشركة": r["company"], "الموظفة": r["employee"], "حوّل العميل": r["transferred"],
                        "نصيبها (المكافأة)": r["bonus_due"], "المطلوب منها": r["owed"],
                        "المحصَّل": r["collected"], "الفرق": r["diff"]} for r in rows])
    excel_button(df, f"collections_{month}", "col_xl")
    pos = select_table(df, f"col_t_{month}")
    toast_flash(vouchers_page._FLASH)
    if pos is None:
        st.caption("💡 اضغط مربع الاختيار على يسار الصف لتسجيل ما حصّلته من الموظفة.")
        return
    r = rows[pos]
    st.markdown(f"**{r['employee']}** — المتبقي عليها {r['diff']:,.2f}")
    actions = row_action_bar(view=True, print_=True, prefix=f"col_row_{r['employee_id']}")
    if actions["view"]:
        st.info(f"الموظفة: {r['employee']} — المطلوب: {r['owed']:,.2f} — المحصل: {r['collected']:,.2f}")
    if actions["print"]:
        st.download_button("طباعة التحصيل", pd.DataFrame([r]).to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"collection_{r['employee_id']}.csv", mime="text/csv",
                           key=f"col_print_{r['employee_id']}")
    if can and st.button("➕ تسجيل تحصيل من الموظفة", type="primary", key="col_go"):
        vouchers_page.issue_dialog("receipt", "employee", r["employee_id"], "col", month, max(r["diff"], 0) or None)
    st.caption("الفرق الموجب = لم تُعد كامل المبلغ بعد. السالب = أعادت أكثر من المطلوب.")


def _pay_tab(can):
    months = ["كل الأشهر"] + E.month_options()
    c1, c2 = st.columns(2)
    month = c1.selectbox("شهر العمل", months, key="pay_m")
    ptype = c2.selectbox("الجهة", [t[0] for t in _PAY_TYPES], format_func=dict(_PAY_TYPES).get, key="pay_t")
    mref = None if month == "كل الأشهر" else month
    bal = [b for b in V.party_balances(ptype, mref) if abs(b["due"]) > 0.004 or abs(b["settled"]) > 0.004]
    if not bal:
        st.info("لا مستحقات لهذه الجهة ضمن الفترة.")
        return
    labels = ("المردود المستحق", "المصروف", "المتبقي") if ptype == "company" else ("المستحق", "المصروف", "المتبقي")
    tot_d = sum(b["due"] for b in bal); tot_s = sum(b["settled"] for b in bal)
    m1, m2, m3 = st.columns(3)
    m1.metric(labels[0], f"{tot_d:,.2f}"); m2.metric(labels[1], f"{tot_s:,.2f}"); m3.metric(labels[2], f"{tot_d - tot_s:,.2f}")
    df = pd.DataFrame([{"الاسم": b["name"], labels[0]: b["due"], labels[1]: b["settled"], labels[2]: b["balance"]} for b in bal])
    excel_button(df, f"payables_{ptype}", "pay_xl")
    pos = select_table(df, f"pay_t_{ptype}_{month}")
    toast_flash(vouchers_page._FLASH)
    if pos is None:
        st.caption("💡 اختر صفاً ثم اضغط «إذن صرف» لتسجيل ما دفعته.")
        return
    b = bal[pos]
    actions = row_action_bar(view=True, print_=True, prefix=f"pay_row_{ptype}_{b['id']}")
    if actions["view"]:
        st.info(f"{b['name']} — المستحق: {b['due']:,.2f} — المصروف: {b['settled']:,.2f} — المتبقي: {b['balance']:,.2f}")
    if actions["print"]:
        st.download_button("طباعة كشف المصروفات", pd.DataFrame([b]).to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"payable_{b['id']}.csv", mime="text/csv",
                           key=f"pay_print_{ptype}_{b['id']}")
    if can and st.button(f"➕ إذن صرف إلى {b['name']}", type="primary", key="pay_go"):
        vouchers_page.issue_dialog("payment", ptype, b["id"], "pay", mref, max(b["balance"], 0) or None)


def render():
    can = security.can_write()
    t1, t2 = st.tabs(["📥 التحصيل من الموظفات", "📤 المدفوعات والمستحقات"])
    with t1:
        _collect_tab(can)
    with t2:
        _pay_tab(can)
