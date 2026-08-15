# Writer Lease

- Status: `CLAIMED`
- Task: `PILOT-001` (synthetic E2E acceptance — MVP-AC-01..15)
- Writer: Hermes executor (sole source writer); reviewers read-only
- Claimed at: `2026-08-15T01:43:26Z`
- Heartbeat: `2026-08-15T02:00:08Z` (slice 1 selesai: harness PilotHarness + 36 tests hijau untuk AC-01/02/03/04/06/13 via builder `deleg_99dda5e9` (berhenti max_iterations, semua hijau); verifikasi parent: focused 36/36 OK, full suite 817 = 2 pre-existing + 11 skips by-design, 0 errors, nol regresi; evidence docs ac-01/02/03/04/06/13.md ditulis parent dengan counts aktual; sisa slice: AC-05/07/08/09/10/11/12/14/15 + laporan akhir; commit slice-1 pada tick ini)
- Basis: TASK_QUEUE row order (deterministik — satu-satunya READY); owned paths `tests/e2e/pilot/**`, `docs/evidence/pilot/**`. Steps: (1) seed synthetic roles/units/settings/branding/issuer/tax/ledger/account/customer/services; (2) jalankan MVP-AC-01..15 termasuk template per-unit, unit switching/revocation, no-hardcode onboarding, positive/negative/retry/recovery; (3) laporan product-fit/localization/configurability/performance/restore/assumption. Done when: semua kriteria synthetic pass atau kandidat ditolak dengan evidence; production tetap blocked.
- Backlog teknis: perbaiki 2 state-dependent fixture integration tests (`test_export_is_scope_bounded_with_evidence` CRM; `test_payment_evidence_index` ERPNext adapter — marker-filtered assertion ala references/live-pilot-stateful-fixture-and-status-mapping.md).
