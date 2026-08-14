# ADR-001 — Native ERP Isolation Qualification Verdict (ISO-001)

- Status: `DECIDED`
- Date: 2026-08-14 (UTC)
- Task: ISO-001 (R-003, R-011, R-021)
- Target under test: isolated ERPNext pilot `http://127.0.0.1:18080`, site `erpnext-pilot.localhost`, **ERPNext pinned v16.32.1** (frappe 16.31.0), verified live by `test_seed_harness.TestSeedFixtures.test_pinned_erpnext_version`.
- Evidence: `matrix.md`, `raw/probes-20260814.jsonl` (52 probes in the latest run, run-id grouped), test suites under `tests/security/native_erp/` (60 tests; 54 PASS, 6 FAIL = verified genuine leaks kept red by design).

## Context

`NATIVE_ERP_ISOLATION.md` requires fail-closed unit isolation across every native
surface with direct unit-sales credentials before single-site adoption remains
eligible. Gateway-only claims and vendor documentation are insufficient; raw
probes at the pinned version decide.

## Method

Synthetic actors (no real personal data):

- `iso-sales-bm@example.test` — role Sales User, User Permission Company=`UNIT-BM`.
- `iso-sales-p1@example.test` — role Sales User, User Permission Company=`UNIT-PR1ME`.
- `iso-owner@example.test` — cross-unit owner (explicit roll-up by design).
- `iso-deactivated@example.test` — disabled account; `iso-unknown@example.test` — never created.

Synthetic marker records per unit (Leads, Customers, Quotations, one private
File attachment on the BM lead), all with opaque marker strings. Every probe
records actor, action, expected outcome, HTTP status, observed leak tokens, and
timing bucket into append-only JSONL. Assertions are never weakened: a genuine
leak remains a failing test and is itself the qualification evidence.

## Findings — surfaces that enforce isolation (PASS)

Probed and fail-closed on pinned v16.32.1:

- Lead/Quotation REST list and direct GET — company-scoped via User Permission;
  cross-unit rows absent; cross-unit direct GET denied; error bodies disclose no
  protected field values.
- Desk list count endpoint (`frappe.desk.reportview.get_count`) — count is
  user-permission-scoped (admin ground truth comparison; no cross-unit count
  inflation).
- `search_link` autocomplete and global search for company-scoped doctypes —
  no cross-unit results; existence-oracle probe (existing cross-unit vs random
  nonexistent query) returns indistinguishable result sets.
- Query report / export / print-PDF paths probed — no cross-unit rows/bytes.
- Comment / ToDo / Notification Log / Communication — denied or scoped; no
  cross-unit content.
- Scope-escape mutations (5/5 denied, admin read-back verified unchanged):
  reassign own Lead company to the other unit; create a User Permission for
  self; self-grant a role; delete an existing User Permission; create a
  document directly in the other unit.
- Scheduled Job Log / RQ Job / Activity / Version / Data Import surfaces —
  denied for unit-sales users.
- Private file bytes: direct `/private/files/<name>` URL is denied cross-unit
  (403) while readable in-unit (200) — byte-level protection holds.

## Findings — unavoidable native leaks (FAIL, kept red)

1. **Customer master is unscopeable by Company User Permission** (4 suite FAILs,
   8 leak-positive probes). `Customer` has no `company` field; User Permission
   scoping cannot express it. Both unit users enumerate all customers
   (`GET /api/resource/Customer` returns `CUST-ALPHA`, `ISO-CUST-BM-001`,
   `ISO-CUST-P1-001` to both), read the other unit's Customer by direct GET
   (HTTP 200), surface cross-unit customers via `search_link` autocomplete
   (including exact-name query returning the cross-unit record), and observe
   **cross-unit count inflation** (`frappe.client.get_count` /
   `reportview.get_count` return the admin ground-truth total). This violates
   "cannot enumerate protected records/counts" and "cannot infer customer
   existence".
2. **File metadata enumerates cross-unit** (1 FAIL, 1 leak-positive probe).
   `GET /api/resource/File` filtered to Lead attachments lists the other unit's
   private attachment filename (`iso-private-bm-001.txt`) and parent document
   name to a cross-unit user. Bytes remain protected (403 on direct URL), but
   metadata disclosure alone leaks which records exist and carry attachments.
3. **Existence oracle via status-code split** (1 FAIL, 1 leak-positive probe).
   An existing cross-unit Lead returns **403** while a nonexistent Lead returns
   **404** — a unit user can confirm/deny the existence of any guessed record
   name cross-unit without reading a single field.

These are properties of native ERPNext v16.32.1 permission resolution. They
cannot be closed by the **declarative admin mechanisms this project allows
itself** (roles, User Permissions, role/custom-role permission rules). Frappe
does expose supported extension points — per-doctype `permission_query_conditions`
hooks and Server Scripts — that could in principle filter Customer lists and
search results, but those are per-doctype code patches deployed into the site:
they are operationally fragile across upgrades, must be re-proven per doctype
per release, do not address the File-metadata enumeration class, and cannot
unify the 403/404 existence oracle without patching core error handling. The
project explicitly rejects maintaining a growing patch surface as its isolation
boundary; see the Decision below.

## Decision

**VERDICT: `REQUIRES_GATEWAY_ONLY`** (multi-site is an acceptable alternative
but operationally heavier for one shared office).

- Single-site native access for unit-sales roles is **disqualified** on pinned
  v16.32.1: the three leak classes above are unavoidable on native surfaces.
- Selected architecture for **ISOFIX-001**: unit actors (sales, and any role
  whose scope is a single operating unit) access ERP exclusively through the
  proven gateway/adapter layer (`src/adapters/erpnext*`, CRM port), which
  enforces scope fail-closed. Direct native desk/API credentials are not issued
  to unit-scoped roles at all. Owner/controller roll-up remains explicit,
  server-side, and auditable. Native access, where unavoidable for operations,
  is limited to non-unit-scoped operator roles under a separate control.
- Per the task contract, ISO-001 records the verdict only; implementing the
  gateway-only final architecture and re-running the full matrix as
  `ISOLATION_FINAL=PASS` is **ISOFIX-001**. ISO-001 alone never opens
  PILOT-001.

## Consequences

- ISOFIX-001 owned paths (`src/isolation_architecture/**`,
  `environments/isolation-final/**`, `tests/security/isolation_final/**`,
  `docs/evidence/isolation-final/**`) must implement the gateway-only decision
  and re-run this matrix against the final architecture, where the three leak
  classes above must be impossible by construction (no unit-scoped native
  credentials exist to probe).
- CRM-001/ADP-002 gateway isolation evidence already demonstrates the gateway
  layer enforces scope fail-closed; ISOFIX-001 requalifies it as the final
  architecture rather than an interim layer.
- Residual accepted scope: owner cross-unit roll-up is explicit and auditable
  (`test_owner_rollup_is_explicit_and_auditable`).
