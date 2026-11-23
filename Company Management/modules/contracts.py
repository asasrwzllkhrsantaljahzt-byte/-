import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
import security
import app_settings
from db import get_connection, query_all, query_one, execute
from audit import log_audit
from ui import toast_flash, select_table, excel_button, tbump

TYPE_AR = {"client": "عقد عميل", "contractor": "عقد متعهد", "representative": "عقد مندوب",
           "employee": "عقد موظف", "other": "أخرى"}
STATUS_AR = {"draft": "مسودة", "active": "ساري", "suspended": "موقوف", "ended": "منتهٍ"}
PARTY_AR = {"company": "شركة عميلة", "contractor": "متعهد", "representative": "مندوب", "employee": "موظف"}
PARTY_TABLE = {"company": ("companies", "name"), "contractor": ("contractors", "name"),
               "representative": ("representatives", "name"), "employee": ("employees", "full_name")}
# a typed contract must be with the matching kind of party; "other" may be with any
TYPE_PARTY = {"client": "company", "contractor": "contractor", "representative": "representative", "employee": "employee"}

CONTRACTS_SCHEMA = """
-- party must exist and match the contract type
CREATE TRIGGER IF NOT EXISTS trg_contracts_party_ins
BEFORE INSERT ON contracts
WHEN NOT (
    (NEW.party_type = 'company'        AND EXISTS (SELECT 1 FROM companies       WHERE id = NEW.party_id)) OR
    (NEW.party_type = 'contractor'     AND EXISTS (SELECT 1 FROM contractors     WHERE id = NEW.party_id)) OR
    (NEW.party_type = 'representative' AND EXISTS (SELECT 1 FROM representatives WHERE id = NEW.party_id)) OR
    (NEW.party_type = 'employee'       AND EXISTS (SELECT 1 FROM employees       WHERE id = NEW.party_id))
)
BEGIN
    SELECT RAISE(ABORT, 'الطرف المحدد غير موجود في النظام.');
END;

CREATE TRIGGER IF NOT EXISTS trg_contracts_type_match
BEFORE INSERT ON contracts
WHEN (NEW.contract_type = 'client' AND NEW.party_type != 'company')
  OR (NEW.contract_type = 'contractor' AND NEW.party_type != 'contractor')
  OR (NEW.contract_type = 'representative' AND NEW.party_type != 'representative')
  OR (NEW.contract_type = 'employee' AND NEW.party_type != 'employee')
BEGIN
    SELECT RAISE(ABORT, 'نوع العقد لا يتوافق مع نوع الطرف.');
END;

-- contracts are history: never deleted, party never changed
CREATE TRIGGER IF NOT EXISTS trg_contracts_no_delete
BEFORE DELETE ON contracts
BEGIN
    SELECT RAISE(ABORT, 'لا يجوز حذف العقود. أنهِ العقد بدلاً من ذلك ليبقى سجله.');
END;

CREATE TRIGGER IF NOT EXISTS trg_contracts_party_fixed
BEFORE UPDATE ON contracts
WHEN NEW.party_type != OLD.party_type OR NEW.party_id != OLD.party_id
  OR NEW.contract_type != OLD.contract_type OR NEW.company_id IS NOT OLD.company_id
BEGIN
    SELECT RAISE(ABORT, 'لا يمكن تغيير نوع العقد أو أطرافه. أنشئ عقداً جديداً.');
END;

-- an ended contract is closed: it cannot be reopened or have its dates changed
CREATE TRIGGER IF NOT EXISTS trg_contracts_ended_frozen
BEFORE UPDATE ON contracts
WHEN OLD.status = 'ended'
  AND (NEW.status != 'ended' OR NEW.start_date != OLD.start_date OR NEW.end_date IS NOT OLD.end_date)
BEGIN
    SELECT RAISE(ABORT, 'العقد المنتهي مغلق ولا يمكن إعادة فتحه أو تعديل تواريخه. أنشئ عقداً جديداً.');
END;

CREATE TRIGGER IF NOT EXISTS trg_contracts_end_needs_date_ins
BEFORE INSERT ON contracts
WHEN NEW.status = 'ended' AND NEW.end_date IS NULL
BEGIN
    SELECT RAISE(ABORT, 'العقد المنتهي يحتاج إلى تاريخ انتهاء.');
END;

CREATE TRIGGER IF NOT EXISTS trg_contracts_end_needs_date_upd
BEFORE UPDATE ON contracts
WHEN NEW.status = 'ended' AND NEW.end_date IS NULL
BEGIN
    SELECT RAISE(ABORT, 'العقد المنتهي يحتاج إلى تاريخ انتهاء.');
END;
"""


def ensure_contracts_schema() -> None:
    conn = get_connection()
    try:
        conn.executescript(CONTRACTS_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _iso(d) -> str:
    return d.strftime("%Y-%m-%d")


def _to_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _party_name(party_type, party_id):
    t = PARTY_TABLE.get(party_type)
    if not t:
        return "-"
    row = query_one(f"SELECT {t[1]} AS n FROM {t[0]} WHERE id=?", (party_id,))
    return row["n"] if row else "(محذوف)"


def _flash(msg):
    st.session_state["_ct_flash"] = msg
    tbump("ct")
    st.rerun()


# ------------------------------------------------------------ business rules
def validate_contract(contract_type, party_type, party_id, company_id, start, end, status, exclude_id=None) -> list:
    """Returns Arabic error messages. Dates are date objects (end may be None)."""
    errors = []
    need = TYPE_PARTY.get(contract_type)
    if need and party_type != need:
        errors.append(f"عقد من نوع «{TYPE_AR[contract_type]}» يجب أن يكون طرفه: {PARTY_AR[need]}.")
    if not party_id:
        errors.append("اختر الطرف.")
    if end and end < start:
        errors.append("تاريخ الانتهاء لا يسبق تاريخ البداية.")
    if status == "ended" and not end:
        errors.append("العقد المنتهي يحتاج إلى تاريخ انتهاء.")
    if status == "active" and party_id:
        # no two overlapping active contracts of the same kind with the same party (and client company)
        rows = query_all(
            """SELECT id, start_date, end_date FROM contracts
               WHERE status='active' AND contract_type=? AND party_type=? AND party_id=?
                 AND COALESCE(company_id,0)=COALESCE(?,0) AND id != COALESCE(?,0)""",
            (contract_type, party_type, party_id, company_id, exclude_id))
        for r in rows:
            r_start, r_end = _to_date(r["start_date"]), _to_date(r["end_date"]) if r["end_date"] else None
            if (r_end is None or r_end >= start) and (end is None or end >= r_start):
                errors.append(f"يوجد عقد ساري متداخل معه (#{r['id']}). أنهِ القديم أولاً أو عدّل التواريخ.")
                break
    return errors


def add_contract(contract_type, party_type, party_id, company_id, start, end, status, terms, doc_ref, notes) -> int:
    errors = validate_contract(contract_type, party_type, party_id, company_id, start, end, status)
    if errors:
        raise ValueError(" ".join(errors))
    payload = {"contract_type": contract_type, "party_type": party_type, "party_id": party_id,
               "company_id": company_id, "start_date": _iso(start), "end_date": _iso(end) if end else None,
               "status": status, "terms_summary": terms or None, "document_ref": doc_ref or None, "notes": notes or None}
    new_id = execute(
        """INSERT INTO contracts(contract_type, party_type, party_id, company_id, start_date, end_date,
                                 status, terms_summary, document_ref, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        tuple(payload.values()))
    log_audit("contracts", new_id, "INSERT", None, payload, note="إضافة عقد")
    return new_id


def update_contract(contract_id, start, end, status, terms, doc_ref, notes) -> None:
    old = query_one("SELECT * FROM contracts WHERE id=?", (contract_id,))
    if not old:
        raise ValueError("العقد غير موجود.")
    errors = validate_contract(old["contract_type"], old["party_type"], old["party_id"], old["company_id"],
                               start, end, status, exclude_id=contract_id)
    if errors:
        raise ValueError(" ".join(errors))
    new = {"start_date": _iso(start), "end_date": _iso(end) if end else None, "status": status,
           "terms_summary": terms or None, "document_ref": doc_ref or None, "notes": notes or None}
    execute("""UPDATE contracts SET start_date=?, end_date=?, status=?, terms_summary=?, document_ref=?, notes=?,
               updated_at=CURRENT_TIMESTAMP WHERE id=?""", (*new.values(), contract_id))
    action = "STATUS_CHANGE" if old["status"] != status else "UPDATE"
    log_audit("contracts", contract_id, action, old, new, note="تعديل عقد")


def expiry_alerts(today: date = None, days: int = None) -> dict:
    """Active contracts already past their end date, and those ending within `days`."""
    today = today or date.today()
    days = days or app_settings.get_int("contract_alert_days")
    rows = query_all("SELECT * FROM contracts WHERE status='active' AND end_date IS NOT NULL ORDER BY end_date")
    overdue, soon = [], []
    for r in rows:
        end = _to_date(r["end_date"])
        if end < today:
            overdue.append(r)
        elif end <= today + timedelta(days=days):
            soon.append(r)
    return {"overdue": overdue, "soon": soon, "days": days}


def _label(r):
    return (f"#{r['id']} | {TYPE_AR[r['contract_type']]} | {_party_name(r['party_type'], r['party_id'])} "
            f"| {r['start_date']} → {r['end_date'] or 'مفتوح'} [{STATUS_AR[r['status']]}]")


# ------------------------------------------------------------------- UI
def _tab_list():
    al = expiry_alerts()
    if al["overdue"]:
        st.error(f"{len(al['overdue'])} عقد ساري انتهت مدته ولم يُنهَ في النظام: "
                 + "، ".join(f"#{r['id']}" for r in al["overdue"]))
    if al["soon"]:
        st.warning(f"{len(al['soon'])} عقد ينتهي خلال {al['days']} يوماً: "
                   + "، ".join(f"#{r['id']} ({r['end_date']})" for r in al["soon"]))
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        search = st.text_input("بحث (اسم الطرف أو رقم المستند)", key="ct_search")
    with c2:
        tf = st.selectbox("النوع", ["الكل"] + list(TYPE_AR.values()), key="ct_type_f")
    with c3:
        sf = st.selectbox("الحالة", ["الكل"] + list(STATUS_AR.values()), key="ct_status_f")
    rows = query_all("SELECT * FROM contracts ORDER BY id DESC")
    inv_t = {v: k for k, v in TYPE_AR.items()}
    inv_s = {v: k for k, v in STATUS_AR.items()}
    out = []
    for r in rows:
        name = _party_name(r["party_type"], r["party_id"])
        if search and search not in name and search not in (r["document_ref"] or ""):
            continue
        if tf != "الكل" and r["contract_type"] != inv_t[tf]:
            continue
        if sf != "الكل" and r["status"] != inv_s[sf]:
            continue
        company = _party_name("company", r["company_id"]) if r["company_id"] else ""
        out.append({"id": r["id"], "النوع": TYPE_AR[r["contract_type"]], "الطرف": name, "العميل": company,
                    "البداية": r["start_date"], "النهاية": r["end_date"] or "مفتوح",
                    "الحالة": STATUS_AR[r["status"]], "المستند": r["document_ref"] or ""})
    if not out:
        st.info("لا توجد عقود مطابقة.")
        return
    df = pd.DataFrame(out)
    excel_button(df.drop(columns=["id"]), "contracts", "ct_xl")
    pos = select_table(df.drop(columns=["id"]), "ct")
    if pos is None:
        st.caption(f"عدد النتائج: {len(out)} — 💡 اضغط مربع الاختيار أول أي صف لتعديل العقد أو إنهائه.")
        return
    cid = out[pos]["id"]
    st.markdown(f"**المحدد:** عقد #{cid} — {out[pos]['الطرف']}")
    from ui import row_action_bar
    actions = row_action_bar(edit=security.can_write(), view=True, print_=True,
                            prefix=f"ct_row_{cid}")
    if actions["edit"]:
        _dlg_edit(cid)
    if actions["view"]:
        _dlg_edit(cid)
    if actions["print"]:
        st.button("طباعة العقد", key=f"ct_print_{cid}", icon=":material/print:")
    st.caption("العقود لا تُحذف ولا يتغير طرفها، لإنهاء العقد اختر الحالة «منتهٍ» مع تاريخ انتهاء.")


def _tab_add():
    if not security.can_write():
        st.info("ليست لديك صلاحية إضافة عقود.")
        return
    with st.form("contract_add_form"):
        ctype = st.selectbox("نوع العقد *", list(TYPE_AR.keys()), format_func=lambda k: TYPE_AR[k], key="ct_add_type")
        need = TYPE_PARTY.get(ctype)
        ptype = need or st.selectbox("نوع الطرف *", list(PARTY_AR.keys()), format_func=lambda k: PARTY_AR[k], key="ct_add_ptype")
        t, col = PARTY_TABLE[ptype]
        party_opts = {f"{r['id']} - {r[col]}": r["id"] for r in query_all(f"SELECT id, {col} FROM {t} ORDER BY {col}")}
        plabel = st.selectbox(f"الطرف ({PARTY_AR[ptype]}) *", list(party_opts.keys()) or ["(لا يوجد)"], key="ct_add_party")
        comp_opts = {"(بدون)": None}
        comp_opts.update({f"{r['id']} - {r['name']}": r["id"] for r in query_all("SELECT id, name FROM companies ORDER BY name")})
        clabel = st.selectbox("الشركة العميلة المرتبطة (اختياري)", list(comp_opts.keys()), key="ct_add_company")
        c1, c2 = st.columns(2)
        with c1:
            start = st.date_input("تاريخ البداية *", value=date.today(), key="ct_add_start")
        with c2:
            has_end = st.checkbox("له تاريخ انتهاء", value=False, key="ct_add_has_end")
            end = st.date_input("تاريخ الانتهاء", value=date.today() + timedelta(days=365), key="ct_add_end")
        status = st.selectbox("الحالة", ["draft", "active"], index=1, format_func=lambda k: STATUS_AR[k], key="ct_add_status")
        terms = st.text_area("ملخص الشروط", key="ct_add_terms")
        doc_ref = st.text_input("رقم/مرجع المستند", key="ct_add_doc")
        notes = st.text_area("ملاحظات", key="ct_add_notes")
        sub = st.form_submit_button("حفظ العقد", type="primary")
    if sub:
        try:
            if plabel not in party_opts:
                raise ValueError("اختر الطرف.")
            cid = add_contract(ctype, ptype, party_opts[plabel], comp_opts[clabel], start,
                               end if has_end else None, status, terms.strip(), doc_ref.strip(), notes.strip())
            _flash(f"تمت إضافة العقد #{cid}.")
        except ValueError as ex:
            st.error(str(ex))
        except Exception as ex:  # noqa: BLE001
            st.error(f"تعذر الحفظ: {ex}")


def _tab_edit(contract_id=None):
    if not security.can_write():
        st.info("ليست لديك صلاحية تعديل العقود.")
        return
    if contract_id is None:
        rows = query_all("SELECT * FROM contracts ORDER BY id DESC")
        if not rows:
            st.info("لا توجد عقود بعد.")
            return
        opts = {_label(r): r["id"] for r in rows}
        contract_id = opts[st.selectbox("اختر العقد", list(opts.keys()), key="ct_edit_sel")]
    cur = query_one("SELECT * FROM contracts WHERE id=?", (contract_id,))
    closed = cur["status"] == "ended"
    if closed:
        st.info("العقد منتهٍ ومغلق: يمكن تعديل الشروط والمستند والملاحظات فقط. لتجديده أنشئ عقداً جديداً.")
    st.caption("لا يمكن حذف العقد ولا تغيير طرفه. لإنهائه اختر الحالة «منتهٍ» مع تاريخ انتهاء.")
    with st.form("contract_edit_form"):
        c1, c2 = st.columns(2)
        with c1:
            start = st.date_input("تاريخ البداية", value=_to_date(cur["start_date"]), disabled=closed, key="ct_edit_start")
        with c2:
            has_end = st.checkbox("له تاريخ انتهاء", value=bool(cur["end_date"]), key="ct_edit_has_end")
            end = st.date_input("تاريخ الانتهاء", value=_to_date(cur["end_date"]) if cur["end_date"] else date.today(),
                                disabled=closed, key="ct_edit_end")
        keys = list(STATUS_AR.keys())
        status = st.selectbox("الحالة", keys, index=keys.index(cur["status"]), format_func=lambda k: STATUS_AR[k],
                              disabled=closed, key="ct_edit_status")
        terms = st.text_area("ملخص الشروط", value=cur["terms_summary"] or "", key="ct_edit_terms")
        doc_ref = st.text_input("رقم/مرجع المستند", value=cur["document_ref"] or "", key="ct_edit_doc")
        notes = st.text_area("ملاحظات", value=cur["notes"] or "", key="ct_edit_notes")
        sub = st.form_submit_button("حفظ التعديل", type="primary")
    if sub:
        try:
            if closed:
                start, end, has_end, status = _to_date(cur["start_date"]), (_to_date(cur["end_date"])), True, "ended"
            update_contract(cur["id"], start, end if has_end else None, status, terms.strip(), doc_ref.strip(), notes.strip())
            _flash(f"تم تحديث العقد #{cur['id']}.")
        except ValueError as ex:
            st.error(str(ex))
        except Exception as ex:  # noqa: BLE001
            st.error(f"تعذر الحفظ: {ex}")


@st.dialog("إضافة عقد")
def _dlg_add():
    _tab_add()


def _dlg_edit(contract_id):
    @st.dialog(f"تعديل العقد #{contract_id}")
    def _d():
        _tab_edit(contract_id)
    _d()


def render():
    ensure_contracts_schema()
    toast_flash("_ct_flash")
    if security.can_write() and st.button("➕ إضافة عقد", type="primary", key="ct_add_btn"):
        _dlg_add()
    _tab_list()
