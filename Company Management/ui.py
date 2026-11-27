import streamlit as st
import pandas as pd


_DEFAULT_BG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900' viewBox='0 0 1600 900'>"
    "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='#0b3b4a'/>"
    "<stop offset='0.55' stop-color='#0f766e'/><stop offset='1' stop-color='#1d4e89'/></linearGradient>"
    "<pattern id='p' width='80' height='80' patternUnits='userSpaceOnUse' patternTransform='rotate(30)'>"
    "<path d='M0 40h80M40 0v80' stroke='#ffffff' stroke-opacity='0.06' stroke-width='1.2'/>"
    "<circle cx='40' cy='40' r='3' fill='#ffffff' fill-opacity='0.10'/></pattern></defs>"
    "<rect width='1600' height='900' fill='url(#g)'/><rect width='1600' height='900' fill='url(#p)'/>"
    "<circle cx='1350' cy='160' r='260' fill='#ffffff' fill-opacity='0.05'/>"
    "<circle cx='200' cy='760' r='320' fill='#ffffff' fill-opacity='0.05'/></svg>"
)


def _background_css() -> str:
    """Custom assets/background.(jpg|png|webp) is served as a static file (never embedded in the page on every click);
    without one, the small built-in generated design is used."""
    import shutil
    from pathlib import Path
    base = Path(__file__).resolve().parent
    for ext in ("jpg", "jpeg", "png", "webp"):
        f = base / "assets" / f"background.{ext}"
        try:
            if f.is_file():
                dst = base / "static" / f"background.{ext}"
                if not dst.exists() or dst.stat().st_mtime < f.stat().st_mtime:
                    dst.parent.mkdir(exist_ok=True)
                    shutil.copyfile(f, dst)
                return f"url('app/static/background.{ext}?v={int(f.stat().st_mtime)}')"
        except OSError:
            pass
    return "url(\"data:image/svg+xml;utf8," + _DEFAULT_BG.replace("#", "%23").replace('"', "'") + "\")"


def apply_rtl_style():
    st.markdown(
        """
        <style>
        :root {
            --brand: #0f766e;
            --brand-dark: #115e59;
            --ink: #172b3a;
            --muted: #647585;
            --line: #e2e8ef;
            --surface: #ffffff;
            --dialog-sidebar-width: 15rem;
        }
        .stApp {
            direction: rtl; font-family: "Segoe UI", Tahoma, Arial, sans-serif;
            color: var(--ink); background: #edf2f6;
        }
        .stMarkdown, .stText, label, input, textarea, select, button, p { text-align: right; }
        .stApp::before { content: ""; position: fixed; inset: 0; z-index: -1; pointer-events: none;
            background-image: __BG__; background-size: cover; background-position: center; opacity: 0.22; }
        header[data-testid="stHeader"] { background: rgba(237,242,246,0.82); }
        .block-container {
            padding: 2.4rem 2.2rem 2rem; max-width: 1480px;
            background: rgba(255,255,255,0.97); border: 1px solid rgba(216,225,233,0.9);
            border-radius: 18px; margin-top: 1.1rem; margin-bottom: 1.1rem;
            box-shadow: 0 12px 36px rgba(27,45,62,0.10);
        }
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #10293b 0%, #123747 100%);
            border-left: 1px solid rgba(255,255,255,0.08);
        }
        /* collapsed sidebar must not leak its contents over the page (Streamlit marks it data-collapsed or aria-expanded) */
        section[data-testid="stSidebar"][data-collapsed="true"], section[data-testid="stSidebar"][aria-expanded="false"] {
            visibility: hidden !important; background: transparent !important; box-shadow: none !important; border: none !important; }
        section[data-testid="stSidebar"][data-collapsed="true"] *, section[data-testid="stSidebar"][aria-expanded="false"] * {
            visibility: hidden !important; }
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stMetric"] { border: none; background: transparent; padding: 0; }
        section[data-testid="stSidebar"] [data-testid="stPopover"] button { background: rgba(255,255,255,0.10) !important; border: 1px solid rgba(255,255,255,0.3) !important; }
        section[data-testid="stSidebar"] { direction: rtl; color: #eaf4f4; }
        section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] span, section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] button, section[data-testid="stSidebar"] summary, section[data-testid="stSidebar"] h2 { text-align: right; color: #eaf4f4 !important; }
        section[data-testid="stSidebar"] .stButton>button {
            min-height: 2.55rem; border-radius: 10px;
            background: rgba(255,255,255,0.055); border: 1px solid rgba(255,255,255,0.12); color: #eaf4f4;
            transition: background 160ms ease, border-color 160ms ease, transform 160ms ease;
        }
        section[data-testid="stSidebar"] .stButton>button:hover { background: rgba(255,255,255,0.13); border-color: rgba(255,255,255,0.24); }
        section[data-testid="stSidebar"] .stButton>button[kind="primary"] {
            background: #19a99b; color: #062b32 !important; border: 1px solid #19a99b;
            box-shadow: 0 4px 12px rgba(0,0,0,0.14);
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] details,
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary { background: transparent !important; border: none !important; }
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover { background: rgba(255,255,255,0.08) !important; }
        .stButton>button, .stDownloadButton>button, [data-testid="stFormSubmitButton"] button {
            min-height: 2.55rem; border-radius: 10px; font-weight: 650;
            transition: background 160ms ease, border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
        }
        .stButton>button:not(:disabled):hover, .stDownloadButton>button:not(:disabled):hover,
        [data-testid="stFormSubmitButton"] button:not(:disabled):hover {
            transform: translateY(-1px); box-shadow: 0 5px 14px rgba(23,43,58,0.12);
        }
        .stButton>button[kind="primary"], .stDownloadButton>button[kind="primary"],
        [data-testid="stFormSubmitButton"] button[kind="primary"] {
            background: var(--brand); border-color: var(--brand); color: #fff;
        }
        .stButton>button[kind="primary"]:hover, .stDownloadButton>button[kind="primary"]:hover,
        [data-testid="stFormSubmitButton"] button[kind="primary"]:hover {
            background: var(--brand-dark); border-color: var(--brand-dark); color: #fff;
        }
        .stButton>button[kind="secondary"], .stDownloadButton>button[kind="secondary"],
        [data-testid="stFormSubmitButton"] button[kind="secondary"] {
            background: #fff; border-color: #d7e0e8; color: #243b4c;
        }
        .stButton>button[kind="secondary"]:hover, .stDownloadButton>button[kind="secondary"]:hover {
            background: #f5f8fa; border-color: #aebecb; color: #172b3a;
        }
        input, textarea { border-radius: 9px !important; }
        div[data-baseweb="select"] > div, div[data-baseweb="input"] > div,
        div[data-baseweb="textarea"] > div { border-color: #d7e0e8; border-radius: 9px; }
        div[data-baseweb="select"] > div:focus-within, div[data-baseweb="input"] > div:focus-within,
        div[data-baseweb="textarea"] > div:focus-within { border-color: var(--brand); box-shadow: 0 0 0 1px var(--brand); }
        div[data-testid="stMetric"] {
            background: linear-gradient(145deg,#ffffff,#f6f9fb); border: 1px solid var(--line);
            border-radius: 13px; padding: 12px 15px; box-shadow: 0 2px 8px rgba(23,43,58,0.035);
        }
        div[data-testid="stMetric"] label { color: var(--muted); font-weight: 600; }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 13px; border-color: var(--line); background: #fff;
            box-shadow: 0 2px 9px rgba(23,43,58,0.035);
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid var(--line); border-radius: 12px; overflow: hidden;
            box-shadow: 0 2px 8px rgba(23,43,58,0.035);
        }
        div[data-testid="stAlert"] { border-radius: 11px; }
        div[data-testid="stDialog"] {
            box-sizing: border-box !important;
            padding-right: var(--dialog-sidebar-width) !important;
            justify-content: center !important;
            align-items: center !important;
            background: rgba(14, 33, 48, 0.48) !important;
            backdrop-filter: blur(3px);
        }
        .stApp:has(section[data-testid="stSidebar"][aria-expanded="false"]) div[data-testid="stDialog"],
        .stApp:has(section[data-testid="stSidebar"][data-collapsed="true"]) div[data-testid="stDialog"] {
            padding-right: 0 !important;
        }
        div[data-testid="stDialog"] div[role="dialog"] {
            width: min(56rem, calc(100vw - var(--dialog-sidebar-width) - 3rem)) !important;
            max-width: calc(100vw - var(--dialog-sidebar-width) - 3rem) !important;
            max-height: 86vh !important;
            overflow-y: auto !important;
            background: #fff !important;
            border: 1px solid var(--line); border-radius: 16px;
            box-shadow: 0 18px 55px rgba(18,41,59,0.20);
        }
        button[data-baseweb="tab"] { font-weight: 650; color: var(--muted); }
        button[data-baseweb="tab"][aria-selected="true"] { color: var(--brand-dark); }
        .small-muted { color: var(--muted); font-size: 0.9rem; }
        .page-title {
            font-size: 1.65rem; font-weight: 750; margin-bottom: 0.25rem; color: #17364b;
            border-right: 4px solid var(--brand); padding-right: 12px;
        }
        .page-sub { color: var(--muted); margin-bottom: 1.15rem; padding-right: 16px; }
        div[data-testid="stDataFrame"], div[data-testid="stDataFrame"] * { direction: ltr !important; }
        @media (max-width: 768px) {
            .block-container { padding: 1.4rem 1rem 1.2rem; margin-top: 0.4rem; border-radius: 12px; }
            div[data-testid="stDialog"] { padding-right: 0 !important; }
            div[data-testid="stDialog"] div[role="dialog"] {
                width: calc(100vw - 1.5rem) !important;
                max-width: calc(100vw - 1.5rem) !important;
                max-height: 90vh !important;
            }
        }
        </style>
        """.replace("__BG__", _background_css()),
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = ""):
    st.markdown(f"<div class='page-title'>{title}</div>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<div class='page-sub'>{subtitle}</div>", unsafe_allow_html=True)



# ---------------------------------------------------------------- save UX helpers
_UNIQUE_MSG = {
    "companies.name": "يوجد شركة بهذا الاسم مسجلة مسبقاً.",
    "employees.national_id": "رقم الهوية هذا مسجل مسبقاً لموظف آخر.",
}


def flash_set(msg: str, ver_key: str = None):
    """Remember a success message across the rerun that follows a save, and reset the form's fields."""
    st.session_state["_flash_ok"] = msg
    if ver_key:
        st.session_state[ver_key] = st.session_state.get(ver_key, 0) + 1


def show_flash():
    msg = st.session_state.pop("_flash_ok", None)
    if msg:
        st.toast(msg, icon="✅")


def form_ver(ver_key: str) -> int:
    return st.session_state.get(ver_key, 0)


def friendly_error(e, prefix: str = "تعذر الحفظ") -> str:
    text = str(e)
    if text.startswith("UNIQUE constraint failed:"):
        key = text.split(":", 1)[1].strip()
        return _UNIQUE_MSG.get(key, "يوجد سجل مطابق مسجل مسبقاً (قيمة يجب ألا تتكرر).")
    return f"{prefix}: {text}" if text else prefix


def duplicate_of(table: str, name: str, phone: str, name_col: str = "name"):
    """id of an existing row with the same name and phone (blank phones compare equal), else None."""
    from db import query_all
    n = " ".join((name or "").split()).lower()
    p = (phone or "").strip()
    for r in query_all(f"SELECT id, {name_col} AS name, phone FROM {table}"):
        if " ".join((r["name"] or "").split()).lower() == n and (r["phone"] or "").strip() == p:
            return r["id"]
    return None


def toast_flash(key: str):
    """Show (once) a success message stored in session_state[key], as a toast so the layout does not move."""
    msg = st.session_state.pop(key, None)
    if msg:
        st.toast(msg, icon="✅")


# ---------------------------------------------------------------- navigation
MASTER_DATA_GROUPS = [
    ("الشركات والموظفون", ("الشركات والموظفون",)),
    ("المتعهدون", ("المتعهدون",)),
    ("المندوبون", ("المندوبون",)),
]


def set_page(page: str):
    current = st.session_state.get("_page")
    if page in ("التسجيل", "العرض"):
        st.session_state.pop("_return_page", None)
    elif current in ("التسجيل", "العرض"):
        st.session_state["_return_page"] = current
    st.session_state["_page"] = page


def goto_button(label: str, page: str, key: str):
    """A shortcut button that jumps to another page (callers check the user may open it)."""
    st.button(label, key=key, use_container_width=True, on_click=set_page, args=(page,))


# ------------------------------------------------------------ selectable tables
def tver(name: str) -> int:
    return st.session_state.get(f"_tv_{name}", 0)


def tbump(name: str):
    st.session_state[f"_tv_{name}"] = tver(name) + 1


def select_table(df, name: str):
    """Shows a table whose rows can be clicked; returns the selected row position or None.
    tbump(name) clears the selection."""
    try:
        cfg = {c: st.column_config.Column(alignment="right") for c in df.columns}
    except TypeError:                      # older Streamlit without column alignment
        cfg = None
    ev = st.dataframe(df.fillna(""), use_container_width=True, hide_index=True, on_select="rerun",
                      selection_mode="single-row", column_config=cfg, key=f"_tbl_{name}_{tver(name)}")
    rows = ev.selection.rows if ev is not None else []
    return rows[0] if rows else None


def row_action_bar(*, edit=False, delete=False, print_=False, view=False, prefix: str,
                   edit_help="تعديل", delete_help="حذف", print_help="طباعة", view_help="عرض"):
    """Compact icon actions for the selected row, kept at the left side in RTL layouts."""
    cols = st.columns([1, 1, 1, 1, 6])
    actions = {"edit": False, "delete": False, "print": False, "view": False}
    if view:
        actions["view"] = cols[0].button("👁", key=f"{prefix}_view", help=view_help,
                                           icon=":material/visibility:", icon_position="right")
    if print_:
        actions["print"] = cols[1].button("🖨️", key=f"{prefix}_print", help=print_help,
                                            icon=":material/print:", icon_position="right")
    if delete:
        actions["delete"] = cols[2].button("🗑️", key=f"{prefix}_delete", help=delete_help,
                                            icon=":material/delete:", icon_position="right")
    if edit:
        actions["edit"] = cols[3].button("✏️", key=f"{prefix}_edit", help=edit_help,
                                           icon=":material/edit:", icon_position="right")
    return actions


def excel_button(df, filename: str, key: str, label: str = "⬇️ تصدير Excel"):
    """Download button for the table currently shown (exactly the rows/columns on screen)."""
    import io
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="البيانات")
    st.download_button(label, out.getvalue(), file_name=f"{filename}.xlsx", key=key,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def pdf_button(df, title: str, filename: str, key: str):
    import exports
    import app_settings

    ok, reason = exports.pdf_available()
    if not ok:
        st.caption(f"تنزيل PDF غير متاح: {reason}")
        return
    content = exports.table_pdf(title, [(title, df)], org=app_settings.get("org_name"))
    st.download_button("⬇️ تصدير PDF", content, file_name=f"{filename}.pdf", key=key, mime="application/pdf")


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٬٫،", "01234567890123456789,.,")


MONTH_EXAMPLE = "\u20662026-03\u2069"   # shown left-to-right even inside Arabic text


def norm_month(text):
    """'2026-10', '10-2026', '2026/10', Arabic digits -> '2026-10'. None if it is not a month."""
    import re as _re
    t = (text or "").strip().translate(_DIGITS).replace("/", "-").replace("\\", "-").replace(".", "-").replace(" ", "")
    m = _re.fullmatch(r"(\d{4})-(\d{1,2})", t)
    if m:
        y, mo = m.group(1), int(m.group(2))
    else:
        m = _re.fullmatch(r"(\d{1,2})-(\d{4})", t)
        if not m:
            return None
        mo, y = int(m.group(1)), m.group(2)
    return f"{y}-{mo:02d}" if 1 <= mo <= 12 else None


def parse_number(text):
    """'1,500.50' / '١٥٠٠' / '1500' -> float. Empty -> None. Raises ValueError with an Arabic message."""
    t = str(text or "").translate(_DIGITS).replace(",", "").replace(" ", "").strip()
    if not t:
        return None
    try:
        n = float(t)
    except ValueError:
        raise ValueError("اكتب رقماً صحيحاً (أرقام فقط).")
    if n != n or n in (float("inf"), float("-inf")):
        raise ValueError("اكتب رقماً صحيحاً (أرقام فقط).")
    return n


def number_field(label, key, value=None, placeholder="0.00", integer=False, minimum=None, maximum=None, help=None):
    """Typed number box. (Streamlit's number_input mangles typing in right-to-left pages: '1500' becomes '0.001500'.)
    Returns a float/int, or None when empty or invalid (an inline message explains the problem)."""
    shown = "" if value in (None, "") else (str(int(value)) if integer else f"{float(value):g}")
    raw = st.text_input(label, value=shown, key=key, placeholder=placeholder, help=help)
    try:
        n = parse_number(raw)
    except ValueError as e:
        st.caption(f"⚠️ {e}")
        return None
    if n is None:
        return None
    if integer and n != int(n):
        st.caption("⚠️ اكتب عدداً صحيحاً.")
        return None
    if minimum is not None and n < minimum:
        st.caption(f"⚠️ الحد الأدنى {minimum:g}.")
        return None
    if maximum is not None and n > maximum:
        st.caption(f"⚠️ الحد الأقصى {maximum:g}.")
        return None
    return int(n) if integer else n
