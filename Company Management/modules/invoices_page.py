import pandas as pd
import streamlit as st
from datetime import date

import app_settings
import invoicing
import security
from db import query_all
from ui import select_table, tbump, toast_flash, friendly_error, row_action_bar

_FLASH = "_inv_flash"
STATUS_AR = {"issued": "سارية", "void": "ملغاة"}


@st.dialog("إصدار فاتورة جديدة")
def _dlg_issue():
    companies = query_all("SELECT id, name FROM companies ORDER BY name")
    if not companies:
        st.info("أضف شركة عميلة أولاً.")
        return
    names = {c["name"]: c["id"] for c in companies}
    cname = st.selectbox("الشركة العميلة", list(names), key="inv_company")
    cid = names[cname]
    months = invoicing.months_with_accounts(cid)
    if not months:
        st.warning("لا توجد إيرادات فعلية لهذه الشركة بعد. سجّل تحويلات العميل من «الحركات المالية».")
        return
    month = st.selectbox("الشهر", months, key="inv_month")
    pv = invoicing.preview(cid, month)
    df = pd.DataFrame([{"الموظف": l["full_name"], "أيام العمل": f"{l['active_days']}/{l['month_days']}",
                        "المبلغ": float(l["amount"])} for l in pv["lines"]])
    st.dataframe(df, hide_index=True, use_container_width=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("قبل الضريبة", f"{pv['subtotal']:,.2f}")
    c2.metric(f"الضريبة {pv['vat_rate']:g}%", f"{pv['vat_amount']:,.2f}")
    c3.metric("الإجمالي", f"{pv['total']:,.2f}")
    if not pv["month_closed"]:
        st.caption("⚠️ بعض حسابات هذا الشهر غير معتمدة بعد. الأفضل اعتماد الشهر قبل إصدار الفاتورة.")
    d = st.date_input("تاريخ الفاتورة", value=date.today(), key="inv_date")
    notes = st.text_area("ملاحظات (اختياري)", key="inv_notes")
    if st.button("إصدار الفاتورة", type="primary", key="inv_issue_btn"):
        try:
            iid = invoicing.issue_invoice(cid, month, d, notes)
            st.session_state[_FLASH] = "تم إصدار الفاتورة."
            tbump("inv")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(friendly_error(e))


@st.dialog("إلغاء الفاتورة")
def _dlg_void(inv):
    st.warning(f"سيتم إلغاء الفاتورة {inv['invoice_no']} ولا يمكن التراجع. تبقى محفوظة في السجل.")
    reason = st.text_input("سبب الإلغاء (مطلوب)", key="inv_void_reason")
    if st.button("تأكيد الإلغاء", type="primary", key="inv_void_btn"):
        try:
            st.session_state[_FLASH] = invoicing.void_invoice(inv["id"], reason)
            tbump("inv")
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def render():
    toast_flash(_FLASH)
    can_write = security.can_write()
    st.caption("فواتير داخلية مبنية على الحسابات الشهرية المحتسبة. لا تُغني عن الفاتورة الإلكترونية المعتمدة من هيئة الزكاة والضريبة والجمارك.")
    if not app_settings.get("org_tax_number").strip():
        st.warning("أدخل الرقم الضريبي للمنشأة في «الإعدادات» حتى تتمكن من إصدار الفواتير.")
    if can_write and st.button("➕ إصدار فاتورة", type="primary", key="inv_new"):
        _dlg_issue()
    f1, f2 = st.columns(2)
    comps = query_all("SELECT id, name FROM companies ORDER BY name")
    fc = f1.selectbox("الشركة", ["الكل"] + [c["name"] for c in comps], key="inv_f_company")
    fs = f2.selectbox("الحالة", ["الكل", "سارية", "ملغاة"], key="inv_f_status")
    cid = next((c["id"] for c in comps if c["name"] == fc), None)
    status = {"سارية": "issued", "ملغاة": "void"}.get(fs)
    rows = invoicing.list_invoices(company_id=cid, status=status)
    if not rows:
        st.info("لا توجد فواتير.")
        return
    df = pd.DataFrame([{"رقم الفاتورة": r["invoice_no"], "العميل": r["buyer_name"], "الشهر": r["month_ref"],
                        "التاريخ": r["issue_date"], "قبل الضريبة": float(r["subtotal"]), "الضريبة": float(r["vat_amount"]),
                        "الإجمالي": float(r["total"]), "الحالة": STATUS_AR[r["status"]]} for r in rows])
    pos = select_table(df, "inv")
    if pos is None:
        st.caption("اضغط على صف لعرض الفاتورة وتنزيلها.")
        return
    inv = rows[pos]
    st.markdown(f"**{inv['invoice_no']}** — {inv['buyer_name']} — {inv['month_ref']}")
    st.dataframe(pd.DataFrame(invoicing.invoice_lines(inv["id"]))[["description", "active_days", "month_days", "amount"]]
                 .rename(columns={"description": "البيان", "active_days": "أيام العمل", "month_days": "أيام الشهر", "amount": "المبلغ"}),
                 hide_index=True, use_container_width=True)
    actions = row_action_bar(delete=can_write and inv["status"] == "issued", print_=True, view=True,
                            prefix=f"inv_row_{inv['id']}")
    if actions["view"]:
        st.dataframe(pd.DataFrame(invoicing.invoice_lines(inv["id"])), hide_index=True, use_container_width=True)
    if actions["print"]:
        st.download_button("", invoicing.invoice_html(inv["id"]).encode("utf-8"),
                           file_name=f"{inv['invoice_no']}.html", mime="text/html", key=f"inv_h_{inv['id']}")
    if actions["delete"]:
        _dlg_void(inv)
