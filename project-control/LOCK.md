# Writer Lease

- Status: `CLAIMED`
- Owner: hermes-executor (cron tick 2026-08-14T13:16Z — reclaimed stale lease)
- Session/run ID: `adp-002-integration-seed-20260814T1316Z`
- Task ID: `ADP-002` — ERPNext adapter/tests (integration seeding phase)
- Worktree: `/home/tejo/agentic/projects/erp-kreasi-hebat`
- Owned paths: `tests/integration/erpnext/**`, `src/adapters/erpnext/**`
- Claimed at: `2026-08-14T13:16:00Z` (reclaim: prior lease heartbeat 13:04Z expired 13:11:30Z with uncommitted candidate; sibling-commit check: HEAD `3527732` = control-only, candidate intact in index)
- Heartbeat: `2026-08-14T14:10:00Z` — fresh QA retry (`deleg_1e9f985b`): PASS_WITH_FINDINGS. F-01..F-10 CLOSED via 14 probe independen; 8/8 mutants KILLED; 1 new LOW N-01 (empty-scope fail-open di read_invoice/read_payment/payment_evidence_index) — ditutup via TDD (test_empty_scope_fail_closed + guard `not self._scope`); 1 INFO N-02 (payload tidak di read_payment) accepted. Full suite 348/348 PASS; compileall PASS; diff --check PASS; plan validator PASS; secret scan clean. Commit + release lease next.
- Expires at: `2026-08-14T14:25:00Z` (15 min)
- Recovery basis: HEAD `3527732`, trusted base `1d22460`. Candidate = seeder (`tests/integration/erpnext/_seeder.py`, 375 LOC, idempotent) + adapter fixes (DRAFT-prefix handles, party/company resolution via invoice lookup, evidence_ref uniqueness, paid_to/paid_from account discovery, reverse-via-cancel) + 23 integration tests GREEN against live pilot.
