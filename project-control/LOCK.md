# Writer Lease

- Status: `CLAIMED`
- Owner: hermes-executor (cron tick 2026-08-14T20:25Z)
- Task: `OPS-001` — backup, restore, observability, operations (R-008, R-009, R-016)
- Owned paths: `ops/**`, `scripts/backup/**`, `docs/runbooks/operations/**`, `tests/operations/**`
- Heartbeat: `2026-08-14T20:25:16Z` (pre-mutation)
- Claim basis: UX-001 DONE + committed (`a80941a`, post-commit verified: focused 81/81 + validator PASS + tree bersih); OPS-001 deps (EVAL-002, FND-004, ADP-002, REC-001) lengkap; LOCK FREE → CLAIMED; OPS-001 READY deterministik pertama dalam urutan queue.
- Last task: `UX-001` — DONE (commit `a80941a`; stale lease reclaimed + candidate verified; QA r1 PASS_WITH_FINDINGS 3M/5L/2I remediated TDD 12 regression tests; fresh QA r2 final PASS zero findings >INFO — 15/15 closure probes, 14 adversarial probes bersih, mutation spot-check 4/4 KILLED; focused 81/81; validator PASS baseline `3dc1e317`; lease FREE `20:21:55Z`)
- Released at: `2026-08-14T20:21:55Z`
- Recovery basis: HEAD commit UX-001 = trusted implementation base. Backlog teknis: perbaiki 2 state-dependent fixture integration tests (`test_export_is_scope_bounded_with_evidence` CRM; `test_payment_evidence_index` ERPNext adapter — pagination page-1 membership vs live pilot >1000 rows; marker-filtered assertion ala references/live-pilot-stateful-fixture-and-status-mapping.md).
