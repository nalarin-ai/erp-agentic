# Product Selection Rubric — ERP Core

- Status: `DRAFT`
- Candidates: ERPNext/Frappe (primary) and ERPClaw (optional comparator).
- Rule: score only from reproduced evidence at pinned revisions; README claims alone score as unverified.

## Hard gates (pass/fail)

A candidate is rejected for official-ledger use if any remain unmitigated:

1. Cannot enforce unit/role negative authorization at API and UI layers.
2. Cannot represent or safely extend operating unit vs legal issuer vs tax/account policy.
3. Cannot guarantee idempotent invoice/payment actions under retries/concurrency.
4. Cannot support correct posting, cancellation/reversal, AR, and audit evidence.
5. Cannot export and restore database/documents/configuration reproducibly.
6. Requires unsafe unrestricted agent/shell permissions for normal finance actions.
7. License/edition prevents required self-hosted capabilities.
8. No bounded upgrade/security-maintenance path.

## Weighted rubric

| Area | Weight | Evidence |
|---|---:|---|
| Accounting/AR correctness and reversal | 20 | invariant tests, ledger reconciliation, supported docs |
| RBAC and competing-sales isolation | 15 | negative API/UI matrix |
| Unit/issuer/PPN/account configurability | 15 | synthetic policy journeys and extension audit |
| API stability, idempotency, recovery | 12 | contract/concurrency/failure tests |
| Audit, evidence, and observability | 8 | event and read-back proof |
| Backup/export/restore | 10 | isolated restore drill |
| Indonesian localization effort | 8 | qualified gap review; no invented compliance |
| Self-host operations/upgrades/security | 7 | pinned install/update/rollback rehearsal |
| UX/chat integration effort | 3 | prototype and accessibility evidence |
| Community/maintainer/supply-chain risk | 2 | canonical source/license/activity/security audit |

Total 100. Hard gates override weighted score.

## Decision outputs

- `ADOPT_FOR_PILOT`
- `REJECT`
- `COMPARATOR_ONLY`
- `NEEDS_MORE_EVIDENCE`

The final report records candidate/version/hash, environment, fixture, commands, raw results, gaps/custom work, residual risk, and rollback/export path.
