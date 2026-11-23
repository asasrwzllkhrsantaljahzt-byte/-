-- SQLite schema for Saudi Recruitment Company Management System (Phase 1)
-- Professional, history-preserving core schema.

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    commercial_register TEXT,
    tax_number TEXT,
    contact_person TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    national_id TEXT UNIQUE, -- sensitive
    phone TEXT,
    email TEXT,
    bank_name TEXT, -- sensitive
    iban TEXT,      -- sensitive
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'suspended')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contractors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    id_number TEXT,
    phone TEXT,
    email TEXT,
    bank_name TEXT, -- sensitive
    iban TEXT,      -- sensitive
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS representatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    id_number TEXT,
    phone TEXT,
    email TEXT,
    bank_name TEXT, -- sensitive
    iban TEXT,      -- sensitive
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Historical placements/assignments of employees to client companies
CREATE TABLE IF NOT EXISTS employee_placements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL,
    start_date TEXT NOT NULL, -- YYYY-MM-DD
    end_date TEXT,            -- approved stop date; NULL means ongoing
    stop_reason TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended', 'suspended')),
    notes TEXT,
    flow_mode TEXT NOT NULL DEFAULT 'direct' CHECK (flow_mode IN ('direct', 'via_company')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CHECK (end_date IS NULL OR end_date >= start_date)
);

-- General contracts/agreements table (extensible foundation)
CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_type TEXT NOT NULL CHECK (contract_type IN ('client', 'contractor', 'representative', 'employee', 'other')),
    party_type TEXT NOT NULL, -- e.g. company/contractor/representative/employee
    party_id INTEGER NOT NULL,
    company_id INTEGER,
    start_date TEXT NOT NULL,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'ended', 'suspended')),
    terms_summary TEXT,
    document_ref TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CHECK (end_date IS NULL OR end_date >= start_date)
);

-- Audit log (foundation for immutable financial/history tracking in later phases)
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE_ATTEMPT', 'STATUS_CHANGE')),
    old_values TEXT, -- JSON string
    new_values TEXT, -- JSON string
    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by TEXT,
    note TEXT
);

-- Indexes for common lookups and history queries
CREATE INDEX IF NOT EXISTS idx_placements_employee ON employee_placements(employee_id);
CREATE INDEX IF NOT EXISTS idx_placements_company ON employee_placements(company_id);
CREATE INDEX IF NOT EXISTS idx_placements_dates ON employee_placements(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_contracts_party ON contracts(party_type, party_id);
CREATE INDEX IF NOT EXISTS idx_audit_record ON audit_log(table_name, record_id);

COMMIT;

-- Audit log is append-only: entries can never be edited or deleted.
CREATE TRIGGER IF NOT EXISTS trg_audit_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'سجل التدقيق للقراءة والإضافة فقط ولا يمكن تعديله.');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'سجل التدقيق للقراءة والإضافة فقط ولا يمكن حذفه.');
END;
