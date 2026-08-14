# Writer Lease

- Status: `CLAIMED`
- Owner: `hermes-executor-cron`
- Session/run ID: `adp-002-integration-20260814T122119Z`
- Task ID: `ADP-002` — ERPNext adapter/tests (integration phase)
- Worktree: `/home/tejo/agentic/projects/erp-kreasi-hebat`
- Owned paths: `src/adapters/erpnext/**`, `tests/integration/erpnext/**`, `environments/erpnext-pilot/**` (runtime only), `docs/evidence/erpnext-runtime/**`, `project-control/LOCK.md`, `project-control/STATUS.md`, `project-control/TASK_QUEUE.md`, `project-control/PLAN_GATE.md`
- Claimed at: `2026-08-14T12:21:19Z`
- Heartbeat: `2026-08-14T12:33:00Z` (session auth fix: token→login+cookie via TDD (4 RED→GREEN unit tests); URL-encoding fix for doctype names with spaces; full unit suite 310/310 PASS; live integration progressed from setUpClass-skip → 20 tests running; 13 remaining errors are legitimate ERPNext LinkValidationError — missing master data (Company/Customer/Item); next: seed synthetic fixtures in setUpClass)
- Expires at: `2026-08-14T12:36:19Z` (15 min, renewable by heartbeat)
- Recovery basis: ADP-002 initial implementation committed `a737065`; integration phase starts ERPNext pilot and runs contract tests against live isolated instance.
