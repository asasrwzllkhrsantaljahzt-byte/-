"""Month parsing + release integrity check. Run: py -3 tests\\test_release_check.py"""
import sys, types, tempfile, shutil
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.dont_write_bytecode = True
st = types.ModuleType("streamlit"); st.session_state = {}; sys.modules["streamlit"] = st
import ui, integrity

for raw, want in (("2026-10", "2026-10"), ("10-2026", "2026-10"), ("2026/3", "2026-03"), ("١٠-٢٠٢٦", "2026-10"), (" 2026-3 ", "2026-03"),
                  ("13-2026", None), ("2026-00", None), ("abc", None), ("", None)):
    assert ui.norm_month(raw) == want, (raw, ui.norm_month(raw))

tmp = Path(tempfile.mkdtemp(prefix="cm_rel_"))
for pat in ("*.py", "modules/*.py", "database/*.sql"):
    for p in BASE.glob(pat):
        d = tmp / p.relative_to(BASE); d.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, d)
integrity.BASE = tmp; integrity.MANIFEST = tmp / "release_manifest.json"
assert integrity.check().get("no_manifest")
n = integrity.build_manifest("t1"); assert n > 20
assert integrity.check()["ok"]
(tmp / "ui.py").write_text("# old copy\n", encoding="utf-8")
(tmp / "vouchers.py").unlink()
r = integrity.check()
assert r["different"] == ["ui.py"] and r["missing"] == ["vouchers.py"] and not r["ok"], r
# Windows line endings must not count as a difference
shutil.copy2(BASE / "ui.py", tmp / "ui.py")
(tmp / "ui.py").write_bytes((BASE / "ui.py").read_bytes().replace(b"\n", b"\r\n"))
assert "ui.py" not in integrity.check()["different"]
print("release check tests OK")
