# ERPClaw Comparator Audit — EVAL-003

> Audit date: `2026-08-14`
> Candidate: `avansaber/erpclaw` (GitHub)
> Audited ref: `v4.1.2` (latest tag at audit time)
> Source: https://github.com/avansaber/erpclaw
> License: GPL-3.0 (verified via `LICENSE.txt` and `SKILL.md` badge)

## 1. Canonical source and version pinning

| Item | Value | Evidence |
|---|---|---|
| Repository | `avansaber/erpclaw` | GitHub API `full_name` |
| Default branch | `main` | GitHub API |
| Latest tag | `v4.1.2` (`8cd0b70`) | GitHub API tags |
| Language | Python | GitHub API |
| License | GPL-3.0 | `LICENSE.txt` verbatim; `SKILL.md` badge |
| Runtime requirements | `python3`, `git` | `SKILL.md` `metadata.openclaw.requires.bins` |
| Optional env | `ERPCLAW_DB_PATH` | `SKILL.md` `metadata.openclaw.optionalEnv` |

**Pinned decision:** for any evaluation, pin exactly one tag (e.g. `v4.1.2`) and record the Git SHA. Do not track `main` branch for reproducibility.

## 2. License and redistribution assessment

- **License:** GPL-3.0 (copyleft). Same terms as ERPNext.
- **Implication for ERP Kreasi Hebat:** acceptable for internal use; no distribution planned.
- **Risk:** LOW — internal use only.

## 3. Architecture and runtime

### 3.1 Core architecture

- **Pattern:** OpenClaw "skill" — a collection of Python scripts invoked via CLI (`bin/erpclaw`).
- **Database:** SQLite (default) or PostgreSQL (claimed in README, not verified in code).
- **Deployment:** local-first; no web server required for core operations.
- **Module system:** 43 optional expansion modules claimed in `SKILL.md`; module installation mechanism (`module_manager.py` sparse checkout) is an architectural observation from `SKILL.md` metadata, not independently verified in code.

### 3.2 Key structural observations

| Component | Path | Evidence |
|---|---|---|
| Entry point | `bin/erpclaw` | CLI dispatcher |
| Database init | `scripts/erpclaw-setup/db_query.py` | `initialize-database` action |
| Chart of accounts | `scripts/erpclaw-gl/db_query.py` | `setup-chart-of-accounts` with `us_gaap` template |
| Audit logging | `scripts/erpclaw-setup/lib/erpclaw_lib/audit.py` | `audit()` function writes to `audit_log` table |
| GL invariants | `scripts/erpclaw-setup/lib/erpclaw_lib/gl_invariants.py` | Post-test verification of double-entry balance |
| RBAC | `scripts/erpclaw-setup/lib/erpclaw_lib/rbac.py` | Role-based access control with wildcard patterns |
| Credentials | `scripts/erpclaw-setup/lib/erpclaw_lib/credentials.py` | Column-level encryption for sensitive fields |
| Crypto | `scripts/erpclaw-setup/lib/erpclaw_lib/crypto.py` | PBKDF2 for password hashing |

### 3.3 Action surface

`SKILL.md` claims 467 actions across 14 domains. Verified action categories:
- Setup & Admin (44 actions)
- GL, Selling, Buying, Inventory, Payments, Tax, Billing, HR, Payroll, Reports, Accounting-adv, OS, Meta

**Critical gap:** No web UI, no REST API, no background job scheduler. All operations are CLI-driven. This is fundamentally different from ERPNext's web-based architecture.

## 4. Indonesian localization and tax readiness

- **Finding:** No evidence of Indonesian localization, PPN support, or e-Faktur integration.
- **Currency:** Exchange rate fetching via `fetch-exchange-rates` (public API). No native IDR formatting or Indonesian tax rules.
- **Tax:** `erpclaw-tax` module exists but is US-centric (W-2, garnishment, US GAAP references in README).

## 5. Financial identity and account mapping (R-016, R-017, R-019)

| Requirement | ERPClaw native support | Gap |
|---|---|---|
| Legal issuer | `company` table with `company_id` | No explicit legal-issuer/tax-identity separation |
| Tax profile | `erpclaw-tax` module | US-centric; no PPN/Indonesian tax |
| Invoice series | `naming.py` | Unclear if customizable per unit |
| Receivable ledger | GL accounts via `erpclaw-gl` | Standard chart of accounts; no unit-level ledger separation |
| Destination bank account | `erpclaw-payments` | No native bank account allowlist per unit |

**Critical gap:** ERPClaw's `company` is the primary boundary. No native concept of operating unit/brand with separate sales pipelines. The `user_role` table has `company_id` but no unit-level granularity.

## 6. Idempotency, audit, and recovery (R-007, R-008, R-009)

### 6.1 Idempotency

- No native idempotency-key mechanism visible in audited code.
- `db_query.py` scripts appear to be direct SQL operations without deduplication guards.

### 6.2 Audit trail

- `audit_log` table exists with `id`, `user_id`, `skill`, `action`, `entity_type`, `entity_id`, `old_values`, `new_values`, `description`.
- **Gap:** No cryptographic chaining, no immutable append-only guarantee, no hash-linked audit. Entries are standard SQLite rows.

### 6.3 GL invariants

- `gl_invariants.py` provides post-hoc verification: global balance, per-voucher balance, no zero-zero entries, valid accounts, valid fiscal year.
- Uses `Decimal` for money — good practice.
- **Gap:** Invariants are checked *after* posting, not enforced *during* posting via database constraints.

### 6.4 Backup and restore

- SQLite file-based: backup is file copy.
- No native PITR, no application-consistent backup orchestration.
- **Gap:** Recovery is manual; no automated restore verification.

## 7. Security and isolation (R-005, R-006)

### 7.1 Network exposure

- Local-first: no web server by default.
- `fetch-exchange-rates` calls public API — only external network access mentioned.
- Module installation fetches from GitHub — user-approved per `SKILL.md`.

### 7.2 RBAC and permissions

- `rbac.py` provides role-based access with wildcard patterns.
- `get_user_companies()` returns list of accessible company IDs.
- **Gap:** No row-level security in SQLite. Company isolation is application-level only.
- **Gap:** RBAC is "opt-in" — if no `erp_user` records exist, all actions are allowed.

### 7.3 Data protection

- `credentials.py` and `crypto.py` suggest column-level encryption.
- PBKDF2 for password hashing.
- **Gap:** No evidence of field-level redaction in audit logs or API responses.

## 8. Synthetic fixture and isolation strategy

### 8.1 Proposed fixture

- **Company:** synthetic `PT TKH` + operating units as separate companies (breaks one-office model) or as custom field on documents.
- **Database:** temporary SQLite file in `/tmp` or isolated directory.
- **Users:** fixture users with `System Manager` and custom roles.
- **Chart of accounts:** `us_gaap` template (not Indonesian).

### 8.2 Isolation/teardown

- Use `ERPCLAW_DB_PATH` to point to temporary SQLite file.
- Teardown: delete SQLite file and module cache.
- No network access to external services during test; stub `fetch-exchange-rates`.

## 9. Gaps and decision inputs

| Gap ID | Severity | Description | Mitigation |
|---|---|---|---|
| GAP-C01 | CRITICAL | No web UI / REST API / background jobs | Not suitable as primary system of record for chat-driven ERP |
| GAP-C02 | CRITICAL | No native unit/brand isolation | Would require complete custom layer |
| GAP-C03 | HIGH | No Indonesian localization/PPN/e-Faktur | Custom development required |
| GAP-C04 | HIGH | Audit trail is mutable SQLite rows, not immutable/append-only | Does not meet R-008 audit integrity requirement |
| GAP-C05 | HIGH | GL invariants are post-hoc checks, not enforced constraints | Risk of unbalanced entries between checks |
| GAP-C06 | MEDIUM | RBAC is opt-in and application-level only | Not enforceable at database level |
| GAP-C07 | MEDIUM | No native idempotency for chat-driven retries | External integration layer required |
| GAP-C08 | MEDIUM | Module system fetches from GitHub on demand | Supply-chain risk; needs hash pinning |
| GAP-C09 | LOW | No native backup/restore orchestration | File-based backup is simple but not managed |

## 10. Recommendation

ERPClaw `v4.1.2` is **not acceptable** as the primary system of record for ERP Kreasi Hebat because:

1. **Architectural mismatch:** CLI-only, no web UI/REST API, no background jobs. Cannot serve as backend for chat-driven workflows without building a complete web layer.
2. **No unit isolation:** No native concept of operating units with separate sales pipelines.
3. **Audit integrity insufficient:** Mutable audit log does not meet R-008's immutable audit trail requirement.
4. **Indonesian localization absent:** No PPN, no e-Faktur, no Indonesian tax rules.

**Role for ERPClaw:** may serve as a **read-only reference** for AI-native UX patterns (chat-to-action mapping, natural language onboarding), but never as the official ledger.

**Next step:** EVAL-002 (ERPNext isolated environment) remains the only forward track for system-of-record evaluation.
