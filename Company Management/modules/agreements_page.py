"""«الاتفاقات المالية»: any beneficiary (representative / contractor) <-> a whole client, one employee, or a group."""
import streamlit as st
import pandas as pd
from datetime import date, datetime
import security
import agreements as A
import vouchers as V
from db import query_all, query_one
from ui import toast_flash, select_table, tbump, excel_button, number_field, norm_month, row_action_bar

_FLASH = "_ag_flash"


def _flash(msg):
    st.session_state[_FLASH] = msg
    st.rerun()


def _iso(d):
    return d.strftime("%Y-%m-%d")


def _placements(open_only=True):
    rows = query_all("""SELECT p.id, e.full_name, c.name AS company, c.id AS company_id, p.start_date, p.end_date, p.status
                        FROM employee_placements p JOIN employees e ON e.id=p.employee_id JOIN companies c ON c.id=p.company_id
                        ORDER BY c.name, e.full_name""")
    return [r for r in rows if not open_only or r["status"] != "ended"]


def _pl_label(r):
    return f"{r['full_name']} @ {r['company']} (#{r['id']})"


def _clear(prefix):
    for k in [k for k in st.session_state if str(k).startswith(prefix)]:
        del st.session_state[k]


def _row_text(a):
    return {"الرقم": a["id"], "المستفيد": f"{A.BENEFICIARY_AR[a['beneficiary_type']]} · {A.beneficiary_name(a['beneficiary_type'], a['beneficiary_id'])}",
            "النطاق": A.scope_label(a), "طريقة الحساب": A.describe(a) + ("" if a["prorate"] else " (شهر كامل دائماً)"),
            "من": a["start_date"], "إلى": a["end_date"] or "مفتوح", "الحالة": A.STATUS_AR[a["status"]], "ملاحظات": a["notes"] or ""}


# ------------------------------------------------------------------ dialogs
@st.dialog("اتفاق مالي", width="large")
def _dlg_agreement(a=None):
    pre = f"agd_{a['id'] if a else 'new'}_"
    members0 = A.members_of(a["id"]) if a else []
    btypes = list(A.BENEFICIARY_AR)
    c1, c2 = st.columns(2)
    bt = c1.radio("المستفيد (صاحب العمولة)", btypes, format_func=A.BENEFICIARY_AR.get, horizontal=True, key=pre + "bt",
                  index=btypes.index(a["beneficiary_type"]) if a else 0)
    t, col = A.PARTY_TABLE[bt]
    parties = {f"{r['n']} (#{r['id']})": r["id"] for r in query_all(f"SELECT id, {col} AS n FROM {t} WHERE status='active' ORDER BY {col}")}
    if not parties:
        st.warning(f"لا يوجد {A.BENEFICIARY_AR[bt]} نشط. أضفه من صفحته أولاً.")
        return
    keys = list(parties)
    idx = next((i for i, k in enumerate(keys) if a and parties[k] == a["beneficiary_id"]), 0)
    party = c2.selectbox(A.BENEFICIARY_AR[bt], keys, index=idx, key=pre + f"party_{bt}")

    st.markdown("**على ماذا تُحسب العمولة؟**")
    scopes = list(A.SCOPE_AR)
    scope = st.radio("النطاق", scopes, format_func=A.SCOPE_AR.get, horizontal=True, key=pre + "scope",
                     index=scopes.index(a["scope_type"]) if a else 0, label_visibility="collapsed")
    comp_id = pl_id = None
    members = []
    if scope == "client":
        comps = {f"{r['name']} (#{r['id']})": r["id"] for r in query_all("SELECT id, name FROM companies ORDER BY name")}
        if not comps:
            st.warning("أضف شركة عميلة أولاً.")
            return
        ck = list(comps)
        ci = next((i for i, k in enumerate(ck) if a and comps[k] == a["company_id"]), 0)
        comp_id = comps[st.selectbox("الشركة العميلة", ck, index=ci, key=pre + "comp")]
        st.caption("تشمل كل موظفي هذه الشركة النشطين في الشهر، ويدخل فيها أي موظف جديد يُعيَّن لديها تلقائياً.")
    else:
        pls = {_pl_label(r): r["id"] for r in _placements()}
        if not pls:
            st.warning("لا توجد تعيينات. أضف تعييناً أولاً.")
            return
        pk = list(pls)
        if scope == "placement":
            pi = next((i for i, k in enumerate(pk) if a and pls[k] == a["placement_id"]), 0)
            pl_id = pls[st.selectbox("الموظف", pk, index=pi, key=pre + "pl")]
        else:
            default = [k for k in pk if pls[k] in members0]
            sel = st.multiselect("موظفو المجموعة", pk, default=default, key=pre + "members")
            members = [pls[k] for k in sel]

    st.markdown("**طريقة الحساب**")
    m1, m2, m3 = st.columns(3)
    methods = list(A.METHOD_AR)
    method = m1.selectbox("الطريقة", methods, format_func=A.METHOD_AR.get, key=pre + "method",
                          index=methods.index(a["method"]) if a else 1)
    basis = None
    if method == "percent":
        bases = list(A.BASIS_AR)
        basis = m2.selectbox("النسبة من", bases, format_func=A.BASIS_AR.get, key=pre + "basis",
                             index=bases.index(a["percent_basis"]) if a and a["percent_basis"] else 0)
    with m3:
        val = number_field("القيمة (% للنسبة، ريال لغيرها)", pre + "val", value=a["value"] if a else None, minimum=0)
    hints = {"fixed_monthly": "مبلغ واحد شهرياً للنطاق كله، يُقسَّم بالتساوي على موظفيه.",
             "per_employee": "يُضرب المبلغ في عدد الموظفين النشطين في النطاق (مثال: 50 ريالاً عن كل موظف).",
             "percent": "تُحسب النسبة من الأساس المختار لكل موظف في الشهر."}
    st.caption(hints[method])
    prorate = st.checkbox("احتساب بالأيام الفعلية (يُخفَّض المبلغ إن عمل الموظف جزءاً من الشهر)", value=bool(a["prorate"]) if a else True,
                          key=pre + "prorate")

    d1, d2 = st.columns(2)
    start = d1.date_input("تاريخ بداية الاتفاق", value=datetime.strptime(a["start_date"], "%Y-%m-%d").date() if a else date.today(),
                          key=pre + "start")
    has_end = d2.checkbox("له تاريخ نهاية", value=bool(a and a["end_date"]), key=pre + "has_end")
    end = d2.date_input("تاريخ النهاية", value=datetime.strptime(a["end_date"], "%Y-%m-%d").date() if a and a["end_date"] else date.today(),
                        key=pre + "end") if has_end else None
    notes = st.text_input("ملاحظات", value=(a or {}).get("notes") or "", key=pre + "notes")

    data = dict(beneficiary_type=bt, beneficiary_id=parties[party], scope_type=scope, company_id=comp_id, placement_id=pl_id,
                method=method, value=val or 0, percent_basis=basis, prorate=prorate, start_date=_iso(start),
                end_date=_iso(end) if end else None, notes=notes)

    with st.container(border=True):
        st.markdown("**👁 معاينة الاتفاق**")
        month = norm_month(st.text_input("شهر المعاينة (مثل 2026-03)", value=date.today().strftime("%Y-%m"), key=pre + "pm")) or date.today().strftime("%Y-%m")
        try:
            if not val:
                st.caption("اكتب القيمة لتظهر المعاينة.")
            else:
                pv = A.preview(data, members, month.strip())
                st.write(f"**{A.BENEFICIARY_AR[bt]}:** {party.rsplit(' (', 1)[0]} — **{A.describe(dict(data))}**")
                if not pv["rows"]:
                    st.info("لا يوجد موظف ينطبق عليه هذا الاتفاق في الشهر المختار (تحقق من التواريخ والنطاق).")
                else:
                    st.dataframe(pd.DataFrame(pv["rows"]).assign(**{"المبلغ": [f"{r['المبلغ']:,.2f}" for r in pv["rows"]]}),
                                 use_container_width=True, hide_index=True)
                    st.success(f"إجمالي ما سيُستحق في {month}: {pv['total']:,.2f} ريال")
                    if pv["no_figures"]:
                        st.caption("ℹ️ لا توجد أرقام محتسبة لهذا الشهر بعد، لذلك تظهر النسبة صفراً. ستُحسب عند احتساب الشهر.")
        except ValueError as ex:
            st.caption(f"⚠️ {ex}")
        except Exception:  # noqa: BLE001
            st.caption("تعذرت المعاينة لهذا الشهر.")
    if st.button("حفظ الاتفاق", type="primary", use_container_width=True, key=pre + "save"):
        try:
            if a:
                msg = A.update_agreement(a["id"], data, members)
            else:
                msg = f"تم إنشاء الاتفاق رقم {A.create_agreement(data, members)}."
        except ValueError as ex:
            st.error(str(ex))
            return
        _clear(pre)
        tbump("ag")
        _flash(msg)


@st.dialog("إنهاء اتفاق مالي")
def _dlg_end(a):
    st.markdown(f"**{A.beneficiary_name(a['beneficiary_type'], a['beneficiary_id'])}** — {A.scope_label(a)} — {A.describe(a)}")
    st.caption("لا يُحذف الاتفاق: يُسجَّل تاريخ نهاية ويبقى في السجل، وتتوقف عمولاته بعد هذا التاريخ.")
    d = st.date_input("آخر يوم استحقاق", value=date.today(), key=f"age_{a['id']}")
    if st.button("اعتماد الإنهاء", type="primary", use_container_width=True, key=f"age_ok_{a['id']}"):
        try:
            msg = A.end_agreement(a["id"], d)
        except ValueError as ex:
            st.error(str(ex)); return
        tbump("ag"); _flash(msg)


@st.dialog("حذف اتفاق مالي")
def _dlg_delete(a):
    st.markdown(f"**{A.beneficiary_name(a['beneficiary_type'], a['beneficiary_id'])}** — {A.scope_label(a)} — {A.describe(a)}")
    st.warning("يُحذف فقط الاتفاق الذي لم يدخل في أي حساب. إن كان مستخدماً فأنهِه بدلاً من حذفه.")
    if st.button("🗑️ تأكيد الحذف", type="primary", use_container_width=True, key=f"agdel_{a['id']}"):
        try:
            msg = A.delete_agreement(a["id"])
        except ValueError as ex:
            st.error(str(ex)); return
        tbump("ag"); _flash(msg)


# ------------------------------------------------------------------ tabs
def _tab_list(can):
    c1, c2, c3, c4 = st.columns([1.4, 1.6, 1.4, 1.4])
    bt = c1.selectbox("المستفيد", ["all"] + list(A.BENEFICIARY_AR), format_func=lambda x: "كل المستفيدين" if x == "all" else A.BENEFICIARY_AR[x],
                      key="ag_f_bt", label_visibility="collapsed")
    comps = {"كل العملاء": None}
    comps.update({r["name"]: r["id"] for r in query_all("SELECT id, name FROM companies ORDER BY name")})
    cf = c2.selectbox("العميل", list(comps), key="ag_f_c", label_visibility="collapsed")
    sf = c3.selectbox("الحالة", ["all", "active", "ended"], format_func=lambda x: {"all": "كل الحالات", "active": "ساري", "ended": "منتهٍ"}[x],
                      key="ag_f_s", label_visibility="collapsed")
    with c4:
        if can and st.button("➕ اتفاق جديد", type="primary", use_container_width=True, key="ag_new"):
            _dlg_agreement()
    rows = A.list_agreements(None if bt == "all" else bt, None, comps[cf], None if sf == "all" else sf)
    if not rows:
        st.info("لا توجد اتفاقات. اضغط «➕ اتفاق جديد» — مثال: مندوب يأخذ 50 ريالاً عن كل موظف في شركة العربية.")
        return
    df = pd.DataFrame([_row_text(a) for a in rows])
    excel_button(df, "agreements", "ag_xl")
    sel = select_table(df, "ag")
    if sel is None:
        st.caption(f"عدد الاتفاقات: {len(rows)} — 💡 اضغط مربع الاختيار أول أي صف لتعديله أو إنهائه أو حذفه.")
        return
    a = rows[sel]
    with st.container(border=True):
        st.markdown(f"**المحدد:** {df.iloc[sel]['المستفيد']} — {df.iloc[sel]['النطاق']} — {df.iloc[sel]['طريقة الحساب']}")
        actions = row_action_bar(edit=can, delete=can, view=True, print_=True,
                                prefix=f"ag_row_{a['id']}")
        if actions["edit"]:
            _dlg_agreement(a)
        if actions["delete"]:
            _dlg_delete(a)
        if actions["view"]:
            st.info(f"الاتفاق #{a['id']} — مستفيد: {df.iloc[sel]['المستفيد']} — الحالة: {df.iloc[sel]['الحالة']}")
        if actions["print"]:
            st.download_button("طباعة الاتفاق", pd.DataFrame([df.iloc[sel].to_dict()]).to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"agreement_{a['id']}.csv", mime="text/csv",
                               key=f"ag_print_{a['id']}")


def _tab_map():
    comps = {f"{r['name']} (#{r['id']})": r["id"] for r in query_all("SELECT id, name FROM companies ORDER BY name")}
    if not comps:
        st.info("لا توجد شركات عميلة بعد.")
        return
    label = st.selectbox("اختر العميل لرؤية كل علاقاته", list(comps), key="ag_map_c")
    cid = comps[label]
    st.markdown("##### علاقات هذا العميل")
    rel = V.relations("company", cid)
    if rel:
        st.dataframe(pd.DataFrame(rel), use_container_width=True, hide_index=True)
    else:
        st.caption("لا علاقات مباشرة بعد (موظفون أو مناديب أو متعهدون).")
    st.markdown("##### الاتفاقات المالية المرتبطة بهذا العميل")
    rows = A.list_agreements(company_id=cid)
    if rows:
        st.dataframe(pd.DataFrame([_row_text(a) for a in rows]), use_container_width=True, hide_index=True)
    else:
        st.caption("لا اتفاقات مالية جديدة مرتبطة به.")
    st.markdown("##### الدورة المالية لموظفيه")
    pls = query_all("""SELECT p.id, e.full_name, p.start_date, p.end_date, p.status, p.flow_mode FROM employee_placements p
                       JOIN employees e ON e.id=p.employee_id WHERE p.company_id=? ORDER BY p.id DESC""", (cid,))
    if pls:
        st.dataframe(pd.DataFrame([{"الموظف": r["full_name"], "من": r["start_date"], "إلى": r["end_date"] or "مفتوح",
                                    "الحالة": {"active": "نشط", "ended": "منتهٍ", "suspended": "موقوف"}[r["status"]],
                                    "دورة المبلغ": FLOW_AR[r["flow_mode"]]} for r in pls]), use_container_width=True, hide_index=True)


FLOW_AR = {"direct": "العميل يحوّل للموظف مباشرة", "via_company": "العميل يدفع للشركة والشركة تدفع للموظف"}


def _tab_log():
    st.caption("يشرح كيف وصل البرنامج لكل عمولة: المستفيد والموظف والقاعدة والقيمة والفترة. يتجدد عند احتساب الشهر ويُحفظ عند اعتماده.")
    c1, c2 = st.columns([1, 2])
    months = [r["m"] for r in query_all("SELECT DISTINCT month_ref AS m FROM agreement_calc_log ORDER BY m DESC")]
    if not months:
        st.info("لا يوجد سجل بعد. احتسب شهراً من «مراجعة الحركات وإقفال الأشهر».")
        return
    m = c1.selectbox("الشهر", months, key="ag_log_m")
    bt = c2.selectbox("المستفيد", ["all", "contractor", "representative"], key="ag_log_b",
                      format_func=lambda x: {"all": "الكل", "contractor": "المتعهدون", "representative": "المندوبون"}[x])
    rows = A.calc_log(m, None if bt == "all" else bt)
    df = pd.DataFrame([{"المستفيد": f"{A.BENEFICIARY_AR[r['beneficiary_type']]} · {A.beneficiary_name(r['beneficiary_type'], r['beneficiary_id'])}",
                        "الموظف": r["employee"], "العميل": r["company"], "المبلغ": r["amount"],
                        "المصدر": "اتفاق مالي" if r["source"] == "fin_agreements" else "اتفاق التعيين",
                        "كيف حُسب": r["detail"] or ""} for r in rows])
    if df.empty:
        st.info("لا توجد بنود لهذا الاختيار.")
        return
    excel_button(df, f"commission_log_{m}", "ag_log_xl")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"إجمالي العمولات المعروضة: {df['المبلغ'].sum():,.2f} ريال")


def render():
    toast_flash(_FLASH)
    can = security.can_write()
    st.caption("اربط أي مندوب أو متعهد بعميل كامل، أو بموظف معيّن، أو بمجموعة موظفين، وحدد طريقة الحساب: مبلغ ثابت، أو عن كل موظف، أو نسبة. "
               "يمكن وجود أكثر من اتفاق لنفس العميل أو المستفيد، والبرنامج يجمعها كلها عند احتساب الشهر دون تكرار.")
    t1, t2, t3 = st.tabs(["📋 الاتفاقات", "🕸️ علاقات العميل", "🧮 كيف حُسبت العمولات"])
    with t1:
        _tab_list(can)
    with t2:
        _tab_map()
    with t3:
        _tab_log()
