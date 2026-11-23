import html as _html

import pandas as pd
import streamlit as st

import exports as X
import vouchers as V
import hub_accounts as HA
from db import query_all
from ui import excel_button

_TYPES = [("company", "شركة عميلة"), ("employee", "موظفة"), ("contractor", "متعهد / عمولة خارجية"), ("representative", "مندوب")]


def _print_html(title, summary, acc_df):
    cards = "".join(f"<td><b>{_html.escape(k)}</b><br>{_html.escape(v)}</td>" for k, v in summary.items())
    body = "<p>لا توجد بيانات.</p>" if acc_df.empty else acc_df.fillna("").to_html(index=False, border=1, escape=True)
    return (f"<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><title>{_html.escape(title)}</title>"
            "<style>body{font-family:Tahoma,Arial;margin:28px}table{border-collapse:collapse;width:100%;margin:8px 0}"
            "th,td{border:1px solid #999;padding:5px 8px;text-align:right}th{background:#eee}</style></head><body>"
            f"<div>{__import__('branding').logo_img_html(50)}</div><h2>{_html.escape(title)}</h2><table><tr>{cards}</tr></table><h3>كشف الحساب</h3>{body}</body></html>")


def render():
    c1, c2, c3 = st.columns([1, 2, 1])
    ptype = c1.selectbox("نوع الطرف", [t[0] for t in _TYPES], format_func=dict(_TYPES).get, key="st_type")
    t, col = V.PARTY_TABLE[ptype]
    opts = {f"{r['n']} (#{r['id']})": r["id"] for r in query_all(f"SELECT id, {col} AS n FROM {t} ORDER BY {col}")}
    if not opts:
        st.info("لا توجد سجلات لهذا النوع بعد.")
        return
    label = c2.selectbox("اختر الطرف (اكتب للبحث)", list(opts), key=f"st_party_{ptype}")
    pid = opts[label]
    acc = V.party_account(ptype, pid)
    months = sorted({r["month_ref"] for r in acc["by_month"]} | {V.voucher_month(v) for v in acc["vouchers"]}, reverse=True)
    month = c3.selectbox("الفترة", ["كل الفترات"] + months, key=f"st_month_{ptype}")
    mref = None if month == "كل الفترات" else month
    bal = next(b for b in V.party_balances(ptype, mref) if b["id"] == pid)
    m1, m2, m3 = st.columns(3)
    m1.metric(acc["due_label"], f"{bal['due']:,.2f}")
    m2.metric(acc["settled_label"], f"{bal['settled']:,.2f}")
    m3.metric(acc["balance_label"], f"{bal['balance']:,.2f}")
    st.info("📌 " + V.balance_phrase(ptype, bal["balance"]))

    rows = V.statement_rows(ptype, pid)
    if mref:
        rows = [r for r in rows if str(r["التاريخ"]).startswith(mref) or r["البيان"].endswith(mref)]
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("لا توجد مستحقات أو إذون ضمن الفترة.")
    else:
        shown = df.copy()
        for c in ("مستحق", "مسدد", "الرصيد"):
            shown[c] = shown[c].map(lambda x: "" if pd.isna(x) else f"{float(x):,.2f}")
        st.dataframe(shown, use_container_width=True, hide_index=True)
    st.caption("المستحق يُحسب مباشرة من «التحويلات والحساب الشهري»، والمسدَّد من الإذون السارية.")
    summary = {acc["due_label"]: f"{bal['due']:,.2f}", acc["settled_label"]: f"{bal['settled']:,.2f}",
               acc["balance_label"]: f"{bal['balance']:,.2f}"}
    title = f"كشف حساب — {label.rsplit(' (#', 1)[0]}" + (f" — {mref}" if mref else "")
    st.markdown("---")
    b1, b2, b3 = st.columns(3)
    ok, why = X.pdf_available()
    with b1:
        data = X.export_excel({"كشف الحساب": df, "الملخص": pd.DataFrame([summary])})
        st.download_button("⬇️ تصدير Excel", data=data, file_name=f"statement_{ptype}_{pid}.xlsx", key="st_xl",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with b2:
        st.download_button("🖨️ نسخة للطباعة (HTML)", _print_html(title, summary, df).encode("utf-8"),
                           file_name=f"statement_{ptype}_{pid}.html", mime="text/html", key="st_html")
    with b3:
        if ok:
            try:
                import app_settings
                sdf = pd.DataFrame([summary])
                pdf = X.table_pdf(title, [("الملخص", sdf), ("كشف الحساب", df)], "", app_settings.get("org_name"))
                st.download_button("⬇️ تنزيل PDF", pdf, file_name=f"statement_{ptype}_{pid}.pdf", mime="application/pdf", key="st_pdf")
            except Exception as ex:  # noqa: BLE001
                st.caption(f"تعذر PDF: {ex}")
        else:
            st.caption(f"PDF غير متاح: {why}")
