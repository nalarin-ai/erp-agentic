# Normative Traceability Matrix

- Status: `REVISED_DRAFT`
- Rule: each row requires implementation evidence; planning coverage alone is insufficient.

## A. Discovery requirements

| Req | Owning task(s) | Acceptance assertion | Test/failure case | Evidence path |
|---|---|---|---|---|
| R-001 | UNIT-001, RPT-001 | Confirmed operating units are configured and owner roll-up preserves boundaries | RT-001 unit seed; unknown unit denied | `docs/evidence/units/rt-001.*` |
| R-002 | UNIT-001, CRM-001 | Banyumedia, Pr1me, Contractor domains are represented; later modules remain explicitly phased | RT-002 fixture/service categories; unsupported module not falsely reported | `docs/evidence/units/rt-002.*` |
| R-003 | FND-002, CRM-001, ISO-001, ISOFIX-001 | Competing sales cannot read/claim each other's pipelines across the finally implemented gateway/native architecture | RT-003 direct/search/export/count denials; failed single-site requires implemented alternative and rerun | `docs/evidence/isolation-final/rt-003.*` |
| R-004 | FND-001, FND-002, FLOW-001 | Chat resolves identity/scope and only then prepares authorized ERP intent | RT-004 unknown/ambiguous actor makes zero writes | `docs/evidence/chat/rt-004.*` |
| R-005 | EVAL-001, MIG-001, MIGDEC-001 | ERP core is authoritative; source/import/go-live boundary is explicit | RT-005 chat/session not used as ledger; migration branch required | `docs/evidence/architecture/rt-005.*` |
| R-006 | ADP-001, ADP-002, FLOW-001..003 | Invoice→AR flow passes provider contracts and E2E | RT-006 draft/post/PDF/payment/aging with provider failures | `docs/evidence/pilot/rt-006.*` |
| R-007 | FND-002, FND-004, REC-001 | Mutations are authorized, idempotent, audited, and reconciled | RT-007 race/crash/stale-worker/denial matrix | `docs/evidence/recovery/rt-007.*` |
| R-008 | FND-004, REC-001, MIG-001, OPS-001 | Failures are observable/recoverable and imports/backups reconciled | RT-008 storage-full, lost response, corrupt backup/import | `docs/evidence/operations/rt-008.*` |
| R-009 | EVAL-002, EVAL-003, OPS-001 | Candidate is tested isolated with synthetic data and restore proof | RT-009 environment separation and teardown | `docs/evidence/evaluation/rt-009.*` |
| R-010 | INT-001 | Specialist connector pattern is separate/read-only to accounting | RT-010 connector cannot mutate ERP ledger | `docs/evidence/integrations/rt-010.*` |
| R-011 | FND-002, CRM-001, ISO-001, ISOFIX-001, RPT-001 | Unit-private operations plus explicit owner/controller roll-up on final architecture | RT-011 role matrix/no leakage/reconciled roll-up | `docs/evidence/authz/rt-011.*` |
| R-012 | UNIT-001 | Banyumedia unit is provisioned with own sales/account policy | RT-012 wrong unit account denied | `docs/evidence/units/rt-012.*` |
| R-013 | UNIT-001, FLOW-003 | Pr1me unit is provisioned with own sales/account and AR path | RT-013 cross-unit/wrong account denied | `docs/evidence/units/rt-013.*` |
| R-014 | UNIT-001 | Contractor supports paving/asphalt/house categories configurably | RT-014 add category without core migration | `docs/evidence/units/rt-014.*` |
| R-015 | UNIT-001, CRM-001 | Heavy Equipment is separate sales scope and shares only approved Contractor account | RT-015 shared mapping positive; other account/cross-sales denied | `docs/evidence/units/rt-015.*` |
| R-016 | FND-003, ADP-002, EXP-001 | PT TKH PPN path binds PT issuer/tax/series/account | RT-016 unit account or non-PT issuer denied | `docs/evidence/policy/rt-016.*` |
| R-017 | FND-001, FND-003, FLOW-002 | Unit, sales, issuer, tax, series, ledger, account are explicit/compatible/immutable posted | RT-017 wrong ledger/account/currency and post-edit denied | `docs/evidence/policy/rt-017.*` |
| R-018 | UNIT-001 | Balonesia onboarding is configuration-only with own account alias | RT-018 schema/core diff unchanged | `docs/evidence/units/rt-018.*` |
| R-019 | FND-003, FLOW-001..003 | Real account details stay restricted; alias selected deterministically; PPN uses PT account | RT-019 secret canary/redaction/ambiguous account block | `docs/evidence/security/rt-019.*` |
| R-020 | UNIT-001, FLOW-001, FLOW-002, UX-001 | Each unit renders its versioned logo/template while protected financial identity remains separately derived and immutable | RT-020 two-unit PDF snapshot; template spoof/unsafe placeholder/version drift denied | `docs/evidence/branding/rt-020.*` |
| R-021 | FND-002, UNIT-001, ADP-002, CRM-001, ISO-001, ISOFIX-001, FLOW-001, FLOW-002, REM-001, RPT-001, UX-001 | Actor may hold multiple assignments but each request has exactly one authorized active unit; switch/expiry/revoke is fail-closed across gateway and native surfaces | RT-021 zero/one/multi assignment, switch, expiry/revoke, stale cache/preview across UI/API/direct URL/search/report/export/PDF/attachment/notification/jobs | `docs/evidence/authz/rt-021.*` |
| R-022 | UNIT-001, FLOW-001, FLOW-002, UX-001 | Unit behavior is typed/versioned configuration with validate/preview/activate/rollback and no unit-specific source branch | RT-022 unknown/wrong type/dangling ref/script/concurrent update denied; synthetic onboarding source-diff proof | `docs/evidence/config/rt-022.*` |

## B. PRD functional requirements

| FR | Owning task(s) | Acceptance/test ID | Failure case | Evidence |
|---|---|---|---|---|
| FR-001 | FND-002, UNIT-001 | FT-001 identity+scope resolution | unknown/conflicting mapping denied | `docs/evidence/trace/ft-001.*` |
| FR-002 | CRM-001, ISO-001 | FT-002 sales isolation | direct/search/export/count leak denied | `docs/evidence/trace/ft-002.*` |
| FR-003 | FND-003, EXP-001 | FT-003 issuer/tax policy | prompt override/unknown config blocked | `docs/evidence/trace/ft-003.*` |
| FR-004 | FND-003, UNIT-001 | FT-004 account allowlist | wrong/shared-unapproved account denied | `docs/evidence/trace/ft-004.*` |
| FR-005 | FLOW-001 | FT-005 complete deterministic draft | missing field no number/write | `docs/evidence/trace/ft-005.*` |
| FR-006 | FLOW-002 | FT-006 review/post separation | requester self-post/stale preview denied | `docs/evidence/trace/ft-006.*` |
| FR-007 | FLOW-002 | FT-007 PDF and delivery orthogonality | PDF-before-post; delivery failure | `docs/evidence/trace/ft-007.*` |
| FR-008 | FLOW-003, REM-001 | FT-008 AR/aging/reminder | paid/cancelled duplicate reminder suppressed | `docs/evidence/trace/ft-008.*` |
| FR-009 | FLOW-003 | FT-009 evidence payment | chat-only, wrong account, duplicate race denied | `docs/evidence/trace/ft-009.*` |
| FR-010 | FND-004, REC-001 | FT-010 idempotency/fencing | crash/lost response/stale worker | `docs/evidence/trace/ft-010.*` |
| FR-011 | FND-004, REC-001 | FT-011 durable audit | storage full/outcome write fail/orphan | `docs/evidence/trace/ft-011.*` |
| FR-012 | ADP-001, ADP-002, FLOW-002 | FT-012 supported correction/reversal | hard delete/in-place posted edit denied | `docs/evidence/trace/ft-012.*` |
| FR-013 | RPT-001 | FT-013 owner report reconciliation | unauthorized aggregate/export denied | `docs/evidence/trace/ft-013.*` |
| FR-014 | UNIT-001 | FT-014 Balonesia onboarding | core schema edit detected | `docs/evidence/trace/ft-014.*` |
| FR-015 | MIG-001, MIGSRC-001 | FT-015 staged import | hostile/duplicate/no-write dry-run | `docs/evidence/trace/ft-015.*` |
| FR-016 | OPS-001 | FT-016 backup/restore | corrupt/undecryptable/inconsistent set rejected | `docs/evidence/trace/ft-016.*` |
| FR-017 | INT-001 | FT-017 specialist boundary | accounting mutation/secret leakage denied | `docs/evidence/trace/ft-017.*` |
| FR-018 | FND-003, FLOW-002 | FT-018 ledger compatibility | wrong company/currency/ledger denied | `docs/evidence/trace/ft-018.*` |
| FR-019 | ISO-001, ISOFIX-001 | FT-019 native isolation | leakage rejects current architecture and blocks pilot until alternative is implemented/requalified | `docs/evidence/trace/ft-019.*` |
| FR-020 | UNIT-001, FLOW-001, FLOW-002 | FT-020 per-unit branding snapshot | wrong logo/template, spoofed issuer field, unsafe placeholder, post-update historical rewrite denied | `docs/evidence/trace/ft-020.*` |
| FR-021 | FND-002, UNIT-001, ADP-002, CRM-001, ISO-001, ISOFIX-001, FLOW-001, FLOW-002, REM-001, RPT-001, UX-001 | FT-021 multi-unit assignment/context on every gateway/native surface | unassigned/inactive/expired/revoked/ambiguous/stale context, cross-unit cache/export/PDF/notification/job leak denied | `docs/evidence/trace/ft-021.*` |
| FR-022 | UNIT-001, UX-001 | FT-022 typed versioned settings | unknown key/type/ref/script, unauthorized activation, conflict, rollback mismatch, hardcoded unit branch fail | `docs/evidence/trace/ft-022.*` |

## C. Journeys

| Journey | Owning tasks | UI/chat → contract → persistence → failure → observability | Test/evidence |
|---|---|---|---|
| J-001 Draft invoice | FLOW-001, FLOW-002 | chat states → command/preview → draft/intent/ERP → stale/denied/uncertain → scope/preview/post/readback events | JT-001, `docs/evidence/journeys/jt-001.*` |
| J-002 PT TKH PPN | FND-003, FLOW-001, FLOW-002, EXP-001 | explicit PT preview → financial policy → immutable posted snapshot → wrong issuer/account/ledger blocked → policy/post events | JT-002, `docs/evidence/journeys/jt-002.*` |
| J-003 Payment | FLOW-003, REC-001 | evidence form/chat → payment command → ERP payment/AR → duplicate/overpay/uncertain → payment/readback/reconcile events | JT-003, `docs/evidence/journeys/jt-003.*` |
| J-004 Sales isolation | CRM-001, ISO-001 | scoped UI/search → query contract → ERP CRM → no-leak conflict/denial → denial/controller-transfer events | JT-004, `docs/evidence/journeys/jt-004.*` |
| J-005 Balonesia | UNIT-001 | admin config → unit contract → config/ERP seed → invalid mapping rollback → config audit/smoke | JT-005, `docs/evidence/journeys/jt-005.*` |
| J-006 Multi-unit sales context | FND-002, UNIT-001, FLOW-001, FLOW-002, UX-001 | assigned-unit selector → scoped context contract → CRM/draft/config snapshot/PDF → unassigned/stale/revoked/spoof denied → select/switch/invalidate/post events | JT-006, `docs/evidence/journeys/jt-006.*` |

## D. MVP acceptance criteria

| ID | Criterion | Owner | Test/layer | Failure assertion | Evidence |
|---|---|---|---|---|---|
| MVP-AC-01 | Banyumedia + Contractor and denied cross-sales | UNIT-001, CRM-001, ISOFIX-001 | E2E/security | native/gateway leak on final architecture fails | `docs/evidence/pilot/ac-01.*` |
| MVP-AC-02 | Heavy Equipment→Contractor shared account | UNIT-001, FND-003 | unit/policy/E2E | other account denied | `docs/evidence/pilot/ac-02.*` |
| MVP-AC-03 | non-PPN + PT PPN correct path | FND-003, FLOW-001 | policy/E2E | wrong issuer/tax/ledger/account denied | `docs/evidence/pilot/ac-03.*` |
| MVP-AC-04 | required ambiguity blocks posting | FLOW-001 | state/E2E | zero official number/provider write | `docs/evidence/pilot/ac-04.*` |
| MVP-AC-05 | retry never duplicates | FND-004, REC-001 | concurrency/integration | stale worker/lost response safe | `docs/evidence/pilot/ac-05.*` |
| MVP-AC-06 | unauthorized sensitive actions denied | FND-002, ISO-001 | negative auth E2E | zero disclosure/mutation | `docs/evidence/pilot/ac-06.*` |
| MVP-AC-07 | number/PDF only after post | FLOW-002 | provider/E2E | draft cannot claim official number | `docs/evidence/pilot/ac-07.*` |
| MVP-AC-08 | payment evidence and correct AR | FLOW-003 | money/E2E | chat-only/overpay/duplicate denied | `docs/evidence/pilot/ac-08.*` |
| MVP-AC-09 | durable audit/readback/redaction | FND-004, REC-001 | durability/security | audit failure no false success | `docs/evidence/pilot/ac-09.*` |
| MVP-AC-10 | export/backup/isolated restore | OPS-001 | operational drill | corrupt/inconsistent set rejected | `docs/evidence/pilot/ac-10.*` |
| MVP-AC-11 | compact/wide/a11y/recovery UX | UX-001 | browser/independent review | overflow/focus/state gap fails | `docs/evidence/pilot/ac-11.*` |
| MVP-AC-12 | assumptions reported; production blocked pending qualified sign-off | PILOT-001, EXP-001 | pilot report/readiness gate | no sign-off cannot set PROD approved | `docs/evidence/pilot/ac-12.*` |
| MVP-AC-13 | distinct unit logo/template and immutable posted branding snapshot | UNIT-001, FLOW-002 | PDF/visual/provider E2E | wrong unit asset, financial-identity override, or historical rewrite fails | `docs/evidence/pilot/ac-13.*` |
| MVP-AC-14 | multi-unit user selects exactly one authorized active unit across gateway/native surfaces | FND-002, ADP-002, CRM-001, ISOFIX-001, FLOW-001, FLOW-002, REM-001, RPT-001, UX-001 | authz/browser/chat/API/report/PDF/notification/job E2E | unassigned/expired/revoked selection, cross-unit leak, stale cache/preview, export/PDF/notification/job access fails | `docs/evidence/pilot/ac-14.*` |
| MVP-AC-15 | new unit and variable behavior configured without hardcode | UNIT-001, UX-001 | config lifecycle/source-diff E2E | unknown/script setting, invalid reference, unauthorized activation, conflict, rollback mismatch, or unit-name source branch fails | `docs/evidence/pilot/ac-15.*` |

## E. Observability event contract

All events carry schema version, correlation ID, action/aggregate alias, actor/source/unit/issuer/ledger aliases where authorized, policy/adapter version, timestamp, result, latency, and redacted error. Required pairs/terminals:

- `scope_resolution_started → scope_resolved|scope_denied`
- `preview_started → preview_created|preview_rejected|preview_stale`
- `mutation_intent_claimed → provider_started → readback_verified|recovery_required|failed_no_mutation`
- `reconciliation_started → resolved_present|resolved_absent_reissued|manual_escalation|provider_unavailable`
- `delivery_queued → delivery_sent|delivery_retryable_failed|delivery_terminal_failed`
- `payment_started → payment_verified|payment_recovery_required|payment_rejected`
- `reminder_eligible → reminder_queued|reminder_suppressed → reminder_sent|failed`
- `reversal_started → reversal_verified|reversal_recovery_required|reversal_rejected`
- `configuration_previewed → configuration_applied|configuration_rejected|rolled_back`
- `unit_context_required → unit_context_selected|unit_context_denied`; `unit_context_switched → scoped_state_invalidated`
- `branding_previewed → branding_snapshot_bound|branding_rejected`; `unit_config_drafted → unit_config_validated|unit_config_rejected → unit_config_activated|unit_config_conflict|unit_config_rolled_back`
- `conflict_detected → conflict_resolved|conflict_closed`
- `evidence_received → evidence_accepted|evidence_quarantined|evidence_rejected`
- `import_started → import_dryrun_complete|import_batch_verified|import_rejected|import_reversed`
- `backup_started → backup_verified|backup_failed`; `restore_started → restore_verified|restore_failed`

Test FT-011 asserts correlation and legal terminal event for every mutation path.
