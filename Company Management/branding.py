"""Company logo: a PNG in assets/logo.png (replaceable from Settings)."""
import base64
import io
from pathlib import Path

LOGO = Path(__file__).resolve().parent / "assets" / "logo.png"
MAX_BYTES = 3 * 1024 * 1024


def logo_path():
    return str(LOGO) if LOGO.exists() else None


def logo_b64() -> str:
    try:
        return base64.b64encode(LOGO.read_bytes()).decode() if LOGO.exists() else ""
    except OSError:
        return ""


def logo_img_html(height=56) -> str:
    b = logo_b64()
    return f'<img src="data:image/png;base64,{b}" style="height:{height}px;vertical-align:middle">' if b else ""


def save_logo(data: bytes) -> str:
    """Validates an uploaded image, shrinks it and stores it as the logo. Raises ValueError."""
    if not data or len(data) > MAX_BYTES:
        raise ValueError("الصورة فارغة أو أكبر من 3 ميجابايت.")
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as ex:  # noqa: BLE001
        raise ValueError("الملف ليس صورة صالحة (استخدم PNG أو JPG).") from ex
    im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
    im.thumbnail((400, 400))
    LOGO.parent.mkdir(exist_ok=True)
    im.save(LOGO, format="PNG", optimize=True)
    return "تم حفظ الشعار."
