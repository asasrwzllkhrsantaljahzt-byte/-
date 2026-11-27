"""Notification bell: everything that needs the accountant's attention, with the page that fixes it."""
import logging
from datetime import date, datetime, timedelta

import app_settings
import hub_engine as E
import hub_accounts as HA
import vouchers as V

HIGH, MID, LOW = "high", "mid", "low"
_LOGGER = logging.getLogger(__name__)


def _month_end(m):
    return E.month_bounds(m)[1]


def collect(today: date = None) -> list:
    """[{level, text, page}] most urgent first. Each source is isolated so one failure never hides the others."""
    today = today or date.today()
    out = []

    failures = []

    def safe(fn, source):
        try:
            fn()
        except Exception:
            _LOGGER.exception("Failed to collect %s notifications", source)
            failures.append(source)

    def contracts():
        if not app_settings.get_bool("contract_alerts_enabled"):
            return
        from modules import contracts as C
        al = C.expiry_alerts(today)
        if al["overdue"]:
            out.append({"level": HIGH, "text": f"{len(al['overdue'])} عقد ساري انتهت مدته ولم يُنهَ.", "page": "العقود"})
        if al["soon"]:
            out.append({"level": MID, "text": f"{len(al['soon'])} عقد ينتهي خلال {al['days']} يوماً.", "page": "العقود"})

    def docs():
        if not app_settings.get_bool("doc_alerts_enabled"):
            return
        import documents as D
        al = D.expiry_alerts(today)
        if al["expired"]:
            out.append({"level": HIGH, "text": f"{len(al['expired'])} وثيقة منتهية.", "page": "الوثائق"})
        if al["soon"]:
            out.append({"level": MID, "text": f"{len(al['soon'])} وثيقة تنتهي خلال {al['days']} يوماً.", "page": "الوثائق"})

    def months():
        monthly_enabled = app_settings.get_bool("month_alerts_enabled")
        dues_enabled = app_settings.get_bool("dues_alerts_enabled")
        if not monthly_enabled and not dues_enabled:
            return
        cur = today.strftime("%Y-%m")
        unclosed, dues_c, dues_p, no_tr, review = [], 0.0, 0.0, [], []
        n_days = app_settings.get_int("dues_alert_days") if dues_enabled else 0
        prev = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        for m in E.month_options():
            if m >= cur:
                continue
            res = E.compute_month(m)
            if not res["companies"]:
                continue
            if monthly_enabled and not res.get("closed"):
                unclosed.append(m)
                if res["warnings"]:
                    review.append(m)
            if monthly_enabled and m == prev and res["totals"]["not_transferred"]:
                no_tr.append(res["totals"]["not_transferred"])
            if dues_enabled and _month_end(m) + timedelta(days=n_days) < today:
                dues_c += sum(r["diff"] for r in HA.collection_rows(m) if r["diff"] > 0)
                for pt in ("contractor", "representative", "company"):
                    dues_p += sum(b["balance"] for b in V.party_balances(pt, m) if b["balance"] > 0)
        if monthly_enabled and unclosed:
            out.append({"level": MID, "text": "أشهر لم تُقفل بعد: " + "، ".join(sorted(unclosed)[:4]) + ("…" if len(unclosed) > 4 else ""),
                        "page": "مراجعة وإقفال الشهر"})
        if monthly_enabled and review:
            out.append({"level": MID, "text": f"شهر {review[-1]} فيه ملاحظات تنتظر المراجعة.", "page": "مراجعة وإقفال الشهر"})
        if monthly_enabled and no_tr:
            out.append({"level": MID, "text": f"{no_tr[0]} موظفة بلا أي تحويل من العميل عن الشهر الماضي ({prev}).", "page": "التحويلات والحساب الشهري"})
        if dues_enabled and dues_c > 0.004:
            out.append({"level": MID, "text": f"مبالغ لم تُحصَّل من الموظفات ({dues_c:,.2f}) مضى عليها أكثر من {n_days} يوماً.", "page": "التحويلات والحساب الشهري"})
        if dues_enabled and dues_p > 0.004:
            out.append({"level": MID, "text": f"مستحقات غير مدفوعة ({dues_p:,.2f}) للمتعهدين/المناديب/العملاء مضى عليها أكثر من {n_days} يوماً.",
                        "page": "التحويلات والحساب الشهري"})

    def backup():
        if not app_settings.get_bool("backup_alerts_enabled"):
            return
        import backup as B
        days = app_settings.get_int("backup_reminder_days")
        items = B.list_backups()
        if not items:
            out.append({"level": MID, "text": "لا توجد نسخة احتياطية. خذ نسخة الآن.", "page": "النسخ الاحتياطي والاستعادة"})
            return
        last = datetime.strptime(items[0]["modified"], "%Y-%m-%d %H:%M:%S").date()
        if (today - last).days >= days:
            out.append({"level": LOW, "text": f"آخر نسخة احتياطية قبل {(today - last).days} يوماً.", "page": "النسخ الاحتياطي والاستعادة"})

    for source, fn in (("العقود", contracts), ("الوثائق", docs), ("الإقفالات والمستحقات", months),
                       ("النسخ الاحتياطي", backup)):
        safe(fn, source)
    if failures:
        out.append({
            "level": HIGH,
            "text": "تعذر التحقق من بعض التنبيهات (" + "، ".join(failures) + "). أعد المحاولة أو راجع سجل النظام.",
            "page": "",
            "system_error": True,
        })
    order = {HIGH: 0, MID: 1, LOW: 2}
    return sorted(out, key=lambda a: order[a["level"]])
