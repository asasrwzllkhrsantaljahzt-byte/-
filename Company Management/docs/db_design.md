# تصميم قاعدة بيانات نظام إدارة شركة توظيف (المرحلة الأولى)

## 1) المبادئ العامة
- **قاعدة البيانات**: SQLite (`database/app.db`) مع تفعيل قيود المفاتيح الخارجية (`PRAGMA foreign_keys = ON`).
- **الحفاظ على السجل التاريخي**: لا يتم حذف السجلات التشغيلية/المالية المعتمدة؛ يتم استخدام الحقول الزمنية والحالات (مثل `status`, `end_date`) لتعطيل/إيقاف العلاقات مع الاحتفاظ بتاريخها.
- **منع فقدان العمليات السابقة**: العلاقات التاريخية (التعيينات، التوقفات، ارتباطات المتعهدين والمندوبين) تُخزن في جداول سجلات مستقلة ولا تُستبدل.
- **التدقيق**: حقول `created_at`, `updated_at` في الجداول الأساسية، وجدول `audit_log` مخصص لتسجيل التعديلات (سيُستخدم بالكامل في المراحل اللاحقة).
- **البيانات الحساسة**: حقول الهوية والحسابات البنكية مخزنة في الجداول الأساسية لكن يجب حمايتها على مستوى التطبيق/الصلاحيات وعدم عرضها في التقارير العامة (سيُ enforced في المراحل اللاحقة).

## 2) مخطط الكيانات والعلاقات (ERD نصي)

```text
[companies] 1---* [company_representatives] *---1 [representatives]
     |  \
     |   \_________________________
     |                             \
     1                              (مرجع تاريخي لجلب الشركة)
     |
     * 
[employee_placements] *---1 [employees]
     |  \
     |   *---* [placement_contractors] *---1 [contractors]
     |
     *---* [placement_representatives] *---1 [representatives]

[agreements/contracts] (جدول عقود عام اختياري للربط المستقبلي)
[audit_log] يسجل عمليات على أي جدول (مرجع عام)
```

### تفسير العلاقات الأساسية
- **الموظف ↔ الشركة العميلة**: عبر جدول `employee_placements` (سجل تعيين/إسناد) يحتوي `employee_id`, `company_id`, `start_date`, `end_date`, `stop_reason`, `status`.
  - يسمح بالاحتفاظ بتاريخ جميع التعيينات والتوقفات (سجلات متعددة لنفس الموظف عبر الزمن).
- **الموظف ↔ المتعهد**: الموظف قد يكون له أكثر من متعهد باتفاقات مالية مستقلة. يتم الربط على مستوى التعيين عبر `placement_contractors`:
  - `placement_id`, `contractor_id`, `commission_type/value`, `start_date`, `end_date`, `status`, `notes`.
  - يسمح بتعدد المتعهدين واستقلال الاتفاق المالي لكل واحد.
- **الموظف ↔ المندوب**: المندوب يجلب الشركة العميلة، ويحصل على عمولة شهرية عن موظفي الشركات التي جلبها. 
  - علاقة "جلب الشركة" محفوظة تاريخياً في `company_representatives` (مندوب/شركة + فترة العلاقة).
  - استحقاق المندوب على مستوى الموظف/التعيين يُسجل في `placement_representatives` لتمثيل الاتفاق المالي المستقل لكل مندوب (مع السماح بالتعدد) مع ربطه بالسياق الزمني للتعيين.
  - عند انتهاء علاقة المندوب بالشركة، تُغلق سجلات العلاقة/الاستحقاق الجديدة بتاريخ الانتهاء مع الاحتفاظ بالسجل التاريخي.

## 3) الجداول وتعريفاتها

### 3.1 companies (الشركات العملاء)
- `id` INTEGER PK
- `name` TEXT NOT NULL UNIQUE
- `commercial_register` TEXT
- `tax_number` TEXT
- `contact_person` TEXT
- `phone` TEXT
- `email` TEXT
- `address` TEXT
- `status` TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive'))
- `notes` TEXT
- `created_at` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
- `updated_at` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

### 3.2 employees (الموظفون السعوديون)
- `id` INTEGER PK
- `full_name` TEXT NOT NULL
- `national_id` TEXT UNIQUE (حساس)
- `phone` TEXT
- `email` TEXT
- `bank_name` TEXT (حساس)
- `iban` TEXT (حساس)
- `status` TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive','suspended'))
- `notes` TEXT
- `created_at`, `updated_at`

### 3.3 contractors (المتعهدون)
- `id` INTEGER PK
- `name` TEXT NOT NULL
- `id_number` TEXT
- `phone` TEXT
- `bank_name` TEXT (حساس)
- `iban` TEXT (حساس)
- `status` TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive'))
- `notes` TEXT
- `created_at`, `updated_at`

### 3.4 representatives (المندوبون)
- نفس بنية المتعهد تقريباً (اسم، تواصل، حساب بنكي حساس، حالة).

### 3.5 company_representatives (تاريخ علاقة المندوب بالشركة العميلة)
يحفظ من جلب الشركة ومتى انتهت العلاقة.
- `id` INTEGER PK
- `company_id` INTEGER NOT NULL FK -> companies(id)
- `representative_id` INTEGER NOT NULL FK -> representatives(id)
- `relationship_start` TEXT NOT NULL (YYYY-MM-DD)
- `relationship_end` TEXT NULL (NULL = مستمرة)
- `status` TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','ended'))
- `notes` TEXT
- `created_at`, `updated_at`
- قيود: `CHECK(relationship_end IS NULL OR relationship_end >= relationship_start)`

### 3.6 employee_placements (سجل تعيينات الموظف لدى الشركات - تاريخي)
- `id` INTEGER PK
- `employee_id` INTEGER NOT NULL FK -> employees(id)
- `company_id` INTEGER NOT NULL FK -> companies(id)
- `start_date` TEXT NOT NULL
- `end_date` TEXT NULL (تاريخ التوقف المعتمد)
- `stop_reason` TEXT NULL
- `status` TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','ended','suspended'))
- `notes` TEXT
- `created_at`, `updated_at`
- قيود: `CHECK(end_date IS NULL OR end_date >= start_date)`
- فهرس على (`employee_id`, `company_id`, `start_date`)

### 3.7 placement_contractors (اتفاقات المتعهدين لكل تعيين موظف - متعددة ومستقلة)
- `id` INTEGER PK
- `placement_id` INTEGER NOT NULL FK -> employee_placements(id)
- `contractor_id` INTEGER NOT NULL FK -> contractors(id)
- `agreement_start` TEXT NOT NULL
- `agreement_end` TEXT NULL
- `commission_type` TEXT NOT NULL CHECK(commission_type IN ('fixed','percentage'))
- `commission_value` NUMERIC NOT NULL CHECK(commission_value >= 0)
- `currency` TEXT NOT NULL DEFAULT 'SAR'
- `status` TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','ended'))
- `notes` TEXT
- `created_at`, `updated_at`
- قيود تاريخية وفهرس (`placement_id`, `contractor_id`)

### 3.8 placement_representatives (اتفاقات المندوبين لكل تعيين موظف - متعددة ومستقلة)
- `id` INTEGER PK
- `placement_id` INTEGER NOT NULL FK -> employee_placements(id)
- `representative_id` INTEGER NOT NULL FK -> representatives(id)
- `company_representative_id` INTEGER NULL FK -> company_representatives(id) (لربط الاستحقاق بسجل جلب الشركة إن وجد)
- `agreement_start` TEXT NOT NULL
- `agreement_end` TEXT NULL
- `commission_type` TEXT NOT NULL CHECK(commission_type IN ('fixed','percentage'))
- `commission_value` NUMERIC NOT NULL CHECK(commission_value >= 0)
- `currency` TEXT NOT NULL DEFAULT 'SAR'
- `status` TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','ended'))
- `notes` TEXT
- `created_at`, `updated_at`

### 3.9 contracts (العقود/الاتفاقات العامة - أساس للتوسع)
- `id` INTEGER PK
- `contract_type` TEXT NOT NULL CHECK(contract_type IN ('client','contractor','representative','other'))
- `party_table` TEXT NOT NULL (اسم الجدول/نوع الطرف)
- `party_id` INTEGER NOT NULL
- `company_id` INTEGER NULL FK -> companies(id)
- `start_date`, `end_date`, `terms`, `status`, `document_ref`
- يسمح بتوثيق الاتفاقات بشكل مستقل مع الحفاظ على التاريخ.

### 3.10 audit_log (سجل التدقيق)
- `id` INTEGER PK
- `table_name` TEXT NOT NULL
- `record_id` INTEGER NOT NULL
- `action` TEXT NOT NULL CHECK(action IN ('INSERT','UPDATE','DELETE_ATTEMPT','STATUS_CHANGE'))
- `old_values` TEXT (JSON)
- `new_values` TEXT (JSON)
- `changed_at` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
- `changed_by` TEXT NULL (للمستخدمين مستقبلاً)
- `note` TEXT

## 4) سياسات الحماية ومنع فقدان البيانات (على مستوى القاعدة)
- تفعيل `PRAGMA foreign_keys = ON`.
- استخدام `ON DELETE RESTRICT` (افتراضي) للعلاقات المرجعية لمنع حذف طرف لديه سجلات تاريخية مرتبطة.
- عدم حذف سجلات `employee_placements`, `placement_contractors`, `placement_representatives`, `company_representatives` بعد اعتمادها؛ يتم الإيقاف عبر `end_date`/`status`.
- يمكن إضافة triggers لاحقاً لمنع حذف/تعديل الحركات المالية المعتمدة وتسجيل أي محاولة في `audit_log` (ستكتمل مع جداول الحسابات في المراحل التالية).

## 5) ما يغطيه هذا التصميم في المرحلة الأولى
- إدارة الكيانات الأساسية: الشركات العملاء، الموظفون، المتعهدون، المندوبون.
- ربط الموظف بالشركة والمتعهد والمندوب مع **سجل تاريخي** للتعيينات والتوقفات.
- دعم تعدد المتعهدين والمندوبين لكل موظف/تعيين مع اتفاق مالي مستقل لكل واحد.
- أساس قوي للتوسع نحو العقود، الحسابات الشهرية، التحصيلات، المدفوعات، المصروفات، والتقارير دون فقدان السجلات السابقة.
