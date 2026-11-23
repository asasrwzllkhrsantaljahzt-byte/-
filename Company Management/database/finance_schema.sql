-- Finance engine schema extension (Phase 2 foundation)
PRAGMA foreign_keys = ON;
BEGIN TRANSACTION;

-- Integrated financial ledger / movements
CREATE TABLE IF NOT EXISTS financial_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_date TEXT NOT NULL,              -- YYYY-MM-DD
    month_ref TEXT NOT NULL,            -- YYYY-MM
    placement_id INTEGER,
    employee_id INTEGER,
    company_id INTEGER,
    contractor_id INTEGER,
    representative_id INTEGER,
    party_type TEXT,                    -- employee/contractor/representative/company/external/other
    party_id INTEGER,
    category TEXT NOT NULL CHECK (category IN (
        'client_agreed_amount',         -- المبلغ المتفق عليه مع العميل (تعاقدي/استحقاق)
        'recorded_wage',                -- الأجر المسجل تعاقدياً
        'bank_transfer_actual',         -- حوالة بنكية فعلية
        'refund_returned',              -- مبلغ مردود/معاد
        'external_expense',             -- مصروف خارجي
        'contractor_entitlement',       -- مستحق متعهد (محسوب)
        'representative_entitlement',   -- مستحق مندوب (محسوب)
        'approved_company_revenue',     -- إيراد معتمد للشركة
        'other'
    )),
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out', 'info')),
    amount NUMERIC NOT NULL CHECK (amount >= 0),
    currency TEXT NOT NULL DEFAULT 'SAR',
    review_status TEXT NOT NULL DEFAULT 'approved' CHECK (review_status IN ('approved', 'pending_review', 'rejected')),
    source_type TEXT NOT NULL DEFAULT 'manual' CHECK (source_type IN ('manual', 'system_calc', 'import')),
    description TEXT,
    document_ref TEXT,
    related_tx_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (placement_id) REFERENCES employee_placements(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (contractor_id) REFERENCES contractors(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (representative_id) REFERENCES representatives(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (related_tx_id) REFERENCES financial_transactions(id) ON DELETE RESTRICT ON UPDATE CASCADE
);

-- Monthly calculated results per employee placement context
CREATE TABLE IF NOT EXISTS monthly_employee_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month_ref TEXT NOT NULL,            -- YYYY-MM
    employee_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL,
    placement_id INTEGER NOT NULL,
    active_days INTEGER NOT NULL CHECK (active_days >= 0),
    month_days INTEGER NOT NULL CHECK (month_days >= 28),
    client_agreed_total NUMERIC NOT NULL DEFAULT 0,
    recorded_wages_total NUMERIC NOT NULL DEFAULT 0,
    bank_transfers_actual_total NUMERIC NOT NULL DEFAULT 0,
    refunds_returned_total NUMERIC NOT NULL DEFAULT 0,
    external_expenses_total NUMERIC NOT NULL DEFAULT 0,
    contractor_entitlements_total NUMERIC NOT NULL DEFAULT 0,
    representative_entitlements_total NUMERIC NOT NULL DEFAULT 0,
    approved_company_revenue_total NUMERIC NOT NULL DEFAULT 0,
    pending_review_total NUMERIC NOT NULL DEFAULT 0,
    company_margin NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'calculated' CHECK (status IN ('calculated', 'approved', 'void')),
    calculation_note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(month_ref, placement_id),
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (placement_id) REFERENCES employee_placements(id) ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ftx_month ON financial_transactions(month_ref);
CREATE INDEX IF NOT EXISTS idx_ftx_employee ON financial_transactions(employee_id);
CREATE INDEX IF NOT EXISTS idx_ftx_company ON financial_transactions(company_id);
CREATE INDEX IF NOT EXISTS idx_ftx_contractor ON financial_transactions(contractor_id);
CREATE INDEX IF NOT EXISTS idx_ftx_representative ON financial_transactions(representative_id);
CREATE INDEX IF NOT EXISTS idx_ftx_category ON financial_transactions(category, review_status);
CREATE INDEX IF NOT EXISTS idx_mea_month ON monthly_employee_accounts(month_ref);
CREATE INDEX IF NOT EXISTS idx_mea_employee ON monthly_employee_accounts(employee_id);

-- ===== Phase 5 protections (enforced inside the database) =====

-- 1) An approved transaction can never be deleted.
CREATE TRIGGER IF NOT EXISTS trg_ftx_no_delete_approved
BEFORE DELETE ON financial_transactions
WHEN OLD.review_status = 'approved'
BEGIN
    SELECT RAISE(ABORT, 'لا يجوز حذف حركة مالية معتمدة. استخدم الإلغاء المسجل من صفحة مراجعة الحركات.');
END;

-- 2) Financial fields of an approved transaction can never change; the only status change allowed is cancellation (rejected).
CREATE TRIGGER IF NOT EXISTS trg_ftx_approved_immutable
BEFORE UPDATE ON financial_transactions
WHEN OLD.review_status = 'approved' AND (
        OLD.tx_date IS NOT NEW.tx_date OR OLD.month_ref IS NOT NEW.month_ref
     OR OLD.placement_id IS NOT NEW.placement_id OR OLD.employee_id IS NOT NEW.employee_id
     OR OLD.company_id IS NOT NEW.company_id OR OLD.contractor_id IS NOT NEW.contractor_id
     OR OLD.representative_id IS NOT NEW.representative_id OR OLD.party_type IS NOT NEW.party_type
     OR OLD.party_id IS NOT NEW.party_id OR OLD.category IS NOT NEW.category
     OR OLD.direction IS NOT NEW.direction OR OLD.amount IS NOT NEW.amount
     OR OLD.currency IS NOT NEW.currency OR OLD.source_type IS NOT NEW.source_type
     OR NEW.review_status NOT IN ('approved', 'rejected'))
BEGIN
    SELECT RAISE(ABORT, 'لا يجوز تعديل بيانات حركة مالية معتمدة. يمكن فقط إلغاؤها مع تسجيل السبب.');
END;

-- 3) A closed (approved) month accepts no new, changed or cancelled transactions.
CREATE TRIGGER IF NOT EXISTS trg_ftx_month_locked_insert
BEFORE INSERT ON financial_transactions
WHEN EXISTS (SELECT 1 FROM monthly_employee_accounts WHERE month_ref = NEW.month_ref AND status = 'approved')
BEGIN
    SELECT RAISE(ABORT, 'هذا الشهر معتمد ومقفل. أعد فتح الشهر أولاً (مع تسجيل السبب) قبل إضافة حركات إليه.');
END;

CREATE TRIGGER IF NOT EXISTS trg_ftx_month_locked_update
BEFORE UPDATE ON financial_transactions
WHEN EXISTS (SELECT 1 FROM monthly_employee_accounts
             WHERE status = 'approved' AND month_ref IN (OLD.month_ref, NEW.month_ref))
BEGIN
    SELECT RAISE(ABORT, 'هذا الشهر معتمد ومقفل. أعد فتح الشهر أولاً (مع تسجيل السبب) قبل تعديل حركاته.');
END;

-- 4) Approved monthly results are frozen (only reopening, approved -> calculated, is allowed).
CREATE TRIGGER IF NOT EXISTS trg_mea_frozen_update
BEFORE UPDATE ON monthly_employee_accounts
WHEN OLD.status = 'approved' AND NEW.status = 'approved'
BEGIN
    SELECT RAISE(ABORT, 'نتائج هذا الشهر معتمدة ومقفلة ولا يمكن تعديلها.');
END;

CREATE TRIGGER IF NOT EXISTS trg_mea_frozen_delete
BEFORE DELETE ON monthly_employee_accounts
WHEN OLD.status = 'approved'
BEGIN
    SELECT RAISE(ABORT, 'نتائج هذا الشهر معتمدة ومقفلة ولا يمكن حذفها.');
END;

COMMIT;

-- ===== Per-party dues per month (written by calculate_month; frozen together with an approved month) =====
-- company  = what the client owes us (agreed amount)    employee = recorded wage owed to the employee
-- contractor / representative = their commission entitlements
CREATE TABLE IF NOT EXISTS party_dues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month_ref TEXT NOT NULL,
    placement_id INTEGER NOT NULL,
    party_type TEXT NOT NULL CHECK (party_type IN ('company','employee','contractor','representative')),
    party_id INTEGER NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    UNIQUE(month_ref, placement_id, party_type, party_id)
);
CREATE INDEX IF NOT EXISTS idx_party_dues_party ON party_dues(party_type, party_id);

CREATE TRIGGER IF NOT EXISTS trg_party_dues_frozen_del BEFORE DELETE ON party_dues
WHEN EXISTS (SELECT 1 FROM monthly_employee_accounts WHERE month_ref = OLD.month_ref AND placement_id = OLD.placement_id AND status = 'approved')
BEGIN SELECT RAISE(ABORT, 'مستحقات شهر معتمد مقفلة. أعد فتح الشهر أولاً.'); END;

CREATE TRIGGER IF NOT EXISTS trg_party_dues_frozen_upd BEFORE UPDATE ON party_dues
WHEN EXISTS (SELECT 1 FROM monthly_employee_accounts WHERE month_ref = OLD.month_ref AND placement_id = OLD.placement_id AND status = 'approved')
BEGIN SELECT RAISE(ABORT, 'مستحقات شهر معتمد مقفلة. أعد فتح الشهر أولاً.'); END;

-- ===== Flexible financial agreements (any beneficiary <-> client / employee / group) =====
CREATE TABLE IF NOT EXISTS fin_agreements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    beneficiary_type TEXT NOT NULL CHECK (beneficiary_type IN ('representative','contractor')),
    beneficiary_id INTEGER NOT NULL,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('client','placement','group')),
    company_id INTEGER,
    placement_id INTEGER,
    method TEXT NOT NULL CHECK (method IN ('fixed_monthly','per_employee','percent')),
    value NUMERIC NOT NULL CHECK (value >= 0),
    percent_basis TEXT CHECK (percent_basis IS NULL OR percent_basis IN ('agreed','after_refund','surplus','wage','margin')),
    prorate INTEGER NOT NULL DEFAULT 1 CHECK (prorate IN (0,1)),
    start_date TEXT NOT NULL,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','ended')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (end_date IS NULL OR end_date >= start_date),
    CHECK (scope_type <> 'client' OR company_id IS NOT NULL),
    CHECK (scope_type <> 'placement' OR placement_id IS NOT NULL),
    CHECK (method <> 'percent' OR percent_basis IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_fin_agr_ben ON fin_agreements(beneficiary_type, beneficiary_id);

CREATE TABLE IF NOT EXISTS fin_agreement_members (
    agreement_id INTEGER NOT NULL,
    placement_id INTEGER NOT NULL,
    PRIMARY KEY (agreement_id, placement_id),
    FOREIGN KEY (agreement_id) REFERENCES fin_agreements(id) ON DELETE CASCADE,
    FOREIGN KEY (placement_id) REFERENCES employee_placements(id) ON DELETE RESTRICT
);

-- How every commission number was reached (who, why, count, rule, value, period)
CREATE TABLE IF NOT EXISTS agreement_calc_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month_ref TEXT NOT NULL,
    placement_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_id INTEGER,
    beneficiary_type TEXT NOT NULL,
    beneficiary_id INTEGER NOT NULL,
    amount NUMERIC NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_acl_month ON agreement_calc_log(month_ref, placement_id);
CREATE INDEX IF NOT EXISTS idx_acl_ben ON agreement_calc_log(beneficiary_type, beneficiary_id);

CREATE TRIGGER IF NOT EXISTS trg_fin_agr_no_delete_used BEFORE DELETE ON fin_agreements
WHEN EXISTS (SELECT 1 FROM agreement_calc_log WHERE source='fin_agreements' AND source_id=OLD.id)
BEGIN SELECT RAISE(ABORT, 'هذا الاتفاق دخل في حسابات سابقة ولا يُحذف. أنهِه بتاريخ انتهاء بدلاً من ذلك.'); END;

-- ===== Legacy placement agreement compatibility =====
-- Kept for older pages/tests and for automatic migration of databases created
-- before the company-hub engine became the primary interface.
CREATE TABLE IF NOT EXISTS company_representatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    representative_id INTEGER NOT NULL,
    relationship_start TEXT NOT NULL,
    relationship_end TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended')),
    end_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (representative_id) REFERENCES representatives(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CHECK (relationship_end IS NULL OR relationship_end >= relationship_start)
);

CREATE TABLE IF NOT EXISTS placement_contractors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    placement_id INTEGER NOT NULL,
    contractor_id INTEGER NOT NULL,
    agreement_start TEXT NOT NULL,
    agreement_end TEXT,
    commission_type TEXT NOT NULL CHECK (commission_type IN ('fixed', 'percentage')),
    commission_value NUMERIC NOT NULL CHECK (commission_value >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended')),
    end_reason TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (placement_id) REFERENCES employee_placements(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (contractor_id) REFERENCES contractors(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CHECK (agreement_end IS NULL OR agreement_end >= agreement_start)
);

CREATE TABLE IF NOT EXISTS placement_representatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    placement_id INTEGER NOT NULL,
    representative_id INTEGER NOT NULL,
    company_representative_id INTEGER,
    agreement_start TEXT NOT NULL,
    agreement_end TEXT,
    commission_type TEXT NOT NULL CHECK (commission_type IN ('fixed', 'percentage')),
    commission_value NUMERIC NOT NULL CHECK (commission_value >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended')),
    end_reason TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (placement_id) REFERENCES employee_placements(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (representative_id) REFERENCES representatives(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (company_representative_id) REFERENCES company_representatives(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CHECK (agreement_end IS NULL OR agreement_end >= agreement_start)
);
