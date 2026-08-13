# Test Strategy — ERP Kreasi Hebat

- Status: `DRAFT`
- Test data: synthetic only until production-readiness decision.

## 1. Test layers

### Unit
Money/decimal rules, canonicalization, RBAC, actor-unit assignment/context, typed unit-setting schema/lifecycle, branding/template placeholder allowlist, issuer/tax/account policy, redaction, dialogue state, idempotency keys, error mapping.

### Contract
One provider-neutral ERP adapter suite run against fixture and ERPNext adapters: create/read draft, post, PDF reference, receivable, payment, cancel/reverse, permissions, timeout/read-back.

### Integration
Gateway persistence, concurrency, audit, ERPNext synthetic site, document storage, outbox/channel fixture, backup/restore.

### E2E/browser
Chat request through preview/post/receivable/payment plus review UI, compact/wide, keyboard/focus, and failure recovery.

### Operational/security
Secrets scan, dependency audit, negative authorization, rate limit, health failure injection, backup checksum, isolated restore, recovery runbooks.

## 2. Normative acceptance mapping

The authoritative criteria are `MVP-AC-01..12` in `TRACEABILITY_MATRIX.md`. Each criterion binds owner task, test/layer, failure assertion, and evidence path. The matrix below is an implementation-oriented view and must remain consistent with that source.

| ID | Journey/requirement | UI/chat | API/contract | Persistence/integration | Failure/security | Observability | Proof |
|---|---|---|---|---|---|---|---|
| MVP-AC-01 | unit seed + sales isolation | scoped CRM | query/RBAC | ERP CRM | native/gateway leakage fails | denial events | E2E/security |
| MVP-AC-02 | Heavy Equipment shared account | explicit alias | account policy | mapping snapshot | any other account denied | policy event | policy/E2E |
| MVP-AC-03 | non-PPN + PT PPN | explicit preview | financial policy | ERP draft | wrong issuer/tax/ledger/account denied | policy event | matrix/E2E |
| MVP-AC-04 | missing/ambiguous data | targeted error | preview contract | zero provider writes | no number/post | rejection event | transcript/assertion |
| MVP-AC-05 | one mutation under retry | recovery UX | fenced mutation | intent/audit/ERP | race/crash/lost response | recovery terminals | concurrency/integration |
| MVP-AC-06 | unauthorized actions denied | generic denial | authz | zero protected access | no disclosure/mutation | denial event | negative E2E |
| MVP-AC-07 | number/PDF after post | review result | adapter | ERP/readback | draft cannot claim official | post/readback | provider E2E |
| MVP-AC-08 | evidence + AR | payment UX | payment contract | ERP AR | overpay/duplicate/wrong account | payment events | money/E2E |
| MVP-AC-09 | durable audit/redaction | safe status | audit contract | append-only/reconcile | storage/terminal failure | integrity/orphan alerts | durability/security |
| MVP-AC-10 | backup/restore | operator report | health/export | isolated restore | corrupt/inconsistent/undecryptable fails | restore event | drill |
| MVP-AC-11 | responsive/a11y/recovery | full UX states | UI contracts | state persistence | overflow/focus/state gaps fail | UI outcomes | browser/independent review |
| MVP-AC-12 | assumption report + production block | readiness status | gate contract | production state | no expert sign-off cannot approve | readiness event | report/validator |
| MVP-AC-13 | distinct unit branding | branding/PDF preview | template/config snapshot | ERP PDF/private asset | spoof/unsafe placeholder/historical rewrite fails | branding events | PDF/visual/E2E |
| MVP-AC-14 | multi-unit assignment/context | assigned-unit selector/chat | authz/context contract | scoped CRM/draft | unassigned/stale/revoked/leak fails | context events | browser/chat/security E2E |
| MVP-AC-15 | settings without hardcode | typed settings lifecycle | config schema/API | versioned ERP/app config | unknown/script/ref/conflict/rollback/source-branch fails | config events | config/source-diff E2E |

## 3. RBAC negative matrix

Mandatory denials:

- unknown actor/chat;
- Banyumedia sales reading Pr1me/Contractor leads/customer/pricing;
- unit sales posting, delivering, voiding, or marking paid;
- requester changing issuer/PPN/account;
- non-PT role posting PT PPN document;
- Heavy Equipment selecting an unapproved account;
- any user submitting payment without evidence/reference;
- deactivated assignment;
- direct adapter invocation without authorization context.
- multi-unit actor reading/writing without exactly one active assigned unit;
- selecting inactive/unassigned unit, reusing a stale preview after switch, or accessing after assignment revocation;
- ordinary user editing unit settings or protected finance mappings;
- template/config attempting to override issuer/tax/ledger/account or execute arbitrary code.

Every denial verifies status/error contract, zero provider mutation, zero protected-data disclosure, and redacted audit event.

## 4. Idempotency and failure matrix

- Same idempotency key/same payload concurrently → one mutation, same result.
- Same key/different payload → conflict, zero new mutation.
- Failure before provider call → `FAILED_NO_MUTATION`, safe retry policy.
- Timeout during provider call → `RECOVERY_REQUIRED`, no blind retry.
- Provider succeeds, local outcome write fails → reconciliation path finds existing record.
- ERP succeeds, Telegram delivery fails → document remains posted; delivery retries independently.
- Process restart during pending/uncertain state → durable recovery continues.

## 5. Financial invariants

- Decimal arithmetic and explicit currency.
- Line/subtotal/tax/total reconcile to ERP output.
- Due date semantics valid.
- Posted identity fields immutable except supported amendment/reversal.
- Partial payments sum to open amount; overpayment behavior explicitly configured/tested.
- Cancel/reversal preserves audit and ledger balance.
- PT TKH/PPN path uses qualified policy and approved PT account.

## 6. UX/a11y evidence

- Compact 360–430px and wide 1280px+ screenshots with synthetic data.
- No horizontal page overflow.
- Keyboard path and visible focus for review/post confirmation/payment evidence.
- Accessible names, labels, error association, text/icon status beyond color.
- Loading/empty/denied/stale/uncertain/delivery-failed/success states.
- Reduced-motion behavior where motion exists.
- Independent reviewer verdict.
- Assigned-unit selector at 0/1/multiple assignments, keyboard/focus, switch confirmation, stale/revoked context, compact/wide.
- Unit settings draft/validate/preview/activate/rollback, read-only/denied, invalid reference, version conflict, and safe branding preview.

## 6A. Unit configuration and no-hardcode proof

- Schema/property tests cover every registered setting type, constraint, default, sensitivity class, and compatibility validator.
- Unknown key, wrong type, unsafe template placeholder, arbitrary script/expression, dangling reference, incompatible issuer/tax/ledger/account, and overlapping effective version are rejected.
- Concurrent edits use monotonic `expected_version` CAS; stale activation fails as `CONFIG_VERSION_CONFLICT` without partial configuration.
- Race tests cover activate-vs-activate, activate-vs-rollback, rollback-vs-rollback, and overlapping effective intervals. Exactly one valid winner commits activation/retirement/snapshot/audit atomically; losers leave zero active/config/audit-success partial state.
- Activation invalidates affected draft previews/caches and preserves audit/before-after/effective date.
- Rollback restores a verified prior configuration as a new audited event and never changes historical posted snapshots.
- Add Balonesia plus a synthetic new unit using fixtures/settings only; automated source scan and reviewed diff reject unit-code/name conditionals outside seed/config/evidence paths and reject upstream ERP core modifications.
- Render two synthetic unit PDFs with distinct assets/templates; verify legal issuer/tax/series/ledger/account come from policy, not template payload.

## 7. Performance/reliability

Measure p50/p95 for scoped reads, preview, posting, and reports using pilot volumes. Initial product targets are provisional: ordinary read <3s and document action <10s excluding external messaging latency. Fail if retries cause duplicates or requests hide partial/uncertain outcomes.

## 8. Backup/restore proof

- Backup inventory includes DB, private files, config/custom app, and audit state.
- Hash and size recorded without secrets.
- Restore into separate target.
- Verify schema/version, record counts, sample PDFs/evidence, permissions, unit/account mappings, and synthetic balances.
- Document elapsed time; choose production RPO/RTO later.

## 9. Product evaluation rubric

Score ERPNext and optional ERPClaw on:

- accounting correctness and reversal;
- multi-unit/legal issuer/tax/account fit;
- permission isolation;
- API/action stability;
- audit/idempotency/recovery;
- Indonesian localization burden;
- backup/export/restore;
- UI/chat integration effort;
- maintainership/security/supply chain;
- upgrade/customization burden.

A conversational demo does not compensate for failed ledger, permission, or recovery evidence.

## 10. Required commands (to become exact after stack selection)

The plan gate must not invent unavailable test commands. Once source/tooling is selected, replace these categories with repository-exact commands:

- format/lint/type check;
- unit and contract tests;
- integration test against isolated ERP;
- browser/E2E tests;
- dependency/secret/security scans;
- backup/restore drill;
- configuration and plan validators.

Until then, documentation checks and plan validator are the only executable gates.
