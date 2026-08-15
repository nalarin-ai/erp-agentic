# ISOFIX-001 — Final Isolation Architecture (gateway-only)

## Status
`GATEWAY_ONLY_FINAL`

## Decision (from ISO-001 ADR-001, verdict REQUIRES_GATEWAY_ONLY)
- Unit-scoped roles (sales / any single-operating-unit role) hold **no
  direct native ERPNext desk/API credentials**. Accounts that previously
  existed for ISO-001 qualification are disabled and their User
  Permissions purged (`tests/security/isolation_final/seed_final.py`).
- All unit access flows through the proven gateway/adapter layer:
  - `src/adapters/erpnext` (ErpPort — invoices/payments/receivables)
  - `src/adapters/erpnext_crm` + `src/crm/port.py` (CRM port)
  - `src/reports/owner` (RPT-001 explicit server-side roll-up)
- Owner/controller cross-unit roll-up is explicit, server-side, auditable,
  and flows exclusively through the gateway report service.
- Native access, where unavoidable for operations, is limited to
  non-unit-scoped operator roles under a separate ops control.

## Admission policy
`src/isolation_architecture/policy.py` is the fail-closed admission
boundary: role classification, (role, surface) decision matrix, and the
native-credential issuance guard. Unknown roles, malformed inputs, and
unknown surfaces are denied.

## Environment
The final architecture reuses the existing isolated pilot:

| Component | Source | Port |
|---|---|---|
| ERPNext pilot | `environments/erpnext-pilot/docker-compose.yml` (`frappe/erpnext:v16.32.1`, frappe 16.31.0) | `127.0.0.1:18080` |

No new containers are required: the architectural change is credential
topology (who may hold native credentials), not a new runtime.

## Fixture migration / rollback
- Migration: disable ISO-001 unit-scoped synthetic users + purge their
  User Permissions (idempotent, admin-only, evidence-recorded).
- Rollback: re-enable users + re-seed User Permissions via
  `tests/security/native_erp/_harness.py::seed_users` (idempotent).
- Configuration drift test: `test_config_drift.py` proves the pinned
  config hash detects any tampering and matches the live pilot version.

## Evidence
- `docs/evidence/isolation-final/raw/probes-*.jsonl` — append-only probe rows (run_id grouped).
- `docs/evidence/isolation-final/matrix.md` — per-surface summary of the latest run.
- `docs/evidence/isolation-final/isolation_final.json` — ISOLATION_FINAL verdict + config hash.
- `docs/evidence/isolation-final/ADR-002-final-isolation-architecture.md` — final ADR.
