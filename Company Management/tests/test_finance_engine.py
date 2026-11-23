import os
import sqlite3
import tempfile
from pathlib import Path
import importlib.util
import sys

BASE = Path(__file__).resolve().parents[1]
SCHEMA = (BASE / "database" / "schema.sql").read_text(encoding="utf-8")
FIN_SCHEMA = (BASE / "database" / "finance_schema.sql").read_text(encoding="utf-8")


def setup_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.executescript(FIN_SCHEMA)
    return conn


def load_engine(db_path):
    # load finance_engine with db module pointing to temp db by monkeypatching db functions via import
    # Easier: import finance_engine and override get_connection
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    import finance_engine as fe

    def get_conn_override():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    fe.get_connection = get_conn_override
    fe.ensure_finance_schema = lambda conn=None: None  # schema already applied
    return fe


def insert_base(conn):
    conn.execute("INSERT INTO companies(id,name) VALUES (1,'شركة عميل أ')")
    conn.execute("INSERT INTO employees(id,full_name) VALUES (1,'موظف نشط')")
    conn.execute("INSERT INTO employees(id,full_name) VALUES (2,'موظف متوقف منتصف الشهر')")
    conn.execute("INSERT INTO employees(id,full_name) VALUES (3,'موظف بدأ منتصف الشهر')")
    conn.execute("INSERT INTO contractors(id,name) VALUES (1,'متعهد 1')")
    conn.execute("INSERT INTO representatives(id,name) VALUES (1,'مندوب 1')")
    # placements: (1) full month active, (2) ended mid-month, (3) started mid-month
    conn.execute("INSERT INTO employee_placements(id,employee_id,company_id,start_date,end_date,status) VALUES (1,1,1,'2026-03-01',NULL,'active')")
    conn.execute("INSERT INTO employee_placements(id,employee_id,company_id,start_date,end_date,stop_reason,status) VALUES (2,2,1,'2026-03-01','2026-03-15','توقف','ended')")
    conn.execute("INSERT INTO employee_placements(id,employee_id,company_id,start_date,end_date,status) VALUES (3,3,1,'2026-03-16',NULL,'active')")
    # agreements: fixed contractor 310 SAR/month full (prorated by days), representative 5% of base
    for pid in (1,2,3):
        conn.execute("INSERT INTO placement_contractors(placement_id,contractor_id,agreement_start,commission_type,commission_value,status) VALUES (?,?,?,?,?,?)", (pid,1,'2026-03-01','fixed',310.0,'active'))
        conn.execute("INSERT INTO placement_representatives(placement_id,representative_id,agreement_start,commission_type,commission_value,status) VALUES (?,?,?,?,?,?)", (pid,1,'2026-03-01','percentage',5.0,'active'))
    conn.commit()


def add_tx(conn, **kw):
    cols = [
        'tx_date','month_ref','placement_id','employee_id','company_id','contractor_id','representative_id','party_type','party_id',
        'category','direction','amount','currency','review_status','source_type','description'
    ]
    vals = [kw.get(c) for c in cols]
    conn.execute(f"INSERT INTO financial_transactions({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})", vals)


def main():
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        conn = setup_db(db_path)
        insert_base(conn)
        month = '2026-03'  # 31 days
        # Employee 1 (active full month): agreed 5000, wage 3000, bank 3000, refund 200, expense 100, pending_review 700
        add_tx(conn, tx_date='2026-03-05', month_ref=month, placement_id=1, employee_id=1, company_id=1, party_type='company', party_id=1, category='client_agreed_amount', direction='in', amount=5000, currency='SAR', review_status='approved', source_type='manual', description='اتفاق عميل')
        add_tx(conn, tx_date='2026-03-28', month_ref=month, placement_id=1, employee_id=1, company_id=1, party_type='employee', party_id=1, category='recorded_wage', direction='out', amount=3000, currency='SAR', review_status='approved', source_type='manual', description='أجر مسجل')
        add_tx(conn, tx_date='2026-03-28', month_ref=month, placement_id=1, employee_id=1, company_id=1, party_type='employee', party_id=1, category='bank_transfer_actual', direction='out', amount=3000, currency='SAR', review_status='approved', source_type='manual', description='حوالة فعلية')
        add_tx(conn, tx_date='2026-03-20', month_ref=month, placement_id=1, employee_id=1, company_id=1, party_type='company', party_id=1, category='refund_returned', direction='out', amount=200, currency='SAR', review_status='approved', source_type='manual', description='مبلغ مردود')
        add_tx(conn, tx_date='2026-03-10', month_ref=month, placement_id=1, employee_id=1, company_id=1, party_type='external', party_id=None, category='external_expense', direction='out', amount=100, currency='SAR', review_status='approved', source_type='manual', description='مصروف خارجي')
        add_tx(conn, tx_date='2026-03-12', month_ref=month, placement_id=1, employee_id=1, company_id=1, party_type='company', party_id=1, category='client_agreed_amount', direction='in', amount=700, currency='SAR', review_status='pending_review', source_type='manual', description='مبلغ قيد مراجعة نظامية')

        # Employee 2 stopped mid-month (ended 2026-03-15): agreed 3100, wage 1500, expense 0
        add_tx(conn, tx_date='2026-03-05', month_ref=month, placement_id=2, employee_id=2, company_id=1, party_type='company', party_id=1, category='client_agreed_amount', direction='in', amount=3100, currency='SAR', review_status='approved', source_type='manual', description='اتفاق عميل')
        add_tx(conn, tx_date='2026-03-15', month_ref=month, placement_id=2, employee_id=2, company_id=1, party_type='employee', party_id=2, category='recorded_wage', direction='out', amount=1500, currency='SAR', review_status='approved', source_type='manual', description='أجر مسجل')
        add_tx(conn, tx_date='2026-03-15', month_ref=month, placement_id=2, employee_id=2, company_id=1, party_type='employee', party_id=2, category='bank_transfer_actual', direction='out', amount=1400, currency='SAR', review_status='approved', source_type='manual', description='حوالة فعلية جزئية')

        # Employee 3 started mid-month (2026-03-16): agreed 1600, wage 800
        add_tx(conn, tx_date='2026-03-20', month_ref=month, placement_id=3, employee_id=3, company_id=1, party_type='company', party_id=1, category='client_agreed_amount', direction='in', amount=1600, currency='SAR', review_status='approved', source_type='manual', description='اتفاق عميل')
        add_tx(conn, tx_date='2026-03-28', month_ref=month, placement_id=3, employee_id=3, company_id=1, party_type='employee', party_id=3, category='recorded_wage', direction='out', amount=800, currency='SAR', review_status='approved', source_type='manual', description='أجر مسجل')
        add_tx(conn, tx_date='2026-03-28', month_ref=month, placement_id=3, employee_id=3, company_id=1, party_type='employee', party_id=3, category='bank_transfer_actual', direction='out', amount=800, currency='SAR', review_status='approved', source_type='manual', description='حوالة فعلية')
        conn.commit()
        conn.close()

        fe = load_engine(db_path)
        results = fe.calculate_month(month)
        by_pid = {r['placement_id']: r for r in results}

        # Assertions
        assert len(results) == 3, f"expected 3 results, got {len(results)}"
        r1, r2, r3 = by_pid[1], by_pid[2], by_pid[3]

        # Active full month: 31 days
        assert r1['active_days'] == 31
        assert r1['bank_transfers_actual_total'] == 3000.0
        assert r1['recorded_wages_total'] == 3000.0
        assert r1['refunds_returned_total'] == 200.0
        assert r1['external_expenses_total'] == 100.0
        assert r1['pending_review_total'] == 700.0
        # contractor fixed 310 prorated 31/31 = 310; rep 5% of approved client agreed 5000 = 250
        assert abs(r1['contractor_entitlements_total'] - 310.0) < 0.01
        assert abs(r1['representative_entitlements_total'] - 250.0) < 0.01
        # approved revenue = 5000-200=4800 (pending excluded); margin = 4800 - 3000 - 100 - 310 - 250 = 1140
        assert abs(r1['approved_company_revenue_total'] - 4800.0) < 0.01
        assert abs(r1['company_margin'] - 1140.0) < 0.01

        # Stopped mid-month (1-15): 15 days
        assert r2['active_days'] == 15
        assert r2['bank_transfers_actual_total'] == 1400.0
        assert r2['recorded_wages_total'] == 1500.0
        assert abs(r2['contractor_entitlements_total'] - round(310.0 * 15/31, 2)) < 0.01
        assert abs(r2['representative_entitlements_total'] - round(3100.0 * 0.05 * 15/31, 2)) < 0.01

        # Started mid-month (16-31): 16 days
        assert r3['active_days'] == 16
        assert abs(r3['contractor_entitlements_total'] - round(310.0 * 16/31, 2)) < 0.01
        assert abs(r3['representative_entitlements_total'] - round(1600.0 * 0.05 * 16/31, 2)) < 0.01

        # Party statements exist independently
        emp_stmt = fe.get_party_statement('employee', 1, month)
        con_stmt = fe.get_party_statement('contractor', 1, month)
        rep_stmt = fe.get_party_statement('representative', 1, month)
        comp_stmt = fe.get_party_statement('company', 1, month)
        assert len(emp_stmt) >= 2
        assert len(comp_stmt) >= 1
        # contractor/rep statements from manual/system txs in ledger (entitlements may be stored as calc txs in future; statement reads ledger)

        # Pending review not in margin check (explicit): r1 had 700 pending, margin unaffected by it
        assert r1['pending_review_total'] == 700.0
        assert abs(r1['company_margin'] - 1140.0) < 0.01

        print('FINANCE_TESTS_PASSED')
        print(f"month={month} month_days=31")
        for r in results:
            print('---')
            print(f"placement={r['placement_id']} employee={r['employee_name']} active_days={r['active_days']}/{r['month_days']}")
            print(f"client_agreed={r['client_agreed_total']} recorded_wage={r['recorded_wages_total']} bank_actual={r['bank_transfers_actual_total']} refunds={r['refunds_returned_total']} expenses={r['external_expenses_total']}")
            print(f"contractor_due={r['contractor_entitlements_total']} representative_due={r['representative_entitlements_total']} pending_review={r['pending_review_total']}")
            print(f"approved_revenue={r['approved_company_revenue_total']} company_margin={r['company_margin']}")
        print('---')
        print(f"statements: employee1={len(emp_stmt)} contractor1={len(con_stmt)} representative1={len(rep_stmt)} company1={len(comp_stmt)}")
        print('rule_pending_review_excluded_from_margin=True')
        return 0
    finally:
        try:
            os.remove(db_path)
        except OSError:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
