import os
import sqlite3
import tempfile
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
FINANCE_SCHEMA_PATH = Path(__file__).resolve().parent / "finance_schema.sql"


def run_tests():
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    finance_schema_sql = FINANCE_SCHEMA_PATH.read_text(encoding="utf-8")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(schema_sql)
        conn.executescript(finance_schema_sql)

        # Insert core entities
        conn.execute("INSERT INTO companies(name) VALUES ('شركة عميل تجريبية')")
        conn.execute("INSERT INTO employees(full_name) VALUES ('موظف تجريبي')")
        conn.execute("INSERT INTO contractors(name) VALUES ('متعهد تجريبي')")
        conn.execute("INSERT INTO representatives(name) VALUES ('مندوب تجريبي')")
        conn.execute("INSERT INTO representatives(name) VALUES ('مندوب تجريبي 2')")

        # Company-representative history (who brought company) with end date support
        conn.execute(
            """INSERT INTO company_representatives(company_id, representative_id, relationship_start, relationship_end, status)
               VALUES (1, 1, '2026-01-01', NULL, 'active')"""
        )
        conn.execute(
            """INSERT INTO company_representatives(company_id, representative_id, relationship_start, relationship_end, status)
               VALUES (1, 1, '2025-01-01', '2025-12-31', 'ended')"""
        )

        # Employee placement history (assignment and stop)
        conn.execute(
            """INSERT INTO employee_placements(employee_id, company_id, start_date, end_date, stop_reason, status)
               VALUES (1, 1, '2025-01-01', '2025-06-30', 'انتهاء فترة', 'ended')"""
        )
        conn.execute(
            """INSERT INTO employee_placements(employee_id, company_id, start_date, end_date, status)
               VALUES (1, 1, '2026-01-01', NULL, 'active')"""
        )

        # Multiple contractors per placement with independent agreements
        conn.execute(
            """INSERT INTO placement_contractors(placement_id, contractor_id, agreement_start, agreement_end, commission_type, commission_value, status)
               VALUES (2, 1, '2026-01-01', NULL, 'fixed', 300.0, 'active')"""
        )
        conn.execute(
            """INSERT INTO placement_contractors(placement_id, contractor_id, agreement_start, agreement_end, commission_type, commission_value, status)
               VALUES (2, 1, '2026-02-01', NULL, 'percentage', 5.0, 'active')"""
        )

        # Multiple representatives per placement with independent agreements
        conn.execute(
            """INSERT INTO placement_representatives(placement_id, representative_id, company_representative_id, agreement_start, commission_type, commission_value, status)
               VALUES (2, 1, 1, '2026-01-01', 'fixed', 200.0, 'active')"""
        )
        conn.execute(
            """INSERT INTO placement_representatives(placement_id, representative_id, agreement_start, commission_type, commission_value, status)
               VALUES (2, 2, '2026-01-01', 'percentage', 2.5, 'active')"""
        )

        # History preserved: both placements exist
        placements = conn.execute("SELECT COUNT(*) AS c FROM employee_placements WHERE employee_id=1").fetchone()["c"]
        assert placements == 2, f"expected 2 placement history records, got {placements}"

        # Multiple agreements exist independently
        pc = conn.execute("SELECT COUNT(*) AS c FROM placement_contractors WHERE placement_id=2").fetchone()["c"]
        pr = conn.execute("SELECT COUNT(*) AS c FROM placement_representatives WHERE placement_id=2").fetchone()["c"]
        assert pc == 2, f"expected 2 contractor agreements, got {pc}"
        assert pr == 2, f"expected 2 representative agreements, got {pr}"

        # FK prevents deleting company with placements (history protection)
        fk_blocked = False
        try:
            conn.execute("DELETE FROM companies WHERE id=1")
            conn.commit()
        except sqlite3.IntegrityError:
            fk_blocked = True
            conn.rollback()
        assert fk_blocked, "expected FK RESTRICT to prevent deleting company with historical placements"

        # Date check constraint works
        date_check_blocked = False
        try:
            conn.execute(
                """INSERT INTO employee_placements(employee_id, company_id, start_date, end_date, status)
                   VALUES (1, 1, '2026-05-01', '2026-01-01', 'ended')"""
            )
            conn.commit()
        except sqlite3.IntegrityError:
            date_check_blocked = True
            conn.rollback()
        assert date_check_blocked, "expected CHECK constraint to block invalid end_date"

        conn.commit()
        print("ALL TESTS PASSED")
        print(f"- placements_history={placements}")
        print(f"- contractor_agreements={pc}")
        print(f"- representative_agreements={pr}")
        print("- fk_restrict_on_company_delete=True")
        print("- date_check_constraint=True")
    finally:
        conn.close()
        try:
            os.remove(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    run_tests()
