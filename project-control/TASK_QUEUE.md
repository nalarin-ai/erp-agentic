# Task Queue

Only dependency-satisfied, gate-authorized source tasks may be `READY`; statuses below are canonical. Dependency IDs must exactly match `EXECUTION_PLAN.md`.

| Task ID | Requirement scope | Dependencies | Owned path/worktree | Status | Evidence required |
|---|---|---|---|---|---|
| SEC-001 | R-005, R-007, R-008 | none | executor gateway | DONE | bound active policy + safety prohibitions |
| PLAN-001 | R-001..R-022 | SEC-001 | control/plans/validator only | DONE | Pass 1/2 revisions + fresh Pass 3 + structural gate |
| EVAL-001 | R-005, R-006, R-009, R-016, R-017, R-019 | PLAN-001 | ERPNext evaluation/evidence | DONE | pinned source/license/capability audit |
| EVAL-002 | R-005, R-006, R-009, R-016 | EVAL-001 | ERPNext environment/scripts/evidence | DONE | health + reproducible restore |
| EVAL-003 | R-005, R-006, R-009 | PLAN-001 | isolated comparator/evidence | BACKLOG_OPTIONAL | identical synthetic rubric |
| FND-001 | R-004, R-005, R-006, R-007, R-008, R-017, R-019 | PLAN-001 | domain/contracts/unit tests | DONE | type/money/financial identity/redaction |
| FND-002 | R-003, R-004, R-007, R-011, R-021 | FND-001 | authz paths | DONE | assignment/context positive-negative matrix |
| FND-003 | R-016, R-017, R-019 | FND-001 | policy paths | DONE | exhaustive compatibility matrix + trusted issuance evidence |
| FND-004 | R-007, R-008 | FND-001 | mutation/audit/migration/test paths | DONE | concurrency/crash/durability evidence |
| UNIT-001 | R-001, R-002, R-012, R-013, R-014, R-015, R-018, R-020, R-021, R-022 | FND-001, FND-002, FND-003 | unit fixture/config paths | DONE | schema+lifecycle+rollback+no-hardcode onboarding |
| ADP-001 | R-005, R-006, R-007, R-008, R-017 | FND-001, FND-004 | fixture adapter/contracts | DONE | network-disabled vertical slice |
| REC-001 | R-007, R-008 | FND-004, ADP-001 | reconciliation UI/worker/tests/runbook | DONE | crash/restart/operator queue evidence |
| ADP-002 | R-005, R-006, R-007, R-008, R-016, R-017, R-019, R-021 | EVAL-002, ADP-001, FND-002, FND-003, FND-004, REC-001 | ERPNext adapter/tests | DONE | provider contracts/readback/permission |
| CRM-001 | R-002, R-003, R-011, R-015, R-021 | FND-002, UNIT-001, ADP-002 | CRM/adapter/tests | DONE | search/export/conflict isolation |
| ISO-001 | R-003, R-011, R-021 | EVAL-002, UNIT-001, CRM-001 | native security tests/evidence | BACKLOG | all native surfaces + ADR |
| ISOFIX-001 | R-003, R-011, R-021 | ISO-001 | final isolation runtime/source/tests/evidence | BACKLOG | implemented final architecture + fresh ISOLATION_FINAL=PASS |
| FLOW-001 | R-003, R-004, R-006, R-007, R-011, R-016, R-017, R-019, R-020, R-021, R-022 | FND-002, FND-003, ADP-001, UNIT-001 | invoice draft/channel/tests | DONE | unit/config state transcripts + zero writes |
| FLOW-002 | R-004, R-005, R-006, R-007, R-008, R-016, R-017, R-019, R-020, R-021, R-022 | FLOW-001, ADP-002, REC-001 | invoice post/tests | DONE | immutable branding/config snapshot + verified post |
| FLOW-003 | R-006, R-007, R-008, R-013, R-017, R-019 | FLOW-002 | payment/receivable/tests | DONE | balances/evidence/privacy |
| REM-001 | R-006, R-007, R-011, R-021 | FLOW-003, FND-002 | reminders/tests | BACKLOG_POST_MVP | schedule/dedupe/privacy/failure |
| RPT-001 | R-001, R-011, R-021 | FND-002, FLOW-003 | owner report UI/service/tests | READY | reconciled aggregation/no leakage |
| UX-001 | R-004, R-006, R-007, R-011, R-020, R-021, R-022 | FLOW-001, FLOW-002, FLOW-003 | bounded UI/test/evidence paths | BACKLOG | responsive/keyboard/config lifecycle/independent review |
| MIG-001 | R-005, R-008 | FND-001, ADP-001 | import/test paths | DONE | hostile fixtures + dry-run/reconcile |
| MIGSRC-001 | R-005, R-008 | MIG-001, ADP-002 | migration profile/maps/sanitized fixtures | BLOCKED_OWNER_INPUT | source-specific trial reconciliation |
| OPS-001 | R-008, R-009, R-016 | EVAL-002, FND-004, ADP-002, REC-001 | ops/backup/runbook/tests | BACKLOG | application-consistent restore/RPO/RTO |
| PILOT-001 | R-001..R-022 except R-010 post-MVP delivery | FLOW-001, FLOW-002, FLOW-003, CRM-001, UNIT-001, ISOFIX-001, UX-001, RPT-001, OPS-001, REC-001 | pilot E2E/evidence | BACKLOG | MVP-AC-01..15 |
| INT-001 | R-010 | PILOT-001 | specialist integration/test/evidence | BACKLOG_POST_MVP | read-only connector pattern |
| MIGDEC-001 | R-005 | PILOT-001, MIG-001 | migration decision | BLOCKED_OWNER_INPUT | exactly one evidence-complete branch |
| EXP-001 | R-016, R-017, R-019 | PILOT-001 | qualified-review/readiness docs | BLOCKED_OWNER_EXPERT | qualified checklist/regressions |
| PROD-001 | R-001..R-022 | PILOT-001, MIGDEC-001, EXP-001 | readiness/evidence only | BLOCKED_OWNER_EXPERT | explicit APPROVED/no-go record |

`BACKLOG` is not `READY`. `BLOCKED_OWNER_*` indicates genuine external input; technical revisions remain engineering work. One source writer lease applies to every task, and intersecting paths must be serialized.
