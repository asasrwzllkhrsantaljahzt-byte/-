"""Generic list + add-dialog + click-to-edit page used by companies, employees, contractors and representatives."""
import sqlite3
import streamlit as st
import pandas as pd
import security
from db import query_all, query_one, execute
from audit import log_audit
from ui import flash_set, show_flash, friendly_error, duplicate_of, excel_button, row_action_bar

STATUS_AR = {"active": "نشط", "inactive": "غير نشط", "suspended": "موقوف"}


def _clean(v):
    return (v or "").strip() or None


# ------------------------------------------------------------------ data layer
def load_rows(cfg, search="", status="all"):
    sql = cfg["list_sql"] + " WHERE 1=1"
    params = []
    if search.strip():
        sql += " AND (" + " OR ".join(f"t.{c} LIKE ?" for c in cfg["search"]) + ")"
        params += [f"%{search.strip()}%"] * len(cfg["search"])
    if status != "all":
        sql += " AND t.status=?"
        params.append(status)
    return query_all(sql + " ORDER BY t.id DESC", tuple(params))


def save_record(cfg, rid, values):
    """Insert or update. Returns (id, Arabic success message). Raises ValueError with an Arabic message."""
    table, name_f = cfg["table"], cfg["name_field"]
    names = [f["name"] for f in cfg["fields"]]
    payload = {n: _clean(values.get(n)) for n in names}
    payload["status"] = values.get("status") or "active"
    if payload["status"] not in cfg["statuses"]:
        raise ValueError("الحالة غير صحيحة.")
    if not payload.get(name_f):
        raise ValueError(f"{cfg['name_label']} مطلوب.")
    existing = query_one(f"SELECT * FROM {table} WHERE id=?", (rid,)) if rid else None
    if rid and not existing:
        raise ValueError("السجل غير موجود.")
    payload = security.keep_sensitive(payload, existing)
    if not rid and cfg.get("dup_check"):
        dup = duplicate_of(table, payload[name_f], payload.get("phone"), name_col=name_f)
        if dup:
            raise ValueError(f"يوجد سجل بالاسم والهاتف نفسيهما (رقم {dup}). لا حاجة لإضافته مرة أخرى.")
    cols = list(payload.keys())
    try:
        if rid:
            execute(f"UPDATE {table} SET " + ", ".join(f"{c}=?" for c in cols) +
                    ", updated_at=CURRENT_TIMESTAMP WHERE id=?", tuple(payload[c] for c in cols) + (rid,))
            log_audit(table, rid, "UPDATE", existing, payload, note=f"تحديث بيانات {cfg['singular']}")
            return rid, f"تم تحديث بيانات {cfg['singular']}: {payload[name_f]}"
        new_id = execute(f"INSERT INTO {table}(" + ", ".join(cols) + ") VALUES (" + ",".join("?" * len(cols)) + ")",
                         tuple(payload[c] for c in cols))
        log_audit(table, new_id, "INSERT", None, payload, note=f"إضافة {cfg['singular']}")
        return new_id, f"تمت إضافة {cfg['singular']}: {payload[name_f]}"
    except sqlite3.IntegrityError as ex:
        raise ValueError(friendly_error(ex)) from ex


PARTY_OF = {"emp": "employee", "co": "company", "con": "contractor", "rep": "representative"}
_FK = {"employee": "employee_id", "company": "company_id", "contractor": "contractor_id", "representative": "representative_id"}


def link_counts(ptype, pid) -> dict:
    """How many records of each kind refer to this party (used to decide whether it can be deleted)."""
    def n(sql, *a):
        try:
            return query_one(sql, a)["c"]
        except sqlite3.Error:
            return 0
    out = {}
    if ptype == "employee":
        out["تعيينات"] = n("SELECT COUNT(*) c FROM employee_placements WHERE employee_id=?", pid)
    elif ptype == "company":
        out["تعيينات"] = n("SELECT COUNT(*) c FROM employee_placements WHERE company_id=?", pid)
        out["فواتير"] = n("SELECT COUNT(*) c FROM invoices WHERE company_id=?", pid)
    elif ptype == "contractor":
        out["موظفون"] = n("SELECT COUNT(*) c FROM employee_placements WHERE contractor_id=? OR external_id=?", pid, pid)
    elif ptype == "representative":
        out["شركات"] = n("SELECT COUNT(*) c FROM company_rep_terms WHERE representative_id=?", pid)
    out["إذون"] = n("SELECT COUNT(*) c FROM vouchers WHERE party_type=? AND party_id=?", ptype, pid)
    out["عقود"] = n("SELECT COUNT(*) c FROM contracts WHERE party_type=? AND party_id=?", ptype, pid)
    out["وثائق"] = n("SELECT COUNT(*) c FROM documents WHERE owner_type=? AND owner_id=?", ptype, pid)
    return {k: v for k, v in out.items() if v}


def delete_record(cfg, rid) -> str:
    """Deletes a record that nothing refers to. Otherwise raises ValueError saying what blocks it."""
    row = query_one(f"SELECT * FROM {cfg['table']} WHERE id=?", (rid,))
    if not row:
        raise ValueError("السجل غير موجود.")
    links = link_counts(PARTY_OF[cfg["key"]], rid)
    if links:
        detail = "، ".join(f"{k}: {v}" for k, v in links.items())
        raise ValueError(f"لا يمكن حذفه لأنه مرتبط بسجلات ({detail}). السجلات المالية لا تُحذف؛ "
                         f"غيّر حالته إلى «غير نشط» ليخرج من القوائم مع بقاء تاريخه.")
    try:
        execute(f"DELETE FROM {cfg['table']} WHERE id=?", (rid,))
    except sqlite3.IntegrityError as ex:
        raise ValueError(friendly_error(ex, "تعذر الحذف")) from ex
    log_audit(cfg["table"], rid, "STATUS_CHANGE", row, {"deleted": True}, note=f"حذف {cfg['singular']}")
    return f"تم حذف {cfg['singular']}: {row[cfg['name_field']]}"


# --------------------------------------------------------------------- widgets
def _fields(cfg, data, kp, only=None):
    """Draws the input widgets; returns {field: value, 'status': value}. `kp` keeps widget keys unique per record."""
    data = data or {}
    k = f"{cfg['key']}_{kp}_"
    vals = {}
    fields = [f for f in cfg["fields"] if only is None or f["name"] in only]
    first = fields[0]
    vals[first["name"]] = st.text_input(first["label"], value=data.get(first["name"]) or "", key=k + first["name"])
    short = [f for f in fields[1:] if f.get("kind", "text") != "area"]
    areas = [f for f in fields[1:] if f.get("kind") == "area"]
    cols = st.columns(2)
    for i, f in enumerate(short):
        with cols[i % 2]:
            cur = data.get(f["name"])
            if f.get("kind") == "sensitive":
                vals[f["name"]] = security.sensitive_input(f["label"], cur, k + f["name"])
            elif f.get("kind") == "select":
                opts = list(f["options"].keys())
                vals[f["name"]] = st.selectbox(f["label"], opts, index=opts.index(cur) if cur in opts else 0,
                                               format_func=lambda x, _o=f["options"]: _o.get(x, x), key=k + f["name"])
            else:
                vals[f["name"]] = st.text_input(f["label"], value=cur or "", key=k + f["name"])
    if only is None:
        keys = list(cfg["statuses"].keys())
        with cols[len(short) % 2]:
            cur = data.get("status") or "active"
            vals["status"] = st.selectbox("الحالة", keys, index=keys.index(cur) if cur in keys else 0,
                                          format_func=lambda x: STATUS_AR.get(x, x), key=k + "status")
    for f in areas:
        vals[f["name"]] = st.text_area(f["label"], value=data.get(f["name"]) or "", key=k + f["name"])
    return vals


def _ver(cfg, name):
    return st.session_state.get(f"{cfg['key']}_{name}", 0)


def _bump(cfg, name):
    st.session_state[f"{cfg['key']}_{name}"] = _ver(cfg, name) + 1


def add_dialog(cfg, quick=False, on_saved=None):
    """Opens a modal 'add' form on top of the current page. quick=True shows only the main fields."""
    @st.dialog(f"إضافة {cfg['singular']} جديد" if cfg.get("masculine", True) else f"إضافة {cfg['singular']} جديدة")
    def _dlg():
        only = cfg.get("quick_fields") if quick else None
        with st.form(f"{cfg['key']}_{'q' if quick else 'a'}_form"):
            vals = _fields(cfg, None, f"{'q' if quick else 'a'}{_ver(cfg, 'addv')}", only)
            sub = st.form_submit_button("حفظ", type="primary", icon=":material/save:", icon_position="right",
                                        use_container_width=True)
        if sub:
            try:
                rid, msg = save_record(cfg, None, vals)
            except ValueError as ex:
                st.error(str(ex))
                return
            _bump(cfg, "addv")
            flash_set(msg)
            if on_saved:
                on_saved(rid)
            st.rerun()
    _dlg()


def edit_dialog(cfg, rec):
    @st.dialog(f"تعديل {cfg['singular']}")
    def _dlg():
        data = query_one(f"SELECT * FROM {cfg['table']} WHERE id=?", (rec["id"],))
        if not data:
            st.error("السجل غير موجود.")
            return
        with st.form(f"{cfg['key']}_edit_form_{rec['id']}"):
            vals = _fields(cfg, data, f"e{rec['id']}")
            sub = st.form_submit_button("حفظ التعديلات", type="primary", icon=":material/save:",
                                        icon_position="right", use_container_width=True)
        if sub:
            try:
                _, msg = save_record(cfg, rec["id"], vals)
            except ValueError as ex:
                st.error(str(ex))
                return
            flash_set(msg)
            _bump(cfg, "tv")
            st.rerun()
    _dlg()


def delete_dialog(cfg, rec):
    @st.dialog(f"حذف {cfg['singular']}")
    def _dlg():
        name = rec.get(cfg["name_field"]) or ""
        links = link_counts(PARTY_OF[cfg["key"]], rec["id"])
        if links:
            st.error("لا يمكن الحذف لأنه مرتبط بسجلات: " + "، ".join(f"{k}: {v}" for k, v in links.items()))
            st.info("السجلات المالية والتاريخية لا تُحذف. غيّر حالته إلى «غير نشط» من زر التعديل ليخرج من القوائم مع بقاء تاريخه.")
            return
        st.warning(f"سيُحذف «{name}» نهائياً ولا يمكن التراجع. هذا ممكن لأنه غير مرتبط بأي سجل.")
        if st.button("تأكيد الحذف", type="primary", icon=":material/delete:", icon_position="right",
                     key=f"{cfg['key']}_del_ok_{rec['id']}", use_container_width=True):
            try:
                msg = delete_record(cfg, rec["id"])
            except ValueError as ex:
                st.error(str(ex))
                return
            flash_set(msg)
            _bump(cfg, "tv")
            st.rerun()
    _dlg()


def render(cfg):
    show_flash()
    can = security.can_write()
    c1, c2, c3 = st.columns([4, 1.4, 1.4])
    with c1:
        search = st.text_input("بحث", placeholder=cfg["search_hint"], key=f"{cfg['key']}_q", label_visibility="collapsed")
    with c2:
        keys = ["all"] + list(cfg["statuses"].keys())
        status = st.selectbox("الحالة", keys, format_func=lambda x: "كل الحالات" if x == "all" else STATUS_AR[x],
                              key=f"{cfg['key']}_sf", label_visibility="collapsed")
    with c3:
        if can and st.button(f"إضافة {cfg['singular']}", key=f"{cfg['key']}_add_btn", type="primary",
                             icon=":material/add:", icon_position="right", use_container_width=True):
            add_dialog(cfg)
    rows = load_rows(cfg, search, status)
    total = query_one(f"SELECT COUNT(*) c, SUM(status='active') a FROM {cfg['table']}")
    st.caption(f"الإجمالي: {total['c']} — النشط: {total['a'] or 0} — المعروض: {len(rows)}")
    if not rows:
        st.info(f"لا توجد سجلات مطابقة. {'اضغط «إضافة» لإنشاء أول سجل.' if can else ''}")
        return
    df = pd.DataFrame(rows)
    df["status"] = df["status"].map(lambda s: STATUS_AR.get(s, s))
    for f in cfg["fields"]:
        if f.get("kind") == "select" and f["name"] in df.columns:
            df[f["name"]] = df[f["name"]].map(lambda v, _o=f["options"]: _o.get(v, v))
    df = df[[c for c, _ in cfg["columns"]]].fillna("")
    df.columns = [lbl for _, lbl in cfg["columns"]]
    excel_button(df, cfg["key"], f"{cfg['key']}_xl")
    ev = st.dataframe(df, use_container_width=True, hide_index=True, on_select="rerun",
                      selection_mode="single-row", key=f"{cfg['key']}_tbl_{_ver(cfg, 'tv')}")
    sel = ev.selection.rows if ev is not None else []
    if sel and sel[0] < len(rows):
        rec = rows[sel[0]]
        st.markdown(f"**المحدد:** {rec[cfg['name_field']]}")
        actions = row_action_bar(
            edit=can,
            delete=can,
            prefix=f"{cfg['key']}_row_{rec['id']}",
        )
        if actions["edit"]:
            edit_dialog(cfg, rec)
        if actions["delete"]:
            delete_dialog(cfg, rec)
        if not can:
            st.info("ليست لديك صلاحية التعديل.")
    elif can:
        st.caption("💡 اضغط مربع الاختيار أول أي صف لتعديله أو حذفه.")
