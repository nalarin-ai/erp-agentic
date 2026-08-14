# ERPNext Candidate Audit — EVAL-001

> Audit date: `2026-08-14`
> Candidate: `frappe/erpnext` (GitHub)
> Audited ref: `v16.32.1` (latest stable at audit time)
> Source: https://github.com/frappe/erpnext
> License: GPL-3.0 (verified via `license.txt` and `hooks.py` `app_license`)

## 1. Canonical source and version pinning

| Item | Value | Evidence |
|---|---|---|
| Repository | `frappe/erpnext` | GitHub API `full_name` |
| Default branch | `develop` | GitHub API |
| Latest stable release | `v16.32.1` (2026-08-14) | GitHub API releases |
| Language | Python | GitHub API |
| License | GPL-3.0 | `license.txt` verbatim; `hooks.py` `app_license = "GNU General Public License (v3)"` |
| Build backend | `flit_core` | `pyproject.toml` `[build-system]` |
| Frappe dependency | `>=16.21.0,<17.0.0` | `pyproject.toml` `[tool.bench.frappe-dependencies]` |
| Python requirement | `>=3.14` | `pyproject.toml` `requires-python` |

**Pinned decision:** for any pilot environment, pin exactly one release tag (e.g. `v16.32.1`) and record the Git SHA. Do not track `develop` branch for reproducibility.

## 2. License and redistribution assessment

- **License:** GPL-3.0 (copyleft). Internal use without distribution does not trigger source-disclosure obligations. If the project ever distributes the combined work to third parties, GPL-3.0 obligations apply.
- **Implication for ERP Kreasi Hebat:** acceptable for internal ERP use. No license conflict with proprietary configuration or custom app code that is not distributed.
- **Risk:** LOW — internal use only; no distribution planned.

## 3. Core runtime and API surface

### 3.1 DocType architecture (verified via JSON schemas)

| DocType | Module | Submittable | Track changes | Permission roles | Key fields verified |
|---|---|---|---|---|---|
| `Sales Invoice` | Accounts | Yes | Yes | `Accounts Manager`, `Accounts User`, `All` | `naming_series`, `company`, `customer`, `taxes`, `payment_schedule` (233 fields) |
| `Payment Entry` | Accounts | Yes | Yes | `Accounts Manager`, `Accounts User` | 93 fields; no direct `default_account` on parent |
| `Mode of Payment` | Accounts | No | — | `Accounts Manager`, `Accounts User`, `HR Manager`, `HR User` | 4 fields |
| `Mode of Payment Account` (child) | Accounts | — | — | — | `company`, `default_account` |
| `Company` | Setup | No | — | `Accounts Manager`, `Accounts User`, `Auditor`, `Employee`, `HR Manager`, `HR User`, `Projects User`, `Purchase User`, `Sales User`, `Stock User`, `System Manager` | `default_bank_account`, `default_currency`, `tax_id`, `default_receivable_account` (131 fields) |
| `Account` | Accounts | No | — | `Accounts Manager`, `Accounts User`, `Auditor`, `HR Manager`, `HR User`, `Purchase User`, `Sales User` | `account_type`, `root_type`, `company` |
| `Sales Taxes and Charges Template` | Accounts | No | — | `Accounts Manager`, `Sales Master Manager`, `Sales User` | `company`, `tax_category` |

**Finding:** ERPNext has a mature submittable-document model with lifecycle hooks (`validate`, `on_submit`, `on_cancel`, `before_submit`, `before_cancel`) and automatic GL entry generation (`make_gl_entries`, `make_gl_entries_on_cancel`). `track_changes` is enabled on transactional documents.

### 3.2 Permissions model

- Permissions are role-based at DocType level (`permissions` array in JSON schema).
- `Sales Invoice` allows read access to role `All` by default — this must be restricted in pilot configuration to prevent cross-unit leakage.
- `Company` is readable by many roles including `Employee`, `Sales User`, `Stock User` — bank account and tax_id fields must be access-controlled via field-level permissions or custom roles.
- **Gap:** No native row-level/unit-level permission on `Sales Invoice` or `Customer` out-of-the-box. Frappe's `Permission Query Conditions` and `User Permissions` (document-level user permissions) are the supported mechanism for unit isolation.

### 3.3 Naming and series

- `Sales Invoice` uses `naming_series` field with `autoname = "naming_series:"`.
- **Gap:** Native naming series is per-Company, not per-Unit. Multi-unit series require either (a) separate Companies, or (b) custom naming logic via `autoname` hook in a bounded custom app.

## 4. Indonesian localization and tax readiness

### 4.1 Regional structure

`erpnext/regional/` contains: `australia`, `italy`, `south_africa`, `turkey`, `united_arab_emirates`, `united_states`, `address_template`, `print_format`, `report`.

**Finding:** No `indonesia` directory under `erpnext/regional/`. Indonesian tax (PPN) and e-Faktur integration are not native.

### 4.2 Tax capability

- `Sales Taxes and Charges Template` exists with `company` and `tax_category` fields.
- Tax calculation is engine-driven via `taxes` child table on `Sales Invoice`.
- **Gap:** No native PPN 11%/12% Indonesian tax template, no e-Faktur CSV export, no NPWP validation logic.

### 4.3 Currency

- `Company` has `default_currency`.
- `Sales Invoice` has `currency` field and `conversion_rate`.
- **Assessment:** Multi-currency support is mature; IDR is supported as a standard currency.

## 5. Financial identity and account mapping (R-016, R-017, R-019)

| Requirement | ERPNext native support | Gap / required customization |
|---|---|---|
| Legal issuer (`PT TKH` vs unit) | `Company` doctype represents legal entity | Must create one `Company` per legal issuer; units sharing one issuer map to same Company |
| Tax profile (PPN vs non-PPN) | `tax_category` + `Sales Taxes and Charges Template` | No native PPN template; must configure via fixtures/custom app |
| Invoice series | `naming_series` per Company | Per-unit series require custom `autoname` hook or separate Companies |
| Receivable ledger | `default_receivable_account` on Company; `Account` doctype with `root_type` | Must create separate `Account` per unit/ledger and map via custom logic or Company defaults |
| Destination bank account | `default_bank_account` on Company; `Mode of Payment Account` child table | No native unit-level bank account restriction; must enforce via custom validation or permission query conditions |

**Critical gap:** ERPNext's native `Company` is the primary financial boundary. The project requirement (R-017) treats `operating_unit`, `legal_issuer`, `tax_profile`, `invoice_series`, `receivable_ledger`, and `destination_account` as separate dimensions. ERPNext conflates these under `Company`. This means either:
- **Option A:** one Company per unit (breaks "one office" reporting, may over-fragment), or
- **Option B:** one Company per legal issuer + custom fields/permissions for unit-level dimensions (requires bounded custom app).

## 6. Idempotency, audit, and recovery (R-007, R-008, R-009)

### 6.1 Idempotency

- Frappe framework provides `frappe.db.savepoint` and transaction rollback.
- No native idempotency-key mechanism on document submission; duplicate submissions rely on database unique constraints (e.g., naming series collision) which are not user-friendly.
- **Gap:** External idempotency keys (chat message IDs) require a custom integration layer or middleware.

### 6.2 Audit trail

- `track_changes = 1` on `Sales Invoice` and `Payment Entry` enables field-level change history in the `Version` doctype.
- `Comment` doctype provides unstructured audit notes.
- **Gap:** No immutable append-only audit log with cryptographic chaining. The project's `FND-004` durable audit core is more rigorous than ERPNext native versioning.

### 6.3 Backup and restore

- Frappe framework supports `bench backup` (mariadb-dump + files tar).
- Restore is site-level, not per-document.
- **Gap:** No native point-in-time recovery (PITR) without external binlog management. Application-consistent backup requires quiescing workers.

## 7. Security and isolation (R-005, R-006)

### 7.1 Requirement traceability

| Requirement | Audit section | Coverage |
|---|---|---|
| R-005 | §3.2, §7.1, §7.2 | Finance/HR visibility narrower than general ops: ERPNext has role-based permissions but `Sales Invoice` readable by `All` by default. Separate create/approve/issue/mark-paid/admin permissions require custom role matrix. |
| R-006 | §1, §2, §8 | First pilot workflow is draft invoice → review/approval → official number/PDF → receivable → payment evidence/reminder, using synthetic data only. Audit confirms ERPNext supports submittable documents, naming series, payment entry, and print/PDF. |
| R-009 | §6.3, §10 | Backup, export, and restore must be exercised before production use. Indonesian accounting, tax, currency, numbering, and chart-of-accounts assumptions require qualified review (EXP-001). |
| R-016 | §5 | PT TKH as distinct VAT-registered legal issuer: ERPNext `Company` represents legal entity; `tax_id` field present. PPN transactions must be invoiced under PT TKH Company. |
| R-017 | §5 | Distinguish operating brand/unit, sales ownership, legal issuer, tax treatment, invoice series, receivable ledger, destination bank account: ERPNext conflates these under `Company`; custom fields or Company proliferation required. |
| R-019 | §5 | Bank accounts are configurable payment destinations; unit/legal issuer may have own default; approved account may be shared by multiple units: ERPNext `Mode of Payment Account` child table maps `company` → `default_account`; sharing across units requires either shared Company or custom validation. |

### 7.2 Network exposure

- ERPNext is a web application; by default it exposes HTTP/HTTPS.
- REST API (`/api/resource/...`) is available with token-based auth.
- **Risk:** API surface is broad; token leakage would allow document-level access within role permissions.

### 7.3 Native surfaces requiring isolation testing (per `NATIVE_ERP_ISOLATION.md`)

- Desk UI (list views, form views, reports)
- REST API (`/api/resource/...`, `/api/method/...`)
- Print/PDF generation
- File attachments
- Email notifications
- Background jobs (`frappe.enqueue`)
- Search (`frappe.search`)
- Report/export (CSV/Excel)

**Assessment:** All surfaces exist and are accessible to authenticated users within role permissions. Row-level isolation requires explicit configuration (User Permissions + Permission Query Conditions) and must be tested on every surface.

## 8. Synthetic fixture and isolation strategy

### 8.1 Proposed fixture

- **Company:** `PT TKH` (legal issuer) + one synthetic operating unit mapped to it.
- **Customer:** synthetic customer with no real PII.
- **Items:** synthetic service items (Google Ads, Event Organizer, Paving Block).
- **Tax:** custom `Sales Taxes and Charges Template` for PPN 11% (non-validated, fixture-only).
- **Bank account:** synthetic account with redacted alias.
- **Users:** `fixture-requester`, `fixture-finance`, `fixture-owner` with role assignments.

### 8.2 Isolation/teardown

- Use Frappe's `bench new-site` with `--db-name` isolated to a dedicated MariaDB schema.
- Use `--install-app erpnext` with exact pinned version.
- Teardown: `bench drop-site` + manual schema verification.
- No network access to external services; email disabled; background workers run in isolated queue.

## 9. Gaps and decision inputs for EVAL-002

| Gap ID | Severity | Description | Mitigation for EVAL-002 |
|---|---|---|---|
| GAP-001 | HIGH | No native Indonesian PPN/e-Faktur support | Custom fixture template + manual verification; no automated tax filing |
| GAP-002 | HIGH | Unit-level financial dimensions require custom app or Company proliferation | Evaluate Option B (custom fields + permission query conditions) in EVAL-002 |
| GAP-003 | MEDIUM | No native idempotency-key for external chat integration | Integration layer must implement idempotency before calling ERPNext |
| GAP-004 | MEDIUM | Audit trail is mutable `Version` doctype, not append-only | Rely on project's `FND-004` for durable audit; ERPNext versioning is secondary |
| GAP-005 | MEDIUM | No native PITR; backup is dump-based | Document RPO/RTO limits; require external binlog if tighter RPO needed |
| GAP-006 | LOW | `Sales Invoice` readable by role `All` | Restrict via custom role/permission in pilot setup |

## 10. Recommendation

ERPNext `v16.32.1` is **conditionally acceptable** as the system-of-record candidate for the synthetic pilot, provided that:

1. EVAL-002 builds an isolated environment with pinned version `v16.32.1` and validates all gaps above.
2. A bounded custom app (not upstream patches) implements unit-level fields and permission query conditions.
3. Indonesian localization gaps are documented and accepted by qualified finance/tax review (EXP-001) before any production consideration.
4. No live data, official posting, banking, or tax filing occurs until PROD-001 approves.

**Next step:** EVAL-002 — build isolated ERPNext environment with synthetic fixture and health-check.
