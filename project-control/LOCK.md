# Writer Lease

- Status: `CLAIMED`
- Task: `ISOFIX-001` (final isolation architecture: gateway-only implementation + fresh ISOLATION_FINAL=PASS)
- Writer: Hermes executor (sole source writer); reviewers read-only
- Claimed at: `2026-08-15T00:06:42Z`
- Heartbeat: `2026-08-15T00:06:42Z` (pre-mutation, post validator resync PASS)
- Basis: ISO-001 verdict REQUIRES_GATEWAY_ONLY (ADR-001); owned paths `src/isolation_architecture/**`, `environments/isolation-final/**`, `tests/security/isolation_final/**`, `docs/evidence/isolation-final/**`. Backlog teknis: perbaiki 2 state-dependent fixture integration tests (`test_export_is_scope_bounded_with_evidence` CRM; `test_payment_evidence_index` ERPNext adapter — marker-filtered assertion ala references/live-pilot-stateful-fixture-and-status-mapping.md). Catatan ops: pilot RQ queue sempat penuh (550 jobs, scheduler disabled) — drained via one-shot worker; scheduler di-enable.
