"""Excel and Arabic PDF export helpers."""
import io
import os
import pandas as pd

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\tahoma.ttf", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
]
_FONT_BOLD = {r"C:\Windows\Fonts\tahoma.ttf": r"C:\Windows\Fonts\tahomabd.ttf", r"C:\Windows\Fonts\arial.ttf": r"C:\Windows\Fonts\arialbd.ttf"}


def export_excel(dfs: dict) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        for name, df in dfs.items():
            df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
            df.to_excel(w, sheet_name=(name or "Sheet")[:31], index=False)
            ws = w.sheets[(name or "Sheet")[:31]]
            ws.sheet_view.rightToLeft = True
            for i, col in enumerate(df.columns, 1):
                width = max([len(str(col))] + [len(str(x)) for x in df[col].head(200)]) + 3
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 40)
    return out.getvalue()


def _shape(t):
    t = "" if t is None else str(t)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(t))
    except Exception:  # noqa: BLE001
        return t


def pdf_available() -> tuple:
    """(ok, reason)"""
    try:
        import reportlab  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "مكتبة reportlab غير مثبتة"
    try:
        import arabic_reshaper, bidi  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "ثبّت المكتبتين: py -3 -m pip install arabic-reshaper python-bidi"
    if not any(os.path.exists(f) for f in _FONT_CANDIDATES):
        return False, "لم يُعثر على خط عربي"
    return True, ""


def table_pdf(title: str, sections: list, subtitle: str = "", org: str = "") -> bytes:
    """sections = [(heading, DataFrame)]. Landscape A4, right-to-left tables."""
    ok, why = pdf_available()
    if not ok:
        raise RuntimeError(why)
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    path = next(f for f in _FONT_CANDIDATES if os.path.exists(f))
    pdfmetrics.registerFont(TTFont("AR", path))
    bold = _FONT_BOLD.get(path)
    pdfmetrics.registerFont(TTFont("AR-B", bold if bold and os.path.exists(bold) else path))
    h1 = ParagraphStyle("h1", fontName="AR-B", fontSize=15, alignment=2, leading=22)
    h2 = ParagraphStyle("h2", fontName="AR-B", fontSize=11, alignment=2, leading=16, spaceBefore=8)
    sm = ParagraphStyle("sm", fontName="AR", fontSize=8.5, alignment=2, leading=12, textColor=colors.HexColor("#555555"))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24, title=title)
    el = []
    try:
        import branding
        from reportlab.platypus import Image as RLImage
        if branding.logo_path():
            img = RLImage(branding.logo_path(), width=42, height=42)
            img.hAlign = "RIGHT"
            el.append(img)
    except Exception:  # noqa: BLE001
        pass
    if org:
        el.append(Paragraph(_shape(org), sm))
    el += [Paragraph(_shape(title), h1)]
    if subtitle:
        el.append(Paragraph(_shape(subtitle), sm))
    el.append(Spacer(1, 6))
    width = landscape(A4)[0] - 48
    for heading, df in sections:
        if heading:
            el.append(Paragraph(_shape(heading), h2))
        if df is None or df.empty:
            el.append(Paragraph(_shape("لا توجد بيانات."), sm)); continue
        cols = list(df.columns)[::-1]
        cell = ParagraphStyle("c", fontName="AR", fontSize=8, alignment=1, leading=11)
        def fmt(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return ""
            if isinstance(v, float):
                return f"{v:,.2f}"
            return str(v)
        data = [[Paragraph(_shape(c), ParagraphStyle("hd", parent=cell, fontName="AR-B")) for c in cols]]
        for _, r in df.iterrows():
            data.append([Paragraph(_shape(fmt(r[c])), cell) for c in cols])
        t = Table(data, repeatRows=1, colWidths=[width / len(cols)] * len(cols))
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe7ec")), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f9fa")])]))
        el.append(t)
    doc.build(el)
    return buf.getvalue()
