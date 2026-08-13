# Product Requirements Document — ERP Kreasi Hebat

- Status: `DRAFT_DISCOVERY`
- Version: `0.1.0`
- Date: `2026-08-13`
- Product owner: Didik / authorized Bos `233301028`
- Project: `erp-kreasi-hebat`
- Approval policy: project-bound `FULL_AUTO`
- Source priority: current owner instruction → `PROJECT.md`/`DECISIONS.md` → this PRD → supporting design documents.

## 1. Executive summary

ERP Kreasi Hebat is an internal, multi-unit operating platform for one office that runs several commercially distinct brands. It must preserve separate sales pipelines and operational visibility while allowing owner/finance roll-ups. The operating unit, legal invoice issuer, tax treatment, receivable ledger, and destination bank account are separate dimensions.

Hermes on the dedicated executor Telegram bot is the conversational control layer. The ERP is the authoritative system of record. Chat history and Hermes memory are never the accounting ledger.

The first evidence-gathering pilot is a synthetic invoice-to-receivable journey. ERPNext/Frappe is the maturity-first candidate; ERPClaw is an isolated comparator only until it proves permissions, accounting invariants, reversals, auditability, localization, and recoverability.

## 2. Problem statement

Today, work originates across separate business groups and teams. Without a structured system, the office risks:

- sales teams seeing or taking each other's leads;
- invoices using the wrong brand, legal issuer, PPN treatment, numbering, or bank account;
- duplicate transactions caused by retried chat instructions;
- payment claims without evidence;
- fragmented owner reporting;
- weak auditability and role separation;
- treating chat context as durable business records.

## 3. Product goals

### G-001 — Multi-unit operations
Support Banyumedia, Pr1me, Contractor/Paving Block, Heavy-equipment Rental, PT TKH, and later Balonesia/additional units without redesigning tenancy.

### G-002 — Sales isolation
Keep competing sales pipelines private by default while permitting explicit owner/controller and authorized finance roll-ups.

### G-003 — Correct commercial identity
Every quotation/invoice/payment must bind an operating unit, sales scope, legal issuer, tax profile, invoice series, receivable ledger, and allowed destination account.

### G-004 — Safe conversational operations
Allow authorized users to request, review, and track business actions from chat, with deterministic validation and no free-form guessing of financial/tax identity.

### G-005 — Audit and recoverability
Provide idempotency, immutable business-event evidence, controlled corrections/reversals, export, backup, and tested restore.

### G-006 — Extensibility
Add units, services, workflows, and specialist tools through configuration/integration rather than modifying upstream ERP core.

## 4. Non-goals for initial release

- Automatic bank transfer, payment execution, or banking credential handling.
- Automatic tax judgment or replacement of Indonesian finance/tax professionals.
- Production use of real books before pilot, localization review, and restore proof.
- Full HR/payroll, manufacturing, SEO, social publishing, or every rental workflow in MVP.
- A new custom dashboard before adopted ERP UI and chat workflow prove insufficient.
- Cross-project/server access beyond `/home/tejo/agentic/projects/erp-kreasi-hebat`.

## 5. Organization and account model

| Unit/entity | Scope | Sales visibility | Default receiving account |
|---|---|---|---|
| Banyumedia | Google Ads and digital marketing | Unit-private | Own Banyumedia account |
| Pr1me | Event organizer and rental | Unit-private | Own Pr1me account |
| Contractor/Paving Block | Paving, asphalt, house construction, related construction | Unit-private | Own Contractor account |
| Heavy-equipment Rental | Heavy-equipment rental | Unit-private | Explicitly shares Contractor account |
| PT Tumbuh Kreasi Hebat | VAT-registered legal issuer | Restricted PT/finance | Own PT TKH account |
| Balonesia | Promotional balloons; later phase | To define | Own Balonesia account |

PPN transactions issued under PT TKH must use an approved PT TKH account. Unit default accounts apply only when compatible with legal issuer and tax treatment. Shared accounts require an explicit allowlist.

## 6. Personas and roles

- **Owner/controller:** cross-unit roll-up, exception approval, configuration oversight, audit access.
- **Unit sales:** leads, customers, quotations, and follow-ups only inside assigned unit/scope.
- **Unit operations:** fulfillment/project/rental status inside assigned unit; limited financial visibility.
- **Finance requester:** prepare draft invoices/payments and attach evidence within assigned scope.
- **Finance reviewer:** validate issuer, tax, account, numbering, amount, and evidence; approve/post within authority.
- **PT tax/finance:** PT TKH PPN invoice/faktur preparation, reconciliation, and reporting evidence.
- **HR:** later-phase employee records, with no automatic sales/finance access.
- **System integration account:** API-only, least privilege, no interactive owner authority.
- **Unauthorized user:** denied without leaking existence, amount, customer, or account details.

## 7. Functional requirements

### FR-001 — Unit and identity resolution
Resolve actor, source chat/group, operating unit, role, and action scope before any business read/write. Ambiguity fails closed.

### FR-002 — Lead and customer isolation
Leads, opportunities, assigned customers, quotations, price lists, targets, and commissions are unit-scoped by default. Cross-unit duplicate detection may reveal only a safe conflict signal to non-owner users.

### FR-003 — Legal issuer and tax profile
Select legal issuer and PPN/non-PPN profile from deterministic policy. Free-form chat cannot override the mapping. Overrides require authorized role, reason, and audit event.

### FR-004 — Bank-account allowlist
Each unit has a default opaque account alias and zero or more allowed accounts. Account selection must validate issuer/tax compatibility. No account numbers appear in logs, general chat, source, or project-control.

### FR-005 — Draft quotation/invoice
Collect customer, service/items, quantity, price, discount, tax treatment, currency, dates, issuer, unit, sales owner, and payment destination. Missing required fields produce a targeted question; no official number is consumed while draft is incomplete.

### FR-006 — Approval and posting
Separate draft creation, financial review, posting/issuance, delivery, void/cancel, and mark-paid permissions. Posting generates an official number only after validation.

### FR-007 — PDF and delivery
Generate an issuer-correct PDF. Customer delivery is a separate audited action and cannot occur merely because a document was posted.

### FR-008 — Receivables and reminders
Track due date, open amount, partial/full payment, aging, and reminders. Reminder delivery must respect chat/user authorization and avoid disclosure in unauthorized channels.

### FR-009 — Payment evidence
Mark-paid requires an authorized payment record plus evidence/reference. Chat text alone is insufficient. Duplicate evidence/reference handling must be defined.

### FR-010 — Idempotency
Every chat-originated mutation carries a stable namespaced idempotency/external reference. Concurrent retries, worker crashes, lease takeover, and lost provider responses must reconcile to one provider action under the fencing/recovery contract, not create duplicates.

### FR-011 — Audit trail
Record actor, source, unit, issuer, ledger, action, reason, before/after descriptors, correlation ID, idempotency key, timestamp, result, and verification. Mutation fails closed if durable intent/audit precondition cannot be stored. Secrets and full account numbers are redacted.

### FR-012 — Correction and reversal
Posted financial records are corrected through supported amendment/cancel/reversal semantics, not silent overwrite or hard delete.

### FR-013 — Owner reporting
Provide unit-level and consolidated authorized views of leads, quotation conversion, revenue, receivables, overdue amounts, cash receipt evidence, and workload without merging legal ledgers.

### FR-014 — Extensible unit onboarding
Create a unit, roles, chat mappings, issuer/tax/account policy, invoice series, templates, and test fixtures without schema redesign. Balonesia is the onboarding acceptance case.

### FR-015 — Import staging
Current Excel/CSV records enter a staging area with validation, deduplication, preview, error report, and rollback; never direct blind import into official books.

### FR-016 — Backup/export/restore
Support encrypted/controlled backup, document export, configuration export, and tested restore to an isolated environment.

### FR-017 — Specialist integrations
Website uptime, SEO ranks, analytics, marketing automation, and social publishing integrate later via APIs/webhooks and remain outside the accounting source of truth.

### FR-018 — Receivable ledger compatibility
Every commercial posting resolves an approved receivable ledger compatible with operating unit, legal issuer/accounting company, tax profile, and currency. The posted mapping/version is immutable and visible in authorized preview/audit evidence.

### FR-019 — Native ERP isolation
If users receive native ERP access, sales isolation must hold across direct UI/API, search/autocomplete, reports/exports, PDFs/attachments, notifications, background jobs, and direct record URLs. Single-site architecture is rejected if this cannot be proven fail-closed.

### FR-020 — Per-unit branding and document templates
Each operating unit has an independently configurable, versioned branding profile containing its logo and quotation/invoice template. Draft preview and posted PDF use the active branding snapshot of the transaction unit. Branding never determines or overrides legal issuer, PPN/tax profile, invoice series, receivable ledger, or destination account; these remain separately visible and policy-validated.

### FR-021 — Multi-unit user and sales assignment
Authorized administrators can assign a user or sales actor to one or more operating units with role/sales scope and effective dates. Each request, CRM view, draft, and posted document has exactly one active unit context. If an actor has multiple eligible units and context is ambiguous, the UI/chat asks the actor to choose; unassigned, inactive, or expired units are denied without data disclosure.

### FR-022 — Configuration-driven unit behavior
Unit differences are represented through a typed, versioned configuration contract rather than unit-name conditionals in source. Supported variables include branding assets/templates, document series, currency, price list, payment terms, approval workflow/thresholds, sales pipeline, enabled modules, and allowlisted issuer/tax/ledger/account references. Changes support draft/preview/validate/activate/rollback, have effective dates and audit history, and reject unknown keys, invalid references, unsafe template placeholders, and arbitrary executable content.

## 8. Primary user journeys

### J-001 — Draft invoice from chat
1. Authorized user requests invoice.
2. System resolves actor/chat/unit and collects missing fields.
3. System derives allowed issuer/tax/account choices.
4. System shows a safe preview.
5. Finance reviewer approves draft/posting according to configured workflow.
6. ERP posts once, generates number/PDF, and reads record back.
7. System returns status and safe document reference.

### J-002 — PPN transaction through PT TKH
1. Unit opportunity is marked as requiring PT TKH/PPN under policy.
2. PT identity, tax profile, invoice series, and PT account become mandatory.
3. Unauthorized account/issuer combinations are rejected.
4. PT finance reviews and posts.
5. Faktur/tax follow-up state and evidence are tracked without claiming tax filing automation unless implemented.

### J-003 — Record partial/full payment
1. User supplies invoice reference, amount/date, approved account alias, and evidence.
2. System validates authorization, balance, account compatibility, and duplicate reference.
3. Payment is recorded once and read back.
4. Receivable and reminder states update.

### J-004 — Competing sales isolation
1. Banyumedia salesperson searches leads/customers.
2. Only Banyumedia scope is returned.
3. A conflicting record in another unit yields a non-sensitive conflict workflow, not record disclosure.
4. Owner sees authorized roll-up and audit history.

### J-005 — Add Balonesia later
Create unit, account alias, sales scope, permissions, numbering/template, chat mapping, and synthetic smoke test without migration of core schema.

### J-006 — Multi-unit salesperson selects working unit
1. An authorized salesperson with two unit assignments opens chat or ERP.
2. The system lists only assigned active units and requires one active context when ambiguous.
3. CRM searches and draft creation are scoped to the selected unit.
4. Invoice preview/PDF uses that unit's logo/template while showing the separately validated legal issuer/tax/account identity.
5. Switching unit invalidates stale previews and cannot expose records from the previous unit.

## 9. Non-functional requirements

- **Security:** least privilege, default deny, server-side authorization, secret redaction, MFA for private dashboard where supported.
- **Privacy:** finance/HR and cross-unit data minimized by role and source channel.
- **Integrity:** decimal money, explicit currency, immutable posted identity, idempotency, supported reversal.
- **Availability:** health checks, observable failures, bounded retries, no silent partial success.
- **Performance:** target pilot response <3s for normal ERP reads and <10s for document draft/post excluding external messaging latency; measure rather than assume.
- **Accessibility:** Indonesian-first clear labels, keyboard operation, visible focus, semantic controls, non-color-only status, compact mobile support.
- **Portability:** self-hosted, documented export, no lock-in to Hermes memory/session format.
- **Maintainability:** upstream configuration/extensions before core forks; versioned integration contracts.

## 10. MVP acceptance criteria

MVP is accepted only when synthetic evidence proves:

1. At least Banyumedia and Contractor units exist with denied cross-unit sales access.
2. Heavy-equipment unit maps to the Contractor account via explicit allowlist.
3. One non-PPN draft and one PT TKH/PPN draft select correct issuer/account paths.
4. Missing/ambiguous issuer, tax, account, customer, amount, or due date blocks posting.
5. Retry does not duplicate an invoice/payment.
6. Unauthorized actor cannot approve/post/deliver/void/mark paid or inspect protected data.
7. Official number/PDF appear only after posting.
8. Partial/full payment changes receivable correctly and requires evidence.
9. Audit records and read-after-write verification exist with secrets redacted.
10. Export, backup, and isolated restore succeed.
11. Compact/wide UI plus keyboard/focus and one failure-recovery journey pass.
12. Pilot reports all finance/tax assumptions and blocks production books until a qualified reviewer signs off. Qualified sign-off is a production-readiness criterion, not a prerequisite to complete a synthetic pilot.
13. Banyumedia and Contractor synthetic invoices render their own distinct logo/template; changing branding cannot change issuer/tax/ledger/account fields, and the posted PDF retains the reviewed branding version.
14. A synthetic sales user assigned to two units can explicitly switch active unit; only assigned units are selectable, every action is single-unit scoped, stale previews are invalidated, and revocation denies subsequent access.
15. A new synthetic unit can be configured with distinct variables without application-source branches or upstream ERP core edits; invalid/unknown variables fail closed, and activation/rollback is audited.

## 11. Success metrics

Pilot metrics, not production promises:

- 0 duplicate mutations across retry tests.
- 100% denial of negative authorization matrix.
- 100% issuer/tax/account compatibility checks pass expected cases.
- 100% posted records have audit + verification evidence.
- Restore drill meets documented RPO/RTO target once chosen.
- Draft preparation time and correction rate measured against current process.

## 12. Dependencies and constraints

- Hermes is the designated sole source writer; Claude Code authentication is not an implementation prerequisite.
- Product/ERP selection remains evidence-gated.
- Real account numbers, credentials, taxpayer identifiers, and live books must not enter planning artifacts.
- Indonesian tax/accounting interpretation requires a qualified human.
- Current repository contains control documents only; no application source exists yet.

## 13. Open decisions

See `OPEN_QUESTIONS.md`. Unknowns do not authorize guesses. Fixture-based architecture and pilot planning may continue, while production posting remains blocked until legal/tax/role/source-data decisions are closed.
