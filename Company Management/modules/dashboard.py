import streamlit as st
import pandas as pd
from datetime import datetime
import app_settings
import backup
import security
import hub_engine as E
from db import query_all, query_one
from ui import goto_button


def _fmt(n) -> str:
    return f"{float(n or 0):,.0f}"


def _alerts():
    notes = []
    try:
        from modules import contracts
        al = contracts.expiry_alerts()
        if al["overdue"]:
            notes.append(("error", f"{len(al['overdue'])} عقد ساري انتهت مدته ولم يُنهَ — راجع صفحة العقود."))
        if al["soon"]:
            notes.append(("warning", f"{len(al['soon'])} عقد ينتهي خلال {al['days']} يوماً."))
    except Exception:  # noqa: BLE001
        pass
    try:
        import documents
        dal = documents.expiry_alerts()
        if dal["expired"]:
            notes.append(("error", f"{len(dal['expired'])} وثيقة منتهية — راجع صفحة الوثائق."))
        if dal["soon"]:
            notes.append(("warning", f"{len(dal['soon'])} وثيقة تنتهي خلال {dal['days']} يوماً."))
    except Exception:  # noqa: BLE001
        pass
    try:
        days = app_settings.get_int("backup_reminder_days")
        items = backup.list_backups()
        if not items:
            notes.append(("warning", "لا توجد نسخة احتياطية بعد. أنشئ واحدة من صفحة النسخ الاحتياطي."))
        else:
            age = (datetime.now() - datetime.strptime(items[0]["modified"], "%Y-%m-%d %H:%M:%S")).days
            if age >= days:
                notes.append(("warning", f"آخر نسخة احتياطية قبل {age} يوماً (حد التذكير {days})."))
    except Exception:  # noqa: BLE001
        pass
    for kind, msg in notes:
        getattr(st, kind)(msg)


def _card(col, label, value, help_text=None):
    with col:
        with st.container(border=True):
            st.metric(label, value, help=help_text)


def _setup_checklist():
    """Shown while the system is still empty: tells the user what to do next."""
    steps = [
        ("أضف شركة عميلة", query_one("SELECT COUNT(*) c FROM companies")["c"] > 0, "الشركات والموظفون"),
        ("أضف موظفاً داخل الشركة", query_one("SELECT COUNT(*) c FROM employee_placements")["c"] > 0, "الشركات والموظفون"),
        ("سجّل أول تحويل من العميل", query_one("SELECT COUNT(*) c FROM client_transfers")["c"] > 0, "التحويلات والحساب الشهري"),
    ]
    if all(done for _, done, _ in steps):
        return
    with st.container(border=True):
        st.markdown("#### 🚀 ابدأ من هنا")
        cols = st.columns(len(steps))
        for i, (label, done, page) in enumerate(steps):
            with cols[i]:
                st.markdown(("✅ " if done else f"**{i + 1}.** ") + label)
                if not done and page in security.allowed_pages((security.current_user() or {}).get("role", "")):
                    goto_button("افتح الصفحة", page, f"dash_step_{i}")


_SEARCH = [("employee", "employees", "full_name"), ("company", "companies", "name"),
           ("contractor", "contractors", "name"), ("representative", "representatives", "name")]
_PTYPE_PAGE = {"employee": "الشركات والموظفون", "company": "الشركات والموظفون", "contractor": "المتعهدون",
               "representative": "المندوبون"}


def _open_profile(ptype, pid):
    from modules import party_profile
    party_profile.open_profile(ptype, pid)


def _global_search():
    import vouchers as V
    st.markdown("##### 🔎 بحث سريع")
    q = st.text_input("ابحث", key="dash_search", label_visibility="collapsed",
                      placeholder="اكتب اسم موظف أو شركة أو متعهد أو مندوب (حرفان على الأقل) ثم اضغط Enter").strip()
    if len(q) < 2:
        return
    like = "%" + q.replace("%", "").replace("_", "") + "%"
    found = False
    cols = st.columns(4)
    n = 0
    for ptype, table, col in _SEARCH:
        for r in query_all(f"SELECT id, {col} AS n FROM {table} WHERE {col} LIKE ? ORDER BY {col} LIMIT 6", (like,)):
            found = True
            cols[n % 4].button(f"{V.PARTY_AR[ptype]} · {r['n']}", key=f"ds_{ptype}_{r['id']}", on_click=_open_profile,
                               args=(ptype, r["id"]), use_container_width=True)
            n += 1
    if not found:
        st.caption("لا توجد نتائج مطابقة.")
    else:
        st.caption("اضغط على أي نتيجة لفتح ملف الجهة (حسابها وعلاقاتها وإذونها).")


def _company_table(res):
    rows = []
    for c in res["companies"]:
        rows.append({"الشركة": c["company"], "الموظفون": len(c["employees"]), "المحوّل": c["transferred"], "الإيراد": c["revenue"],
                     "المردود للعميل": c["refund"], "المكافآت": c["bonus_due"], "المتعهدون": c["contractor_due"],
                     "عمولة خارجية": c["external_due"], "الصافي": c["net"],
                     "المندوب": f"{c['rep_name']} ({c['rep_percent']:g}%)" if c["rep_name"] else "—",
                     "عمولة المندوب": c["rep_due"], "الهامش": c["margin"]})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                 column_config={k: st.column_config.Column(alignment="right") for k in rows[0]})


def _quick_actions():
    allowed = security.allowed_pages((security.current_user() or {}).get("role", "viewer"))
    if not security.can_write():
        return
    from ui import set_page
    acts = [("➕ شركة جديدة", "الشركات والموظفون"), ("💸 تحويل جديد", "التحويلات والحساب الشهري"),
            ("📥 تحصيل من موظفة", "التحصيل والمدفوعات"), ("📤 إذن صرف", "التحصيل والمدفوعات"),
            ("🔒 إقفال الشهر", "مراجعة وإقفال الشهر"), ("📊 التقارير", "التقارير المالية والإدارية")]
    acts = [a for a in acts if a[1] in allowed]
    cols = st.columns(len(acts)) if acts else []
    for i, (lab, pg) in enumerate(acts):
        cols[i].button(lab, key=f"qa_{i}", use_container_width=True, on_click=set_page, args=(pg,))


def _months_chart(month):
    import altair as alt
    import hub_close as C
    df = C.year_df(month[:4])
    if len(df) < 2:
        return
    st.markdown(f"##### 📈 الصافي وهامش الشركة خلال {month[:4]}")
    long = df.melt(id_vars="الشهر", value_vars=["الصافي", "هامش الشركة"], var_name="المؤشر", value_name="المبلغ")
    st.altair_chart(alt.Chart(long).mark_bar().encode(x="الشهر:N", y="المبلغ:Q", color="المؤشر:N", xOffset="المؤشر:N"),
                    use_container_width=True)


def render():
    can_open = "ملف الجهة" in security.allowed_pages((security.current_user() or {}).get("role", "viewer"))
    if can_open:
        _global_search()
    _alerts()
    _quick_actions()
    _setup_checklist()

    months = E.month_options()
    head1, head2 = st.columns([3, 1])
    with head2:
        month = st.selectbox("الشهر", months, key="dash_month", label_visibility="collapsed")
    with head1:
        st.markdown(f"##### 📊 مؤشرات شهر {month}")
    res = E.compute_month(month)
    t = res["totals"]

    r1 = st.columns(4)
    _card(r1[0], "الموظفون العاملون هذا الشهر", t["employees"])
    _card(r1[1], "المحوّل من العملاء", _fmt(t["transferred"]), "ما حوّله العملاء فعلاً عن شهر العمل هذا")
    _card(r1[2], "إيراد الشركة", _fmt(t["revenue"]), "المحوّل بحدود التكلفة المتفق عليها")
    _card(r1[3], "هامش الشركة (الربح)", _fmt(t["margin"]), "الصافي بعد عمولات المناديب")
    r2 = st.columns(4)
    _card(r2[0], "مكافآت الموظفين المستحقة", _fmt(t["bonus_due"]))
    _card(r2[1], "مستحقات المتعهدين", _fmt(t["contractor_due"]))
    _card(r2[2], "العمولات الخارجية", _fmt(t["external_due"]))
    _card(r2[3], "مستحقات المناديب", _fmt(t["rep_due"]))
    r3 = st.columns(3)
    _card(r3[0], "المردود للعملاء", _fmt(t["refund"]), "ما حُوِّل زيادة عن التكلفة ويُرد للعميل")
    _card(r3[1], "على الموظفين إعادته للشركة", _fmt(t["employee_returns"]), "المحوّل للموظف ناقص مكافأته")
    _card(r3[2], "موظفون لم يُحوَّل لهم", t["not_transferred"], "عملوا في الشهر ولم يُسجَّل لهم تحويل")
    for w in res["warnings"]:
        st.warning(w)

    counts = query_one("""SELECT
        (SELECT COUNT(*) FROM companies WHERE status='active') AS co,
        (SELECT COUNT(*) FROM employee_placements WHERE status='active') AS emp,
        (SELECT COUNT(*) FROM contractors WHERE status='active') AS con,
        (SELECT COUNT(*) FROM representatives WHERE status='active') AS rep""")
    try:
        ncontracts = query_one("SELECT COUNT(*) c FROM contracts WHERE status='active'")["c"]
    except Exception:  # noqa: BLE001
        ncontracts = 0
    c5 = st.columns(5)
    _card(c5[0], "الشركات النشطة", counts["co"])
    _card(c5[1], "الموظفون النشطون", counts["emp"])
    _card(c5[2], "المتعهدون النشطون", counts["con"])
    _card(c5[3], "المندوبون النشطون", counts["rep"])
    _card(c5[4], "العقود السارية", ncontracts)

    _months_chart(month)
    st.markdown("---")
    st.markdown("### 🏦 حساب كل شركة")
    if res["companies"]:
        _company_table(res)
    else:
        st.info("لا يوجد موظفون يعملون في هذا الشهر بعد.")

    st.markdown("---")
    left, right = st.columns(2)
    with left:
        st.markdown("**العقود القريبة من الانتهاء**")
        try:
            from modules import contracts as C
            al = C.expiry_alerts()
            rows = [{"العقد": f"#{r['id']}", "النوع": C.TYPE_AR[r["contract_type"]],
                     "الطرف": C._party_name(r["party_type"], r["party_id"]), "ينتهي": r["end_date"]}
                    for r in al["overdue"] + al["soon"]]
        except Exception:  # noqa: BLE001
            rows = []
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.success("لا توجد عقود تقترب من الانتهاء.")
    with right:
        st.markdown("**آخر النشاطات**")
        if security.can_write() or (security.current_user() or {}).get("role") == "admin":
            acts = query_all("""SELECT changed_at, changed_by, note FROM audit_log
                                WHERE note IS NOT NULL AND note NOT LIKE '%دخول%' ORDER BY id DESC LIMIT 8""")
            if acts:
                st.dataframe(pd.DataFrame(acts).rename(columns={"changed_at": "الوقت", "changed_by": "المستخدم", "note": "العملية"}),
                             use_container_width=True, hide_index=True)
            else:
                st.info("لا توجد نشاطات بعد.")
        else:
            st.caption("سجل النشاطات متاح للمدير والمحاسب.")
