"""Offline rule-based assistant: explains how to use the program and answers from the data. It never changes anything."""
import re
from datetime import date, timedelta

import hub_engine as E
import hub_accounts as HA
import vouchers as V
from db import query_all

_AR_MONTHS = {"يناير": 1, "كانون الثاني": 1, "فبراير": 2, "شباط": 2, "مارس": 3, "اذار": 3, "ابريل": 4, "نيسان": 4, "مايو": 5, "ايار": 5,
              "يونيو": 6, "حزيران": 6, "يوليو": 7, "تموز": 7, "اغسطس": 8, "اب": 8, "سبتمبر": 9, "ايلول": 9, "اكتوبر": 10,
              "تشرين الاول": 10, "نوفمبر": 11, "تشرين الثاني": 11, "ديسمبر": 12, "كانون الاول": 12}

HOWTO = [
    (("اضيف شركه", "شركه جديده", "تسجيل شركه", "اسجل شركه", "اضافه شركه"), "إضافة شركة",
     "من **الشركات والموظفون** اضغط «➕ شركة جديدة»، اكتب الاسم والرقم الضريبي والسجل والعنوان والهاتف والمسؤول وتاريخ بداية العمل. بعد الحفظ تُفتح شاشة الشركة لتضيف المندوب والموظفات."),
    (("اضيف موظف", "موظفه جديده", "تسجيل موظف", "اسجل موظف", "اضافه موظف", "اضيف موظفه"), "إضافة موظفة",
     "افتح الشركة من **الشركات والموظفون** ثم «➕ إضافة موظف»: الراتب الأساسي، التكلفة الفعلية (المتفق عليها مع العميل)، المكافأة، المتعهد وعمولته، العمولة الخارجية، وتاريخ البداية. أو استورد عدداً كبيراً من **📥 استيراد Excel**."),
    (("اكسيل", "excel", "استيراد", "شيت"), "الاستيراد من Excel",
     "في **الشركات والموظفون** اضغط «📥 استيراد Excel»، نزّل القالب واملأه، ثم ارفعه وراجع المعاينة وانفّذ. الموظف الموجود يُحدَّث ولا يتكرر، والصفوف الخاطئة تُتجاهل مع بيان السبب."),
    (("تحويل", "حولت", "يحول", "اسجل تحويل", "قسط"), "تسجيل تحويل العميل",
     "من **المالية** اختر **التحويلات والحساب الشهري** ← تبويب «💸 تحويلات العميل» اضغط «تحويل جديد» أو «تحويل جماعي لشركة». اختر الموظفة وشهر العمل (وليس شهر التحويل) والتاريخ والمبلغ. يمكن تسجيل عدة دفعات لنفس الشهر وتُجمع."),
    (("كيف يحسب", "طريقه الحساب", "الاحتساب", "المعادله", "كيف تحسب", "شرح الحساب"), "طريقة الحساب",
     "لكل موظفة وشهر: إن كان المحوَّل **أقل** من التكلفة فالنسبة = المحوَّل ÷ التكلفة، ولا مردود للعميل، وتُضرب المكافأة والعمولات بالنسبة. وإن كان **أكبر أو يساوي** فالنسبة 1 والزيادة مردود للعميل. الصافي = الإيراد − المكافأة − المتعهد − العمولة الخارجية. المندوب = نسبته من صافي الشركة، والباقي هامش الشركة. الشهر الأول والأخير يُحسبان بالأيام الفعلية."),
    (("اقفال", "اقفل", "اغلاق", "مراجعه الشهر"), "إقفال الشهر",
     "من **المالية** اختر **مراجعة وإقفال الشهر**، راجع القائمة ثم «إقفال الشهر». تتثبّت الأرقام ويُمنع تعديل تحويلاته. تقدر تعيد الفتح بسبب مكتوب."),
    (("تحصيل", "اسجل تحصيل", "ما اعادته", "تعيد"), "تسجيل التحصيل من الموظفة",
     "من **المالية** اختر **التحصيل والمدفوعات والسندات** ثم «متابعة التحصيل والمدفوعات» ← «التحصيل من الموظفات»: اختر الشهر والموظفة ثم «تسجيل تحصيل» فيُصدر إذن استلام. يظهر المطلوب والمحصّل والفرق."),
    (("سند", "اذن صرف", "ادفع", "صرف"), "الصرف والسندات",
     "من **المالية** اختر **التحصيل والمدفوعات والسندات** ثم «متابعة التحصيل والمدفوعات» ← «المدفوعات والمستحقات» واختر الجهة ثم «إذن صرف». سجل كل الإذون من اختيار «سجل السندات». السند لا يُحذف، يُلغى بسبب."),
    (("استبعاد", "استبعد", "ايقاف موظف", "تركت العمل", "استقالت"), "استبعاد موظفة",
     "داخل شاشة الشركة اختر الموظفة ثم «استبعاد» وحدد آخر يوم عمل. يُحسب شهرها الأخير بالأيام الفعلية، وتبقى بياناتها محفوظة."),
    (("غير المندوب", "تغيير المندوب", "مندوب جديد", "استقاله المندوب"), "تغيير المندوب",
     "في شاشة الشركة قسم المندوب: «تغيير المندوب» يغلق المندوب السابق ويبدأ الجديد بتاريخ تحدده، وتبقى الأشهر السابقة بمندوبها ونسبته."),
    (("تقرير", "pdf", "طباعه", "تنزيل"), "التقارير والتنزيل",
     "من **المالية** اختر **التقارير المالية والإدارية**: ملخص الشهر، تفصيل الموظفات، الأرصدة، السنوي، وكلها تُنزَّل Excel وPDF. كشف حساب طرف محدد من اختيار **كشوف الحسابات**."),
    (("نسخه احتياطيه", "باك اب", "backup"), "النسخ الاحتياطي",
     "من **النسخ الاحتياطي والاستعادة** (للمدير) اضغط إنشاء نسخة، ويذكّرك الجرس إذا مضت أيام على آخر نسخة."),
    (("شعار", "اسم الشركه", "اعدادات"), "الشعار والإعدادات",
     "من **الإعدادات** (للمدير): اسم المنشأة وبياناتها وأيام التنبيه، ورفع الشعار الذي يظهر في القائمة والمطبوعات."),
    (("فاتوره",), "فواتير العملاء",
     "من **المالية** اختر **فواتير العملاء**، ثم اختر الشركة والشهر. تُبنى الفاتورة من الإيراد الفعلي للشهر مع الضريبة (يُشترط الرقم الضريبي في الإعدادات)."),
]


def norm(t: str) -> str:
    t = re.sub(r"[ً-ْـ]", "", t or "")
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    t = t.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    return re.sub(r"\s+", " ", t.strip().lower())


def _has(q, *words):
    return any(norm(w) in q for w in words)


def parse_month(q: str, today: date, default=None):
    m = re.search(r"(20\d\d)\s*[-/]\s*(\d{1,2})", q)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    if _has(q, "الشهر الماضي", "الشهر السابق", "شهر فات"):
        p = today.replace(day=1) - timedelta(days=1)
        return p.strftime("%Y-%m")
    if _has(q, "هذا الشهر", "الشهر الحالي", "الشهر ده", "الشهر دا"):
        return today.strftime("%Y-%m")
    year = re.search(r"\b(20\d\d)\b", q)
    for name, num in sorted(_AR_MONTHS.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"(?<!\w)" + re.escape(norm(name)) + r"(?!\w)", q):
            return f"{int(year.group(1)) if year else today.year:04d}-{num:02d}"
    return default


def _find(q, table, col):
    hits = []
    for r in query_all(f"SELECT id, {col} AS n FROM {table}"):
        n = norm(r["n"])
        if n and n in q:
            hits.append(r)
    return sorted(hits, key=lambda r: -len(r["n"]))[:1]


def _money(x):
    return f"{float(x):,.2f}"


def _default_month(today):
    ms = E.month_options()
    cur = today.strftime("%Y-%m")
    for m in ([cur] + ms):
        if m in ms and E.compute_live(m)["companies"]:
            return m
    return cur


def answer(question: str, today: date = None) -> str:
    today = today or date.today()
    q = norm(question)
    if not q:
        return "اكتب سؤالك، مثل: «كم صافي الشهر الماضي؟» أو «كيف أضيف موظفة؟»."
    month = parse_month(q, today, None)
    mdef = month or _default_month(today)
    co = _find(q, "companies", "name")
    emp = _find(q, "employees", "full_name")
    con = _find(q, "contractors", "name")
    rep = _find(q, "representatives", "name")
    asks_how = _has(q, "كيف", "ازاي", "طريقه", "اضيف", "اسجل", "اعمل", "شرح", "وين", "اين", "فين", "خطوات")

    # ---- alerts
    if _has(q, "تنبيه", "تنبيهات", "ايش المطلوب", "ماذا يلزم", "الجرس"):
        import alerts
        al = alerts.collect(today)
        return "التنبيهات الحالية:\n" + "\n".join(f"- {a['text']} (صفحة «{a['page']}»)" for a in al) if al else "لا توجد تنبيهات الآن ✅"

    # ---- data questions (not "how to")
    if not asks_how or emp or co or con or rep:
        if emp and _has(q, "تعيد", "عليها", "المتبقي", "تحصيل", "حصلنا", "استلمنا"):
            rows = [r for r in HA.collection_rows(mdef) if r["employee_id"] == emp[0]["id"]]
            if rows:
                r = rows[0]
                return (f"**{r['employee']}** — شهر {mdef}: المطلوب منها {_money(r['owed'])}، المحصَّل {_money(r['collected'])}، "
                        f"المتبقي {_money(r['diff'])}.")
            return f"لا توجد بيانات للموظفة {emp[0]['n']} في شهر {mdef}."
        if emp and _has(q, "حول", "تحويل", "استلمت", "صافي", "مكافاه", "حساب", "كم"):
            res = E.compute_month(mdef)
            for c in res["companies"]:
                for r in c["employees"]:
                    if r["employee_id"] == emp[0]["id"]:
                        return (f"**{r['employee']}** ({c['company']}) — شهر {mdef}: التكلفة {_money(r['cost_eff'])}، حوّل العميل {_money(r['transferred'])} "
                                f"(نسبة {r['ratio']*100:.1f}%)، مكافأتها {_money(r['bonus_due'])}، المردود للعميل {_money(r['refund'])}، "
                                f"الصافي للشركة {_money(r['net'])}، وتعيد للشركة {_money(r['employee_returns'])}.")
            return f"لا توجد بيانات للموظفة {emp[0]['n']} في شهر {mdef}."
        if (con or rep) and _has(q, "مستحق", "رصيد", "حساب", "له", "كم", "عمولت", "مبلغ"):
            pt, hit = ("contractor", con[0]) if con else ("representative", rep[0])
            a = V.party_account(pt, hit["id"])
            return (f"**{hit['n']}**: المستحق الكلي {_money(a['due'])}، المصروف {_money(a['settled'])}، المتبقي {_money(a['balance'])}. "
                    f"({a['note']})")
        if co and _has(q, "مردود", "استرداد", "نرد", "للعميل"):
            c = [x for x in E.compute_month(mdef, co[0]["id"])["companies"]]
            return f"مردود **{co[0]['n']}** لشهر {mdef}: {_money(c[0]['refund'])}." if c else f"لا بيانات لـ{co[0]['n']} في {mdef}."
        if _has(q, "لم تحول", "بدون تحويل", "ما حول", "لم يحول", "بلا تحويل", "ما تحول"):
            res = E.compute_month(mdef)
            names = [f"{r['employee']} ({c['company']})" for c in res["companies"] for r in c["employees"] if r["days"] > 0 and r["transferred"] == 0]
            return (f"موظفات بلا تحويل في {mdef}:\n" + "\n".join(f"- {n}" for n in names)) if names else f"كل الموظفات لهن تحويلات في {mdef} ✅"
        if _has(q, "صافي", "هامش", "ربح", "ارباح", "ملخص", "اجمالي", "ايراد", "حول", "تحويل", "مردود", "مناديب"):
            res = E.compute_month(mdef, co[0]["id"] if co else None)
            t = res["totals"]
            if not res["companies"]:
                return f"لا توجد بيانات لشهر {mdef}."
            who = f"**{co[0]['n']}** " if co else ""
            return (f"{who}شهر {mdef} ({'مقفل' if res.get('closed') else 'مفتوح'}): حوّل العميل {_money(t['transferred'])}، الإيراد الفعلي {_money(t['revenue'])}، "
                    f"المردود {_money(t['refund'])}، المكافآت {_money(t['bonus_due'])}، المتعهدون {_money(t['contractor_due'])}، "
                    f"الصافي {_money(t['net'])}، عمولة المندوب {_money(t['rep_due'])}، **هامش الشركة {_money(t['margin'])}**.")
        if _has(q, "كم موظف", "عدد الموظف", "كم موظفه", "عدد الموظفات", "كم عدد"):
            n = query_all("SELECT COUNT(*) c FROM employee_placements WHERE status='active'")[0]["c"]
            k = query_all("SELECT COUNT(*) c FROM companies WHERE status='active'")[0]["c"]
            return f"عدد الموظفات النشطات: {n} في {k} شركة نشطة."
        if _has(q, "تحصيل", "المتبقي", "لم يحصل", "ما حصلنا", "ما اعادت"):
            rows = HA.collection_rows(mdef)
            left = sum(r["diff"] for r in rows if r["diff"] > 0)
            return f"المطلوب تحصيله من الموظفات لشهر {mdef}: {_money(sum(r['owed'] for r in rows))}، المحصَّل {_money(sum(r['collected'] for r in rows))}، المتبقي {_money(left)}."

    # ---- how-to
    best, score = None, 0
    for keys, title, text in HOWTO:
        s = sum(1 for k in keys if norm(k) in q)
        if s > score:
            best, score = (title, text), s
    if best:
        return f"**{best[0]}**\n\n{best[1]}"
    return ("لم أفهم سؤالك تماماً. جرّب مثلاً:\n- كم صافي الشهر الماضي؟\n- كم هامش شركة [اسمها] في 2026-10؟\n- كم تعيد [اسم موظفة]؟\n"
            "- مين لم يحوَّل لها هذا الشهر؟\n- كم مستحق [اسم المتعهد]؟\n- كيف أضيف موظفة؟ / كيف يُحسب الشهر؟ / كيف أقفل الشهر؟\n- ما التنبيهات؟")
