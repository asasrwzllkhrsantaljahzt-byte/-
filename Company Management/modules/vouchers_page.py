import pandas as pd
import streamlit as st
from datetime import date

import vouchers as V
import security
from db import query_all
from ui import select_table, tbump, toast_flash, excel_button, friendly_error, number_field, norm_month, row_action_bar

_FLASH = "_vo_flash"


def _names(ptype):
    t, col = V.PARTY_TABLE[ptype]
    return {f"{r['n']} (#{r['id']})": r["id"] for r in query_all(f"SELECT id, {col} AS n FROM {t} ORDER BY {col}")}


def issue_dialog(kind, party_type=None, party_id=None, tbl="vo", month=None, amount=None):
    m0, a0 = month, amount
    """Modal 'issue voucher' form. If party_type/party_id are given the party is fixed (called from a party file)."""
    @st.dialog(f"{V.KIND_AR[kind]} جديد")
    def _dlg():
        fixed = party_type is not None and party_id is not None
        ptype, pid, other = party_type, party_id, None
        if fixed:
            st.markdown(f"**{V.PARTY_AR[ptype]}:** {V.party_name(ptype, pid)}")
        else:
            ptype = st.selectbox("نوع الجهة", list(V.PARTY_AR), format_func=lambda k: V.PARTY_AR[k], key=f"vo_pt_{kind}")
            if ptype == "other":
                other = st.text_input("اسم الجهة", key=f"vo_other_{kind}")
            else:
                names = _names(ptype)
                if not names:
                    st.info(f"لا يوجد {V.PARTY_AR[ptype]} مسجل بعد.")
                    return
                pid = names[st.selectbox("الجهة", list(names), key=f"vo_p_{kind}_{ptype}")]
        c1, c2 = st.columns(2)
        d = c1.date_input("التاريخ", value=date.today(), key=f"vo_d_{kind}")
        with c2:
            amount = number_field("المبلغ (ر.س)", f"vo_a_{kind}_{party_id}_{m0}", value=a0)
        c3, c4 = st.columns(2)
        method = c3.selectbox("طريقة الدفع", list(V.METHOD_AR), format_func=lambda k: V.METHOD_AR[k], key=f"vo_m_{kind}")
        ref = c4.text_input("المرجع (رقم الحوالة/الشيك)", key=f"vo_r_{kind}")
        month = st.text_input("شهر العمل المتعلق (مثل 2026-03)", value=m0 or "", key=f"vo_mo_{kind}_{party_id}_{m0}")
        category = "settlement"
        if kind == "payment" and ptype == "other":
            categories = list(V.ENTRY_CATEGORY_AR)
            category = st.selectbox("تصنيف الصرف", categories, index=1,
                                    format_func=V.ENTRY_CATEGORY_AR.get, key=f"vo_cat_{kind}")
        desc_label = "اسم المصروف أو البيان" if kind == "payment" and ptype == "other" else "البيان"
        desc = st.text_area(desc_label, key=f"vo_desc_{kind}")
        if st.button("إصدار الإذن", type="primary", key=f"vo_go_{kind}", use_container_width=True):
            try:
                vid = V.issue_voucher(kind, d, ptype, pid, amount, method, ref, (norm_month(month) or month), desc,
                                      other, category)
            except ValueError as e:
                st.error(str(e))
                return
            except Exception as e:  # noqa: BLE001
                st.error(friendly_error(e))
                return
            st.session_state[_FLASH] = "تم إصدار الإذن."
            tbump(tbl)
            st.rerun()
    _dlg()


def void_dialog(v, tbl="vo"):
    @st.dialog("إلغاء الإذن")
    def _dlg():
        st.warning(f"سيُلغى {v['voucher_no']} ولا يمكن التراجع، ويبقى محفوظاً في السجل ولا يدخل في الحساب.")
        reason = st.text_input("سبب الإلغاء (مطلوب)", key=f"vo_vr_{v['id']}")
        if st.button("تأكيد الإلغاء", type="primary", key=f"vo_vok_{v['id']}"):
            try:
                st.session_state[_FLASH] = V.void_voucher(v["id"], reason)
            except ValueError as e:
                st.error(str(e))
                return
            tbump(tbl)
            st.rerun()
    _dlg()


def edit_dialog(v, tbl="vo"):
    @st.dialog("تعديل " + V.KIND_AR[v["kind"]])
    def _dlg():
        k = f"vo_edit_{v['id']}_"
        d = st.date_input("التاريخ", value=date.fromisoformat(v["voucher_date"]), key=k + "date")
        amount = number_field("المبلغ (ر.س)", k + "amount", value=v["amount"], minimum=0)
        a, b = st.columns(2)
        with a:
            method = st.selectbox("طريقة الدفع", list(V.METHOD_AR), index=list(V.METHOD_AR).index(v["method"]),
                                  format_func=V.METHOD_AR.get, key=k + "method")
        with b:
            reference = st.text_input("المرجع", value=v["reference"] or "", key=k + "reference")
        month = st.text_input("شهر العمل المتعلق", value=v["month_ref"] or "", key=k + "month")
        category = v.get("entry_category") or "settlement"
        if v["kind"] == "payment" and v["party_type"] == "other":
            categories = list(V.ENTRY_CATEGORY_AR)
            category = st.selectbox("تصنيف الصرف", categories, index=categories.index(category),
                                    format_func=V.ENTRY_CATEGORY_AR.get, key=k + "category")
            other_name = st.text_input("اسم المصروف أو الجهة *", value=v["party_name"], key=k + "party_name")
        else:
            other_name = None
        description = st.text_area("اسم المصروف أو البيان", value=v["description"] or "", key=k + "description")
        reason = st.text_input("سبب التعديل *", key=k + "reason")
        if st.button("حفظ التعديل", type="primary", key=k + "save", use_container_width=True):
            try:
                V.replace_voucher(v["id"], d, amount, method, reference, norm_month(month) or month,
                                  description, category, reason, other_name)
            except ValueError as ex:
                st.error(str(ex))
                return
            st.session_state[_FLASH] = "تم حفظ التصحيح وإلغاء الإذن السابق بسبب موثق."
            tbump(tbl)
            st.rerun()
    _dlg()


def voucher_table(rows, tbl, can):
    """List + actions for a set of voucher rows (shared by the vouchers page and the party file)."""
    if not rows:
        st.info("لا توجد إذون.")
        return
    df = pd.DataFrame([{"الرقم": r["voucher_no"], "النوع": V.KIND_AR[r["kind"]], "التصنيف": V.ENTRY_CATEGORY_AR.get(r.get("entry_category"), "—"),
                        "التاريخ": r["voucher_date"],
                        "الجهة": r["party_name"], "المبلغ": float(r["amount"]), "الطريقة": V.METHOD_AR[r["method"]],
                        "المرجع": r["reference"] or "", "الشهر": r["month_ref"] or "", "البيان": r["description"] or "",
                        "الحالة": V.STATUS_AR[r["status"]]} for r in rows])
    excel_button(df, "vouchers", f"{tbl}_xl")
    from ui import pdf_button
    pdf_button(df, "سجل السندات", "vouchers", f"{tbl}_pdf")
    pos = select_table(df, tbl)
    if pos is None:
        st.caption(f"عدد الإذون: {len(rows)} — 💡 اضغط مربع الاختيار أول صف لطباعته أو إلغائه.")
        return
    v = rows[pos]

    @st.dialog(f"عرض الإذن {v['voucher_no']}")
    def _view_voucher():
        st.write({"الرقم": v["voucher_no"], "النوع": V.KIND_AR[v["kind"]],
              "التصنيف": V.ENTRY_CATEGORY_AR.get(v.get("entry_category"), "—"), "التاريخ": v["voucher_date"],
                  "الجهة": v["party_name"], "المبلغ": f"{float(v['amount']):,.2f} ر.س",
              "الطريقة": V.METHOD_AR[v["method"]], "البيان": v["description"] or "—",
              "الحالة": V.STATUS_AR[v["status"]]})

    actions = row_action_bar(
        edit=can and v["status"] == "issued",
        delete=can and v["status"] == "issued",
        print_=True,
        view=True,
        prefix=f"{tbl}_row_{v['id']}"
    )
    if actions["view"]:
        _view_voucher()
    if actions["edit"]:
        edit_dialog(v, tbl)
    if actions["print"]:
        st.download_button("", V.voucher_html(v["id"]).encode("utf-8"),
                           file_name=f"{v['voucher_no']}.html", mime="text/html",
                           key=f"{tbl}_h_{v['id']}", icon=":material/download:")
    if actions["delete"]:
        void_dialog(v, tbl)


def render():
    toast_flash(_FLASH)
    can = security.can_write()
    c1, c2, c3, c4 = st.columns([1.5, 1.5, 1.4, 1.4])
    with c1:
        if can and st.button("➕ إذن استلام", type="primary", key="vo_new_r", use_container_width=True):
            issue_dialog("receipt")
    with c2:
        if can and st.button("➕ إذن صرف", type="primary", key="vo_new_p", use_container_width=True):
            issue_dialog("payment")
    kind = c3.selectbox("النوع", ["all", "receipt", "payment"], format_func=lambda k: "الكل" if k == "all" else V.KIND_AR[k], key="vo_f_k")
    stt = c4.selectbox("الحالة", ["all", "issued", "void"], format_func=lambda k: "الكل" if k == "all" else V.STATUS_AR[k], key="vo_f_s")
    q = st.text_input("بحث", placeholder="بحث باسم الجهة أو رقم الإذن…", key="vo_f_q", label_visibility="collapsed").strip()
    rows = V.list_vouchers(None if kind == "all" else kind, status=None if stt == "all" else stt)
    if q:
        rows = [r for r in rows if q in r["party_name"] or q in r["voucher_no"]]
    voucher_table(rows, "vo", can)
