# Roadmap — ERP Kreasi Hebat

## Phase 0 — Discovery and plan gate

Deliver complete PRD, architecture, data/RBAC/UX contracts, candidate evaluation rubric, implementation backlog, test matrix, risks, and three-stage plan review. No source implementation before `PLAN_GATE=PASS`.

## Phase 1 — Isolated evaluation environments

- Pin reviewed ERPNext/Frappe versions and supported MariaDB/container stack.
- Create synthetic companies/units/users only.
- Optionally create a fully separate ERPClaw comparator.
- Prove install, health, export, backup, restore, teardown.

Exit: reproducible isolated environments and no live data/secrets in repository.

## Phase 2 — Foundation integration gateway

- Identity/chat/unit mappings.
- RBAC and policy engine.
- Opaque account aliases and allowlists.
- Idempotency, audit, structured redaction, health.
- Fixture ERP adapter before live pilot adapter.

Exit: offline tests prove default-deny, preview zero writes, idempotency, and recovery states.

## Phase 3 — Invoice-to-receivable vertical slice

- Customer and service fixture.
- Draft/preview.
- Finance review/post.
- PDF reference and controlled delivery state.
- Partial/full payment evidence.
- Receivable/aging/reminder.

Exit: MVP acceptance matrix passes with synthetic data.

## Phase 4 — Multi-unit and owner reporting

- Banyumedia, Pr1me, Contractor, Heavy Equipment mappings.
- Competing sales isolation.
- PT TKH/PPN compatibility workflow.
- Owner/controller roll-ups without ledger merge.

Exit: positive and negative RBAC tests plus accounting review.

## Phase 5 — Import rehearsal and internal pilot

- Inspect current Excel/CSV formats.
- Staging validation/deduplication.
- Trial import and reconciliation.
- Private user onboarding and runbooks.
- Backup/restore drill.

Exit: production-readiness review; no automatic go-live.

## Phase 6 — Operational modules

Prioritized only after actual workflow discovery:

- Pr1me event/rental booking, inventory, deposits, returns.
- Contractor quotation, project/terms, paving/asphalt/house workflows.
- Heavy-equipment availability, location, operator, mobilization, maintenance.
- Banyumedia retainers, ad-budget evidence, service delivery/project tracking.
- Balonesia onboarding acceptance case.

## Phase 7 — Specialist integrations

Uptime Kuma, SEO rank tracking, analytics, social publishing, and marketing automation through separate API adapters. Each integration has its own security/license/cost/rollback gate.

## Phase 8 — HR and advanced finance

HR records/payroll, advanced reconciliation, tax reporting support, and broader dashboards only after qualified domain review and strict permission design.
