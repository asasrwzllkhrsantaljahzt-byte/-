import pandas as pd
import streamlit as st

import vouchers as V
import documents as D
import security
from db import query_all, query_one
from modules import entities, vouchers_page
from modules import companies, employees, contractors, representatives
from ui import excel_button, toast_flash, flash_set, show_flash

CFG = {"company": companies.CFG, "employee": employees.CFG, "contractor": contractors.CFG,
       "representative": representatives.CFG}
TYPES = list(V.PARTY_TABLE)


def _options(ptype):
    t, col = V.PARTY_TABLE[ptype]
    return {f"{r['n']} (#{r['id']})": r["id"] for r in query_all(f"SELECT id, {col} AS n FROM {t} ORDER BY {col}")}


def open_profile(ptype, pid):
    """Callback: jump to the party file of a given record."""
    name = V.party_name(ptype, pid)
    st.session_state["pp_type"] = ptype
    st.session_state[f"pp_party_{ptype}"] = f"{name} (#{pid})"
    st.session_state["_page"] = "ملف الجهة"


def _fmt(n):
    return f"{n:,.2f}"


def render():
    show_flash()
    can = security.can_write()
    c1, c2 = st.columns([1, 3])
    ptype = c1.selectbox("نوع الجهة", TYPES, format_func=lambda k: V.PARTY_AR[k], key="pp_type")
    opts = _options(ptype)
    if not opts:
        st.info(f"لا يوجد {V.PARTY_AR[ptype]} مسجل بعد.")
        return
    label = c2.selectbox("اختر الجهة (اكتب للبحث)", list(opts), key=f"pp_party_{ptype}")
    pid = opts[label]
    cfg = CFG[ptype]
    rec = query_one(f"SELECT * FROM {cfg['table']} WHERE id=?", (pid,))
    acc = V.party_account(ptype, pid)

    with st.container(border=True):
        h1, h2 = st.columns([3, 2])
        h1.markdown(f"### {rec[cfg['name_field']]}")
        h1.caption(f"{V.PARTY_AR[ptype]} · الحالة: {entities.STATUS_AR.get(rec['status'], rec['status'])}"
                   + (f" · هاتف: {rec['phone']}" if rec.get("phone") else ""))
        with h2:
            a, b, c = st.columns(3)
            if can and a.button("تعديل", key="pp_edit", icon=":material/edit:",
                                icon_position="right", use_container_width=True):
                entities.edit_dialog(cfg, rec)
            if can and b.button("حذف", key="pp_del", icon=":material/delete:",
                                icon_position="right", use_container_width=True):
                entities.delete_dialog(cfg, rec)
        m1, m2, m3 = st.columns(3)
        m1.metric(acc["due_label"], _fmt(acc["due"]))
        m2.metric(acc["settled_label"], _fmt(acc["settled"]))
        m3.metric(acc["balance_label"], _fmt(acc["balance"]))
        st.info("📌 " + acc["note"])

    tabs = st.tabs(["📒 الحساب", "🔗 العلاقات", "🧾 الإذون", "📎 الوثائق", "📄 العقود"])
    with tabs[0]:
        rows = V.statement_rows(ptype, pid)
        if not rows:
            st.info("لا توجد مستحقات أو إذون لهذه الجهة بعد. تظهر المستحقات بعد احتساب الشهر من «مراجعة الحركات وإقفال الأشهر».")
        else:
            df = pd.DataFrame(rows)
            excel_button(df, f"account_{ptype}_{pid}", "pp_acc_xl")
            shown = df.copy()
            for c in ("مستحق", "مسدد", "الرصيد"):
                shown[c] = shown[c].map(lambda x: "" if pd.isna(x) else f"{float(x):,.2f}")
            st.dataframe(shown, use_container_width=True, hide_index=True)
        st.caption("المستحق يأتي من الحسابات الشهرية المحتسبة، والمسدد من الإذون السارية فقط.")
    with tabs[1]:
        rel = V.relations(ptype, pid)
        if rel:
            st.dataframe(pd.DataFrame(rel), use_container_width=True, hide_index=True)
            st.caption("لفتح ملف أي جهة منها اخترها من القائمة أعلاه. لإضافة علاقة جديدة استخدم «الشركات والموظفون».")
        else:
            st.info("لا توجد علاقات مسجلة. تُنشأ العلاقات من «الشركات والموظفون».")
    with tabs[2]:
        if can:
            a, b, _ = st.columns([1.4, 1.4, 4])
            if a.button("➕ إذن استلام", key="pp_r", use_container_width=True):
                vouchers_page.issue_dialog("receipt", ptype, pid, "ppvo")
            if b.button("➕ إذن صرف", key="pp_p", use_container_width=True):
                vouchers_page.issue_dialog("payment", ptype, pid, "ppvo")
        toast_flash(vouchers_page._FLASH)
        vouchers_page.voucher_table(V.list_vouchers(party_type=ptype, party_id=pid), "ppvo", can)
    with tabs[3]:
        docs = D.list_documents(ptype, None)
        docs = [d for d in docs if d["owner_id"] == pid]
        if docs:
            st.dataframe(pd.DataFrame([{"الوثيقة": d["doc_type"], "الانتهاء": d["expiry_date"] or "", "الحالة": D.state_of(d),
                                        "مؤرشفة": "نعم" if d["status"] == "archived" else ""} for d in docs]),
                         use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد وثائق. أضفها من صفحة «الوثائق».")
    with tabs[4]:
        cs = query_all("SELECT * FROM contracts WHERE party_type=? AND party_id=? ORDER BY id DESC", (ptype, pid))
        if cs:
            st.dataframe(pd.DataFrame([{"الرقم": c["id"], "النوع": c["contract_type"], "البداية": c["start_date"],
                                        "النهاية": c["end_date"] or "مفتوح", "الحالة": c["status"]} for c in cs]),
                         use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد عقود. أضفها من صفحة «العقود».")
