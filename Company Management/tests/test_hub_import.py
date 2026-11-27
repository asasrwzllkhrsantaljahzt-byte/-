"""Excel import of employees + branding. Run: py -3 tests\\test_hub_import.py"""
import sys, tempfile, io
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / "tests"))
from test_company_hub import _St, boot, raises, D


def main():
    sys.modules["streamlit"] = _St()
    tmp = Path(tempfile.mkdtemp(prefix="cm_imp_"))
    db, fe = boot(tmp)
    db.init_db()
    import company_hub as H, hub_import as HI, pandas as pd, branding
    H.ensure_hub_schema()
    co, _ = H.save_company(None, {"name": "المروة", "work_start_date": D(2026, 1, 1)})
    db.execute("INSERT INTO contractors(name) VALUES ('صفاء')")
    db.execute("INSERT INTO contractors(name, kind) VALUES ('أبو سعد','external')")
    assert HI.template_bytes()[:2] == b"PK"
    rows = [
        {"الشركة": "المروة", "اسم الموظف": "منال", "رقم الهوية": "1000000001", "الراتب الأساسي": 2000, "التكلفة الفعلية": 1700, "المكافأة": 1000,
         "المتعهد": "صفاء", "عمولة المتعهد": 100, "جهة العمولة الخارجية": "أبو سعد", "العمولة الخارجية": 50, "تاريخ البداية": "2026-10-01", "الحالة": "نشط"},
        {"الشركة": "المروة", "اسم الموظف": "نورة", "الراتب الأساسي": 2000, "التكلفة الفعلية": 1700, "المكافأة": 900, "تاريخ البداية": D(2026, 10, 5)},
        {"الشركة": "غير موجودة", "اسم الموظف": "س", "الراتب الأساسي": 2000, "التكلفة الفعلية": 1700, "تاريخ البداية": "2026-10-01"},
        {"الشركة": "المروة", "اسم الموظف": "ص", "الراتب الأساسي": 1000, "التكلفة الفعلية": 1700, "تاريخ البداية": "2026-10-01"},
        {"الشركة": "المروة", "اسم الموظف": "ع", "الراتب الأساسي": 2000, "التكلفة الفعلية": 1700, "المتعهد": "أبو سعد", "تاريخ البداية": "2026-10-01"},
        {"الشركة": "المروة", "اسم الموظف": "ل", "الراتب الأساسي": 2000, "التكلفة الفعلية": 1700, "تاريخ البداية": "01/10/2026"},
    ]
    buf = io.BytesIO(); pd.DataFrame(rows).to_excel(buf, sheet_name="الموظفات", index=False)
    items = HI.plan(HI.read_sheet(buf.getvalue()))
    assert [i["action"] for i in items] == ["add", "add", "error", "error", "error", "error"], [(i["action"], i["error"]) for i in items]
    assert db.query_one("SELECT COUNT(*) c FROM employees")["c"] == 0, "plan must not write"
    res = HI.apply(items)
    assert res["added"] == 2 and len(res["failed"]) == 4
    assert H.company_expected(co)["employees"] == 2

    # re-import = update, not duplicate
    rows[0]["المكافأة"] = 800; rows[1]["اسم الموظف"] = "نورة"
    buf = io.BytesIO(); pd.DataFrame(rows[:2]).to_excel(buf, sheet_name="الموظفات", index=False)
    items = HI.plan(HI.read_sheet(buf.getvalue()))
    assert [i["action"] for i in items] == ["update", "update"]
    res = HI.apply(items)
    assert res["updated"] == 2 and db.query_one("SELECT COUNT(*) c FROM employees")["c"] == 2
    assert db.query_one("SELECT bonus FROM employee_placements WHERE id=?", (items[0]["pid"],))["bonus"] == 800
    # exclude via import
    rows[1].update({"الحالة": "مستبعد", "تاريخ الاستبعاد": "2026-10-20"})
    buf = io.BytesIO(); pd.DataFrame(rows[1:2]).to_excel(buf, sheet_name="الموظفات", index=False)
    HI.apply(HI.plan(HI.read_sheet(buf.getvalue())))
    assert H.company_expected(co)["employees"] == 1
    # per-company sheet: current employees come back pre-filled, round-trips as updates, other company rows rejected
    import pandas as _pd
    cur = _pd.read_excel(io.BytesIO(HI.template_bytes(co)), sheet_name="الموظفات", dtype=object)
    assert len(cur) == 2 and set(cur["اسم الموظف"]) == {"منال", "نورة"}
    items = HI.plan(HI.read_sheet(HI.template_bytes(co)), co)
    assert [i["action"] for i in items] == ["update", "update"], [(i["action"], i["error"]) for i in items]
    co2, _ = H.save_company(None, {"name": "ثانية"})
    items = HI.plan(HI.read_sheet(HI.template_bytes(co)), co2)
    assert all(i["action"] == "error" and "شركة أخرى" in i["error"] for i in items)
    # missing columns / junk
    raises("أعمدة ناقصة", lambda: HI.read_sheet(_xl(pd.DataFrame({"x": [1]}))))
    raises("تعذرت", lambda: HI.read_sheet(b"junk"))
    # duplicate in file
    buf = io.BytesIO(); pd.DataFrame([rows[0], rows[0]]).to_excel(buf, sheet_name="الموظفات", index=False)
    assert [i["action"] for i in HI.plan(HI.read_sheet(buf.getvalue()))] == ["update", "error"]

    # A workbook can contain up to 50 non-empty employee rows.
    bulk_rows = [{
        "الشركة": "المروة", "اسم الموظف": f"موظف {i}", "الراتب الأساسي": 2000,
        "التكلفة الفعلية": 1700, "تاريخ البداية": "2026-10-01",
    } for i in range(50)]
    bulk_frame = pd.DataFrame(bulk_rows)
    assert len(HI.plan(bulk_frame)) == 50
    raises("الحد الأقصى 50", lambda: HI.plan(pd.DataFrame(bulk_rows + [bulk_rows[0]])))
    raises("الحد الأقصى 50", lambda: HI.read_sheet(_xl(pd.DataFrame(bulk_rows + [bulk_rows[0]]))))

    # branding
    assert branding.logo_path() and branding.logo_b64()
    raises("ليس صورة", lambda: branding.save_logo(b"not an image"))
    print("test_hub_import: OK")


def _xl(df):
    b = io.BytesIO(); df.to_excel(b, index=False); return b.getvalue()


if __name__ == "__main__":
    main()
