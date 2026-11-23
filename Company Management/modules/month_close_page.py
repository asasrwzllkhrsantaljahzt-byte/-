"""مراجعة وإقفال الشهر: checklist, totals, close (freeze) and reopen with a reason."""
import pandas as pd
import streamlit as st

import hub_close as C
import hub_engine as E
import security
from ui import toast_flash, flash_set, show_flash, excel_button

_ICON = {"warn": "⚠️", "info": "ℹ️", "ok": "✅"}


def render():
    show_flash()
    can = security.can_write()
    months = E.month_options()
    c1, c2 = st.columns([1, 3])
    month = c1.selectbox("الشهر", months, key="mc_m")
    rv = C.review(month)
    res = rv["res"]
    clo = E.closure(month)
    if clo:
        c2.success(f"🔒 الشهر مقفل منذ {clo['closed_at'][:16]} بواسطة {clo['closed_by']} — الأرقام مثبتة ولا تتغير بتعديل البيانات.")
    else:
        c2.info("🔓 الشهر مفتوح — الأرقام تُحتسب مباشرة وتتغير مع كل تحويل أو تعديل.")
    t = res["totals"]
    m = st.columns(5)
    m[0].metric("الموظفات", t["employees"]); m[1].metric("حوّله العميل", f"{t['transferred']:,.2f}")
    m[2].metric("الصافي", f"{t['net']:,.2f}"); m[3].metric("عمولة المناديب", f"{t['rep_due']:,.2f}"); m[4].metric("هامش الشركة", f"{t['margin']:,.2f}")

    st.markdown("#### قائمة المراجعة")
    for lvl, txt in rv["items"]:
        st.markdown(f"{_ICON[lvl]} {txt}")
    cdf = C.companies_df(res)
    if not cdf.empty:
        st.markdown("#### ملخص الشركات")
        st.dataframe(cdf, use_container_width=True, hide_index=True)
        excel_button(C.employees_df(res), f"month_{month}", "mc_xl")
    st.markdown("---")
    if can:
        if not clo:
            if st.button("🔒 إقفال الشهر وتثبيت الأرقام", type="primary", disabled=rv["blocking"], key="mc_close"):
                try:
                    msg = E.close_month(month)
                    try:
                        import backup as B
                        B.create_backup(f"إقفال {month}")
                        msg += " وأُخذت نسخة احتياطية تلقائياً."
                    except Exception:  # noqa: BLE001
                        msg += " (تعذر أخذ النسخة الاحتياطية، خذها يدوياً)."
                    flash_set(msg)
                except ValueError as ex:
                    st.error(str(ex)); return
                st.rerun()
            st.caption("بعد الإقفال لا يمكن إضافة تحويلات لهذا الشهر أو تعديلها أو إلغاؤها، وتبقى أرقامه كما هي في التقارير والكشوف. يمكن إعادة الفتح بسبب مكتوب.")
        else:
            reason = st.text_input("سبب إعادة الفتح (مطلوب)", key="mc_reason")
            if st.button("🔓 إعادة فتح الشهر", key="mc_reopen"):
                try:
                    flash_set(E.reopen_month(month, reason))
                except ValueError as ex:
                    st.error(str(ex)); return
                st.rerun()
    log = E.closure_log(month)
    if log:
        with st.expander("سجل الإقفال وإعادة الفتح"):
            st.dataframe(pd.DataFrame([{"الإجراء": "إقفال" if r["action"] == "close" else "إعادة فتح", "التاريخ": r["at"][:16],
                                        "بواسطة": r["by"], "السبب": r["reason"] or ""} for r in log]), use_container_width=True, hide_index=True)
