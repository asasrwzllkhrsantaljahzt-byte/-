import streamlit as st
import pandas as pd
import hub_engine as E
import security
from db import query_all, query_one
from ui import set_page


def _fmt(n) -> str:
    return f"{float(n or 0):,.0f}"


def _card(col, label, value, help_text=None):
    with col:
        with st.container(border=True):
            st.metric(label, value, help=help_text)


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


REGISTRATION_ACTIONS = [
    ("الشركات والموظفون", "🏢", "إدارة الشركات وتسجيل الموظفين.", "companies", "#0f766e"),
    ("المتعهدون", "🤝", "إدارة بيانات المتعهدين ومستحقاتهم.", "contractors", "#2563eb"),
    ("المندوبون", "🧑‍💼", "إدارة المندوبين ونسب العمولات.", "representatives", "#7c3aed"),
    ("العقود والوثائق", "📄", "إدارة العقود والوثائق ومواعيد انتهائها.", "contracts_documents", "#d97706"),
    ("الحركات المالية", "💸", "تسجيل تحويلات العملاء والاستلام والصرف.", "financial", "#059669"),
    ("فواتير العملاء", "🧾", "إصدار ومراجعة الفواتير.", "invoices", "#be123c"),
]
VIEW_ACTIONS = [
    ("لوحة التحكم", "🏠", "عرض مؤشرات النظام والحسابات.", "dashboard", "#0f766e"),
    ("مراجعة وإقفال الشهر", "📅", "مراجعة نتائج الشهر وإقفاله.", "month_close", "#dc2626"),
    ("كشوف الحسابات", "📑", "عرض وتصدير كشوف حسابات الجهات.", "statements", "#4f46e5"),
    ("التقارير المالية والإدارية", "📊", "التقارير الشهرية والسنوية والأرصدة.", "reports", "#9333ea"),
]


def render_action_menu(allowed, actions):
    permission_pages = {"الحركات المالية": "التحويلات والحساب الشهري"}
    visible_actions = [
        action for action in actions
        if permission_pages.get(action[0], action[0]) in allowed or (
            action[0] == "العقود والوثائق" and any(page in allowed for page in ("العقود", "الوثائق"))
        )
    ]
    if not visible_actions:
        st.info("لا توجد وظائف متاحة لهذا الحساب في هذه القائمة.")
        return

    style = "".join(
        f".st-key-dash_tool_{slug} button{{background:{color}!important;"
        f"border-color:{color}!important;color:#fff!important;min-height:3rem}}"
        f".st-key-dash_tool_{slug} button:hover{{filter:brightness(.9)}}"
        for _, _, _, slug, color in visible_actions
    )
    st.markdown(f"<style>{style}</style>", unsafe_allow_html=True)
    columns = st.columns(3)
    for index, (title, icon, description, slug, _) in enumerate(visible_actions):
        with columns[index % len(columns)]:
            with st.container(border=True):
                st.markdown(f"### {icon} {title}")
                st.caption(description)
                st.button(
                    f"فتح {title}",
                    key=f"dash_tool_{slug}",
                    use_container_width=True,
                    on_click=set_page,
                    args=(permission_pages.get(title, title),),
                )


def _months_chart(month):
    import altair as alt
    import hub_close as C
    df = C.year_df(month[:4])
    if len(df) < 2:
        return
    st.markdown(f"##### 📈 هامش الشركة والربح بعد المصروفات خلال {month[:4]}")
    long = df.melt(id_vars="الشهر", value_vars=["هامش الشركة قبل المصروفات", "صافي الربح بعد المصروفات"],
                   var_name="المؤشر", value_name="المبلغ")
    st.altair_chart(alt.Chart(long).mark_bar().encode(x="الشهر:N", y="المبلغ:Q", color="المؤشر:N", xOffset="المؤشر:N"),
                    use_container_width=True)


def render():
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
