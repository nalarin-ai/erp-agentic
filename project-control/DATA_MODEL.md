# Data Model Contract — ERP Kreasi Hebat

- Status: `DRAFT_LOGICAL`
- Purpose: product-level canonical model independent of final ERP implementation.
- Rule: store opaque account aliases/references here, never real account numbers or credentials.

## 1. Core masters

### `operating_unit`
- `id` UUID/opaque stable ID, PK
- `code` unique immutable code (`BANYUMEDIA`, `PR1ME`, `CONTRACTOR`, `HEAVY_EQUIPMENT`, `PT_TKH_OPS`, `BALONESIA`)
- `display_name`
- `status` (`ACTIVE`, `INACTIVE`, `PILOT_ONLY`)
- `parent_unit_id` nullable, restricted hierarchy
- `default_currency`
- `created_at`, `updated_at`

### `unit_branding_profile`
- `id`, `unit_id`, `version`, `status` (`DRAFT`, `ACTIVE`, `RETIRED`)
- `display_name`, `logo_asset_ref`, `quotation_template_ref`, `invoice_template_ref`
- `effective_from`, `effective_to`, `created_by`, `approved_by`
- one active profile per unit/document type/effective instant; assets are private/versioned references, not public URLs
- activation is audited; template rendering cannot supply or override legal issuer, tax, series, ledger, account, totals, or other protected financial identity fields.

### `unit_configuration_profile`
- `id`, `unit_id`, `schema_version`, `configuration_version`, `status` (`DRAFT`, `VALIDATED`, `ACTIVE`, `RETIRED`, `ROLLED_BACK`)
- typed references/values for branding profile, document series, currency, price list, payment terms, approval workflow/thresholds, sales pipeline, enabled modules, warehouse/project/cost-center mappings where applicable
- allowlisted `issuer_policy_ref`, `tax_profile_ref`, `receivable_ledger_policy_ref`, and `account_policy_ref`; no raw account number or credential
- `effective_from`, `effective_to`, `created_by`, `reviewed_by`, `activated_by`, `reason`, `previous_version_id`
- exactly one effective active version per unit/context; unknown keys, wrong types, dangling/incompatible references, and executable/script payloads are rejected.
- `configuration_version` is monotonic per unit/context. Every validate/activate/rollback command carries `expected_version`; compare-and-swap permits exactly one winner.
- persistence enforces a non-overlap/exclusion constraint for active effective intervals per unit/context.
- activation atomically validates references, retires/schedules the prior version, activates the new version, binds the immutable snapshot, and appends its audit event in one transaction; any failure rolls back all effects.
- rollback is a new candidate version referencing a verified prior snapshot and competes under the same CAS/interval rules; it never reactivates history in place.

### `unit_setting_definition`
- `key`, `schema_version`, `value_type`, constraints, default policy, sensitivity class, allowed roles, and compatibility validator
- settings are explicitly registered; free-form keys and arbitrary code are prohibited
- defaults may be global only when documented and safe; financial identity ambiguity never falls back silently.

### `legal_issuer`
- `id`, `code`, `display_name`
- `legal_entity_type`
- `tax_status` (`PPN_REGISTERED`, `NON_PPN`, `UNKNOWN_BLOCKED`)
- `status`
- sensitive legal/tax identifiers stored in protected ERP/config, not general audit/chat.

### `tax_profile`
- `id`, `issuer_id`
- `code`, `version`, `effective_from`, `effective_to`
- `tax_mode` (`PPN`, `NON_PPN`, `EXEMPT`, `UNKNOWN_BLOCKED`)
- rate/account mappings are configured only after qualified review.

### `bank_account_alias`
- `id`, `alias`, `display_label`
- `owner_issuer_id` nullable until enumerated
- `status`
- `secret_reference`/ERP record reference, never raw number in app logs
- `masked_hint` only if approved for display

### `unit_account_allowlist`
- `unit_id`, `account_alias_id`
- `is_default`
- `purpose`
- `effective_from`, `effective_to`
- unique active default per unit/purpose

### `issuer_account_allowlist`
- `issuer_id`, `account_alias_id`
- `tax_profile_id` nullable
- `effective_from`, `effective_to`

### `unit_issuer_policy`
- `unit_id`, `issuer_id`, `tax_profile_id`
- deterministic eligibility conditions stored as reviewed configuration
- `override_role`, `requires_reason`
- `policy_version`

### `invoice_series`
- `id`, `issuer_id`, `unit_id` nullable
- `series_code`, `document_type`
- `effective_from`, `effective_to`, `status`
- uniqueness/number generation delegated to ERP-supported mechanism.

### `receivable_ledger`
- `id`, `code`, `display_label`, `legal_issuer_id`, `accounting_company_ref`
- `currency`, `receivable_account_ref`, `status`, `effective_from`, `effective_to`
- provider account references remain protected configuration where sensitive.

### `receivable_ledger_policy`
- `unit_id`, `legal_issuer_id`, `tax_profile_id`, `currency`, `receivable_ledger_id`
- `policy_version`, `effective_from`, `effective_to`
- selected ledger must belong to the accounting company/legal issuer and currency context.

## 2. Identity and authorization

### `actor`
- `id`, `display_alias`, `status`
- no phone number/token in general domain tables.

### `channel_identity`
- `id`, `actor_id`, `platform`, `opaque_platform_user_id`
- `verified_at`, `status`
- unique platform identity binding.

### `channel_scope`
- `id`, `platform`, `opaque_chat_id`
- `unit_id`, `function_scope`, `status`
- chat scope does not grant individual permission by itself.

### `role_assignment`
- `actor_id`, `role_code`, `unit_id` nullable
- `valid_from`, `valid_to`, `assigned_by`, `reason`
- unique effective assignment per actor/role/unit; nullable `unit_id` is reserved for explicitly authorized global roles, never an implicit all-unit grant.

### `actor_unit_assignment`
- `actor_id`, `unit_id`, `status`, `valid_from`, `valid_to`
- `sales_scope_id` nullable, `role_profile_id`, `assigned_by`, `reason`, `version`
- many-to-many membership; at least one effective role/sales scope is required before access
- assignment revocation blocks new reads/writes immediately while preserving historical document/audit attribution.

### `active_unit_context`
- transient/session-bound `actor_id`, `unit_id`, `source_channel_id`, `selected_at`, `expires_at`, `assignment_version`
- never grants access by itself; every request revalidates the underlying assignment
- exactly one unit per command/query/mutation; ambiguous or stale context fails closed.

### `sales_scope`
- `id`, `unit_id`, `owner_actor/team_id`, `visibility_policy`

## 3. CRM and commercial documents

### `lead` / `customer_scope`
- unit and sales scope mandatory
- normalized contact identity stored with privacy controls
- cross-unit duplicate fingerprint may support safe conflict detection without exposing protected fields.

### `commercial_document`
Canonical descriptor mirrored to/from ERP:

- `id`, `external_reference`, `erp_record_id`
- `document_type` (`QUOTATION`, `SALES_INVOICE`, later others)
- orthogonal `posting_status`, `delivery_status`, `receivable_status`, and `recovery_status` as specified by `STATE_MACHINES.md`
- `unit_id`, `sales_scope_id`
- `branding_profile_id` and immutable rendered-branding snapshot/version
- `legal_issuer_id`, `tax_profile_id`, `invoice_series_id`
- `receivable_ledger_id` plus posted policy/configuration snapshot/version
- `destination_account_alias_id`
- `customer_id`
- `currency`, decimal `subtotal`, `discount`, `tax`, `total`, `open_amount`
- `issue_date`, `due_date`
- `source_channel_id`, `requested_by`, `reviewed_by`, `posted_by`
- `policy_version`, `created_at`, `updated_at`

Required database/application checks:

- monetary scale/precision and non-negative constraints according to document semantics;
- due date not before issue date unless explicit supported case;
- selected account must pass unit and issuer allowlists;
- selected receivable ledger must pass unit, issuer, tax, accounting-company, and currency compatibility;
- tax profile belongs to legal issuer;
- posted document identity fields immutable except supported amendment/reversal;
- posted branding snapshot immutable; later logo/template changes affect only new drafts/documents;
- unique `external_reference`/idempotency namespace.

### `commercial_document_line`
- `document_id`, ordered `line_no`
- `item/service_code`, description
- decimal quantity, unit, unit price, discount, tax category
- line totals recomputed/verified by ERP.

## 4. Payments and evidence

### `payment_record`
- `id`, `erp_record_id`, `external_reference`
- `document_id`, `account_alias_id`
- decimal amount, currency, payment date
- `evidence_id`, `reference_alias`
- `status` (`DRAFT`, `RECORDED`, `REVERSED`, `RECOVERY_REQUIRED`)
- actor/reviewer/audit fields
- unique idempotency/external reference.

### `evidence_object`
- `id`, object storage/ERP file reference
- classification, checksum, media type, size
- access policy, retention class
- uploader alias and timestamps
- no secret-bearing public URL.

## 5. Mutation and audit

### `mutation_intent`
- `id`, correlation ID, namespaced idempotency key (unique), canonicalization version
- action class, canonical payload hash
- actor, unit, issuer, target descriptor
- dry-run flag, policy version
- claim owner, monotonic fencing token, heartbeat/lease expiry
- status (`PLANNED`, `IN_PROGRESS`, `SUCCEEDED`, `DENIED`, `FAILED_NO_MUTATION`, `RECOVERY_REQUIRED`)
- timestamps and expiry where applicable.

### `audit_event`
Append-only:

- event ID, correlation ID, mutation intent ID
- actor alias, source alias, action, reason
- redacted before/after descriptors
- target provider/record alias
- outcome and verification descriptor
- timestamp, previous-event/checkpoint integrity metadata, retention/export class.

Exact claim, crash, audit durability, and reconciliation semantics are normative in `IDEMPOTENCY_AUDIT_RECOVERY.md`.

### `outbox_event`
For retryable notifications/webhooks separate from ERP transaction:

- event ID, aggregate/type, redacted payload reference
- attempts, next attempt, status, terminal error descriptor.

## 6. Initial seed mapping

| Unit | Default account alias | Additional rule |
|---|---|---|
| Banyumedia | `ACC-BANYUMEDIA-DEFAULT` | PT account only under valid PT issuer/PPN policy |
| Pr1me | `ACC-PR1ME-DEFAULT` | exact identity configured privately |
| Contractor | `ACC-CONTRACTOR-DEFAULT` | owner/default of shared mapping |
| Heavy Equipment | `ACC-CONTRACTOR-DEFAULT` | explicit shared allowlist |
| PT TKH | `ACC-PTTKH-DEFAULT` | required for PT TKH PPN path |
| Balonesia | `ACC-BALONESIA-DEFAULT` | later onboarding fixture |

Aliases are placeholders, not bank details.

## 7. Retention and deletion

- Posted financial/audit records are not hard-deleted through normal UI/chat.
- Retention periods remain open pending legal/accounting review.
- User/channel mappings may be deactivated; audit references remain pseudonymous as legally required.
- Payment evidence retention must align with accounting/tax requirements and privacy controls.
- Test fixtures are segregated and purgeable without touching production.

## 8. Migration principles

1. Import to staging.
2. Validate schema, unit, issuer, currency, duplicates, and references.
3. Produce dry-run summary and row-level errors.
4. Approve mapping/configuration under project policy.
5. Import a bounded batch with idempotency.
6. Reconcile counts/totals and sample documents.
7. Roll back/reverse using supported mechanism on failure.

No live migration plan is complete until source workbook shapes and authoritative opening balances are known.

## 9. Configuration implementation principle

Provider implementation should use supported ERPNext/Frappe configuration, fixtures, custom fields/DocTypes, print formats, workflows, roles, and a bounded custom app where evidence requires it. Unit-specific source branches and direct upstream-core patches are rejected unless a separately reviewed architecture change proves no supported extension path exists.
