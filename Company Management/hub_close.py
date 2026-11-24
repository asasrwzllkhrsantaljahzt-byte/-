"""Month review checklist before closing, and report datasets built from the engine."""
import pandas as pd
import hub_engine as E
import hub_accounts as HA
import vouchers as V
from db import query_all


def review(month) -> dict:
    """{'items': [(level, text)], 'res': engine result}. level: warn | info | ok"""
    month = E.norm_month(month)
    res = E.compute_month(month)
    items = []
    for w in res["warnings"]:
        items.append(("warn", w))
    for co in res["companies"]:
        for r in co["employees"]:
            if r["days"] > 0 and r["transferred"] == 0:
                items.append(("warn", f"{co['company']} — {r['employee']}: لم يُسجَّل لها أي تحويل من العميل لهذا الشهر."))
            elif r["days"] > 0 and r["ratio"] < 1:
                items.append(("info", f"{co['company']} — {r['employee']}: المحوّل أقل من التكلفة (نسبة {r['ratio']*100:.1f}%) فتُخفَّض المكافأة والعمولات بنفس النسبة."))
            if r["net"] < 0:
                items.append(("warn", f"{co['company']} — {r['employee']}: صافي سالب ({r['net']:,.2f})."))
        if co["rep_id"] is None and co["net"] > 0:
            items.append(("info", f"{co['company']}: لا يوجد مندوب ساري في هذا الشهر."))
    coll = HA.collection_rows(month)
    short = [r for r in coll if r["diff"] > 0.004]
    if short:
        items.append(("info", f"{len(short)} موظفة لم تُعد كامل المبلغ بعد (المتبقي {sum(r['diff'] for r in short):,.2f}). لا يمنع الإقفال."))
    prev = _prev(month)
    if prev and E.compute_live(prev)["companies"] and not E.is_closed(prev):
        items.append(("info", f"الشهر السابق {prev} لم يُقفل بعد."))
    if not res["companies"]:
        items.append(("warn", "لا توجد بيانات لهذا الشهر."))
    if not items:
        items.append(("ok", "لا ملاحظات. الشهر جاهز للإقفال."))
    return {"items": items, "res": res, "blocking": not res["companies"]}


def _prev(month):
    y, m = int(month[:4]), int(month[5:7])
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    p = f"{y:04d}-{m:02d}"
    return p if p in E.month_options() else None


def employees_df(res) -> pd.DataFrame:
    rows = []
    for co in res["companies"]:
        for r in co["employees"]:
            rows.append({"الشركة": co["company"], "الموظفة": r["employee"], "الأيام": f"{r['days']}/{r['month_days']}",
                         "التكلفة": r["cost_eff"], "حوّل العميل": r["transferred"], "النسبة %": round(r["ratio"] * 100, 1),
                         "المردود للعميل": r["refund"], "المكافأة": r["bonus_due"], "المتعهد": r["contractor_due"],
                         "العمولة الخارجية": r["external_due"], "الصافي": r["net"], "تعيده للشركة": r["employee_returns"]})
    return pd.DataFrame(rows)


def companies_df(res) -> pd.DataFrame:
    return pd.DataFrame([{"الشركة": c["company"], "عدد الموظفات": sum(1 for r in c["employees"] if r["days"] > 0),
                          "التكلفة": c["cost_eff"], "حوّل العميل": c["transferred"], "المردود للعميل": c["refund"],
                          "المكافآت": c["bonus_due"], "المتعهدون": c["contractor_due"], "العمولة الخارجية": c["external_due"],
                          "الصافي": c["net"], "المندوب": c["rep_name"] or "—", "عمولة المندوب": c["rep_due"], "هامش الشركة": c["margin"]}
                         for c in res["companies"]])


def totals_df(res) -> pd.DataFrame:
    t = res["totals"]
    return pd.DataFrame([{"البند": k, "المبلغ": t[f]} for k, f in (
        ("الموظفات", "employees"), ("التكلفة (إيراد متوقع)", "cost_eff"), ("حوّله العميل", "transferred"), ("الإيراد الفعلي", "revenue"),
        ("المردود للعميل", "refund"), ("المكافآت", "bonus_due"), ("المتعهدون", "contractor_due"), ("العمولات الخارجية", "external_due"),
        ("الصافي", "net"), ("عمولة المناديب", "rep_due"), ("هامش الشركة", "margin"))])


def balances_df(month=None) -> pd.DataFrame:
    rows = []
    for pt, lab in (("company", "عميل (مردود)"), ("employee", "موظفة (تعيد للشركة)"), ("contractor", "متعهد / عمولة خارجية"), ("representative", "مندوب")):
        for b in V.party_balances(pt, month):
            if abs(b["due"]) > 0.004 or abs(b["settled"]) > 0.004:
                rows.append({"النوع": lab, "الاسم": b["name"], "المستحق": b["due"], "المسدَّد": b["settled"], "المتبقي": b["balance"]})
    return pd.DataFrame(rows)


def year_df(year) -> pd.DataFrame:
    rows = []
    cash = V.other_payment_totals()
    months = {x for x in E.month_options() if x.startswith(str(year))}
    months.update(m for m in cash if m.startswith(str(year)))
    for m in sorted(months):
        t = E.compute_month(m)["totals"]
        operating = cash.get(m, {}).get("operating_expense", 0.0)
        owner_draw = cash.get(m, {}).get("owner_draw", 0.0)
        adjusted_profit = round(t["margin"] - operating, 2)
        if t["employees"] or t["transferred"] or operating or owner_draw:
            rows.append({"الشهر": m, "الموظفات": t["employees"], "حوّل العميل": t["transferred"], "الإيراد الفعلي": t["revenue"],
                         "المردود": t["refund"], "الصافي": t["net"], "عمولة المناديب": t["rep_due"],
                         "هامش الشركة قبل المصروفات": t["margin"], "المصروفات التشغيلية": operating,
                         "صافي الربح بعد المصروفات": adjusted_profit, "مسحوبات المالك (تسوية سنوية)": owner_draw,
                         "المتبقي بعد المسحوبات": round(adjusted_profit - owner_draw, 2)})
    return pd.DataFrame(rows)
