# Writer Lease

- Status: `CLAIMED`
- Owner: hermes-executor (cron tick 2026-08-14T14:30Z)
- Claimed task: `CRM-001` — slice 2: ERPNext CRM adapter + integration tests vs pilot + fresh QA + transition
- Claimed at: `2026-08-14T14:30:00Z`
- Heartbeat: `2026-08-14T14:52:00Z`
- Pre-claim state: PLAN_GATE PASS (baseline `f7db2562`), 378/378 PASS, HEAD `48dc523`.
- Progress: TDD RED (19 tests, ModuleNotFoundError) → adapter + seeder GREEN (19/19+1) → full gates 398/398 → independent QA (`deleg_1f1f4466`) FAIL (3 HIGH: F-001 archived-in-NEW search, F-002 quotation status filter silently dropped, F-003 customer_ref no round-trip; 2 MEDIUM: F-004 state-dependent test, F-005 unmapped quotation statuses; 2 LOW: F-006 transfer non-atomic documented, F-007 count fallback) → remediasi TDD 4 regression tests RED-first (archived-vs-NEW, quotation status filter, customer_ref round-trip via new custom field `custom_crm_customer_ref`, status mapping fail-closed) + F-004 unique-marker test fix → 24/24 erpnext_crm PASS, full suite 402/402 PASS, compileall PASS, diff --check PASS, validator PASS.
- Next: fresh QA retry, then transition review + commit.
