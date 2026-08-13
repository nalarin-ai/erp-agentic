# Requirements

## Discovery baseline — 2026-08-13

Status: `DISCOVERY`; no implementation task is `READY` until the reviewed baseline receives `PLAN_GATE=PASS`.

### Confirmed business scope from WhatsApp discussion

- R-001 — One owner needs role-scoped oversight across multiple businesses/functions without merging their ledgers or leaking records between groups.
- R-002 — Initial business workflows include Google Ads agency, event organizer/rental, contractor and paving-block sales, heavy-equipment rental, marketing/SEO, finance, operations, and HR.
- R-003 — WhatsApp/Telegram are interaction and approval channels; they are not the accounting or ERP system of record.
- R-004 — Every inbound request must resolve an authorized actor, source chat/group, business/legal entity, function, and permitted action before reading or writing business data.
- R-005 — Finance and HR visibility must be narrower than general operations; create, approve, issue/send, mark-paid, and administration are separate permissions.
- R-006 — The first pilot workflow is draft invoice → authorized review/approval → official number/PDF → receivable → payment evidence/reminder, using synthetic data only.
- R-007 — Duplicate/retried chat requests must be idempotent, and every material action must retain actor, timestamp, source, evidence reference, and audit history.
- R-008 — ERP credentials must remain outside chat/source, use least-privilege service accounts, and writes must be verified by reading the resulting record back.
- R-009 — Backup, export, and restore must be exercised before production use; Indonesian accounting, tax, currency, numbering, and chart-of-accounts assumptions require qualified review.
- R-010 — SEO rank tracking, website monitoring, analytics, and social publishing remain specialist integrations rather than accounting-core responsibilities.
- R-011 — The operating brands are business units sharing one office, while maintaining separate sales teams and commercially competing pipelines; sales leads, quotations, targets, commissions, and customer visibility must not leak across units by default.
- R-012 — `Banyumedia` covers Google Ads agency and broader digital-marketing services.
- R-013 — `Pr1me` covers event-organizer and rental operations.
- R-014 — The contractor unit covers paving blocks, asphalt work, house construction, and future construction services under one extensible contractor domain.
- R-015 — Heavy-equipment rental is a distinct operating unit.
- R-016 — `PT Tumbuh Kreasi Hebat` (`PT TKH`) is a distinct VAT-registered legal issuer. Transactions requiring PPN must be invoiced/reported under PT TKH and paid to an approved PT TKH bank account.
- R-017 — The system must distinguish operating brand/unit, sales ownership, legal issuer, tax treatment, invoice series, receivable ledger, and destination bank account on every commercial transaction.
- R-018 — `Balonesia`, selling promotional balloons, is a known future unit but is outside the first pilot; the model must allow it and additional units to be added without redesigning the core tenancy/permission model.
- R-019 — Bank accounts are configurable payment destinations, not a single office-wide account. Units/legal issuers may have their own default accounts, and an explicitly approved account may be shared by multiple units. The selected account must remain compatible with the legal issuer and tax treatment of the transaction.
- R-020 — Each operating unit has its own configurable branding profile, including logo and invoice template. The rendered quotation/invoice must use the selected transaction unit's active branding version while legal issuer name, tax identity, invoice series, receivable ledger, and destination account remain separate validated fields and may not be overridden by branding.
- R-021 — An authorized user or sales actor may be assigned to one or multiple operating units through explicit effective-dated assignments. Every CRM or commercial action executes under exactly one active unit context; a multi-unit user must choose the unit when it cannot be derived unambiguously, and the system must deny unassigned, inactive, stale, or cross-unit access.
- R-022 — Unit-specific behavior must be configuration-driven rather than hardcoded in application source. Each unit has versioned, typed settings for branding/templates, numbering, currency/price list/payment terms, approval workflow/thresholds, enabled modules, sales pipeline, and allowed issuer/tax/ledger/account mappings. Configuration changes require schema validation, authorization, preview, effective date, audit, rollback, and regression evidence; invalid or unknown settings fail closed.

### Current organization model

| Operating unit/brand | Current scope | Sales boundary | Legal/tax treatment |
|---|---|---|---|
| Banyumedia | Google Ads agency and digital marketing | Separate/private pipeline | Own/default account confirmed; PT TKH account only when PT TKH is the legal issuer for PPN |
| Pr1me | Event organizer and rental | Separate/private pipeline | Own/default account confirmed; exact account identity remains secret/config-local |
| Contractor | Paving block, asphalt, house construction, future construction services | Separate/private pipeline | Own/default account confirmed; PT TKH account only when PT TKH is the legal issuer for PPN |
| Heavy-equipment rental | Equipment rental operations | Separate/private pipeline | Explicitly shares the Contractor/Paving Block receiving account; PT TKH account only when PT TKH is the legal issuer for PPN |
| PT Tumbuh Kreasi Hebat | VAT-registered legal issuer and PPN reporting/payment boundary | Access restricted to authorized PT/finance roles | Own PT TKH account; PPN transactions issued by PT TKH use an approved PT account |
| Balonesia (later) | Promotional balloons | To be defined | Own/default account confirmed; future onboarding; not in first pilot |

Design implication: an operating unit/brand is not the same dimension as the legal issuer or bank account. A transaction begins under one unit and sales owner, then selects a validated legal issuer/tax/payment profile and an allowed destination account. Account sharing must be represented by an explicit many-to-many allowlist, not inferred from a matching name or free-form chat. PT TKH must not be inferred solely from free-form chat; the applicable PPN/issuer rule must be deterministic and auditable.

Branding and authorization implication: logo/template selection follows the one active transaction unit, whereas user membership is many-to-many. Branding is presentation configuration, not evidence of legal issuer, PPN status, ledger, or receiving account. Assignment changes are versioned/audited and take effect immediately according to their effective period.

Configuration implication: onboarding or changing a unit must use reviewed settings/fixtures or supported ERP customization surfaces, not `if unit == ...` branches or edits to upstream ERP core. Financial settings are allowlisted references governed by compatibility policy; arbitrary code/script values are not accepted as unit configuration.

### Candidate architecture under evaluation

- Conversation/orchestration: Hermes on the project-bound executor profile and Telegram bot.
- System of record candidate A: ERPNext/Frappe, favored for maturity, MariaDB compatibility, permissions, workflow, API, and established ERP coverage.
- Experimental comparator: ERPClaw, favored for conversation-first UX but not yet accepted as the official ledger because of project maturity, small maintainer base, lack of Indonesian localization proof, PostgreSQL production direction, and Hermes integration risk.
- Candidate specialist systems after core stabilization: Uptime Kuma, SerpBear, Matomo/Umami, Postiz, and Mautic, each subject to a separate fit/security/license review.

### Open discovery decisions

- O-001 — `RESOLVED`: Banyumedia, Pr1me, Contractor, heavy-equipment rental, and future Balonesia are operating units/brands sharing one office. PT TKH is the distinct PPN legal issuer. Other legal entities/“bendera” may exist and must be enumerated before production.
- O-002 — Which single business and invoice type will be used for the synthetic pilot?
- O-003 — Required invoice fields, numbering, currencies, approval thresholds, and payment-evidence rules.
- O-004 — Role matrix: requester, finance reviewer, owner/controller, HR, operations, and explicitly unauthorized cases.
- O-005 — Expected users, monthly transaction volume, current source data/Excel formats, document retention, and required reports.
- O-006 — Whether the pilot compares ERPNext and ERPClaw side-by-side or starts with ERPNext only.
- O-007 — Partially resolved: default own-account status is confirmed for Balonesia, Banyumedia, Pr1me, Contractor/Paving Block, and PT TKH. Heavy-equipment rental explicitly shares the Contractor/Paving Block account. Remaining work: enumerate every legal “bendera”, tax status, invoice series, account alias, and any additional shared mappings. Do not store account numbers in project-control/chat.
- O-008 — Define the deterministic rule for when a unit transaction uses PT TKH/PPN versus another legal issuer/non-PPN path, including who may override it and what evidence is required.
- O-009 — Define sales isolation precisely: whether customer master, leads, price lists, quotations, commissions, and reports are private per unit, and what owner/finance roll-up may cross those boundaries.
- O-010 — `RESOLVED`: the duplicated “Balonesia” mention referred to Banyumedia. Balonesia and Banyumedia each have their own/default account.

### Non-goals for the discovery phase

- No live financial/HR data import, official posting, customer delivery, banking connection, production deployment, or cross-project/server changes.
- No product selection claim until the synthetic pilot and permission/audit/backup checks produce evidence.
