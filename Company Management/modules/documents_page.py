import pandas as pd
import streamlit as st
from datetime import date

import documents as D
import security
from ui import select_table, tbump, toast_flash, excel_button, friendly_error, row_action_bar
from db import query_all

_FLASH = "_doc_flash"
STATE_AR = {"expired": "🔴 منتهية", "soon": "🟠 تنتهي قريباً", "valid": "🟢 سارية", "none": "— بلا تاريخ انتهاء"}


def _owners(otype):
    t, col = D.OWNER_TABLE[otype]
    return {f"{r['n']} (#{r['id']})": r["id"] for r in query_all(f"SELECT id, {col} AS n FROM {t} ORDER BY {col}")}


def _read(upl):
    return (upl.name, upl.getvalue()) if upl is not None else None


@st.dialog("إضافة وثيقة")
def _dlg_add():
    otype = st.selectbox("نوع صاحب الوثيقة", list(D.OWNER_AR), format_func=lambda k: D.OWNER_AR[k], key="doc_a_ot")
    owners = _owners(otype)
    if not owners:
        st.info(f"لا يوجد {D.OWNER_AR[otype]} مسجل. أضفه أولاً.")
        return
    oname = st.selectbox("صاحب الوثيقة", list(owners), key=f"doc_a_o_{otype}")
    dtype = st.selectbox("نوع الوثيقة", D.DOC_TYPES[otype], key=f"doc_a_t_{otype}")
    title = st.text_input("عنوان/وصف (اختياري)", key="doc_a_title")
    c1, c2 = st.columns(2)
    issue = c1.date_input("تاريخ الإصدار", value=None, key="doc_a_issue")
    expiry = c2.date_input("تاريخ الانتهاء", value=None, key="doc_a_exp")
    notes = st.text_area("ملاحظات", key="doc_a_notes")
    upl = st.file_uploader("الملف (PDF أو صورة، حتى 5 ميغابايت)", type=["pdf", "jpg", "jpeg", "png"], key="doc_a_file")
    if st.button("حفظ", type="primary", key="doc_a_save"):
        try:
            D.add_document(otype, owners[oname], dtype, title, issue, expiry, notes, _read(upl))
            st.session_state[_FLASH] = "تمت إضافة الوثيقة."
            tbump("doc")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            st.error(friendly_error(e))


@st.dialog("تعديل / تجديد الوثيقة")
def _dlg_edit(r):
    st.markdown(f"**{r['doc_type']}** — {r['owner_name']}")
    title = st.text_input("عنوان/وصف", value=r["title"] or "", key=f"doc_e_title_{r['id']}")
    c1, c2 = st.columns(2)
    issue = c1.date_input("تاريخ الإصدار", value=D._to_date(r["issue_date"]) if r["issue_date"] else None, key=f"doc_e_i_{r['id']}")
    expiry = c2.date_input("تاريخ الانتهاء", value=D._to_date(r["expiry_date"]) if r["expiry_date"] else None, key=f"doc_e_x_{r['id']}")
    notes = st.text_area("ملاحظات", value=r["notes"] or "", key=f"doc_e_n_{r['id']}")
    upl = st.file_uploader("استبدال الملف (اختياري)", type=["pdf", "jpg", "jpeg", "png"], key=f"doc_e_f_{r['id']}")
    if st.button("حفظ", type="primary", key=f"doc_e_save_{r['id']}"):
        try:
            st.session_state[_FLASH] = D.update_document(r["id"], title, issue, expiry, notes, _read(upl))
            tbump("doc")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            st.error(friendly_error(e))


@st.dialog("أرشفة الوثيقة")
def _dlg_archive(r):
    st.warning("ستُنقل الوثيقة إلى الأرشيف (لا تُحذف) وتختفي من التنبيهات.")
    if st.button("تأكيد الأرشفة", type="primary", key=f"doc_ar_{r['id']}"):
        st.session_state[_FLASH] = D.archive_document(r["id"])
        tbump("doc")
        st.rerun()


def render():
    toast_flash(_FLASH)
    can = security.can_write()
    al = D.expiry_alerts()
    if al["expired"]:
        st.error(f"{len(al['expired'])} وثيقة منتهية.")
    if al["soon"]:
        st.warning(f"{len(al['soon'])} وثيقة تنتهي خلال {al['days']} يوماً.")
    c1, c2, c3, c4 = st.columns([1.4, 1.4, 1.4, 1.4])
    ot = c1.selectbox("صاحب الوثيقة", ["all"] + list(D.OWNER_AR), format_func=lambda k: "الكل" if k == "all" else D.OWNER_AR[k], key="doc_f_ot")
    stt = c2.selectbox("الحالة", ["all", "expired", "soon", "valid", "none"], format_func=lambda k: "الكل" if k == "all" else STATE_AR[k], key="doc_f_st")
    arch = c3.checkbox("عرض المؤرشفة", key="doc_f_arch")
    with c4:
        if can and st.button("➕ إضافة وثيقة", type="primary", key="doc_add_btn", use_container_width=True):
            _dlg_add()
    q = st.text_input("بحث بالاسم", key="doc_f_q", label_visibility="collapsed", placeholder="بحث باسم صاحب الوثيقة…").strip()
    rows = D.list_documents(None if ot == "all" else ot, "archived" if arch else "active")
    for r in rows:
        r["state"] = D.state_of(r)
    rows = [r for r in rows if (stt == "all" or r["state"] == stt) and (not q or q in r["owner_name"])]
    if not rows:
        st.info("لا توجد وثائق مطابقة. اضغط «➕ إضافة وثيقة» لتسجيل أول وثيقة." if can else "لا توجد وثائق مطابقة.")
        return
    df = pd.DataFrame([{"الرقم": r["id"], "الصاحب": r["owner_name"], "النوع": D.OWNER_AR[r["owner_type"]], "الوثيقة": r["doc_type"],
                        "الوصف": r["title"] or "", "الإصدار": r["issue_date"] or "", "الانتهاء": r["expiry_date"] or "",
                        "الحالة": STATE_AR[r["state"]], "ملف": "📎" if r["has_file"] else ""} for r in rows])
    excel_button(df, "documents", "doc_xl")
    pos = select_table(df, "doc")
    if pos is None:
        st.caption(f"عدد الوثائق: {len(rows)} — 💡 اضغط على صف لتعديله أو تنزيل ملفه.")
        return
    r = rows[pos]
    st.markdown(f"**{r['doc_type']}** — {r['owner_name']}")
    f = D.get_file(r["id"]) if r["has_file"] else None
    actions = row_action_bar(edit=can and r["status"] == "active", delete=can and r["status"] == "active",
                            print_=bool(f), view=bool(f), prefix=f"doc_row_{r['id']}")
    if actions["edit"]:
        _dlg_edit(r)
    if actions["delete"]:
        _dlg_archive(r)
    if f and actions["view"]:
        st.download_button("عرض الملف", bytes(f["data"]), file_name=f["file_name"], mime=f["mime"],
                           key=f"doc_view_{r['id']}")
    if f and actions["print"]:
        st.download_button("طباعة الملف", bytes(f["data"]), file_name=f["file_name"], mime=f["mime"],
                           key=f"doc_print_{r['id']}")
