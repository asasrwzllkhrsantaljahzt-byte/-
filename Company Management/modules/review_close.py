import re
import sqlite3
import streamlit as st
import pandas as pd
from datetime import date
from db import query_all, query_one, execute
from audit import log_audit
from finance_engine import ensure_finance_schema, calculate_month
from modules.transactions import CATEGORIES
from ui import toast_flash, norm_month, MONTH_EXAMPLE

CAT_AR = {c[1]: c[0] for c in CATEGORIES}
STATUS_AR = {"approved": "معتمدة", "pending_review": "قيد المراجعة", "rejected": "مرفوضة/ملغاة"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _flash(msg: str):
    st.session_state["_rc_flash"] = msg
    st.rerun()


def _fmt(n) -> str:
    return f"{float(n or 0):,.2f}"


# ------------------------------------------------------------ review of ledger
def _tab_review():
    st.caption("الحركة «قيد المراجعة» لا تدخل في الإيراد أو الهامش حتى تُعتمد. الحركة المعتمدة لا تُحذف ولا تُعدَّل، "
               "ويمكن فقط إلغاؤها مع تسجيل السبب، ويبقى أثرها ظاهراً في سجل التدقيق.")
    c1, c2 = st.columns([1, 1])
    with c1:
        sf = st.selectbox("الحالة", ["قيد المراجعة", "معتمدة", "مرفوضة/ملغاة", "الكل"], key="rc_status_filter")
    with c2:
        month = st.text_input("الشهر (مثل 2026-03) أو اتركه فارغاً", key="rc_month_filter").strip()
    inv = {v: k for k, v in STATUS_AR.items()}
    sql = """SELECT t.id, t.tx_date, t.month_ref, t.category, t.direction, t.amount, t.review_status,
                    e.full_name AS employee, c.name AS company, t.document_ref, t.description
             FROM financial_transactions t
             LEFT JOIN employees e ON e.id = t.employee_id
             LEFT JOIN companies c ON c.id = t.company_id WHERE 1=1"""
    params = []
    if sf != "الكل":
        sql += " AND t.review_status=?"
        params.append(inv[sf])
    if month:
        month = norm_month(month)
        if not month:
            st.error(f"صيغة الشهر غير صحيحة. اكتب السنة ثم الشهر، مثال: {MONTH_EXAMPLE}")
            return
        sql += " AND t.month_ref=?"
        params.append(month)
    sql += " ORDER BY t.id DESC LIMIT 300"
    rows = query_all(sql, tuple(params))
    if not rows:
        st.info("لا توجد حركات مطابقة.")
        return
    df = pd.DataFrame(rows)
    show = df.copy()
    show["category"] = show["category"].map(lambda x: CAT_AR.get(x, x))
    show["direction"] = show["direction"].map({"in": "وارد", "out": "صادر", "info": "بيان"})
    show["review_status"] = show["review_status"].map(STATUS_AR)
    show.columns = ["الرقم", "التاريخ", "الشهر", "النوع", "الاتجاه", "المبلغ", "الحالة", "الموظف", "الشركة", "المستند", "الوصف"]
    st.dataframe(show, use_container_width=True, hide_index=True)
    st.caption(f"عدد الحركات المعروضة: {len(rows)} (الحد الأقصى 300)")

    st.markdown("#### اتخاذ إجراء على حركة")
    labels = {f"#{r['id']} | {r['tx_date']} | {CAT_AR.get(r['category'], r['category'])} | {_fmt(r['amount'])} | {STATUS_AR[r['review_status']]}": r
              for r in rows}
    sel = st.selectbox("اختر الحركة", list(labels.keys()), key="rc_tx_sel")
    r = labels[sel]
    if r["review_status"] == "pending_review":
        actions = {"approve": "اعتماد الحركة", "reject": "رفض الحركة"}
    elif r["review_status"] == "approved":
        actions = {"cancel": "إلغاء الحركة المعتمدة (يتطلب سبباً)"}
    else:
        actions = {"reopen": "إعادة الحركة إلى «قيد المراجعة»"}
    with st.form("rc_action_form"):
        act = st.selectbox("الإجراء", list(actions.keys()), format_func=lambda k: actions[k], key="rc_action")
        reason = st.text_input("السبب / الملاحظة", key="rc_reason")
        sub = st.form_submit_button("تنفيذ الإجراء")
    if not sub:
        return
    new_status = {"approve": "approved", "reject": "rejected", "cancel": "rejected", "reopen": "pending_review"}[act]
    if act in ("cancel", "reject") and not reason.strip():
        st.error("اكتب سبب الرفض/الإلغاء.")
        return
    try:
        stamp = f"[{actions[act]}: {reason.strip()}]" if reason.strip() else f"[{actions[act]}]"
        execute("""UPDATE financial_transactions
                   SET review_status=?, description=CASE WHEN description IS NULL OR description='' THEN ? ELSE description || ' ' || ? END,
                       updated_at=CURRENT_TIMESTAMP WHERE id=?""", (new_status, stamp, stamp, r["id"]))
        log_audit("financial_transactions", r["id"], "STATUS_CHANGE",
                  {"review_status": r["review_status"], "amount": r["amount"], "month_ref": r["month_ref"]},
                  {"review_status": new_status}, note=f"{actions[act]}: {reason.strip()}")
        _flash(f"تم تنفيذ الإجراء على الحركة رقم {r['id']}.")
    except sqlite3.IntegrityError as ex:
        st.error(f"رفضت قاعدة البيانات العملية: {ex}")
    except Exception as ex:  # noqa: BLE001
        st.error(f"تعذر التنفيذ: {ex}")


# ------------------------------------------------------------- month closing
def _tab_close():
    st.caption("إقفال الشهر يجمّد نتائجه: لا تُضاف إليه حركات ولا تُعدَّل ولا يُعاد احتسابه. إعادة الفتح ممكنة مع تسجيل السبب.")
    month = norm_month(st.text_input("الشهر (مثل 2026-03)", value=date.today().strftime("%Y-%m"), key="rc_close_month"))
    if not month:
        st.error(f"صيغة الشهر غير صحيحة. اكتب السنة ثم الشهر، مثال: {MONTH_EXAMPLE}")
        return
    ensure_finance_schema()
    stored = query_all("""SELECT m.id, e.full_name AS employee, c.name AS company, m.active_days, m.client_agreed_total,
                                 m.recorded_wages_total, m.contractor_entitlements_total, m.representative_entitlements_total,
                                 m.approved_company_revenue_total, m.pending_review_total, m.company_margin, m.status
                          FROM monthly_employee_accounts m
                          JOIN employees e ON e.id = m.employee_id JOIN companies c ON c.id = m.company_id
                          WHERE m.month_ref=? ORDER BY m.id""", (month,))
    n_closed = sum(1 for x in stored if x["status"] == "approved")
    is_closed = bool(stored) and n_closed == len(stored)
    pend = query_one("""SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS total FROM financial_transactions
                        WHERE month_ref=? AND review_status='pending_review'""", (month,))

    if is_closed:
        st.success(f"شهر {month} معتمد ومقفل ({n_closed} نتيجة).")
    elif stored:
        st.info(f"شهر {month} محتسب وغير مقفل ({len(stored)} نتيجة).")
    else:
        st.info(f"لم يُحتسب شهر {month} بعد.")
    if pend["n"]:
        st.warning(f"يوجد {pend['n']} حركة قيد المراجعة بإجمالي {_fmt(pend['total'])} في هذا الشهر، وهي مستبعدة من الإيراد والهامش. "
                   "راجعها من التبويب الأول قبل الإقفال.")

    if stored:
        df = pd.DataFrame(stored).drop(columns=["id"])
        df["status"] = df["status"].map({"calculated": "محتسب", "approved": "معتمد ومقفل", "void": "ملغى"})
        df.columns = ["الموظف", "الشركة", "أيام العمل", "المتفق مع العميل", "الأجور المسجلة", "مستحق المتعهدين",
                      "مستحق المندوبين", "الإيراد المعتمد", "قيد المراجعة", "هامش الشركة", "الحالة"]
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.metric("إجمالي هامش الشركة", _fmt(sum(float(x["company_margin"] or 0) for x in stored)))

    if not is_closed:
        st.markdown("#### احتساب الشهر")
        if st.button("تشغيل محرك الاحتساب لهذا الشهر", key="rc_calc_btn"):
            try:
                res = calculate_month(month)
                _flash(f"تم احتساب {len(res)} تعيين لشهر {month}." if res else f"لا توجد تعيينات نشطة في شهر {month}.")
            except Exception as ex:  # noqa: BLE001
                st.error(f"تعذر الاحتساب: {ex}")

        st.markdown("#### اعتماد وإقفال الشهر")
        confirm = st.checkbox("راجعت الأرقام وأؤكد اعتماد الشهر وإقفاله", key="rc_close_confirm")
        if st.button("اعتماد وإقفال الشهر", key="rc_close_btn"):
            if not confirm:
                st.error("فعّل خانة التأكيد أولاً.")
            else:
                try:
                    res = calculate_month(month)  # fresh numbers right before freezing
                    if not res:
                        st.error("لا توجد تعيينات نشطة في هذا الشهر لإقفاله.")
                    else:
                        execute("UPDATE monthly_employee_accounts SET status='approved', updated_at=CURRENT_TIMESTAMP "
                                "WHERE month_ref=? AND status='calculated'", (month,))
                        total = round(sum(x["company_margin"] for x in res), 2)
                        log_audit("monthly_employee_accounts", 0, "STATUS_CHANGE", {"month": month, "status": "calculated"},
                                  {"month": month, "status": "approved", "rows": len(res), "total_margin": total},
                                  note=f"اعتماد وإقفال شهر {month}")
                        _flash(f"تم اعتماد وإقفال شهر {month} ({len(res)} نتيجة، إجمالي الهامش {_fmt(total)}).")
                except Exception as ex:  # noqa: BLE001
                    st.error(f"تعذر الإقفال: {ex}")
    else:
        st.markdown("#### إعادة فتح الشهر")
        reason = st.text_input("سبب إعادة الفتح (إلزامي)", key="rc_reopen_reason")
        if st.button("إعادة فتح الشهر", key="rc_reopen_btn"):
            if not reason.strip():
                st.error("اكتب سبب إعادة الفتح.")
            else:
                try:
                    execute("UPDATE monthly_employee_accounts SET status='calculated', updated_at=CURRENT_TIMESTAMP "
                            "WHERE month_ref=? AND status='approved'", (month,))
                    log_audit("monthly_employee_accounts", 0, "STATUS_CHANGE", {"month": month, "status": "approved"},
                              {"month": month, "status": "calculated"}, note=f"إعادة فتح شهر {month}: {reason.strip()}")
                    _flash(f"تمت إعادة فتح شهر {month}. أعد احتسابه ثم أقفله بعد التصحيح.")
                except Exception as ex:  # noqa: BLE001
                    st.error(f"تعذر إعادة الفتح: {ex}")


def render():
    toast_flash("_rc_flash")
    t1, t2 = st.tabs(["مراجعة الحركات", "إقفال الأشهر"])
    with t1:
        _tab_review()
    with t2:
        _tab_close()
