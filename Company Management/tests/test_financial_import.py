import datetime
import io
import shutil
import sys
import types
from pathlib import Path

import pandas as pd
import pytest


BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


class _StreamlitStub(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}


def _setup(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "streamlit", _StreamlitStub())
    database = tmp_path / "database"
    database.mkdir()
    shutil.copy2(BASE / "database" / "schema.sql", database / "schema.sql")

    import db

    monkeypatch.setattr(db, "BASE_DIR", tmp_path)
    monkeypatch.setattr(db, "SCHEMA_PATH", database / "schema.sql")
    monkeypatch.setattr(db, "DB_PATH", database / "app.db")
    db.init_db()

    import app_settings
    import company_hub
    import hub_engine
    import security
    import vouchers

    security.ensure_security_schema()
    app_settings.ensure_settings_schema()
    company_hub.ensure_hub_schema()
    hub_engine.ensure_engine_schema()
    vouchers.ensure_vouchers_schema()
    import financial_import

    company_id, _ = company_hub.save_company(
        None, {"name": "شركة الاختبار", "work_start_date": datetime.date(2026, 1, 1)}
    )
    placement_id, _ = company_hub.add_employee(
        company_id,
        {"full_name": "موظف الاختبار"},
        {"basic_salary": 2000, "actual_cost": 1700, "start_date": datetime.date(2026, 1, 1)},
    )
    employee_id = company_hub.get_placement(placement_id)["employee_id"]
    return db, financial_import, placement_id, employee_id


def test_transfer_and_employee_receipt_templates_import_valid_rows(tmp_path, monkeypatch):
    db, importer, placement_id, employee_id = _setup(tmp_path, monkeypatch)

    import pyarrow as pa
    from modules import financial_activity_page

    numbered_movements = financial_activity_page._display_frame([
        {"source": "transfer", "id": 3, "operation": "transfer", "date": "2026-03-15", "party": "شركة الاختبار",
         "employee": "موظف الاختبار", "amount": 1000, "method": "—", "month": "2026-03",
         "description": "", "status": "ساري"},
        {"source": "voucher", "id": 4, "operation": "employee_receipt", "date": "2026-03-16", "party": "موظف الاختبار",
         "employee": "موظف الاختبار", "amount": 500, "method": "نقداً", "month": "2026-03",
         "description": "", "status": "ساري"},
    ])
    assert numbered_movements["رقم الحركة"].tolist() == ["تحويل-000003", "سند-000004"]

    transfer_template = importer.template_bytes("transfer")
    transfer_book = pd.ExcelFile(io.BytesIO(transfer_template))
    assert {"الحركات", "تعليمات", "المرجع"} == set(transfer_book.sheet_names)
    assert len(pd.read_excel(io.BytesIO(transfer_template), sheet_name="الحركات")) == 0
    transfer_reference = pd.read_excel(io.BytesIO(transfer_template), sheet_name="المرجع")
    assert {"الشركة", "اسم الموظف"} <= set(transfer_reference.columns)
    assert {"رقم التعيين", "رقم الموظف"}.isdisjoint(transfer_reference.columns)
    assert {("شركة الاختبار", "موظف الاختبار")} <= set(
        zip(transfer_reference["الشركة"], transfer_reference["اسم الموظف"])
    )

    transfer_rows = pd.DataFrame([
        {
            "الشركة": "شركة الاختبار",
            "شهر العمل": "2026-03",
            "اسم الموظف": "موظف الاختبار",
            "المبلغ المحول": "١٠٠٠",
            "تاريخ التحويل": "2026-03-15",
            "ملاحظات": "دفعة أولى",
        },
        {
            "الشركة": "شركة الاختبار",
            "شهر العمل": "2026-03",
            "اسم الموظف": "موظف الاختبار",
            "المبلغ المحول": "١٠٠٠",
            "تاريخ التحويل": "2026-03-15",
            "ملاحظات": "دفعة أولى",
        },
    ])
    transfer_plan = importer.plan(transfer_rows, "transfer")
    assert [item["action"] for item in transfer_plan] == ["add", "error"]
    assert transfer_plan[1]["company"] == "شركة الاختبار"
    assert transfer_plan[1]["employee"] == "موظف الاختبار"
    assert "صف Excel رقم 2" in transfer_plan[1]["error"]
    preview = financial_activity_page._bulk_preview_frame(transfer_plan)
    assert preview.loc[1, "التاريخ"] == "2026-03-15"
    assert preview.loc[1, "المبلغ"] == "1,000.00"
    pa.Table.from_pandas(preview, preserve_index=False)
    assert db.query_one("SELECT COUNT(*) AS n FROM client_transfers")["n"] == 0
    transfer_result = importer.apply(transfer_plan, "transfer")
    assert transfer_result["added"] == 1
    assert transfer_result["failed"] == [(3, "الحركة مطابقة للحركة الموجودة في صف Excel رقم 2.")]
    assert db.query_one("SELECT COUNT(*) AS n FROM client_transfers")["n"] == 1

    receipt_template = importer.template_bytes("employee_receipt")
    receipt_book = pd.ExcelFile(io.BytesIO(receipt_template))
    assert len(pd.read_excel(io.BytesIO(receipt_template), sheet_name="الحركات")) == 0
    receipt_reference = pd.read_excel(io.BytesIO(receipt_template), sheet_name="المرجع")
    assert {"اسم الموظف", "الشركة"} <= set(receipt_reference.columns)
    assert "رقم الموظف" not in receipt_reference.columns

    import company_hub

    duplicate_company_id, _ = company_hub.save_company(
        None, {"name": "شركة أخرى", "work_start_date": datetime.date(2026, 1, 1)}
    )
    company_hub.add_employee(
        duplicate_company_id,
        {"full_name": "موظف الاختبار"},
        {"basic_salary": 2000, "actual_cost": 1700, "start_date": datetime.date(2026, 1, 1)},
    )

    receipt_rows = pd.DataFrame([
        {
            "اسم الموظف": "موظف الاختبار",
            "الشركة": "شركة الاختبار",
            "المبلغ": "٥٠٠٫٥٠",
            "التاريخ": datetime.date(2026, 3, 16),
            "طريقة الدفع": "حوالة بنكية",
            "المرجع": "REF-1",
            "شهر العمل": "2026-03",
            "البيان": "استلام",
        },
        {
            "اسم الموظف": "موظف الاختبار",
            "المبلغ": 100,
            "التاريخ": "2026-03-16",
            "طريقة الدفع": "نقداً",
        },
    ])
    receipt_plan = importer.plan(receipt_rows, "employee_receipt")
    assert [item["action"] for item in receipt_plan] == ["add", "error"]
    assert "اكتب اسم الشركة" in receipt_plan[1]["error"]
    assert db.query_one("SELECT COUNT(*) AS n FROM vouchers")["n"] == 0
    receipt_result = importer.apply(receipt_plan, "employee_receipt")
    assert receipt_result["added"] == 1
    assert receipt_result["failed"][0][0] == 3
    voucher = db.query_one("SELECT party_id, amount, method, month_ref FROM vouchers")
    assert voucher == {
        "party_id": employee_id,
        "amount": 500.5,
        "method": "transfer",
        "month_ref": "2026-03",
    }


def test_financial_import_rejects_bad_headers_and_months(tmp_path, monkeypatch):
    _, importer, placement_id, _ = _setup(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="أعمدة ناقصة"):
        importer.read_sheet(
            _excel(pd.DataFrame({"مبلغ": [100]})),
            "transfer",
        )
    with pytest.raises(ValueError, match="قالب قديم"):
        importer.read_sheet(
            _excel(pd.DataFrame({"رقم التعيين": [1], "شهر العمل": ["2026-03"]})),
            "transfer",
        )

    rows = pd.DataFrame([{
        "الشركة": "شركة الاختبار",
        "شهر العمل": "2026-13",
        "اسم الموظف": "موظف الاختبار",
        "المبلغ المحول": 100,
        "تاريخ التحويل": "2026-03-15",
    }])
    item = importer.plan(rows, "transfer")[0]
    assert item["action"] == "error"
    assert "YYYY-MM" in item["error"]


def test_financial_import_accepts_50_rows_and_rejects_51(tmp_path, monkeypatch):
    _, importer, _, _ = _setup(tmp_path, monkeypatch)
    transfers = pd.DataFrame([{
        "الشركة": "شركة الاختبار",
        "شهر العمل": "2026-03",
        "اسم الموظف": "موظف الاختبار",
        "المبلغ المحول": 100,
        "تاريخ التحويل": "2026-03-15",
        "ملاحظات": f"حركة {index}",
    } for index in range(50)])
    receipts = pd.DataFrame([{
        "اسم الموظف": "موظف الاختبار",
        "المبلغ": 100,
        "التاريخ": "2026-03-16",
        "المرجع": f"REF-{index}",
    } for index in range(50)])

    assert len(importer.plan(transfers, "transfer")) == 50
    assert len(importer.plan(receipts, "employee_receipt")) == 50
    with pytest.raises(ValueError, match="الحد الأقصى 50"):
        importer.plan(pd.concat([transfers, transfers.iloc[[0]]], ignore_index=True), "transfer")
    with pytest.raises(ValueError, match="الحد الأقصى 50"):
        importer.plan(pd.concat([receipts, receipts.iloc[[0]]], ignore_index=True), "employee_receipt")


def _excel(frame):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="الحركات", index=False)
    return out.getvalue()
