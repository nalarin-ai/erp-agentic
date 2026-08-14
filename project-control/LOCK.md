# Writer Lease

- Status: `CLAIMED`
- Owner: hermes-executor (cron tick 2026-08-14T22:41Z)
- Task: `ISO-001` — native ERP isolation qualification (R-003, R-011, R-021)
- Owned paths: `tests/security/native_erp/**`, `docs/evidence/native-isolation/**`
- Heartbeat: `2026-08-14T22:41:40Z` (pre-mutation)
- Claim basis: OPS-001 DONE + committed (HEAD, post-commit verified); ISO-001 deps (EVAL-002, UNIT-001, CRM-001) lengkap; LOCK FREE → CLAIMED; ISO-001 READY deterministik pertama dalam urutan queue.
- Last task: `OPS-001` — DONE (QA r2/r3 remediated, final confirmation PASS zero findings; focused 78/78 (1 skip), full 703 = 2 pre-existing fixture defects; validator PASS; commit `fbb65a4` + baseline `53c1e81`)
- Released at: `2026-08-14T22:31:28Z`
- Recovery basis: HEAD commit OPS-001 = trusted implementation base. Backlog teknis: perbaiki 2 state-dependent fixture integration tests (`test_export_is_scope_bounded_with_evidence` CRM; `test_payment_evidence_index` ERPNext adapter — pagination page-1 membership vs live pilot >1000 rows; marker-filtered assertion ala references/live-pilot-stateful-fixture-and-status-mapping.md). OPS backlog INFO diterima: soft-hyphen/ZWSP redaction keys, bytes-key non-str, unicode dot-lookalike literal-safe.
