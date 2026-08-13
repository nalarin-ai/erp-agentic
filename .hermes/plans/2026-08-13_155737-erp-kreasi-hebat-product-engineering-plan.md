# Product and Engineering Plan

This plan defines discovery through a locally verified synthetic release candidate for ERP Kreasi Hebat. It does not authorize live financial data, official tax filing, banking operations, or production go-live.

## Goal

Build an evidence-backed multi-unit ERP capability in which chat is a safe interface, the ERP is the system of record, competing sales scopes remain isolated, and every invoice/payment binds the correct operating unit, legal issuer, tax profile, ledger, and destination account.

## Current context

- Project boundary and project-bound FULL_AUTO are active.
- Repository currently contains planning/control artifacts only.
- ERPNext is the primary candidate; ERPClaw is an optional isolated comparator.
- Hermes is the sole source writer by direct instruction from Bos; no external coding-agent authentication is an implementation prerequisite.
- Several product/legal/tax/user-volume/source-data details remain open and are explicitly tracked.

## Deliverables

1. Complete product baseline in `project-control/`.
2. Three independent plan-review stages and mechanical gate.
3. Reproducible isolated ERP evaluation.
4. Provider-neutral integration gateway with fixture-first TDD.
5. Synthetic invoice-to-receivable MVP.
6. Unit-sales isolation and owner roll-up.
7. Backup/restore, audit, reconciliation, UX/a11y evidence.
8. Production-readiness decision separate from MVP acceptance.

## Approach

- Plan before source.
- Fixture and synthetic tracks continue while owner/expert inputs remain open.
- Default deny and fail closed for unknown issuer/tax/account/identity.
- One writer lease per worktree.
- Hermes performs source coding under one writer lease; independent read-only reviewers verify the final diff and evidence.
- Prefer upstream ERP configuration/custom app/API over core modifications.

## Exact task plan

The authoritative task graph and per-task paths, steps, tests, and done-when criteria are in `project-control/EXECUTION_PLAN.md`. The authoritative acceptance matrix is `project-control/TEST_STRATEGY.md`.

## Validation before implementation

1. Pass traceability/completeness review.
2. Pass adversarial engineering/security/recovery review.
3. Revise findings.
4. Pass fresh closure/E2E review.
5. Validate requirement/task/test parity and acyclic dependencies.
6. Hash the byte-exact baseline.
7. Set `PLAN_GATE.md` to PASS only for authorized task IDs.

## Risks and trade-offs

- ERPNext maturity vs heavier configuration/integration.
- ERPClaw conversational fit vs immature ledger/security/localization evidence.
- One site vs multiple sites cannot be finalized before complete legal-entity and permission pilot.
- Unit-private sales with owner/finance roll-up requires careful query-level enforcement.
- PT TKH PPN rules require qualified finance/tax confirmation.
- Private self-hosting reduces vendor dependence but adds backup/update/security operations.

## Open questions

See `project-control/OPEN_QUESTIONS.md`. Unknowns block only dependent production/configuration tasks, not fixture-based contracts, policy tests, or isolated evaluation.
