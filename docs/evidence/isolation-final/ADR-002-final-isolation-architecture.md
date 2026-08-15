# ADR-002 — Final Isolation Architecture (ISOFIX-001)

- Status: `DECIDED`
- Date: 2026-08-15 (UTC)
- Task: ISOFIX-001 (R-003, R-011, R-021)
- Implements: ISO-001 ADR-001 verdict `REQUIRES_GATEWAY_ONLY`
- Target under test: isolated ERPNext pilot `http://127.0.0.1:18080`, site
  `erpnext-pilot.localhost`, ERPNext pinned **v16.32.1** (frappe 16.31.0),
  re-verified live by `test_config_drift.TestLiveVersionPin`.
- Evidence: `matrix.md`, `raw/probes-20260815.jsonl` (20 probes, latest
  run, run-id grouped), `isolation_final.json` (verdict PASS, config hash
  `ff6a9123…`), suites under `tests/security/isolation_final/`
  (56 tests, all PASS).

## Decision

**Final architecture: GATEWAY-ONLY for unit-scoped roles.**

1. Unit-scoped roles (`Sales User`, `Sales Manager`, `Support User`) hold
   **no direct native ERPNext desk/API credentials**. The ISO-001
   synthetic unit users (`iso-sales-bm@example.test`,
   `iso-sales-p1@example.test`) are disabled and their User Permissions
   purged (`seed_final.py`, idempotent migration, evidence-recorded).
2. All unit access flows through the proven gateway layer:
   `src/adapters/erpnext` (ErpPort), `src/adapters/erpnext_crm` +
   `src/crm/port.py` (CrmPort), and `src/reports/owner` (RPT-001 explicit
   server-side roll-up). Gateway scope enforcement was already qualified
   fail-closed by CRM-001/ADP-002; this task requalifies it as the final
   architecture.
3. Owner/controller roll-up remains explicit, server-side, and auditable,
   via the gateway report service only — owner roles are also denied
   native surfaces by policy.
4. Native access, where unavoidable for operations, is limited to
   non-unit-scoped operator roles (`Operator`, `System Manager`) under a
   separate ops control.
5. `src/isolation_architecture/policy.py` is the fail-closed admission
   boundary: exact-match role classification (no casefold identity
   confusion), a total (role class, surface) decision matrix, and a
   native-credential issuance guard that denies issuance to unit-scoped
   roles with a generic static message (no reason/username echo).

## Why the ISO-001 leak classes are closed by construction

| ISO-001 leak class | Final-architecture closure |
|---|---|
| Customer master unscopeable (enumeration, direct GET, search, count inflation) | No unit-scoped native credentials exist; `login` returns 401 and every native API probe returns 401/403 without cross-unit markers. Unit actors enumerate customers only through the CRM port, which is scope-bounded and contract-tested. |
| File metadata cross-unit enumeration | Same: `/api/resource/File` probes by unit users are denied (401/403) because no session can be established. |
| 403/404 existence-oracle split | The oracle required an authenticated unit-native session; with no credential issuance, the probe surface does not exist. |

## Migration and rollback

- **Migration** (`seed_final.py`): disable unit-scoped users + purge their
  User Permissions. Idempotent; safe to re-run; admin-only; each action
  recorded as a `final-migration` probe row.
- **Rollback**: set `ISO001_ENABLE_UNIT_USERS=1` and run any ISO-001
  suite — its `setUpClass` calls `seed_users()`, which repairs
  enabled-drift (re-enables the unit users) and re-seeds User
  Permissions idempotently. Verified by
  `test_qa_remediation.TestQA01RollbackPathReEnables`. Rollback re-opens
  the ISO-001 leak classes and therefore invalidates
  `ISOLATION_FINAL=PASS` until the migration is re-applied
  (`ensure_final_architecture_seeded`, convergent: disables AND purges)
  and the matrix re-run.
- **Configuration drift**: `test_config_drift.py` proves the pinned config
  hash (`FinalArchitectureConfig.sha256`) detects version/role/module/URL
  tampering and matches the live pilot's installed versions.

## Fresh matrix (latest run)

See `matrix.md`. 20 probes across `final-native-login`,
`final-native-api`, `final-native-direct`, `final-native-files`,
`final-native-reports`, `final-native-search`, `final-native-desk`,
`final-gateway-crm`, `final-gateway-erp`, `final-migration` — **0
leak-positive**. All unit-native probes denied (401/403) or reduced to
the unauthenticated public Login page with no session markers; all
gateway probes functional with zero cross-unit markers and fail-closed
denials for cross-unit/unassigned access.

## Verdict

`ISOLATION_FINAL=PASS` (`isolation_final.json`). The implemented final
architecture — not a rejected option or prose — carries fresh evidence.
PILOT-001's dependency on ISOFIX-001 can now be evaluated against this
verdict.

## Consequences

- New unit-scoped roles MUST be added to `policy._ROLE_CLASS` as
  `UNIT_SCOPED` and to `config.final_config().unit_scoped_roles`; the
  drift test and total-matrix test fail otherwise.
- Any proposal to re-introduce native credentials for unit-scoped roles
  is a new ADR and must re-run both the ISO-001 matrix (expected to fail)
  and this final matrix.
- Residual accepted scope: owner cross-unit roll-up is explicit and
  auditable; operator native access is governed by a separate ops control
  outside the unit-isolation boundary.
