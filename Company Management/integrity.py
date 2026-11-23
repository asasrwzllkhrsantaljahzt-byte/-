"""Release check: tells you which program files are missing or older than this release.

Run from the project folder:   py -3 فحص_التحديث.py
The app also shows a warning to the admin when something is out of date.
"""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
MANIFEST = BASE / "release_manifest.json"


def _digest(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def check():
    """Returns {"build": str|None, "missing": [...], "different": [...], "ok": bool}. Never raises."""
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"build": None, "missing": [], "different": [], "ok": False, "no_manifest": True}
    missing, different = [], []
    for rel, h in sorted(man.get("files", {}).items()):
        p = BASE / rel
        if not p.exists():
            missing.append(rel)
        else:
            try:
                if _digest(p) != h:
                    different.append(rel)
            except Exception:  # noqa: BLE001
                different.append(rel)
    return {"build": man.get("build"), "missing": missing, "different": different, "ok": not missing and not different}


def build_manifest(build: str):
    """Used by the release builder (not by the app)."""
    files = {}
    for pat in ("*.py", "modules/*.py", "database/*.sql"):
        for p in sorted(BASE.glob(pat)):
            if p.name in ("فحص_التحديث.py",) or "__pycache__" in p.parts:
                continue
            files[p.relative_to(BASE).as_posix()] = _digest(p)
    MANIFEST.write_text(json.dumps({"build": build, "files": files}, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(files)
