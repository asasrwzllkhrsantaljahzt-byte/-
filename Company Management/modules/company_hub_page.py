"""«الشركات والموظفون»: one screen per client company — its data, its representative, and its employees with their terms."""
from datetime import date

import pandas as pd
import streamlit as st

import company_hub as hub
import security
from db import query_all
import html as _html
import streamlit.components.v1 as components
from ui import flash_set, show_flash, select_table, tbump, excel_button, number_field, friendly_error

MIN_D, MAX_D = date(2000, 1, 1), date(2100, 12, 31)
COMPANY_STATUS = {"active": "نشطة", "inactive": "غير نشطة"}


def _fmt(x):
    return "" if x is None else f"{x:,.2f}"


def _ver():
    return st.session_state.get("hub_dv", 0)


def _bump():
    st.session_state["hub_dv"] = _ver() + 1


def _parse_date(s, default=None):
    try:
        return date.fromisoformat(s) if s else default
    except ValueError:
        return default


def _date_field(label, key, value=None):
    return st.date_input(label, value=value or date.today(), key=key, min_value=MIN_D, max_value=MAX_D, format="YYYY-MM-DD")


def _opt_date(label_check, label_date, key, value=None):
    """A date that may be left empty: a checkbox turns it on."""
    on = st.checkbox(label_check, value=bool(value), key=key + "_on")
    if on:
        return _date_field(label_date, key, value)
    return None


# ------------------------------------------------------------------ dialogs
def _dlg_company(cid=None):
    @st.dialog("تعديل بيانات الشركة" if cid else "شركة جديدة", width="large")
    def _d():
        cur = query_all("SELECT * FROM companies WHERE id=?", (cid,))[0] if cid else {}
        k = f"hc{cid or 'n'}_{_ver()}_"
        name = st.text_input("اسم الشركة *", value=cur.get("name") or "", key=k + "name")
        a, b = st.columns(2)
        with a:
            tax = st.text_input("الرقم الضريبي", value=cur.get("tax_number") or "", key=k + "tax")
            phone = st.text_input("الهاتف", value=cur.get("phone") or "", key=k + "phone")
            ws = _opt_date("لها تاريخ بداية عمل", "تاريخ بداية عمل الشركة", k + "ws", _parse_date(cur.get("work_start_date")))
        with b:
            cr = st.text_input("السجل التجاري", value=cur.get("commercial_register") or "", key=k + "cr")
            contact = st.text_input("الشخص المسؤول", value=cur.get("contact_person") or "", key=k + "ct")
            we = _opt_date("توقفت عن العمل", "تاريخ توقف الشركة", k + "we", _parse_date(cur.get("work_end_date")))
        email = st.text_input("البريد الإلكتروني", value=cur.get("email") or "", key=k + "em")
        address = st.text_area("العنوان", value=cur.get("address") or "", key=k + "ad")
        notes = st.text_area("ملاحظات", value=cur.get("notes") or "", key=k + "nt")
        status = st.selectbox("الحالة", list(COMPANY_STATUS), format_func=COMPANY_STATUS.get,
                              index=list(COMPANY_STATUS).index(cur.get("status") or "active"), key=k + "st")
        if st.button("💾 حفظ", type="primary", key=k + "save", use_container_width=True):
            try:
                new_id, msg = hub.save_company(cid, {
                    "name": name, "tax_number": tax, "commercial_register": cr, "phone": phone, "contact_person": contact,
                    "email": email, "address": address, "notes": notes, "status": status,
                    "work_start_date": ws, "work_end_date": we})
            except ValueError as ex:
                st.error(str(ex))
                return
            _bump()
            if not cid:
                st.session_state["_hub_select"] = new_id
            flash_set(msg)
            st.rerun()
    _d()


def _dlg_delete_company(cid, name):
    @st.dialog("حذف الشركة")
    def _d():
        links = hub.company_links(cid)
        if links:
            st.error("لا يمكن الحذف لأن الشركة مرتبطة بسجلات: " + "، ".join(f"{k}: {v}" for k, v in links.items()))
            st.info("غيّر حالتها إلى «غير نشطة» وضع تاريخ توقفها من زر التعديل، ويبقى تاريخها محفوظاً.")
            return
        st.warning(f"سيُحذف «{name}» نهائياً. هذا ممكن لأنها لا تحوي أي سجلات.")
        if st.button("🗑️ تأكيد الحذف", type="primary", key=f"hc_del_{cid}", use_container_width=True):
            try:
                msg = hub.delete_company(cid)
            except ValueError as ex:
                st.error(str(ex))
                return
            st.session_state["hub_open"] = None
            flash_set(msg)
            st.rerun()
    _d()


def _dlg_rep(cid):
    @st.dialog("مندوب الشركة")
    def _d():
        reps = query_all("SELECT id, name FROM representatives WHERE status='active' ORDER BY name")
        cur = hub.current_rep(cid)
        if cur:
            st.info(f"المندوب الحالي: {cur['rep_name']} — {cur['percent']:g}% من {cur['start_date']}")
        k = f"hr{cid}_{_ver()}_"
        ids = [r["id"] for r in reps]
        names = {r["id"]: r["name"] for r in reps}
        add_rep = st.checkbox("إضافة مندوب جديد هنا", value=not bool(reps), key=k + "add_rep")
        if add_rep:
            rep_name = st.text_input("اسم المندوب الجديد *", key=k + "rep_name")
            rid = None
        else:
            rid = st.selectbox("المندوب", ids, format_func=names.get, key=k + "rep",
                               index=ids.index(cur["representative_id"]) if cur and cur["representative_id"] in ids else 0)
            rep_name = ""
        pct = number_field("النسبة % من صافي الشركة (ثابتة كل شهر)", k + "pct", value=cur["percent"] if cur else None,
                           minimum=0, maximum=100)
        start = _date_field("تاريخ بداية النسبة", k + "start")
        st.caption("لو غيّرت المندوب أو النسبة فالسابق ينتهي قبل التاريخ الجديد بيوم، وتبقى الأشهر الماضية بنسبتها.")
        if st.button("💾 حفظ", type="primary", key=k + "save", use_container_width=True):
            if pct is None:
                st.error("اكتب النسبة.")
                return
            try:
                if add_rep:
                    from modules import entities, representatives
                    rid, _ = entities.save_record(representatives.CFG, None, {"name": rep_name, "status": "active"})
                msg = hub.set_rep(cid, rid, pct, start)
            except ValueError as ex:
                st.error(str(ex))
                return
            _bump()
            flash_set(msg)
            st.rerun()
        if cur:
            st.divider()
            st.markdown("**إنهاء المندوب** (استقال أو توقف) دون تعيين غيره")
            end = _date_field("تاريخ الإنهاء", k + "end")
            reason = st.text_input("السبب", key=k + "reason")
            if st.button("إنهاء نسبة المندوب", key=k + "endbtn", use_container_width=True):
                try:
                    msg = hub.end_rep(cid, end, reason)
                except ValueError as ex:
                    st.error(str(ex))
                    return
                _bump()
                flash_set(msg)
                st.rerun()
    _d()


def _terms_inputs(k, cur):
    """Money inputs + live preview. Returns the terms dict."""
    cur = cur or {}
    a, b = st.columns(2)
    with a:
        basic = number_field("الراتب الأساسي * (يحوّله العميل للموظف)", k + "basic", value=cur.get("basic_salary"), minimum=0)
    with b:
        cost = number_field("التكلفة الفعلية * (المتفق عليها مع العميل)", k + "cost", value=cur.get("actual_cost"), minimum=0)
    refund_preview = hub.calc(basic, cost, 0, 0, 0)["refund"]
    st.caption(f"الاسترداد للعميل (الراتب − التكلفة) = **{refund_preview:,.2f}**")
    bonus = number_field("مكافأة الموظف (ما يأخذه)", k + "bonus", value=cur.get("bonus") or None, minimum=0)
    contractors = hub.contractors_of_kind("contractor")
    externals = hub.contractors_of_kind("external")
    c_ids = [None] + [r["id"] for r in contractors]
    c_names = {None: "— بدون —", **{r["id"]: r["name"] for r in contractors}}
    e_ids = [None] + [r["id"] for r in externals]
    e_names = {None: "— بدون —", **{r["id"]: r["name"] for r in externals}}
    a, b = st.columns(2)
    with a:
        add_con = st.checkbox("إضافة متعهد جديد هنا", key=k + "add_con")
        if add_con:
            con_name = st.text_input("اسم المتعهد الجديد *", key=k + "con_name")
            con = None
        else:
            cid_sel = cur.get("contractor_id") if cur.get("contractor_id") in c_ids else None
            con = st.selectbox("المتعهد", c_ids, index=c_ids.index(cid_sel), format_func=c_names.get, key=k + "con")
            con_name = ""
        con_c = number_field("عمولة المتعهد (شهرياً)", k + "conc", value=cur.get("contractor_commission") or None, minimum=0)
    with b:
        add_ext = st.checkbox("إضافة جهة عمولة جديدة هنا", key=k + "add_ext")
        if add_ext:
            ext_name = st.text_input("اسم جهة العمولة الجديدة *", key=k + "ext_name")
            ext = None
        else:
            eid_sel = cur.get("external_id") if cur.get("external_id") in e_ids else None
            ext = st.selectbox("جهة العمولة الخارجية", e_ids, index=e_ids.index(eid_sel), format_func=e_names.get, key=k + "ext")
            ext_name = ""
        ext_c = number_field("العمولة الخارجية (شهرياً)", k + "extc", value=cur.get("external_commission") or None, minimum=0)
    t = {"basic_salary": basic, "actual_cost": cost, "bonus": bonus, "contractor_id": con,
         "contractor_commission": con_c, "external_id": ext, "external_commission": ext_c,
         "_add_contractor": add_con, "_contractor_name": con_name,
         "_add_external": add_ext, "_external_name": ext_name}
    net = hub.calc(basic, cost, bonus, con_c, ext_c)["net"]
    m1, m2 = st.columns(2)
    m1.metric("الاسترداد", f"{refund_preview:,.2f}")
    m2.metric("الصافي (قبل المندوب)", f"{net:,.2f}")
    for w in hub.terms_warnings(t):
        st.warning(w)
    return t


def _dlg_employee(cid, pid=None):
    @st.dialog("تعديل موظف" if pid else "إضافة موظف", width="large")
    def _d():
        cur = hub.get_placement(pid) if pid else None
        k = f"he{pid or 'n'}_{_ver()}_"
        existing_id = None
        emp = {}
        if not pid:
            mode = st.radio("الموظف", ["موظف جديد", "موظف موجود (غير نشط حالياً)"], horizontal=True, key=k + "mode")
            if mode != "موظف جديد":
                avail = hub.available_employees()
                if not avail:
                    st.info("لا يوجد موظفون غير نشطين. اختر «موظف جديد».")
                else:
                    ids = [r["id"] for r in avail]
                    nm = {r["id"]: f"{r['full_name']} {r['phone'] or ''}".strip() for r in avail}
                    existing_id = st.selectbox("اختر الموظف", ids, format_func=nm.get, key=k + "exist")
        if not existing_id:
            st.markdown("**بيانات الموظف**")
            a, b = st.columns(2)
            with a:
                emp["full_name"] = st.text_input("الاسم الكامل *", value=(cur or {}).get("full_name") or "", key=k + "name")
                emp["phone"] = st.text_input("الجوال", value=(cur or {}).get("phone") or "", key=k + "phone")
            with b:
                emp["national_id"] = security.sensitive_input("رقم الهوية (حساس)", (cur or {}).get("national_id"), k + "nid")
                emp["iban"] = security.sensitive_input("الآيبان (حساس)", (cur or {}).get("iban"), k + "iban")
            emp["bank_name"] = (cur or {}).get("bank_name")
        st.markdown("**الأرقام المالية الشهرية**")
        terms = _terms_inputs(k, cur)
        st.markdown("**فترة العمل**")
        a, b = st.columns(2)
        with a:
            start = _date_field("تاريخ بداية العمل *", k + "start", _parse_date((cur or {}).get("start_date")))
        with b:
            status = st.selectbox("الحالة", ["active", "ended"], format_func=lambda x: "نشط" if x == "active" else "مستبعد",
                                  index=1 if (cur or {}).get("status") == "ended" else 0, key=k + "status")
        end = reason = None
        if status == "ended":
            a, b = st.columns(2)
            with a:
                end = _date_field("تاريخ الاستبعاد (آخر يوم عمل)", k + "end", _parse_date((cur or {}).get("end_date")))
            with b:
                reason = st.text_input("سبب الاستبعاد", value=(cur or {}).get("stop_reason") or "", key=k + "reason")
        notes = st.text_area("ملاحظات", value=(cur or {}).get("notes") or "", key=k + "notes")
        terms.update({"start_date": start, "status": status, "end_date": end, "stop_reason": reason, "notes": notes})
        if st.button("💾 حفظ", type="primary", key=k + "save", use_container_width=True):
            try:
                from modules import contractors as contractor_module, entities
                if terms.pop("_add_contractor"):
                    name = terms.pop("_contractor_name").strip()
                    if not name:
                        raise ValueError("اسم المتعهد مطلوب.")
                    terms["contractor_id"], _ = entities.save_record(
                        contractor_module.CFG, None, {"name": name, "kind": "contractor", "status": "active"})
                else:
                    terms.pop("_contractor_name")
                if terms.pop("_add_external"):
                    name = terms.pop("_external_name").strip()
                    if not name:
                        raise ValueError("اسم جهة العمولة الخارجية مطلوب.")
                    terms["external_id"], _ = entities.save_record(
                        contractor_module.CFG, None, {"name": name, "kind": "external", "status": "active"})
                else:
                    terms.pop("_external_name")
                if pid:
                    emp.setdefault("email", (cur or {}).get("email"))
                    msg = hub.update_employee(pid, emp, terms)
                else:
                    _, msg = hub.add_employee(cid, emp, terms, existing_id)
            except ValueError as ex:
                st.error(str(ex))
                return
            _bump()
            tbump("hub_emps")
            flash_set(msg)
            st.rerun()
    _d()


def _dlg_exclude(row):
    @st.dialog("استبعاد موظف")
    def _d():
        st.write(f"استبعاد **{row['full_name']}** من الشركة. يُحسب شهره الأخير بالأيام الفعلية، وتبقى أرقامه السابقة.")
        k = f"hx{row['id']}_{_ver()}_"
        end = _date_field("آخر يوم عمل", k + "end")
        reason = st.text_input("السبب", key=k + "reason")
        if st.button("تأكيد الاستبعاد", type="primary", key=k + "ok", use_container_width=True):
            try:
                msg = hub.exclude_employee(row["id"], end, reason)
            except ValueError as ex:
                st.error(str(ex))
                return
            _bump()
            tbump("hub_emps")
            flash_set(msg)
            st.rerun()
    _d()


def _dlg_delete_emp(row):
    @st.dialog("حذف موظف من الشركة")
    def _d():
        links = hub.placement_links(row["id"])
        if links:
            st.error("لا يمكن الحذف لأن له سجلات مالية: " + "، ".join(f"{k}: {v}" for k, v in links.items()))
            st.info("استخدم «استبعاد» ليبقى تاريخه.")
            return
        st.warning(f"سيُحذف «{row['full_name']}» من الشركة نهائياً. هذا ممكن لأنه لا توجد له أي سجلات مالية.")
        if st.button("🗑️ تأكيد الحذف", type="primary", key=f"hd_{row['id']}", use_container_width=True):
            try:
                msg = hub.delete_employee_placement(row["id"])
            except ValueError as ex:
                st.error(str(ex))
                return
            tbump("hub_emps")
            flash_set(msg)
            st.rerun()
    _d()


# ------------------------------------------------------------------ print sheet
def _dlg_print(cid):
    @st.dialog("طباعة بيانات الشركة", width="large")
    def _d():
        co = query_all("SELECT * FROM companies WHERE id=?", (cid,))[0]
        import branding
        logo = branding.logo_img_html(50)
        e = _html.escape
        rep = hub.current_rep(cid)
        ex = hub.company_expected(cid)
        rows = hub.company_employees(cid, "all")
        tr = "".join(
            f"<tr><td>{e(r['full_name'])}</td><td>{e(hub.STATUS_AR.get(r['status'], r['status']))}</td><td>{e(r['start_date'] or '')}</td>"
            f"<td>{e(r['end_date'] or '')}</td><td>{_fmt(r['basic_salary'])}</td><td>{_fmt(r['actual_cost'])}</td><td>{_fmt(r['refund'])}</td>"
            f"<td>{_fmt(r['bonus'])}</td><td>{e(r['contractor_name'] or '')}</td><td>{_fmt(r['contractor_commission'])}</td>"
            f"<td>{e(r['external_name'] or '')}</td><td>{_fmt(r['external_commission'])}</td><td>{_fmt(r['net'])}</td></tr>" for r in rows)
        doc = f"""<html dir="rtl"><head><meta charset="utf-8"><style>
body{{font-family:Tahoma,Arial,sans-serif;margin:16px;color:#111}} h2{{margin:0 0 8px}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}} th,td{{border:1px solid #888;padding:4px 6px;text-align:right}}
th{{background:#e8eef0}} .meta td{{border:none;padding:2px 8px}} .btn{{padding:8px 18px;font-size:14px;margin-bottom:10px;cursor:pointer}}
@media print{{.btn{{display:none}}}}</style></head><body>
<button class="btn" onclick="window.print()">🖨️ طباعة</button>
<div>{logo}</div><h2>{e(co['name'])}</h2>
<table class="meta"><tr><td>الرقم الضريبي: {e(co['tax_number'] or '—')}</td><td>السجل التجاري: {e(co['commercial_register'] or '—')}</td>
<td>الهاتف: {e(co['phone'] or '—')}</td><td>المسؤول: {e(co['contact_person'] or '—')}</td></tr>
<tr><td>بداية العمل: {e(co['work_start_date'] or '—')}</td><td>توقف الشركة: {e(co['work_end_date'] or '—')}</td>
<td colspan="2">المندوب: {e(rep['rep_name']) + ' (' + format(rep['percent'], 'g') + '%)' if rep else '—'}</td></tr></table>
<table><tr><th>الموظف</th><th>الحالة</th><th>من</th><th>إلى</th><th>الراتب الأساسي</th><th>التكلفة الفعلية</th><th>الاسترداد</th>
<th>المكافأة</th><th>المتعهد</th><th>عمولته</th><th>عمولة خارجية لـ</th><th>قيمتها</th><th>الصافي</th></tr>{tr}</table>
<table class="meta"><tr><td>الموظفون النشطون: {ex['employees']}</td><td>إيراد متوقع/شهر: {_fmt(ex['revenue'])}</td>
<td>صافي الشركة: {_fmt(ex['net'])}</td><td>المندوب: {_fmt(ex['rep_amount'])}</td><td>هامش الشركة المتوقع: {_fmt(ex['margin'])}</td></tr></table>
</body></html>"""
        components.html(doc, height=620, scrolling=True)
    _d()


@st.dialog("استيراد الموظفات من Excel", width="large")
def _dlg_import(cid=None):
    import hub_import as HI
    k = f"hi{cid or 0}_"
    if cid:
        st.markdown("**1) نزّل شيت موظفي هذه الشركة** (مملوء بالبيانات الحالية) وعدّله أو أضف صفوفاً — **2) ارفعه** وراجع المعاينة — **3) نفّذ**.")
        st.download_button("⬇️ تنزيل شيت الموظفين الحاليين", HI.template_bytes(cid), file_name="company_employees.xlsx", key=k + "cur",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.markdown("**1) نزّل القالب واملأه** — ثم **2) ارفع الملف** وراجع المعاينة — ثم **3) نفّذ الاستيراد**.")
    st.caption(f"الحد الأقصى {HI.MAX_IMPORT_ROWS} موظفاً في الملف الواحد.")
    st.download_button("⬇️ تنزيل قالب فارغ", HI.template_bytes(), file_name="employees_template.xlsx", key=k + "tpl",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    up = st.file_uploader("ملف Excel المعبأ", type=["xlsx"], key=k + "file")
    if up is None:
        st.caption("الموظف الموجود (نفس رقم الهوية أو الاسم داخل نفس الشركة) يُحدَّث ولا يتكرر.")
        return
    try:
        items = HI.plan(HI.read_sheet(up.getvalue()), cid)
    except ValueError as ex:
        st.error(str(ex))
        return
    lab = {"add": "➕ إضافة", "update": "✏️ تحديث", "error": "❌ خطأ"}
    preview = pd.DataFrame([{"المسلسل": serial, "صف Excel": i["row"], "الشركة": i["company"],
                             "الموظف": i["name"], "الإجراء": lab[i["action"]], "ملاحظة": i["error"]}
                            for serial, i in enumerate(items, start=1)])
    st.dataframe(preview, use_container_width=True, hide_index=True, height=400)
    good = [i for i in items if i["action"] != "error"]
    st.caption(f"{sum(1 for i in good if i['action']=='add')} إضافة، {sum(1 for i in good if i['action']=='update')} تحديث، "
               f"{len(items) - len(good)} صف به خطأ (يُتجاهل ويمكنك تصحيحه وإعادة رفع الملف).")
    if good and st.button("✅ تنفيذ الاستيراد", type="primary", key=k + "go"):
        res = HI.apply(items)
        msg = f"تم: {res['added']} إضافة و{res['updated']} تحديث."
        if res["failed"]:
            msg += f" تعذر {len(res['failed'])} صف."
        flash_set(msg)
        st.rerun()


# ------------------------------------------------------------------ list page
def _render_list(can):
    f1, f2, f3, f4 = st.columns([2.6, 1.3, 1.2, 1.3])
    with f4:
        if can and st.button("📥 استيراد Excel", key="hub_import", use_container_width=True):
            _dlg_import()
    with f1:
        q = st.text_input("بحث", key="hub_q", placeholder="🔍 ابحث باسم الشركة أو الرقم الضريبي أو الهاتف",
                          label_visibility="collapsed").strip().lower()
    with f2:
        flt = st.selectbox("الحالة", ["all", "active", "inactive"], key="hub_cflt", label_visibility="collapsed",
                           format_func={"all": "كل الشركات", "active": "النشطة", "inactive": "غير النشطة"}.get)
    with f3:
        if can and st.button("➕ شركة جديدة", type="primary", key="hub_new_co", use_container_width=True):
            _dlg_company(None)

    companies = query_all("SELECT * FROM companies ORDER BY (status='active') DESC, name")
    if flt != "all":
        companies = [c for c in companies if c["status"] == flt]
    if q:
        companies = [c for c in companies if q in " ".join(str(c[k] or "") for k in ("name", "tax_number", "phone", "contact_person")).lower()]
    if not companies:
        st.info("لا توجد شركات مطابقة." if q or flt != "all" else "لا توجد شركات بعد." + (" اضغط «شركة جديدة»." if can else ""))
        return

    W = [0.8, 2.0, 1.3, 1.5, 0.9, 1.1, 1.3, 1.2, 1.2, 3.0]    # first column = rightmost (RTL)
    heads = ["رقم الشركة", "الشركة", "الضريبي / الهاتف", "المندوب", "نشطون", "مستبعدون",
             "إيراد/شهر", "صافي الشركة", "هامش الشركة", ""]
    hc = st.columns(W)
    for c, h in zip(hc, heads):
        c.markdown(f"<span style='color:#667;font-size:0.85rem'>{h}</span>", unsafe_allow_html=True)
    tot = {"act": 0, "end": 0, "rev": 0.0, "net": 0.0, "mar": 0.0}
    for co in companies:
        ex = hub.company_expected(co["id"])
        n_end = len(hub.company_employees(co["id"], "ended"))
        tot["act"] += ex["employees"]; tot["end"] += n_end; tot["rev"] += ex["revenue"]; tot["net"] += ex["net"]; tot["mar"] += ex["margin"]
        with st.container(border=True):
            c = st.columns(W, vertical_alignment="center")
            label = co["name"] + ("" if co["status"] == "active" else "  (غير نشطة)")
            c[0].markdown(str(co["id"]))
            if c[1].button(label, key=f"hub_open_{co['id']}", help="فتح الشركة وموظفيها", type="tertiary"):
                st.session_state["hub_open"] = co["id"]
                st.rerun()
            c[2].markdown(f"{co['tax_number'] or '—'}<br><span style='color:#667'>{co['phone'] or ''}</span>", unsafe_allow_html=True)
            c[3].markdown(f"{ex['rep_name']} ({ex['rep_percent']:g}%)" if ex["rep_name"] else "—")
            c[4].markdown(f"**{ex['employees']}**")
            c[5].markdown(f"{n_end}")
            c[6].markdown(_fmt(ex["revenue"]))
            c[7].markdown(_fmt(ex["net"]))
            c[8].markdown(f"**{_fmt(ex['margin'])}**")
            b = c[9].columns(4)
            if b[0].button("📂", key=f"hub_o_{co['id']}", help="فتح"):
                st.session_state["hub_open"] = co["id"]
                st.rerun()
            if can and b[1].button("✏️", key=f"hub_e_{co['id']}", help="تعديل بيانات الشركة"):
                _dlg_company(co["id"])
            if can and b[2].button("🗑️", key=f"hub_d_{co['id']}", help="حذف"):
                _dlg_delete_company(co["id"], co["name"])
            if b[3].button("🖨️", key=f"hub_p_{co['id']}", help="طباعة"):
                _dlg_print(co["id"])
    st.caption(f"عدد الشركات: {len(companies)} — الموظفون النشطون: {tot['act']} — المستبعدون: {tot['end']} — "
               f"إيراد متوقع/شهر: {_fmt(tot['rev'])} — صافي: {_fmt(tot['net'])} — الهامش المتوقع: {_fmt(tot['mar'])}")
    st.caption("الأرقام «متوقعة» من الاتفاق لو حوّل العميل كاملاً. الأرقام الفعلية في «الحركات المالية».")


# ------------------------------------------------------------------ company page
def _render_company(cid, can):
    co = query_all("SELECT * FROM companies WHERE id=?", (cid,))[0]
    t1, t2 = st.columns([1, 5])
    if t1.button("↩️ كل الشركات", key="hub_back"):
        st.session_state["hub_open"] = None
        st.rerun()
    with st.container(border=True):
        h1, h2 = st.columns([4, 2.4])
        h1.markdown(f"### 🏢 {co['name']} — رقم الشركة: {co['id']}")
        with h2:
            e1, e2, e3 = st.columns(3)
            if can and e1.button("✏️ تعديل", key="hub_edit_co"):
                _dlg_company(cid)
            if can and e2.button("🗑️ حذف", key="hub_del_co"):
                _dlg_delete_company(cid, co["name"])
            if e3.button("🖨️ طباعة", key="hub_print_co"):
                _dlg_print(cid)
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**الرقم الضريبي:** {co['tax_number'] or '—'}")
        c1.markdown(f"**السجل التجاري:** {co['commercial_register'] or '—'}")
        c2.markdown(f"**الشخص المسؤول:** {co['contact_person'] or '—'}")
        c2.markdown(f"**الهاتف:** {co['phone'] or '—'}")
        c3.markdown(f"**بداية العمل:** {co['work_start_date'] or '—'}")
        c3.markdown(f"**توقف الشركة:** {co['work_end_date'] or '—'}  |  **الحالة:** {COMPANY_STATUS.get(co['status'], co['status'])}")
        if co["address"]:
            st.caption(f"العنوان: {co['address']}")

    with st.container(border=True):
        r1, r2 = st.columns([4, 1.6])
        rep = hub.current_rep(cid)
        if rep:
            r1.markdown(f"**🧑‍💼 المندوب:** {rep['rep_name']} — نسبته **{rep['percent']:g}%** من صافي الشركة شهرياً (من {rep['start_date']})")
        else:
            r1.markdown("**🧑‍💼 المندوب:** لا يوجد مندوب لهذه الشركة")
        if can and r2.button("تعيين / تغيير / إنهاء المندوب", key="hub_rep_btn"):
            _dlg_rep(cid)
        hist = [t for t in hub.rep_terms(cid) if t["end_date"]]
        if hist:
            with st.expander("المناديب السابقون"):
                st.dataframe(pd.DataFrame([{"المندوب": t["rep_name"], "النسبة %": t["percent"], "من": t["start_date"],
                                            "إلى": t["end_date"], "السبب": t["end_reason"] or ""} for t in hist]),
                             hide_index=True, use_container_width=True)

    st.markdown("#### 👥 موظفو الشركة")
    f1, f2, f3 = st.columns([1.5, 1.5, 1])
    with f1:
        flt = st.selectbox("عرض", ["all", "active", "ended"], key="hub_flt", label_visibility="collapsed",
                           format_func={"all": "كل الموظفين", "active": "النشطون فقط", "ended": "المستبعدون فقط"}.get)
    with f2:
        if can and st.button("📥 تنزيل / رفع شيت Excel", key="hub_emp_xl", use_container_width=True):
            _dlg_import(cid)
    with f3:
        if can and st.button("➕ إضافة موظف", type="primary", key="hub_add_emp", use_container_width=True):
            _dlg_employee(cid)
    rows = hub.company_employees(cid, flt)
    if not rows:
        st.info("لا يوجد موظفون في هذه الشركة بعد." + (" اضغط «إضافة موظف»." if can else ""))
    else:
        df = pd.DataFrame([{
            "رقم الموظف": r["employee_id"], "الموظف": r["full_name"], "الجوال": r["phone"] or "",
            "الحالة": hub.STATUS_AR.get(r["status"], r["status"]),
            "من": r["start_date"], "إلى": r["end_date"] or "",
            "الراتب الأساسي": r["basic_salary"], "التكلفة الفعلية": r["actual_cost"], "الاسترداد": r["refund"],
            "المكافأة": r["bonus"], "المتعهد": r["contractor_name"] or "", "عمولته": r["contractor_commission"],
            "عمولة خارجية لـ": r["external_name"] or "", "قيمتها": r["external_commission"], "الصافي": r["net"],
        } for r in rows])
        excel_button(df, f"موظفو_{co['name']}", "hub_xl")
        pos = select_table(df, "hub_emps")
        if pos is not None and pos < len(rows):
            row = rows[pos]
            st.markdown(f"**المحدد:** {row['full_name']}")
            if can:
                b1, b2, b3, _ = st.columns([1.2, 1.2, 1.2, 3])
                if b1.button("✏️ تعديل", key="hub_emp_edit"):
                    _dlg_employee(cid, row["id"])
                if row["status"] == "active" and b2.button("⛔ استبعاد", key="hub_emp_excl"):
                    _dlg_exclude(row)
                if b3.button("🗑️ حذف", key="hub_emp_del"):
                    _dlg_delete_emp(row)
            if row["net"] is None:
                st.warning("هذا الموظف بلا أرقام مالية (تعيين قديم). افتح «تعديل» وأدخل الراتب والتكلفة.")
        elif can:
            st.caption("💡 اضغط مربع الاختيار أول أي صف لتعديل الموظف أو استبعاده أو حذفه.")

    ex = hub.company_expected(cid)
    st.markdown("#### 📊 المتوقع شهرياً لو حوّل العميل كاملاً (الموظفون النشطون)")
    m = st.columns(4)
    m[0].metric("الموظفون النشطون", ex["employees"])
    m[1].metric("إيراد الشركة (التكلفة)", f"{ex['revenue']:,.2f}")
    m[2].metric("المردود للعميل", f"{ex['refund']:,.2f}")
    m[3].metric("مكافآت الموظفين", f"{ex['bonus']:,.2f}")
    m = st.columns(4)
    m[0].metric("عمولات المتعهدين", f"{ex['contractors']:,.2f}")
    m[1].metric("العمولات الخارجية", f"{ex['external']:,.2f}")
    m[2].metric("صافي الشركة", f"{ex['net']:,.2f}")
    m[3].metric(f"المندوب ({ex['rep_percent']:g}%)", f"{ex['rep_amount']:,.2f}")
    st.metric("هامش الشركة المتوقع (الربح)", f"{ex['margin']:,.2f}")
    st.caption("هذه أرقام متوقعة لو حوّل العميل كاملاً. الأرقام الفعلية في «الحركات المالية».")


def render():
    show_flash()
    can = security.can_write()
    if "_hub_select" in st.session_state:
        st.session_state["hub_open"] = st.session_state.pop("_hub_select")
    cid = st.session_state.get("hub_open")
    if cid and not query_all("SELECT 1 FROM companies WHERE id=?", (cid,)):
        cid = st.session_state["hub_open"] = None
    if cid:
        _render_company(cid, can)
    else:
        _render_list(can)
