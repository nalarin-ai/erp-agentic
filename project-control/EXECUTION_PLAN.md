# Execution Plan — ERP Kreasi Hebat

Plan state: revised after Pass 1/2 and writer amendment. Hermes is the sole source writer and primary verifier; every task still requires one writer lease and independent read-only QA before downstream promotion.

## Rules

- No source task is `READY` before `PLAN-001` passes.
- Requirement tags refer to `REQUIREMENTS.md`; FR/J/MVP ownership is normative in `TRACEABILITY_MATRIX.md`.
- Production/live data/official posting remains prohibited until `PROD-001=APPROVED`.
- Paths below are non-overlapping; later stack-specific amendment may narrow them further before readiness.

## Tasks

### SEC-001 — Verify project approval and safety boundary

**Requirements:** R-005, R-007, R-008
**Dependencies:** none
**Owned paths:** `project-control/project-policy.json`, `project-control/full-auto-standing-approval.json`
**Status:** `DONE`

Steps:
1. Verify project/profile/repository/worktree/bot/chat/authorized Bos bindings.
2. Verify FULL_AUTO standing approval is active and not revoked.
3. Verify mandatory protected and prohibited action sets fail closed under mutation tests.

Tests: strict policy validator plus removal/empty/unknown/duplicate/wrong-type regression mutants.
Done when: exact boundary and mandatory prohibitions pass and evidence contains no credentials.

### PLAN-001 — Complete discovery and plan assurance

**Requirements:** R-001..R-022
**Dependencies:** SEC-001
**Owned paths:** `project-control/**`, `.hermes/plans/**`, `scripts/validate_plan_gate.py`
**Status:** `DONE`

Steps:
1. Maintain normative product/design/traceability baseline.
2. Run Pass 1/2, revise findings, then fresh Pass 3.
3. Run structural/graph/path validation and bind byte-exact baseline.

Tests: plan validator, JSON/link/secret scan, `git diff --check`, review ledger.
Done when: no open CRITICAL/HIGH; MEDIUM resolved/accepted; fresh review and gate PASS.

### EVAL-001 — Audit and pin ERPNext candidate

**Requirements:** R-005, R-006, R-009, R-016, R-017, R-019
**Dependencies:** PLAN-001
**Owned paths:** `evaluation/erpnext/**`, `docs/evidence/erpnext-audit/**`
**Status:** `DONE`

Steps:
1. Audit canonical source/version/license/runtime/API/permissions/localization.
2. Define synthetic fixture and isolation/teardown.
3. Record gaps and pinned decision inputs.

Tests: source/license/version/no-secret audit.
Done when: reproducible audited candidate baseline exists.

### EVAL-002 — Isolated ERPNext environment

**Requirements:** R-005, R-006, R-009, R-016
**Dependencies:** EVAL-001
**Owned paths:** `environments/erpnext-pilot/**`, `docs/evidence/erpnext-runtime/**`
**Status:** `DONE`

Steps:
1. Build non-production configuration with local synthetic secrets.
2. Start and health-check pinned stack.
3. Seed fixtures, back up, restore separately, verify, and tear down.

Tests: config/health/API/backup/restore smoke.
Done when: isolated stack and restore are reproducible.

### EVAL-003 — Optional ERPClaw comparator

**Requirements:** R-005, R-006, R-009
**Dependencies:** PLAN-001
**Owned paths:** `evaluation/erpclaw/**`, `environments/erpclaw-pilot/**`, `docs/evidence/erpclaw/**`
**Status:** `BACKLOG_OPTIONAL`

Steps:
1. Pin/audit source, license, permissions, network, and dependencies.
2. Run isolated synthetic fixture.
3. Apply identical ledger/permission/recovery/restore rubric.

Tests: source/security/invariant/restore evidence.
Done when: comparator decision is evidence-backed and never treated as official ledger by default.

### FND-001 — Provider-neutral domain contracts

**Requirements:** R-004, R-005, R-006, R-007, R-008, R-017, R-019
**Dependencies:** PLAN-001
**Owned paths:** `src/domain/**`, `src/contracts/**`, `tests/unit/domain/**`
**Status:** `DONE`

Steps:
1. Write failing tests for money and unit/issuer/tax/series/ledger/account descriptors.
2. Implement immutable types, canonical payload, errors, and state dimensions.
3. Verify serialization and redaction without network/provider.

Tests: unit/type/lint/redaction.
Done when: every financial identity dimension is explicit and ambiguity fails closed.

### FND-002 — Identity, channel scope, and RBAC

**Requirements:** R-003, R-004, R-007, R-011, R-021
**Dependencies:** FND-001
**Owned paths:** `src/authz/**`, `tests/unit/authz/**`
**Status:** `DONE`

Steps:
1. Write actor+channel+many-to-many-unit+role+action matrix tests including zero/one/multiple assignment contexts.
2. Implement default-deny resolution, exactly-one active unit context, assignment revalidation, and safe denials.
3. Verify unit switching, stale preview/cache invalidation, deactivation/revocation, and cross-unit conflict privacy.

Tests: table-driven positive/negative authorization.
Done when: unauthorized reads/writes disclose nothing protected and make zero provider writes.

### FND-003 — Financial identity policy

**Requirements:** R-016, R-017, R-019
**Dependencies:** FND-001
**Owned paths:** `src/policy/**`, `tests/unit/policy/**`
**Status:** `DONE`

Steps:
1. Test unit defaults, Heavy Equipment sharing, PT PPN, ledger, unknown, and override cases.
2. Implement versioned issuer/tax/series/ledger/account compatibility.
3. Emit redacted preview/audit descriptors and posted snapshot.

Tests: exhaustive matrix/property tests.
Done when: invalid combinations cannot reach adapters; fixture decisions are deterministic.

### FND-004 — Idempotency and durable audit core

**Requirements:** R-007, R-008
**Dependencies:** FND-001
**Owned paths:** `src/mutations/**`, `src/audit/**`, `db/migrations/mutation_audit/**`, `tests/mutation_audit/**`
**Status:** `DONE`

Steps:
1. Test namespaced hash, CAS claim, fencing/lease, stale worker, and every crash boundary.
2. Implement durable precondition, append-only integrity metadata, and uncertain states.
3. Test storage-full, terminal-audit failure, reconnect, redaction, and provider external-reference collision.

Tests: cross-process concurrency/crash/audit durability suite.
Done when: one provider action is evidenced under tested races and audit fails closed before mutation.

### UNIT-001 — Configurable units and onboarding

**Requirements:** R-001, R-002, R-012, R-013, R-014, R-015, R-018, R-020, R-021, R-022
**Dependencies:** FND-001, FND-002, FND-003
**Owned paths:** `src/units/**`, `config/fixtures/units/**`, `tests/units/**`
**Status:** `DONE`

Steps:
1. Define and test the typed allowlisted unit-setting schema, monotonic version/CAS and non-overlapping effective-interval lifecycle, all confirmed units, service categories, assignments, branding, and shared-account mapping.
2. Implement draft/validate/preview/atomic activate-retire-snapshot-audit/rollback for settings covering membership, branding/templates, numbering, currency/price/payment terms, approval workflow, modules, pipeline, policy references, and chat bindings.
3. Add Balonesia and a second synthetic unit only through settings/fixtures; inspect source/upstream-core diff for forbidden unit-name conditionals or patches.

Tests: schema/property/config lifecycle/CAS race/atomicity/effective-interval/permission/branding/onboarding/no-hardcode tests.
Done when: all confirmed units are reproducible, invalid settings fail closed, rollback restores a verified prior version, and Balonesia proves extensibility without unit-specific source branches.

### ADP-001 — Fixture ERP adapter

**Requirements:** R-005, R-006, R-007, R-008, R-017
**Dependencies:** FND-001, FND-004
**Owned paths:** `src/adapters/fixture/**`, `tests/contracts/erp_port/**`
**Status:** `DONE`

Steps:
1. Define document/payment/query provider port and tests.
2. Implement deterministic network-disabled adapter with failure injection.
3. Exercise posting/readback/payment/reversal/outbox/recovery.

Tests: provider contract suite.
Done when: complete synthetic vertical slice runs offline.

### REC-001 — Reconciliation engine and queue

**Requirements:** R-007, R-008
**Dependencies:** FND-004, ADP-001
**Owned paths:** `src/reconciliation/**`, `ui/reconciliation/**`, `tests/reconciliation/**`, `docs/runbooks/reconciliation.md`
**Status:** `DONE`

Steps:
1. Test present/absent/ambiguous/unavailable classification with fencing.
2. Implement durable worker/operator queue, lookup, safe retry, escalation, SLA/alert, and restart replay.
3. Verify terminal audit and ERP-to-audit orphan reports.

Tests: crash/restart/concurrency/reconciliation matrix.
Done when: recovery items cannot remain silently stuck and no blind reissue occurs.

### ADP-002 — ERPNext adapter

**Requirements:** R-005, R-006, R-007, R-008, R-016, R-017, R-019, R-021
**Dependencies:** EVAL-002, ADP-001, FND-002, FND-003, FND-004, REC-001
**Owned paths:** `src/adapters/erpnext/**`, `tests/integration/erpnext/**`
**Status:** `DONE`

Steps:
1. Run provider-neutral contracts against isolated ERPNext.
2. Implement least-privilege customer/invoice/ledger/PDF/AR/payment/reversal/readback APIs.
3. Test zero/one/multi assignment, switch/expiry/revocation and stale context across direct API/record URL/PDF/attachment/notification/job surfaces, plus timeouts, reconciliation, and redacted errors.

Tests: contract/integration/negative permission/no-direct-DB.
Done when: ERPNext passes fixture contracts and verified outcome invariants.

### CRM-001 — Unit-private CRM

**Requirements:** R-002, R-003, R-011, R-015, R-021
**Dependencies:** FND-002, UNIT-001, ADP-002
**Owned paths:** `src/crm/**`, `src/adapters/erpnext_crm/**`, `tests/crm/**`
**Status:** `DONE`

Steps:
1. Define lead/opportunity/customer/quotation/search/export/conflict ports.
2. Implement unit/sales ownership and controller transfer.
3. Test zero/one/multi assignment, switch/expiry/revocation, stale cache, pagination/count/error/export leakage and duplicate conflict privacy.

Tests: CRM provider contracts and authorization matrix.
Done when: competing sales isolation is proven for built CRM surfaces.

### ISO-001 — Native ERP isolation qualification

**Requirements:** R-003, R-011, R-021
**Dependencies:** EVAL-002, UNIT-001, CRM-001
**Owned paths:** `tests/security/native_erp/**`, `docs/evidence/native-isolation/**`
**Status:** `BACKLOG`

Steps:
1. Test all surfaces listed in `NATIVE_ERP_ISOLATION.md` with direct credentials.
2. Exercise zero/one/multi assignment, switch/expiry/revocation and stale context on every native surface; reproduce and mitigate leaks at pinned version.
3. Record ADR for single-site, multi-site, or gateway-only access.

Tests: UI/API/search/report/export/PDF/attachment/notification/background-job matrix.
Done when: current architecture receives a qualification verdict and any unsafe single-site result explicitly selects an alternative for ISOFIX-001; this task alone never opens PILOT-001.

### ISOFIX-001 — Final isolation architecture implementation and requalification

**Requirements:** R-003, R-011, R-021
**Dependencies:** ISO-001
**Owned paths:** `src/isolation_architecture/**`, `environments/isolation-final/**`, `tests/security/isolation_final/**`, `docs/evidence/isolation-final/**`
**Status:** `BACKLOG`

Steps:
1. Read ISO-001 verdict; if current architecture passed, pin its exact configuration, otherwise implement the selected multi-site or gateway-only alternative including runtime/adapter/config and fixture migration changes.
2. Re-run gateway and every native surface matrix against final architecture using fresh zero/one/multi-assignment, switch, expiry, revocation and stale-cache/preview fixtures with direct credentials where applicable.
3. Record final ADR/config hash, migration/rollback evidence, and fail-closed `ISOLATION_FINAL=PASS`; any unresolved leak keeps the task failed and PILOT blocked.

Tests: repeated UI/API/search/report/export/PDF/attachment/notification/background-job matrix plus fixture migration/rollback and configuration drift test.
Done when: the actually implemented final architecture - not merely a rejected option or prose ADR - has fresh `ISOLATION_FINAL=PASS` evidence.

### FLOW-001 — Chat invoice draft and preview

**Requirements:** R-003, R-004, R-006, R-007, R-011, R-016, R-017, R-019, R-020, R-021, R-022
**Dependencies:** FND-002, FND-003, ADP-001, UNIT-001
**Owned paths:** `src/workflows/invoice_draft/**`, `src/channels/**`, `tests/workflows/invoice_draft/**`
**Status:** `DONE`

Steps:
1. Test missing/ambiguous/denied/cancel/edit/stale states plus multi-unit selection, revoked assignment, and configuration-version conflict.
2. Implement normalized collection and preview including one active unit, branding/template version, ledger/account, and separate issuer/tax identity.
3. Prove preview makes zero provider writes and unit/config/material edits invalidate hash and scoped caches.

Tests: transcript/state/zero-write tests.
Done when: users get complete preview or precise safe blocker without guessing.

### FLOW-002 — Invoice review and posting

**Requirements:** R-004, R-005, R-006, R-007, R-008, R-016, R-017, R-019, R-020, R-021, R-022
**Dependencies:** FLOW-001, ADP-002, REC-001
**Owned paths:** `src/workflows/invoice_post/**`, `tests/workflows/invoice_post/**`
**Status:** `DONE`

Steps:
1. Test review separation, stale unit/config/branding preview, template placeholder safety, orthogonal states, and supported cancellation.
2. Implement fenced post/readback, immutable branding/config snapshot, and unit-template PDF reference while financial identity remains provider/policy-derived.
3. Emit separately idempotent delivery outbox state and prove later branding/config changes do not rewrite historical PDFs.

Tests: integration/E2E/audit/state transitions.
Done when: official number exists only after verified post and delivery remains orthogonal.

### FLOW-003 — Payment evidence and receivables

**Requirements:** R-006, R-007, R-008, R-013, R-017, R-019
**Dependencies:** FLOW-002
**Owned paths:** `src/workflows/payments/**`, `src/reports/receivables/**`, `tests/workflows/payments/**`
**Status:** `DONE`

Steps:
1. Test partial/full/overpay, wrong account/ledger, duplicates, races, and denied actions.
2. Implement evidence metadata, payment/readback, and receivable status.
3. Reconcile balances and verify authorized aging query.

Tests: money/integration/E2E/privacy tests.
Done when: balances reconcile and chat text alone cannot confirm payment.

### REM-001 — Receivable reminders

**Requirements:** R-006, R-007, R-011, R-021
**Dependencies:** FLOW-003, FND-002
**Owned paths:** `src/workflows/reminders/**`, `tests/reminders/**`
**Status:** `BACKLOG_POST_MVP`

Steps:
1. Define aging trigger, recipients, destination authorization, opt-out/cancel, and templates.
2. Implement redacted idempotent outbox and bounded retry.
3. Test assignment expiry/revocation between eligibility and job execution, failed delivery, paid/cancelled suppression, privacy, and events.

Tests: schedule/idempotency/privacy/failure injection.
Done when: reminders cannot duplicate, disclose, or send after terminal receivable state.

### RPT-001 — Owner financial roll-up

**Requirements:** R-001, R-011, R-021
**Dependencies:** FND-002, FLOW-003
**Owned paths:** `src/reports/owner/**`, `ui/reports/owner/**`, `tests/reports/owner/**`
**Status:** `DONE`

Steps:
1. Test unit/issuer summaries against synthetic ledgers.
2. Implement explicit authorized aggregation without ledger merge.
3. Verify zero/one/multi assignment, switch/revocation/cache invalidation, filters/count/export/error routes do not leak to unauthorized roles.

Tests: report reconciliation and negative authorization.
Done when: owner roll-up reconciles and unit users see no cross-unit data.

### UX-001 — Review/receivable UX and accessibility

**Requirements:** R-004, R-006, R-007, R-011, R-020, R-021, R-022
**Dependencies:** FLOW-001, FLOW-002, FLOW-003
**Owned paths:** `ui/invoice_review/**`, `ui/receivables/**`, `tests/ui/**`, `docs/evidence/ux/**`
**Status:** `DONE`

Steps:
1. Implement state/journey tables, assigned-unit selector, branding preview, and typed unit-settings lifecycle from UX specification.
2. Test compact/wide, keyboard/focus, semantics, denied/read-only, version conflict, errors, activation/rollback, offline/recovery.
3. Obtain independent UX/a11y review and close findings for review/AR/settings/unit-switch flows.

Tests: component/browser/screenshots/keyboard/build/type/lint.
Done when: UX evidence matrix and independent review pass.

### MIG-001 — Generic safe import contract

**Requirements:** R-005, R-008
**Dependencies:** FND-001, ADP-001
**Owned paths:** `src/imports/**`, `tests/imports/**`
**Status:** `DONE`

Steps:
1. Test hostile/synthetic CSV/XLSX with strict format/size/row/decompression limits.
2. Implement quarantine, encryption/TTL/purge, safe paths, formula-neutralized export, redacted errors, dedupe, and zero-write dry-run.
3. Implement bounded fixture batch, reconciliation, and reversal contract.

Tests: macro/zip bomb/traversal/formula/duplicate/disclosure/parser-limit cases.
Done when: generic fixture import is safe and reconciles without owner workbook.

### MIGSRC-001 — Source workbook profile and trial

**Requirements:** R-005, R-008
**Dependencies:** MIG-001, ADP-002
**Owned paths:** `docs/evidence/migration-source/**`, `config/migration-maps/**`, `tests/fixtures/migration-sanitized/**`
**Status:** `BLOCKED_OWNER_INPUT`

Steps:
1. Inventory authoritative schemas using sanitized samples.
2. Define reviewed mapping, trial, rejection, totals, and opening balances.
3. Reconcile bounded trial and rollback evidence.

Tests: source-specific dry-run/mapping/reconciliation.
Done when: trial reconciles and repository contains no live secrets/data.

### OPS-001 — Backup, restore, observability, operations

**Requirements:** R-008, R-009, R-016
**Dependencies:** EVAL-002, FND-004, ADP-002, REC-001
**Owned paths:** `ops/**`, `scripts/backup/**`, `docs/runbooks/operations/**`, `tests/operations/**`
**Status:** `BACKLOG`

Steps:
1. Define application-consistent multi-store backup manifest, RPO/RTO, encryption-key recovery, immutable off-host retention, and isolated identity/network restore.
2. Implement backup/export/restore and cross-store reconciliation.
3. Test host loss, corrupt/undecryptable backup, version compatibility, storage pressure, and runbooks.

Tests: failure injection, checksums/decryption, isolated restore, measured RPO/RTO.
Done when: fresh restore evidence reconciles DB/files/config/audit/outbox and meets chosen targets.

### PILOT-001 — Synthetic E2E acceptance

**Requirements:** R-001..R-022 except R-010 post-MVP delivery
**Dependencies:** FLOW-001, FLOW-002, FLOW-003, CRM-001, UNIT-001, ISOFIX-001, UX-001, RPT-001, OPS-001, REC-001
**Owned paths:** `tests/e2e/pilot/**`, `docs/evidence/pilot/**`
**Status:** `BACKLOG`

Steps:
1. Seed synthetic roles, multi-unit assignments, versioned unit settings/branding, issuer/tax/ledger/account/customer/services.
2. Run all `MVP-AC-01..15`, including distinct unit templates, unit switching/revocation, and no-hardcode onboarding, plus positive/negative/retry/recovery journeys.
3. Produce product-fit/localization/configurability/performance/restore/assumption report.

Tests: exact acceptance matrix in `TRACEABILITY_MATRIX.md`.
Done when: all synthetic criteria pass or candidate is rejected with evidence; production remains blocked.

### INT-001 — Specialist integrations pattern

**Requirements:** R-010
**Dependencies:** PILOT-001
**Owned paths:** `src/integrations/specialist/**`, `tests/integrations/specialist/**`, `docs/evidence/integrations/**`
**Status:** `BACKLOG_POST_MVP`

Steps:
1. Gate each connector on license/security/cost/API/rollback.
2. Implement one read-only typed fixture connector outside accounting authority.
3. Verify isolation, rate limits, secret references, failures, and teardown.

Tests: connector/network/authz/redaction/rollback contracts.
Done when: one connector proves the pattern without accounting mutation.

### MIGDEC-001 — Explicit migration-scope decision

**Requirements:** R-005
**Dependencies:** PILOT-001, MIG-001
**Owned paths:** `project-control/MIGRATION_DECISION.md`
**Status:** `BLOCKED_OWNER_INPUT`

Steps:
1. Choose empty start, masters-only, or books/opening-balance migration.
2. Require MIGSRC-001 evidence if migration; otherwise prove no current books/balances must move.
3. Record exact data boundary and rollback/reconciliation obligations.

Tests: decision schema and dependency-evidence validator.
Done when: exactly one evidence-complete branch is approved; conditional prose is forbidden.

### EXP-001 — Qualified finance/tax review

**Requirements:** R-016, R-017, R-019
**Dependencies:** PILOT-001
**Owned paths:** `docs/evidence/qualified-review/**`, `project-control/PRODUCTION_READINESS.md`
**Status:** `BLOCKED_OWNER_EXPERT`

Steps:
1. Review issuer/PKP/PPN/chart/ledger/series/account/correction/opening-balance configuration.
2. Record non-secret findings, reviewer provenance, limits, and required changes.
3. Re-run affected policy/adapter/acceptance tests.

Tests: qualified checklist and regression evidence.
Done when: production assumptions are closed by a qualified human, never simulated by AI.

### PROD-001 — Production readiness decision

**Requirements:** R-001..R-022
**Dependencies:** PILOT-001, MIGDEC-001, EXP-001
**Owned paths:** `project-control/PRODUCTION_READINESS.md`, `docs/evidence/production-readiness/**`
**Status:** `BLOCKED_OWNER_EXPERT`

Steps:
1. Review security/privacy/localization/migration/operations/cost/training/residual risks.
2. Verify policy, access, restore, reconciliation, migration branch, and qualified review.
3. Record explicit go/no-go, staged data/users, rollback, and monitoring.

Tests: readiness validator, restore rehearsal, access review, independent audit.
Done when: `PROD-001=APPROVED` is explicit; pilot completion never implies production.

## Dependency summary

The machine-readable source is the exact dependency fields above and `TASK_QUEUE.md`; diagrams are non-normative. Optional `EVAL-003`, `REM-001`, and `INT-001` do not block the MVP. Generic `MIG-001` is fixture-buildable; owner source blocks only `MIGSRC-001` and the explicit migration decision. No application task is READY until `PLAN_GATE=PASS`.
