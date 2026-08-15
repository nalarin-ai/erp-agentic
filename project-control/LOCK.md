# Writer Lease

- Status: `CLAIMED`
- Task: `PILOT-001` (synthetic E2E acceptance — MVP-AC-01..15)
- Writer: Hermes executor (sole source writer); reviewers read-only
- Claimed at: `2026-08-15T01:43:26Z`
- Heartbeat: `2026-08-15T01:43:26Z` (pre-mutation; ISOFIX-001 transition committed `8cbfa98`; PILOT-001 dipromosikan BACKLOG→READY — seluruh 10 dependencies DONE, PLAN_GATE PASS baseline `1ae735ba` masih berlaku + diperkuat ISOFIX-001; validator EXPECTED_STATUS + machine hashes resynced, validator PASS baseline `dce6ee8b`)
- Basis: TASK_QUEUE row order (deterministik — satu-satunya READY); owned paths `tests/e2e/pilot/**`, `docs/evidence/pilot/**`. Steps: (1) seed synthetic roles/units/settings/branding/issuer/tax/ledger/account/customer/services; (2) jalankan MVP-AC-01..15 termasuk template per-unit, unit switching/revocation, no-hardcode onboarding, positive/negative/retry/recovery; (3) laporan product-fit/localization/configurability/performance/restore/assumption. Done when: semua kriteria synthetic pass atau kandidat ditolak dengan evidence; production tetap blocked.
- Backlog teknis: perbaiki 2 state-dependent fixture integration tests (`test_export_is_scope_bounded_with_evidence` CRM; `test_payment_evidence_index` ERPNext adapter — marker-filtered assertion ala references/live-pilot-stateful-fixture-and-status-mapping.md).
