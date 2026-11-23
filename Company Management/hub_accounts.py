"""Party accounts on the new engine: what each party is owed / owes per work month.
company -> refund owed to the client; employee -> amount she returns to the company;
contractor -> contractor + external commissions; representative -> % of company net."""
import hub_engine as E
import vouchers as V
from db import query_all

LABELS = {  # (due, settled, balance)
    "company": ("المردود المستحق للعميل", "المصروف للعميل", "المتبقي للعميل"),
    "employee": ("المطلوب منها للشركة", "المحصَّل منها", "المتبقي عليها"),
    "contractor": ("المستحق له", "المصروف له", "المتبقي له"),
    "representative": ("المستحق له", "المصروف له", "المتبقي له"),
}


_CACHE = {"ver": None, "data": None}


def all_dues() -> dict:
    """{party_type: {party_id: {month: amount}}} computed live for every month (cached per database version)."""
    from datetime import date
    from db import data_version
    ver = (data_version(), date.today())
    if _CACHE["ver"] != ver:
        _CACHE["data"], _CACHE["ver"] = _all_dues(), ver
    return _CACHE["data"]


def _all_dues() -> dict:
    out = {k: {} for k in LABELS}

    def add(pt, pid, m, amt):
        if pid is None or not amt:
            return
        d = out[pt].setdefault(pid, {})
        d[m] = round(d.get(m, 0.0) + amt, 2)
    for m in E.month_options():
        res = E.compute_month(m)
        for co in res["companies"]:
            add("company", co["company_id"], m, co["refund"])
            add("representative", co["rep_id"], m, co["rep_due"])
            for r in co["employees"]:
                add("employee", r["employee_id"], m, r["employee_returns"])
                add("contractor", r["contractor_id"], m, r["contractor_due"])
                add("contractor", r["external_id"], m, r["external_due"])
    return out


def dues_of(party_type, party_id) -> dict:
    return dict(all_dues().get(party_type, {}).get(party_id, {}))


def collection_rows(month, company_id=None) -> list:
    """One row per employee for the work month: owed back to the company vs actually collected (receipt vouchers)."""
    res = E.compute_month(month, company_id)
    got = {}
    for v in query_all("SELECT * FROM vouchers WHERE party_type='employee' AND status='issued'"):
        if V.voucher_month(v) == month:
            got[v["party_id"]] = got.get(v["party_id"], 0.0) + (float(v["amount"]) if v["kind"] == "receipt" else -float(v["amount"]))
    rows = []
    for co in res["companies"]:
        for r in co["employees"]:
            if r["days"] == 0 and r["transferred"] == 0:
                continue
            owed = r["employee_returns"]
            c = round(got.get(r["employee_id"], 0.0), 2)
            rows.append({"company": co["company"], "employee_id": r["employee_id"], "employee": r["employee"],
                         "transferred": r["transferred"], "bonus_due": r["bonus_due"], "owed": owed,
                         "collected": c, "diff": round(owed - c, 2)})
    return rows


