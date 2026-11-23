"""«التحويلات والحساب الشهري»: record what each client actually transferred; the monthly account follows from it."""
from datetime import date

import pandas as pd
import streamlit as st

import company_hub as hub
import hub_engine as E
import security
from db import query_all
from ui import flash_set, show_flash, select_table, tbump, excel_button, number_field, row_action_bar


def _f(x):
    return f"{float(x or 0):,.2f}"


def _ver():
    return st.session_state.get("mo_dv", 0)


def _bump():
    st.session_state["mo_dv"] = _ver() + 1


def _date_field(label, key, value=None):
    return st.date_input(label, value=value or date.today(), key=key, min_value=date(2000, 1, 1),
                         max_value=date(2100, 12, 31), format="YYYY-MM-DD")


def _placements_for(cid, month):
    """Placements of a company that work (at least one day) in the month."""
    co = query_all("SELECT * FROM companies WHERE id=?", (cid,))[0]
    out = []
    for p in hub.company_employees(cid, "all"):
        if p["basic_salary"] is None:
            continue
        d = E.active_days(p, co, month)
        if d > 0:
            _, _, md = E.month_bounds(month)
            p["basic_eff"] = round(float(p["basic_salary"]) * d / md, 2)
            out.append(p)
    return out


# ------------------------------------------------------------------ dialogs
def _dlg_transfer(tid=None):
    @st.dialog("تعديل تحويل" if tid else "تسجيل تحويل من العميل", width="large")
    def _d():
        cur = query_all("""SELECT t.*, p.company_id FROM client_transfers t JOIN employee_placements p ON p.id=t.placement_id
                           WHERE t.id=?""", (tid,))[0] if tid else None
        k = f"mt{tid or 'n'}_{_ver()}_"
        companies = query_all("SELECT id, name FROM companies ORDER BY name")
        if not companies:
            st.warning("أضف شركة وموظفين أولاً من «الشركات والموظفون».")
            return
        cids = [c["id"] for c in companies]
        cnames = {c["id"]: c["name"] for c in companies}
        months = E.month_options(cur["work_month"] if cur else None)
        if tid:
            cid = cur["company_id"]
            st.markdown(f"**الشركة:** {cnames[cid]}")
        else:
            cid = st.selectbox("الشركة", cids, format_func=cnames.get, key=k + "co")
        month = st.selectbox("شهر العمل (الذي يخصه التحويل)", months, index=months.index(cur["work_month"]) if cur else 0, key=k + "month")
        pls = _placements_for(cid, month)
        if not pls:
            st.info("لا يوجد موظفون يعملون في هذه الشركة في هذا الشهر.")
            return
        pids = [p["id"] for p in pls]
        names = {p["id"]: p["full_name"] for p in pls}
        if tid and cur["placement_id"] in pids:
            pid = cur["placement_id"]
            st.markdown(f"**الموظف:** {names[pid]}")
        else:
            pid = st.selectbox("الموظف", pids, format_func=names.get, key=k + "emp")
        p = next(x for x in pls if x["id"] == pid)
        so_far = E.transferred_so_far(pid, month, exclude_id=tid)
        st.caption(f"الراتب الأساسي المستحق لهذا الشهر: **{_f(p['basic_eff'])}** — حُوِّل سابقاً: **{_f(so_far)}** "
                   f"— المتبقي: **{_f(max(p['basic_eff'] - so_far, 0))}**")
        a, b = st.columns(2)
        with a:
            tdate = _date_field("تاريخ التحويل", k + "date", date.fromisoformat(cur["transfer_date"]) if cur else None)
        with b:
            amount = number_field("المبلغ المحوّل *", k + "amt", value=cur["amount"] if cur else None, minimum=0)
        notes = st.text_area("ملاحظات (مثل: دفعة أولى، تأخر الراتب...)", value=(cur or {}).get("notes") or "", key=k + "notes")
        if st.button("💾 حفظ", type="primary", key=k + "save", use_container_width=True):
            try:
                if tid:
                    flash_set(E.update_transfer(tid, month, tdate, amount, notes))
                else:
                    _, msg, warn = E.add_transfer(pid, month, tdate, amount, notes)
                    flash_set(msg + ((" ⚠️ " + warn[0]) if warn else ""))
            except ValueError as ex:
                st.error(str(ex))
                return
            _bump()
            tbump("mo_tr")
            st.rerun()
    _d()


def _dlg_bulk():
    @st.dialog("تسجيل تحويل جماعي لشركة", width="large")
    def _d():
        companies = query_all("SELECT id, name FROM companies ORDER BY name")
        if not companies:
            st.warning("أضف شركة وموظفين أولاً.")
            return
        k = f"mb_{_ver()}_"
        cids = [c["id"] for c in companies]
        cnames = {c["id"]: c["name"] for c in companies}
        a, b, c = st.columns(3)
        with a:
            cid = st.selectbox("الشركة", cids, format_func=cnames.get, key=k + "co")
        with b:
            month = st.selectbox("شهر العمل", E.month_options(), key=k + "month")
        with c:
            tdate = _date_field("تاريخ التحويل", k + "date")
        pls = _placements_for(cid, month)
        if not pls:
            st.info("لا يوجد موظفون يعملون في هذه الشركة في هذا الشهر.")
            return
        rows = []
        for p in pls:
            so_far = E.transferred_so_far(p["id"], month)
            rows.append({"الموظف": p["full_name"], "الراتب المستحق للشهر": p["basic_eff"], "حُوِّل سابقاً": so_far,
                         "المبلغ المحوّل الآن": round(max(p["basic_eff"] - so_far, 0), 2)})
        st.caption("عدّل «المبلغ المحوّل الآن» لكل موظف بما حوّله العميل فعلاً، واتركه صفراً لمن لم يُحوَّل له شيء.")
        edited = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                                disabled=["الموظف", "الراتب المستحق للشهر", "حُوِّل سابقاً"],
                                column_config={"المبلغ المحوّل الآن": st.column_config.NumberColumn(min_value=0.0, format="%.2f")},
                                key=k + f"ed_{cid}_{month}")
        notes = st.text_input("ملاحظات", key=k + "notes")
        if st.button("💾 حفظ التحويلات", type="primary", key=k + "save", use_container_width=True):
            amounts = {pls[i]["id"]: float(v or 0) for i, v in enumerate(edited["المبلغ المحوّل الآن"].tolist())}
            try:
                _, msg = E.add_bulk(month, tdate, amounts, notes)
            except ValueError as ex:
                st.error(str(ex))
                return
            _bump()
            tbump("mo_tr")
            flash_set(msg)
            st.rerun()
    _d()


def _dlg_void(row):
    @st.dialog("إلغاء تحويل")
    def _d():
        st.write(f"إلغاء تحويل **{_f(row['amount'])}** للموظف **{row['full_name']}** عن شهر {row['work_month']}. "
                 "لا يُحذف من السجل، لكنه لا يدخل الحساب بعد الإلغاء.")
        reason = st.text_input("سبب الإلغاء *", key=f"mv_{row['id']}_{_ver()}")
        if st.button("تأكيد الإلغاء", type="primary", key=f"mvb_{row['id']}", use_container_width=True):
            try:
                msg = E.void_transfer(row["id"], reason)
            except ValueError as ex:
                st.error(str(ex))
                return
            _bump()
            tbump("mo_tr")
            flash_set(msg)
            st.rerun()
    _d()


# ------------------------------------------------------------------ tab: monthly account
def _explain(r):
    st.markdown(f"**{r['employee']}** — شهر {r['days']} يوم من {r['month_days']}")
    lines = [f"- التكلفة المستحقة = التكلفة الفعلية × ({r['days']} ÷ {r['month_days']}) = **{_f(r['cost_eff'])}**",
             f"- المحوّل من العميل = **{_f(r['transferred'])}**"]
    if r["cost_eff"] > 0 and r["transferred"] < r["cost_eff"]:
        lines.append(f"- المحوّل أقل من التكلفة، فنسبة التحصيل = {_f(r['transferred'])} ÷ {_f(r['cost_eff'])} = **{r['ratio'] * 100:.2f}%** ولا مردود للعميل")
    else:
        lines.append(f"- المحوّل يغطي التكلفة، فالنسبة 100% والمردود للعميل = {_f(r['transferred'])} − {_f(r['cost_eff'])} = **{_f(r['refund'])}**")
    lines += [f"- إيراد الشركة = **{_f(r['revenue'])}**",
              f"- مكافأة الموظف المستحقة = {_f(r['bonus_eff'])} × النسبة = **{_f(r['bonus_due'])}**",
              f"- عمولة المتعهد = {_f(r['contractor_eff'])} × النسبة = **{_f(r['contractor_due'])}**",
              f"- العمولة الخارجية = {_f(r['external_eff'])} × النسبة = **{_f(r['external_due'])}**",
              f"- **الصافي** = {_f(r['revenue'])} − {_f(r['bonus_due'])} − {_f(r['contractor_due'])} − {_f(r['external_due'])} = **{_f(r['net'])}**",
              f"- على الموظف إعادته للشركة = المحوّل − مكافأته = {_f(r['transferred'])} − {_f(r['bonus_due'])} = **{_f(r['employee_returns'])}**"]
    st.markdown("\n".join(lines))


def _tab_monthly():
    months = E.month_options()
    a, b = st.columns(2)
    with a:
        month = st.selectbox("الشهر", months, key="mo_month")
    companies = query_all("SELECT id, name FROM companies ORDER BY name")
    with b:
        cid = st.selectbox("الشركة", [None] + [c["id"] for c in companies], key="mo_co",
                           format_func={None: "كل الشركات", **{c["id"]: c["name"] for c in companies}}.get)
    res = E.compute_month(month, cid)
    t = res["totals"]
    if not res["companies"]:
        st.info("لا يوجد موظفون يعملون في هذا الشهر. أضف الشركات والموظفين من «الشركات والموظفون».")
        return
    for w in res["warnings"]:
        st.warning(w)
    if t["not_transferred"]:
        st.info(f"{t['not_transferred']} موظف لم يُسجَّل لهم أي تحويل من العميل لهذا الشهر، فأرقامهم صفر حتى تسجّل التحويل.")
    rows1 = st.columns(4)
    for col, (lbl, v) in zip(rows1, (("الموظفون العاملون", t["employees"]), ("المحوّل من العملاء", _f(t["transferred"])),
                                     ("إيراد الشركة", _f(t["revenue"])), ("المردود للعملاء", _f(t["refund"])))):
        with col:
            with st.container(border=True):
                st.metric(lbl, v)
    rows2 = st.columns(4)
    for col, (lbl, v) in zip(rows2, (("مكافآت الموظفين", _f(t["bonus_due"])), ("عمولات المتعهدين", _f(t["contractor_due"])),
                                     ("العمولات الخارجية", _f(t["external_due"])), ("صافي الشركات", _f(t["net"])))):
        with col:
            with st.container(border=True):
                st.metric(lbl, v)
    rows3 = st.columns(3)
    for col, (lbl, v, h) in zip(rows3, (("عمولات المناديب", _f(t["rep_due"]), "نسبة كل مندوب من صافي شركته"),
                                        ("هامش الشركة (الربح)", _f(t["margin"]), "الصافي بعد المندوبين"),
                                        ("على الموظفين إعادته للشركة", _f(t["employee_returns"]), "المحوّل ناقص المكافآت"))):
        with col:
            with st.container(border=True):
                st.metric(lbl, v, help=h)

    flat = []
    for c in res["companies"]:
        st.markdown(f"##### 🏢 {c['company']}")
        df = pd.DataFrame([{
            "الموظف": r["employee"], "الأيام": f"{r['days']}/{r['month_days']}", "الراتب المستحق": r["basic_eff"],
            "التكلفة المستحقة": r["cost_eff"], "المحوّل": r["transferred"], "نسبة التحصيل %": round(r["ratio"] * 100, 2),
            "الإيراد": r["revenue"], "المردود للعميل": r["refund"], "المكافأة": r["bonus_due"],
            "المتعهد": r["contractor_name"] or "", "عمولته": r["contractor_due"], "عمولة خارجية": r["external_due"],
            "الصافي": r["net"], "يعيدها للشركة": r["employee_returns"]} for r in c["employees"]])
        st.dataframe(df, use_container_width=True, hide_index=True,
                     column_config={col: st.column_config.Column(alignment="right") for col in df.columns})
        rep = f"{c['rep_name']} ({c['rep_percent']:g}%) = {_f(c['rep_due'])}" if c["rep_name"] else "بلا مندوب"
        st.caption(f"صافي الشركة: **{_f(c['net'])}** — المندوب: {rep} — **هامش الشركة: {_f(c['margin'])}** "
                   f"(المتوقع لو حوّل العميل كاملاً: {_f(c['expected_margin'])})")
        for x in df.to_dict("records"):
            flat.append({"الشركة": c["company"], **x})
    excel_button(pd.DataFrame(flat), f"الحساب_الشهري_{month}", "mo_xl")

    with st.expander("🔍 كيف حُسب رقم موظف معيّن؟"):
        emps = [(r["placement_id"], f"{c['company']} — {r['employee']}") for c in res["companies"] for r in c["employees"]]
        pick = st.selectbox("الموظف", [e[0] for e in emps], format_func=dict(emps).get, key="mo_explain")
        for c in res["companies"]:
            for r in c["employees"]:
                if r["placement_id"] == pick:
                    _explain(r)


# ------------------------------------------------------------------ tab: transfers
def _tab_transfers(can):
    c1, c2, c3, c4 = st.columns([1.2, 1.4, 1, 1])
    months = ["الكل"] + E.month_options()
    with c1:
        month = st.selectbox("الشهر", months, key="mo_tr_month")
    companies = query_all("SELECT id, name FROM companies ORDER BY name")
    with c2:
        cid = st.selectbox("الشركة", [None] + [c["id"] for c in companies], key="mo_tr_co",
                           format_func={None: "كل الشركات", **{c["id"]: c["name"] for c in companies}}.get)
    with c3:
        status = st.selectbox("الحالة", ["active", "void", "all"], key="mo_tr_st",
                              format_func={"active": "السارية", "void": "الملغاة", "all": "الكل"}.get)
    if can:
        with c4:
            st.write("")
        b1, b2, _ = st.columns([1.3, 1.6, 4])
        if b1.button("➕ تحويل", type="primary", key="mo_add"):
            _dlg_transfer(None)
        if b2.button("➕ تحويل جماعي لشركة", key="mo_bulk"):
            _dlg_bulk()
    rows = E.list_transfers(None if month == "الكل" else month, cid, status)
    if not rows:
        st.info("لا توجد تحويلات مطابقة." + (" سجّل ما حوّله العميل من «تحويل» أو «تحويل جماعي»." if can else ""))
        return
    df = pd.DataFrame([{"الرقم": r["id"], "التاريخ": r["transfer_date"], "شهر العمل": r["work_month"], "الشركة": r["company_name"],
                        "الموظف": r["full_name"], "المبلغ": r["amount"], "الحالة": "ساري" if r["status"] == "active" else "ملغى",
                        "ملاحظات": r["notes"] or r["void_reason"] or ""} for r in rows])
    excel_button(df, "تحويلات_العملاء", "mo_tr_xl")
    pos = select_table(df, "mo_tr")
    st.caption(f"عدد التحويلات: {len(rows)} — إجمالي السارية: {_f(sum(r['amount'] for r in rows if r['status'] == 'active'))}")
    if pos is not None and pos < len(rows):
        row = rows[pos]
        if row["status"] == "active":
            actions = row_action_bar(edit=can, delete=can, view=True, prefix=f"mo_row_{row['id']}")
            if actions["edit"]:
                _dlg_transfer(row["id"])
            if actions["delete"]:
                _dlg_void(row)
            if actions["view"]:
                st.info(f"تحويل {row['id']} — {row['company_name']} — {row['full_name']} — {row['amount']:,.2f} ر.س")
        else:
            st.info(f"هذا التحويل ملغى. السبب: {row['void_reason'] or '—'}")
    elif can:
        st.caption("💡 اضغط مربع الاختيار أول أي صف لتعديل التحويل أو إلغائه.")


def render():
    show_flash()
    can = security.can_write()
    t1, t2 = st.tabs(["📅 الحساب الشهري", "💸 تحويلات العميل"])
    with t1:
        _tab_monthly()
    with t2:
        _tab_transfers(can)
