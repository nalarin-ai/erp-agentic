# ERPNext Audit Evidence — EVAL-001

> Generated: `2026-08-14`
> Source: GitHub API + raw file fetch (read-only, no clone, no credential)
> Repository: `frappe/erpnext` @ `v16.32.1`

## Repository metadata (GitHub API)

```json
{
  "full_name": "frappe/erpnext",
  "html_url": "https://github.com/frappe/erpnext",
  "default_branch": "develop",
  "license": "GPL-3.0",
  "language": "Python",
  "created_at": "2011-06-08T08:20:56Z",
  "updated_at": "2026-08-14T11:04:28Z",
  "pushed_at": "2026-08-14T11:12:32Z",
  "stargazers_count": 38066,
  "forks_count": 12466,
  "open_issues_count": 1932,
  "visibility": "public",
  "archived": false,
  "disabled": false
}
```

## Latest releases (GitHub API)

| Tag | Published | Prerelease | Draft |
|---|---|---|---|
| v16.32.1 | 2026-08-14T06:20:52Z | False | False |
| v15.119.2 | 2026-08-14T06:20:20Z | False | False |
| v16.32.0 | 2026-08-11T23:39:46Z | False | False |
| v15.119.1 | 2026-08-11T23:19:54Z | False | False |
| v16.31.1 | 2026-08-06T08:12:47Z | False | False |

## pyproject.toml (v16.32.1)

- `name = "erpnext"`
- `requires-python = ">=3.14"`
- `frappe = ">=16.21.0,<17.0.0"` (bench dependency)
- Build backend: `flit_core`
- Key dependencies: `Unidecode`, `barcodenumber`, `rapidfuzz`, `holidays`, `googlemaps`, `plaid-python`, `python-youtube`, `pypng`, `mt-940`, `pdfplumber`

## hooks.py (v16.32.1)

- `app_name = "erpnext"`
- `app_license = "GNU General Public License (v3)"`
- `app_home = "/desk"`
- `setup_wizard_stages` present
- `website_route_rules` expose `/orders`, `/invoices`, `/supplier-quotations`, `/purchase-orders`, `/purchase-invoices`, `/quotations`, `/shipments`, `/rfq` to portal
- `extend_doctype_class` and `override_whitelisted_methods` hooks present

## DocType schemas (v16.32.1)

### Sales Invoice (`erpnext/accounts/doctype/sales_invoice/sales_invoice.json`)

- `is_submittable: 1`
- `track_changes: 1`
- `naming_rule: By "Naming Series" field`
- `autoname: naming_series:`
- Permission roles: `Accounts Manager`, `Accounts User`, `All`
- 233 fields; verified: `naming_series`, `company`, `customer`, `taxes`, `payment_schedule`

### Payment Entry (`erpnext/accounts/doctype/payment_entry/payment_entry.json`)

- `is_submittable: 1`
- `track_changes: 1`
- Permission roles: `Accounts Manager`, `Accounts User`
- 93 fields

### Company (`erpnext/setup/doctype/company/company.json`)

- Permission roles: `Accounts Manager`, `Accounts User`, `Auditor`, `Employee`, `HR Manager`, `HR User`, `Projects User`, `Purchase User`, `Sales User`, `Stock User`, `System Manager`
- 131 fields; verified: `default_bank_account`, `default_currency`, `tax_id`, `default_receivable_account`

### Mode of Payment (`erpnext/accounts/doctype/mode_of_payment/mode_of_payment.json`)

- Permission roles: `Accounts Manager`, `Accounts User`, `HR Manager`, `HR User`
- 4 fields

### Mode of Payment Account (child table, `erpnext/accounts/doctype/mode_of_payment_account/mode_of_payment_account.json`)

- `istable: 1`
- Fields: `company`, `default_account`

### Account (`erpnext/accounts/doctype/account/account.json`)

- Permission roles: `Accounts Manager`, `Accounts User`, `Auditor`, `HR Manager`, `HR User`, `Purchase User`, `Sales User`
- Verified fields: `account_type`, `root_type`, `company`

### Sales Taxes and Charges Template (`erpnext/accounts/doctype/sales_taxes_and_charges_template/sales_taxes_and_charges_template.json`)

- Permission roles: `Accounts Manager`, `Sales Master Manager`, `Sales User`
- Verified fields: `company`, `tax_category`

## Regional directories (`erpnext/regional/`)

- `australia`, `italy`, `south_africa`, `turkey`, `united_arab_emirates`, `united_states`, `address_template`, `print_format`, `report`
- **No `indonesia` directory found.**

## Sales Invoice controller (`erpnext/accounts/doctype/sales_invoice/sales_invoice.py`)

- Class: `SalesInvoice(SellingController)`
- Lifecycle methods present: `validate`, `on_submit`, `on_cancel`, `before_submit`, `before_cancel`, `set_status`, `make_gl_entries`
- `on_submit` calls `make_gl_entries()` at line ~509
- `on_cancel` calls `make_gl_entries_on_cancel()` at line ~633
- `check_permission` not overridden in `SalesInvoice` — inherits from `TransactionBase`/`StatusUpdater`

## Security and network observations

- REST API is available under `/api/resource/...` and `/api/method/...`
- Token-based authentication supported (`Authorization: token <api_key>:<api_secret>`)
- No evidence of network calls to external services in the audited files
- `website_route_rules` expose portal routes; these must be disabled or restricted in pilot

## Limitations of this audit

- Audit is based on GitHub API + raw file fetch; no local clone was performed.
- No runtime execution or database migration was tested.
- No Indonesian localization files were found; deeper search may be needed in `erpnext/regional/` subdirectories.
- No third-party app ecosystem (e.g., `frappe/erpnext` marketplace apps) was evaluated.
