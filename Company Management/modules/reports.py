"""التقارير المالية والإدارية — built on the monthly engine, downloadable as Excel and PDF."""
import altair as alt
import pandas as pd
import streamlit as st

import exports as X
import hub_close as C
import hub_engine as E
import vouchers as V
import app_settings
import security
from datetime import date


def _downloads(key, title, sections, subtitle=""):
    xl = X.export_excel({(h or "تقرير")[:30]: df for h, df in sections})
    c1, c2, c3 = st.columns([1, 1, 3])
    c1.download_button("⬇️ Excel", xl, file_name=f"{key}.xlsx", key=f"{key}_xl",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ok, why = X.pdf_available()
    if ok:
        try:
            pdf = X.table_pdf(title, sections, subtitle, app_settings.get("org_name"))
            c2.download_button("⬇️ PDF", pdf, file_name=f"{key}.pdf", key=f"{key}_pdf", mime="application/pdf")
        except Exception as ex:  # noqa: BLE001
            c3.caption(f"تعذر إنشاء PDF: {ex}")
    else:
        c3.caption(f"تنزيل PDF غير متاح: {why}")


def render():
    months = E.month_options()
    c1, c2 = st.columns([1, 3])
    month = c1.selectbox("الشهر", months, key="rp_m")
    res = E.compute_month(month)
    state = "🔒 مقفل" if res.get("closed") else "🔓 مفتوح (أرقام مباشرة)"
    c2.caption(f"حالة الشهر: {state}")
    sections = security.allowed_report_sections((security.current_user() or {}).get("role", ""))
    if not sections:
        st.info("لا توجد أقسام تقارير متاحة لهذا الحساب.")
        return
    labels = {
        "monthly_summary": "📊 ملخص الشهر",
        "employee_details": "👩 تفصيل الموظفات",
        "balances": "💼 الأرصدة والمستحقات",
        "annual": "📈 السنوي",
    }
    if st.session_state.get("_report_section") not in sections:
        st.session_state["_report_section"] = sections[0]
    section = st.segmented_control(
        "قسم التقرير",
        options=sections,
        format_func=labels.get,
        key="_report_section",
        label_visibility="collapsed",
    )
    if section == "monthly_summary":
        if not res["companies"]:
            st.info("لا توجد بيانات لهذا الشهر.")
        else:
            t = res["totals"]
            a = st.columns(4)
            a[0].metric("حوّله العميل", f"{t['transferred']:,.2f}"); a[1].metric("الإيراد الفعلي", f"{t['revenue']:,.2f}")
            a[2].metric("الصافي", f"{t['net']:,.2f}"); a[3].metric("هامش الشركة", f"{t['margin']:,.2f}")
            cdf = C.companies_df(res)
            st.dataframe(cdf, use_container_width=True, hide_index=True)
            _downloads(f"summary_{month}", f"ملخص شهر {month}", [("إجماليات", C.totals_df(res)), ("الشركات", cdf)], f"شهر {month} — {state}")
    elif section == "employee_details":
        df = C.employees_df(res)
        if df.empty:
            st.info("لا توجد بيانات.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            _downloads(f"employees_{month}", f"تفصيل الموظفات — {month}", [("الموظفات", df)], f"شهر {month}")
    elif section == "balances":
        scope = st.radio("النطاق", ["الشهر المختار", "كل الأشهر"], horizontal=True, key="rp_scope")
        mref = month if scope == "الشهر المختار" else None
        df = C.balances_df(mref)
        if df.empty:
            st.info("لا أرصدة.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            _downloads(f"balances_{mref or 'all'}", "الأرصدة والمستحقات", [("الأرصدة", df)], f"{mref or 'كل الأشهر'}")
    elif section == "annual":
        years = sorted({m[:4] for m in set(months) | set(V.other_payment_totals())}, reverse=True) or [str(date.today().year)]
        year = st.selectbox("السنة", years, key="rp_y")
        ydf = C.year_df(year)
        if ydf.empty:
            st.info("لا بيانات لهذه السنة.")
        else:
            st.dataframe(ydf, use_container_width=True, hide_index=True)
            totals = st.columns(3)
            totals[0].metric("مصروفات التشغيل", f"{ydf['المصروفات التشغيلية'].sum():,.2f}")
            totals[1].metric("صافي الربح بعد المصروفات", f"{ydf['صافي الربح بعد المصروفات'].sum():,.2f}")
            totals[2].metric("مسحوبات المالك (للتسوية السنوية)", f"{ydf['مسحوبات المالك (تسوية سنوية)'].sum():,.2f}")
            long = ydf.melt(id_vars="الشهر", value_vars=["هامش الشركة قبل المصروفات", "صافي الربح بعد المصروفات"],
                            var_name="المؤشر", value_name="المبلغ")
            st.altair_chart(alt.Chart(long).mark_bar().encode(x="الشهر:N", y="المبلغ:Q", color="المؤشر:N", xOffset="المؤشر:N"), use_container_width=True)
            _downloads(f"year_{year}", f"التقرير السنوي {year}", [("الأشهر", ydf)], f"سنة {year}")
