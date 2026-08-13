# ERP Kreasi Hebat

Isolated project owned by Hermes profile `executor`, controlled from the dedicated executor Telegram bot. Project execution is bounded to this repository and governed by `project-control/`.

## Planning index

- [`project-control/PROJECT.md`](project-control/PROJECT.md) — binding, scope, approval boundary
- [`project-control/PRD.md`](project-control/PRD.md) — product requirements
- [`project-control/REQUIREMENTS.md`](project-control/REQUIREMENTS.md) — numbered discovery requirements
- [`project-control/ARCHITECTURE.md`](project-control/ARCHITECTURE.md) — logical architecture and trust boundaries
- [`project-control/DATA_MODEL.md`](project-control/DATA_MODEL.md) — canonical logical data contracts
- [`project-control/RBAC_AND_POLICY.md`](project-control/RBAC_AND_POLICY.md) — role and financial-policy rules
- [`project-control/UX_DISCOVERY.md`](project-control/UX_DISCOVERY.md) / [`UX_SPEC.md`](project-control/UX_SPEC.md) — user journeys, states, accessibility
- [`project-control/TRACEABILITY_MATRIX.md`](project-control/TRACEABILITY_MATRIX.md) — normative R/FR/J/MVP crosswalk
- [`project-control/STATE_MACHINES.md`](project-control/STATE_MACHINES.md) — orthogonal business state transitions
- [`project-control/IDEMPOTENCY_AUDIT_RECOVERY.md`](project-control/IDEMPOTENCY_AUDIT_RECOVERY.md) — concurrency, audit, reconciliation contract
- [`project-control/NATIVE_ERP_ISOLATION.md`](project-control/NATIVE_ERP_ISOLATION.md) — native ERP isolation qualification
- [`project-control/DUPLICATE_PAYMENT_POLICY.md`](project-control/DUPLICATE_PAYMENT_POLICY.md) — payment/evidence duplicate decisions
- [`project-control/ROADMAP.md`](project-control/ROADMAP.md) — staged delivery
- [`project-control/EXECUTION_PLAN.md`](project-control/EXECUTION_PLAN.md) — dependency-safe implementation tasks
- [`project-control/TEST_STRATEGY.md`](project-control/TEST_STRATEGY.md) — acceptance and evidence matrix
- [`project-control/OPEN_QUESTIONS.md`](project-control/OPEN_QUESTIONS.md) — non-secret owner/expert inbox
- [`project-control/TASK_QUEUE.md`](project-control/TASK_QUEUE.md) — canonical task states
- [`project-control/RISK_REGISTER.md`](project-control/RISK_REGISTER.md) — risks and mitigations
- [`project-control/PLAN_REVIEW.md`](project-control/PLAN_REVIEW.md) / [`PLAN_GATE.md`](project-control/PLAN_GATE.md) — assurance evidence

## Current state

The reviewed planning baseline is established. `FND-001` is the first dependency-satisfied source task selected for TDD implementation; later tasks remain gated by their canonical dependencies and independent QA.
