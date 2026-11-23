import streamlit as st
import pandas as pd
from datetime import date, datetime
from db import query_all, query_one, execute
from audit import log_audit
import security
from ui import toast_flash, select_table, tbump, excel_button, number_field, row_action_bar
from modules import entities, employees as _emp_page, companies as _co_page

STATUS_AR = {"active": "نشط", "ended": "منتهٍ", "suspended": "موقوف"}
COMM_AR = {"fixed": "مبلغ ثابت شهري", "percentage": "نسبة مئوية"}
KINDS = {
    "contractor": {"table": "placement_contractors", "party_tbl": "contractors", "col": "contractor_id", "ar": "المتعهد", "key": "ct"},
    "representative": {"table": "placement_representatives", "party_tbl": "representatives", "col": "representative_id", "ar": "المندوب", "key": "rp"},
}


def _iso(d) -> str:
    return d.strftime("%Y-%m-%d")


def _to_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _flash(msg: str):
    st.session_state["_pl_flash"] = msg
    st.rerun()


# ============================================================ business logic
FLOW_AR = {"direct": "العميل يحوّل المبلغ للموظف مباشرة، والموظف يعيد الباقي للشركة",
           "via_company": "العميل يدفع للشركة، والشركة تدفع للموظف"}


def add_placement(eid, cid, start, notes=None, flow="direct") -> int:
    if query_one("SELECT id FROM employee_placements WHERE employee_id=? AND status='active' AND end_date IS NULL", (eid,)):
        open_p = query_one("SELECT id FROM employee_placements WHERE employee_id=? AND status='active' AND end_date IS NULL", (eid,))
        raise ValueError(f"لهذا الموظف تعيين نشط مفتوح (#{open_p['id']}). أنهِ ذلك التعيين أولاً بتاريخ الانتهاء، ثم أضف التعيين الجديد.")
    if flow not in FLOW_AR:
        raise ValueError("دورة المبلغ غير صحيحة.")
    pid = execute("INSERT INTO employee_placements(employee_id, company_id, start_date, status, notes, flow_mode) VALUES (?,?,?,?,?,?)",
                  (eid, cid, _iso(start), "active", (notes or "").strip() or None, flow))
    log_audit("employee_placements", pid, "INSERT", None,
              {"employee_id": eid, "company_id": cid, "start_date": _iso(start), "flow_mode": flow}, note="إضافة تعيين")
    return pid


def end_placement(pid, new_status, end_d, reason=None) -> str:
    p = query_one("SELECT * FROM employee_placements WHERE id=?", (pid,))
    if not p:
        raise ValueError("التعيين غير موجود.")
    if new_status not in ("ended", "suspended"):
        raise ValueError("الإجراء غير صحيح.")
    if p["status"] == "ended":
        raise ValueError("هذا التعيين منتهٍ ومغلق.")
    if _iso(end_d) < p["start_date"]:
        raise ValueError("تاريخ الانتهاء لا يمكن أن يسبق تاريخ بداية التعيين.")
    reason = (reason or "").strip() or None
    execute("""UPDATE employee_placements SET status=?, end_date=?, stop_reason=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (new_status, _iso(end_d), reason, pid))
    log_audit("employee_placements", pid, "STATUS_CHANGE", {"status": p["status"], "end_date": p["end_date"]},
              {"status": new_status, "end_date": _iso(end_d), "stop_reason": reason}, note="إنهاء/إيقاف تعيين")
    return f"تم اعتماد التعيين رقم {pid} بحالة «{STATUS_AR[new_status]}» بتاريخ {_iso(end_d)}."


def placement_has_accounts(pid) -> bool:
    try:
        return bool(query_one("SELECT 1 FROM monthly_employee_accounts WHERE placement_id=? LIMIT 1", (pid,)))
    except Exception:  # noqa: BLE001
        return False


def update_placement(pid, start, notes, flow=None) -> str:
    p = query_one("SELECT * FROM employee_placements WHERE id=?", (pid,))
    if not p:
        raise ValueError("التعيين غير موجود.")
    new_start = _iso(start)
    if new_start != p["start_date"]:
        if placement_has_accounts(pid):
            raise ValueError("لا يمكن تغيير تاريخ بداية تعيين له حسابات شهرية محتسبة، لأن ذلك يغيّر نتائج أشهر سابقة.")
        if p["end_date"] and p["end_date"] < new_start:
            raise ValueError("تاريخ البداية لا يمكن أن يتجاوز تاريخ الانتهاء.")
    notes = (notes or "").strip() or None
    flow = flow or p["flow_mode"]
    if flow not in FLOW_AR:
        raise ValueError("دورة المبلغ غير صحيحة.")
    execute("UPDATE employee_placements SET start_date=?, notes=?, flow_mode=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_start, notes, flow, pid))
    log_audit("employee_placements", pid, "UPDATE", {"start_date": p["start_date"], "notes": p["notes"], "flow_mode": p["flow_mode"]},
              {"start_date": new_start, "notes": notes, "flow_mode": flow}, note="تعديل تعيين")
    return f"تم تحديث التعيين رقم {pid}."


def add_agreement(kind, placement_id, party_id, start, ctype, val, notes=None):
    """Returns (agreement_id, warning_or_None)."""
    k = KINDS[kind]
    p = query_one("SELECT * FROM employee_placements WHERE id=?", (placement_id,))
    if not p:
        raise ValueError("التعيين غير موجود.")
    if ctype not in COMM_AR:
        raise ValueError("نوع العمولة غير صحيح.")
    if not val or float(val) <= 0:
        raise ValueError("أدخل قيمة عمولة أكبر من صفر.")
    if ctype == "percentage" and float(val) > 100:
        raise ValueError("النسبة المئوية لا يمكن أن تتجاوز 100.")
    dup = query_one(f"SELECT id FROM {k['table']} WHERE placement_id=? AND {k['col']}=? AND status='active' AND agreement_end IS NULL",
                    (placement_id, party_id))
    if dup:
        raise ValueError(f"يوجد اتفاق نشط مفتوح لنفس {k['ar']} على هذا التعيين (#{dup['id']}). "
                         "أنهِه أولاً بتاريخ الانتهاء، ثم أضف الاتفاق الجديد (مثلاً عند تغيير قيمة العمولة).")
    notes = (notes or "").strip() or None
    warn = None
    if kind == "representative":
        rel = query_one("""SELECT id FROM company_representatives
                           WHERE company_id=? AND representative_id=? AND status='active' AND relationship_end IS NULL
                           ORDER BY id DESC""", (p["company_id"], party_id))
        if not rel:
            warn = ("لا توجد علاقة نشطة بين هذا المندوب وهذه الشركة، فسُجّل الاتفاق بدون ربط. "
                    "أضف العلاقة من تبويب «علاقات المندوبين بالشركات» حتى تتوقف العمولة تلقائياً عند انتهائها.")
        aid = execute("""INSERT INTO placement_representatives(placement_id, representative_id, company_representative_id,
                             agreement_start, commission_type, commission_value, status, notes) VALUES (?,?,?,?,?,?,?,?)""",
                      (placement_id, party_id, rel["id"] if rel else None, _iso(start), ctype, float(val), "active", notes))
    else:
        aid = execute("""INSERT INTO placement_contractors(placement_id, contractor_id, agreement_start,
                             commission_type, commission_value, status, notes) VALUES (?,?,?,?,?,?,?)""",
                      (placement_id, party_id, _iso(start), ctype, float(val), "active", notes))
    log_audit(k["table"], aid, "INSERT", None, {"placement_id": placement_id, k["col"]: party_id, "start": _iso(start),
                                                "type": ctype, "value": float(val)}, note=f"إضافة اتفاق {k['ar']}")
    return aid, warn


def end_agreement(kind, aid, end_d) -> str:
    k = KINDS[kind]
    a = query_one(f"SELECT * FROM {k['table']} WHERE id=?", (aid,))
    if not a:
        raise ValueError("الاتفاق غير موجود.")
    if a["status"] != "active":
        raise ValueError("هذا الاتفاق منتهٍ بالفعل.")
    if _iso(end_d) < a["agreement_start"]:
        raise ValueError("تاريخ الانتهاء لا يمكن أن يسبق تاريخ بداية الاتفاق.")
    execute(f"UPDATE {k['table']} SET status='ended', agreement_end=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (_iso(end_d), aid))
    log_audit(k["table"], aid, "STATUS_CHANGE", {"status": "active", "agreement_end": None},
              {"status": "ended", "agreement_end": _iso(end_d)}, note=f"إنهاء اتفاق {k['ar']}")
    return f"تم إنهاء الاتفاق رقم {aid} بتاريخ {_iso(end_d)}."


def add_relation(cid, rid, start) -> int:
    dup = query_one("""SELECT id FROM company_representatives
                       WHERE company_id=? AND representative_id=? AND status='active' AND relationship_end IS NULL""", (cid, rid))
    if dup:
        raise ValueError(f"توجد علاقة نشطة مفتوحة بين نفس المندوب والشركة (#{dup['id']}).")
    nid = execute("INSERT INTO company_representatives(company_id, representative_id, relationship_start, status) VALUES (?,?,?,'active')",
                  (cid, rid, _iso(start)))
    log_audit("company_representatives", nid, "INSERT", None,
              {"company_id": cid, "representative_id": rid, "start": _iso(start)}, note="إضافة علاقة مندوب بشركة")
    return nid


def end_relation(rid, end_d) -> str:
    r = query_one("SELECT * FROM company_representatives WHERE id=?", (rid,))
    if not r:
        raise ValueError("العلاقة غير موجودة.")
    if r["status"] != "active":
        raise ValueError("هذه العلاقة منتهية بالفعل.")
    if _iso(end_d) < r["relationship_start"]:
        raise ValueError("تاريخ الانتهاء لا يمكن أن يسبق تاريخ البداية.")
    execute("UPDATE company_representatives SET status='ended', relationship_end=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (_iso(end_d), rid))
    log_audit("company_representatives", rid, "STATUS_CHANGE", {"status": "active"},
              {"status": "ended", "relationship_end": _iso(end_d)}, note="إنهاء علاقة مندوب بشركة")
    return f"تم إنهاء العلاقة رقم {rid}."


# ================================================================ queries
def _placements(search="", status="all"):
    rows = query_all("""SELECT p.id, p.employee_id, p.company_id, e.full_name, c.name AS company,
                               p.start_date, p.end_date, p.status, p.stop_reason, p.notes, p.flow_mode
                        FROM employee_placements p JOIN employees e ON e.id=p.employee_id JOIN companies c ON c.id=p.company_id
                        ORDER BY p.id DESC""")
    return [r for r in rows if (not search or search in r["full_name"] or search in r["company"])
            and (status == "all" or r["status"] == status)]


def _placement_label(r):
    end = f" → {r['end_date']}" if r.get("end_date") else ""
    return f"#{r['id']} | {r['full_name']} @ {r['company']} ({r['start_date']}{end}) [{STATUS_AR.get(r['status'], r['status'])}]"


def _agreements(kind, search="", status="all"):
    k = KINDS[kind]
    extra = ", (a.company_representative_id IS NOT NULL) AS linked" if kind == "representative" else ""
    rows = query_all(f"""SELECT a.*, x.name AS party_name, e.full_name, c.name AS company {extra}
                         FROM {k['table']} a JOIN {k['party_tbl']} x ON x.id=a.{k['col']}
                         JOIN employee_placements p ON p.id=a.placement_id
                         JOIN employees e ON e.id=p.employee_id JOIN companies c ON c.id=p.company_id
                         ORDER BY a.id DESC""")
    return [r for r in rows if (not search or search in r["party_name"] or search in r["full_name"] or search in r["company"])
            and (status == "all" or r["status"] == status)]


# ============================================================== dialogs
def _err(ex):
    st.error(str(ex))


@st.dialog("تعيين جديد (ربط موظف بشركة عميلة)")
def _dlg_add_placement():
    emps = {f"#{r['id']} - {r['full_name']}": r["id"] for r in query_all("SELECT id, full_name FROM employees WHERE status!='inactive' ORDER BY full_name")}
    comps = {f"#{r['id']} - {r['name']}": r["id"] for r in query_all("SELECT id, name FROM companies WHERE status='active' ORDER BY name")}
    if not emps or not comps:
        st.warning("يلزم وجود موظف وشركة عميلة نشطة على الأقل. أضفهما بزري «➕ موظف» و«➕ شركة» في أعلى الصفحة.")
        return
    pre_e, pre_c = st.session_state.get("_pl_pre_emp"), st.session_state.get("_pl_pre_comp")
    ie = next((i for i, v in enumerate(emps.values()) if v == pre_e), 0)
    ic = next((i for i, v in enumerate(comps.values()) if v == pre_c), 0)
    with st.form("pl_add_form"):
        el = st.selectbox("الموظف", list(emps.keys()), index=ie, key="pl_add_emp")
        cl = st.selectbox("الشركة العميلة", list(comps.keys()), index=ic, key="pl_add_comp")
        start = st.date_input("تاريخ بداية العمل", value=date.today(), key="pl_add_start")
        flow = st.selectbox("دورة المبلغ", list(FLOW_AR), format_func=FLOW_AR.get, key="pl_add_flow",
                            help="تحدد كيف تظهر أرصدة العميل والموظف: هل حوّل العميل للموظف مباشرة أم دفع للشركة.")
        notes = st.text_area("ملاحظات", key="pl_add_notes")
        sub = st.form_submit_button("حفظ التعيين", type="primary", use_container_width=True)
    if sub:
        try:
            pid = add_placement(emps[el], comps[cl], start, notes, flow)
        except ValueError as ex:
            return _err(ex)
        st.session_state.pop("_pl_pre_emp", None); st.session_state.pop("_pl_pre_comp", None)
        tbump("pl"); _flash(f"تم حفظ التعيين رقم {pid}.")


@st.dialog("إنهاء / إيقاف تعيين")
def _dlg_end_placement(p):
    st.markdown(f"**{p['full_name']}** @ {p['company']} — بدأ في {p['start_date']}")
    st.caption("لا يُحذف أي تعيين. يُسجَّل تاريخ الانتهاء المعتمد وتتوقف الحسابات والعمولات من هذا التاريخ. "
               "للعودة بعد إيقاف مؤقت: أضف تعييناً جديداً بتاريخ العودة.")
    with st.form("pl_end_form"):
        status = st.selectbox("الإجراء", ["ended", "suspended"], format_func=lambda x: "إنهاء نهائي" if x == "ended" else "إيقاف",
                              key="pl_end_status")
        end_d = st.date_input("تاريخ الانتهاء/الإيقاف المعتمد (آخر يوم عمل)", value=date.today(), key="pl_end_date")
        reason = st.text_input("سبب الإيقاف", key="pl_end_reason")
        sub = st.form_submit_button("اعتماد", type="primary", use_container_width=True)
    if sub:
        try:
            msg = end_placement(p["id"], status, end_d, reason)
        except ValueError as ex:
            return _err(ex)
        tbump("pl"); _flash(msg)


@st.dialog("تعديل تعيين")
def _dlg_edit_placement(p):
    st.markdown(f"**{p['full_name']}** @ {p['company']}")
    locked = placement_has_accounts(p["id"])
    if locked:
        st.info("لهذا التعيين حسابات شهرية محتسبة، لذلك تاريخ البداية مقفل. يمكن تعديل الملاحظات فقط.")
    with st.form("pl_edit_form"):
        start = st.date_input("تاريخ بداية العمل", value=_to_date(p["start_date"]), disabled=locked, key="pl_edit_start")
        fl = list(FLOW_AR)
        flow = st.selectbox("دورة المبلغ", fl, format_func=FLOW_AR.get, index=fl.index(p.get("flow_mode") or "direct"), key="pl_edit_flow",
                            help="التغيير يسري على الأشهر المفتوحة فقط؛ الأشهر المعتمدة تبقى كما هي.")
        notes = st.text_area("ملاحظات", value=p.get("notes") or "", key="pl_edit_notes")
        sub = st.form_submit_button("حفظ", type="primary", use_container_width=True)
    if sub:
        try:
            msg = update_placement(p["id"], _to_date(p["start_date"]) if locked else start, notes, flow)
        except ValueError as ex:
            return _err(ex)
        tbump("pl"); _flash(msg)


def _agreement_dialog(kind):
    k = KINDS[kind]

    @st.dialog(f"اتفاق {k['ar']} جديد")
    def _dlg():
        pls = {_placement_label(r): r for r in _placements() if r["status"] != "ended"}
        parties = {f"#{r['id']} - {r['name']}": r["id"] for r in query_all(f"SELECT id, name FROM {k['party_tbl']} WHERE status='active' ORDER BY name")}
        if not pls:
            st.warning("أضف تعييناً نشطاً أولاً.")
            return
        if not parties:
            st.warning(f"لا يوجد {k['ar']} نشط. أضفه من صفحته أولاً.")
            return
        with st.form(f"{k['key']}_add_form"):
            pl = st.selectbox("التعيين (الموظف / الشركة)", list(pls.keys()), key=f"{k['key']}_add_pl")
            party = st.selectbox(k["ar"], list(parties.keys()), key=f"{k['key']}_add_party")
            start = st.date_input("تاريخ بداية الاتفاق", value=date.today(), key=f"{k['key']}_add_start")
            ctype = st.selectbox("نوع العمولة الشهرية", list(COMM_AR.keys()), format_func=lambda x: COMM_AR[x], key=f"{k['key']}_add_type")
            val = number_field("القيمة (ريال إذا ثابت، أو نسبة % إذا نسبة)", f"{k['key']}_add_val", minimum=0)
            notes = st.text_input("ملاحظات", key=f"{k['key']}_add_notes")
            sub = st.form_submit_button("حفظ الاتفاق", type="primary", use_container_width=True)
        if sub:
            try:
                aid, warn = add_agreement(kind, pls[pl]["id"], parties[party], start, ctype, val, notes)
            except ValueError as ex:
                return _err(ex)
            tbump(k["key"])
            _flash(f"تم حفظ الاتفاق رقم {aid}." + (f" تنبيه: {warn}" if warn else ""))
    return _dlg


def _end_agreement_dialog(kind, a):
    k = KINDS[kind]

    @st.dialog(f"إنهاء اتفاق {k['ar']}")
    def _dlg():
        st.markdown(f"**{a['party_name']}** — {a['full_name']} @ {a['company']}")
        st.caption("لا يُحذف الاتفاق. يُسجَّل تاريخ الانتهاء ويبقى في السجل وتتوقف المستحقات الجديدة بعده.")
        with st.form(f"{k['key']}_end_form"):
            end_d = st.date_input("تاريخ انتهاء الاتفاق (آخر يوم استحقاق)", value=date.today(), key=f"{k['key']}_end_date")
            sub = st.form_submit_button("اعتماد الإنهاء", type="primary", use_container_width=True)
        if sub:
            try:
                msg = end_agreement(kind, a["id"], end_d)
            except ValueError as ex:
                return _err(ex)
            tbump(k["key"]); _flash(msg)
    return _dlg


@st.dialog("علاقة مندوب بشركة")
def _dlg_add_relation():
    comps = {f"#{r['id']} - {r['name']}": r["id"] for r in query_all("SELECT id, name FROM companies ORDER BY name")}
    reps = {f"#{r['id']} - {r['name']}": r["id"] for r in query_all("SELECT id, name FROM representatives WHERE status='active' ORDER BY name")}
    if not comps or not reps:
        st.warning("يلزم وجود شركة ومندوب نشط على الأقل.")
        return
    with st.form("cr_add_form"):
        cl = st.selectbox("الشركة", list(comps.keys()), key="cr_add_comp")
        rl = st.selectbox("المندوب", list(reps.keys()), key="cr_add_rep")
        start = st.date_input("بداية العلاقة", value=date.today(), key="cr_add_start")
        sub = st.form_submit_button("حفظ العلاقة", type="primary", use_container_width=True)
    if sub:
        try:
            nid = add_relation(comps[cl], reps[rl], start)
        except ValueError as ex:
            return _err(ex)
        tbump("cr"); _flash(f"تم حفظ العلاقة رقم {nid}.")


@st.dialog("إنهاء علاقة")
def _dlg_end_relation(r):
    st.markdown(f"**{r['rep']}** ← {r['company']} — من {r['relationship_start']}")
    with st.form("cr_end_form"):
        end_d = st.date_input("تاريخ انتهاء العلاقة", value=date.today(), key="cr_end_date")
        sub = st.form_submit_button("اعتماد الإنهاء", type="primary", use_container_width=True)
    if sub:
        try:
            msg = end_relation(r["id"], end_d)
        except ValueError as ex:
            return _err(ex)
        tbump("cr"); _flash(msg)


# ============================================================ tab views
def _statuses():
    return ["all"] + list(STATUS_AR.keys())


def _tab_placements():
    can = security.can_write()
    c1, c2, c3, c4, c5 = st.columns([3, 1.3, 1.3, 1.1, 1.1])
    with c1:
        search = st.text_input("بحث", placeholder="🔍 اسم الموظف أو الشركة", key="pl_search", label_visibility="collapsed")
    with c2:
        sf = st.selectbox("الحالة", _statuses(), format_func=lambda x: "كل الحالات" if x == "all" else STATUS_AR[x],
                          key="pl_status_filter", label_visibility="collapsed")
    with c3:
        if can and st.button("➕ تعيين جديد", key="pl_new", type="primary", use_container_width=True):
            _dlg_add_placement()
    with c4:
        if can and st.button("➕ موظف", key="pl_q_emp", use_container_width=True):
            entities.add_dialog(_emp_page.CFG, quick=True, on_saved=lambda rid: st.session_state.update(_pl_pre_emp=rid))
    with c5:
        if can and st.button("➕ شركة", key="pl_q_comp", use_container_width=True):
            entities.add_dialog(_co_page.CFG, quick=True, on_saved=lambda rid: st.session_state.update(_pl_pre_comp=rid))
    rows = _placements(search, sf)
    if not rows:
        st.info("لا توجد تعيينات. اضغط «➕ تعيين جديد» لإنشاء أول تعيين.")
        return
    df = pd.DataFrame(rows)[["id", "full_name", "company", "start_date", "end_date", "status", "flow_mode", "stop_reason"]]
    df["status"] = df["status"].map(STATUS_AR)
    df["flow_mode"] = df["flow_mode"].map(lambda x: "مباشرة للموظف" if x == "direct" else "عبر الشركة")
    df.columns = ["الرقم", "الموظف", "الشركة العميلة", "بداية التعيين", "نهاية/إيقاف", "الحالة", "دورة المبلغ", "سبب الإيقاف"]
    excel_button(df, "placements", "pl_xl")
    sel = select_table(df, "pl")
    if sel is None:
        st.caption(f"عدد التعيينات: {len(rows)} — 💡 اضغط مربع الاختيار أول أي صف لإنهائه أو تعديله.")
        return
    p = rows[sel]
    with st.container(border=True):
        st.markdown(f"**المحدد:** {p['full_name']} @ {p['company']} — {STATUS_AR[p['status']]}")
        actions = row_action_bar(edit=can, delete=can and p["status"] != "ended", view=True,
                                prefix=f"pl_row_{p['id']}")
        if actions["edit"]:
            _dlg_edit_placement(p)
        if actions["delete"]:
            _dlg_end_placement(p)
        if actions["view"]:
            st.info(f"التعيين #{p['id']} — بداية: {p['start_date']} — الحالة: {STATUS_AR[p['status']]}")


def _tab_agreements(kind):
    k = KINDS[kind]
    can = security.can_write()
    c1, c2, c3 = st.columns([4, 1.4, 1.6])
    with c1:
        search = st.text_input("بحث", placeholder=f"🔍 {k['ar']} أو الموظف أو الشركة", key=f"{k['key']}_search", label_visibility="collapsed")
    with c2:
        sf = st.selectbox("الحالة", ["all", "active", "ended"], format_func=lambda x: {"all": "كل الحالات", "active": "نشط", "ended": "منتهٍ"}[x],
                          key=f"{k['key']}_sf", label_visibility="collapsed")
    with c3:
        if can and st.button("➕ اتفاق جديد", key=f"{k['key']}_new", type="primary", use_container_width=True):
            _agreement_dialog(kind)()
    rows = _agreements(kind, search, sf)
    if not rows:
        st.info("لا توجد اتفاقات. اضغط «➕ اتفاق جديد» لإضافة أول اتفاق.")
        return
    df = pd.DataFrame(rows)
    df["type_ar"] = df["commission_type"].map(COMM_AR)
    df["status_ar"] = df["status"].map(STATUS_AR)
    cols = ["id", "party_name", "full_name", "company", "agreement_start", "agreement_end", "type_ar", "commission_value", "status_ar"]
    names = ["الرقم", k["ar"], "الموظف", "الشركة", "بداية الاتفاق", "نهاية الاتفاق", "نوع العمولة", "القيمة (ر.س أو %)", "الحالة"]
    if kind == "representative":
        df["linked_ar"] = df["linked"].map({1: "نعم", 0: "لا"})
        cols.append("linked_ar"); names.append("مرتبط بعلاقة الشركة")
    out = df[cols]
    out.columns = names
    excel_button(out, f"agreements_{k['key']}", f"ag_xl_{k['key']}")
    sel = select_table(out, k["key"])
    if sel is None:
        st.caption(f"عدد الاتفاقات: {len(rows)} — 💡 اضغط مربع الاختيار أول أي صف لإنهاء الاتفاق.")
        return
    a = rows[sel]
    with st.container(border=True):
        st.markdown(f"**المحدد:** اتفاق #{a['id']} — {a['party_name']} على {a['full_name']} ({STATUS_AR[a['status']]})")
        if can and a["status"] == "active" and st.button("⏹ إنهاء الاتفاق", key=f"{k['key']}_act_end"):
            _end_agreement_dialog(kind, a)()


def _tab_company_reps():
    can = security.can_write()
    st.caption("هذه العلاقة تسجّل أي مندوب جلب أي شركة ومتى. عند انتهائها تتوقف مستحقات المندوب الجديدة عن موظفي تلك الشركة.")
    if can and st.button("➕ علاقة جديدة", key="cr_new", type="primary"):
        _dlg_add_relation()
    rels = query_all("""SELECT r.id, c.name AS company, x.name AS rep, r.relationship_start, r.relationship_end, r.status
                        FROM company_representatives r JOIN companies c ON c.id=r.company_id JOIN representatives x ON x.id=r.representative_id
                        ORDER BY r.id DESC""")
    if not rels:
        st.info("لا توجد علاقات مسجلة.")
        return
    df = pd.DataFrame(rels)
    df["status"] = df["status"].map(STATUS_AR)
    df.columns = ["الرقم", "الشركة", "المندوب", "بداية العلاقة", "نهاية العلاقة", "الحالة"]
    sel = select_table(df, "cr")
    if sel is not None and can and rels[sel]["status"] == "active":
        with st.container(border=True):
            st.markdown(f"**المحدد:** {rels[sel]['rep']} ← {rels[sel]['company']}")
            if st.button("⏹ إنهاء العلاقة", key="cr_act_end"):
                _dlg_end_relation(rels[sel])
    else:
        st.caption("💡 اضغط مربع الاختيار أول صف لإنهاء علاقة نشطة.")


def render():
    toast_flash("_pl_flash")
    t1, t2, t3, t4 = st.tabs(["التعيينات", "اتفاقات المتعهدين", "اتفاقات المندوبين", "علاقات المندوبين بالشركات"])
    with t1:
        _tab_placements()
    with t2:
        _tab_agreements("contractor")
    with t3:
        _tab_agreements("representative")
    with t4:
        _tab_company_reps()
