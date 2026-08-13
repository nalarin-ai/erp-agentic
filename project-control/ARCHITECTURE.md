# Architecture — ERP Kreasi Hebat

- Status: `DRAFT`
- Scope: logical architecture and product boundaries; no deployment authorization.

## 1. Architectural principles

1. ERP owns business records; Hermes owns conversation/orchestration.
2. Operating unit, legal issuer, tax profile, ledger, and bank account are separate.
3. Authorization is enforced server-side, never by prompt wording alone.
4. Financial mutations pass through a deterministic adapter with dry-run/preview, idempotency, audit, and read-after-write verification.
5. Configure/extend upstream before forking ERP core.
6. Start with one vertical slice; add specialist systems only after core evidence.
7. Unit variability is typed, versioned data/configuration; unit-code/name conditionals in business logic are prohibited.

## 2. Logical topology

```text
Telegram/WhatsApp groups
        |
        v
Hermes Executor (intent, dialogue, policy preflight)
        |
        v
ERP Integration Gateway
  - identity/chat mapping
  - multi-unit assignment + one active unit context/RBAC
  - unit configuration registry/resolver
  - branding/template resolver
  - issuer/tax/account policy
  - idempotency + audit
  - preview/dry-run
        |
        v
ERP System of Record (candidate: ERPNext/Frappe)
  - CRM/Sales
  - accounting/AR
  - projects/assets/rental configuration
  - documents/workflow
  - role permissions/audit
        |
        +--> controlled document storage
        +--> backup/export/restore
        +--> later specialist connectors
```

## 3. Component boundaries

### A. Channel adapter
Receives normalized message identity and source chat. It never decides legal issuer, tax, or account. It returns safe, role-scoped summaries.

### B. Identity and scope resolver
Maps opaque Telegram/WhatsApp user/chat identifiers to user, effective many-to-many unit assignments, exactly one active unit context, roles, and allowed actions. Unknown, unassigned, inactive, stale, or conflicting mappings fail closed. Switching unit invalidates scoped caches and previews.

### B1. Unit configuration registry and resolver
Stores allowlisted typed setting definitions and versioned per-unit values. The resolver accepts `unit + action/document type + effective instant`, validates references and compatibility, and returns one immutable configuration snapshot or a fail-closed error. It never executes configuration as code, silently guesses financial mappings, or falls back across units. Draft/validate/preview/activate/rollback are authorized and audited lifecycle operations. Activation/rollback require an `expected_version` CAS; one transaction validates and changes active-version state, binds the snapshot, and appends audit. A database exclusion/unique constraint prevents overlapping active effective intervals. CAS losers receive deterministic `CONFIG_VERSION_CONFLICT` with zero partial state.

### B2. Branding/template resolver
Selects the active unit branding profile and managed logo/template references, binds them to the commercial-document snapshot, and supplies only allowlisted presentation fields to rendering. Legal issuer, tax, series, ledger, account, and totals come from authoritative policy/ERP data and cannot be overridden by template input.

### C. Conversation workflow
Collects missing fields, explains validation errors, presents preview, and requests the next allowed action. It cannot call the ERP directly.

### D. Policy engine
Deterministically validates:

- unit membership;
- sales visibility;
- legal issuer eligibility;
- PPN/tax profile;
- invoice series;
- account allowlist and issuer compatibility;
- action permission and approval threshold.

Policy versions are audit-referenced. No LLM-generated tax decision is authoritative.

### E. Mutation gateway
The only application boundary allowed to create/update ERP records. Contract:

1. canonicalize request;
2. authorize actor/scope;
3. validate policy and required fields;
4. compute idempotency key/action hash;
5. produce preview/dry-run with zero provider writes;
6. persist intent/audit precondition;
7. call ERP API once;
8. read created/updated record back;
9. persist outcome or explicit recovery state;
10. return a redacted result.

### F. Query/report gateway
Applies the same scope rules to reads. Cross-unit aggregation requires an explicit role; it never merges ledgers.

### G. ERP adapter
Versioned API wrapper around the selected ERP. Direct database writes are prohibited. ERP-specific doctypes/models stay behind typed local contracts.

### H. Audit/evidence store
Stores correlation, action, scope, policy version, redacted before/after descriptors, idempotency, provider record ID, outcome, and verification. It must not store secrets or full banking identifiers.

### I. Document storage
Stores invoice PDFs and payment evidence under role-controlled references, retention policy, checksums, and malware/content limits as appropriate.

### J. Specialist connectors
Uptime/SEO/analytics/social integrations are separate bounded adapters. Their data may appear in reports but does not mutate accounting without an explicit ERP workflow.

## 4. Candidate deployment decision

### Recommended pilot baseline

- ERPNext/Frappe self-hosted in an isolated local container/VM.
- MariaDB-compatible database according to supported upstream version.
- ERP integration service as a separate small application/package, not an ERP core fork.
- Tailscale/private access first; public Cloudflare exposure only after explicit security design and evidence.
- Synthetic entities/documents only.

### ERPClaw comparator

Run only in a separate isolated environment with synthetic data. Compare:

- accounting invariants and reversals;
- API/action permissions;
- multi-unit/legal-issuer behavior;
- audit trail and idempotency;
- backup/export/restore;
- Hermes integration surface;
- Indonesian localization effort;
- maintenance/supply-chain risk.

It cannot become official ledger merely because conversational UX is better.

## 5. Multi-unit and legal-issuer design

```text
OperatingUnit --< UnitMembership >-- User
OperatingUnit --< UnitConfigurationProfile
OperatingUnit --< UnitBrandingProfile
OperatingUnit --< SalesScope
OperatingUnit --< UnitIssuerPolicy >-- LegalIssuer
LegalIssuer  --< TaxProfile
LegalIssuer  --< InvoiceSeries
OperatingUnit --< UnitAccountAllowlist >-- BankAccountAlias
LegalIssuer  --< IssuerAccountAllowlist >-- BankAccountAlias
CommercialDocument -> one OperatingUnit
CommercialDocument -> one LegalIssuer
CommercialDocument -> one TaxProfile
CommercialDocument -> one BankAccountAlias
CommercialDocument -> one SalesScope/owner
CommercialDocument -> one immutable UnitConfiguration/Branding snapshot
```

Both unit and issuer account allowlists must pass. For Heavy-equipment Rental, the unit allowlist includes the Contractor account. For PT TKH PPN documents, issuer policy restricts selection to approved PT accounts.

One user may have multiple effective `UnitMembership` records, but every query or mutation carries exactly one revalidated active unit. Adding or changing unit behavior uses supported ERPNext/Frappe configuration, print formats, workflows, roles, fixtures/custom DocTypes, or a bounded custom app—not upstream-core edits or per-unit branches scattered through business logic.

## 6. Security architecture

### Trust boundaries

- External chat/user input is untrusted.
- LLM interpretation is advisory until deterministic validation.
- ERP API is privileged and uses a least-privilege service account.
- ERP/web content and imported files are untrusted.
- Payment evidence may be sensitive and access-controlled.
- Subagent output is a claim until verified by the executor.

### Required controls

- Default-deny RBAC and unit scope.
- Separate requester/reviewer/post/deliver/void/mark-paid/admin privileges.
- Opaque secret references and local secret store.
- Structured redacted logs and correlation IDs.
- CSRF/session/security controls from supported platform.
- Rate limits and bounded retries.
- File type/size policy and controlled download.
- Backup encryption/access policy and restore drills.
- Dependency pinning/scanning and reviewed updates.

## 7. Reliability and consistency

- Monetary values use decimal and explicit currency; never binary floating point.
- Timestamps stored in UTC; user display uses configured Indonesian timezone.
- Idempotency uniqueness is enforced by persistence, not memory cache alone.
- Financial posting uses ERP-supported atomic semantics where available.
- Failure after remote mutation but before local outcome creates `RECOVERY_REQUIRED`; blind retry is prohibited until read-back/reconciliation.
- Outbound chat notification is separate from ERP commit and safely retryable.

## 8. Observability

Events include `request_received`, `scope_resolved`, `policy_denied`, `preview_created`, `mutation_started`, `mutation_succeeded`, `mutation_uncertain`, `readback_verified`, `delivery_succeeded/failed`, and `restore_drill`.

Each event has correlation ID, actor alias, unit, action class, record alias, result, latency, and redacted error descriptor. Health endpoints must distinguish app, database, ERP adapter, queue/job, and channel status without exposing secrets.

## 9. Backup and recovery

- Define RPO/RTO before production.
- Back up ERP database, private files/documents, configuration, custom app, and integration audit state.
- Keep at least one off-host copy when production begins.
- Restore to a separate environment and verify record counts, sample documents, permissions, and checksums.
- Recovery runbooks must cover partial mutation and channel-delivery failure.

## 10. Deployment stages

1. Documentation and policy baseline.
2. Isolated fixture/pilot environments.
3. Synthetic vertical slice.
4. Negative permission and recovery testing.
5. Product comparison decision.
6. Controlled configuration with qualified accounting/tax review.
7. Staged import rehearsal.
8. Private internal pilot.
9. Production readiness review.
10. Optional public/private dashboard hardening and specialist integrations.

## 11. Architecture decision records required later

- ADR: ERPNext vs ERPClaw/adopted core after pilot.
- ADR: single ERP site with companies/scopes vs multiple sites, after complete legal-entity list and permission proof.
- ADR: integration service technology after selected ERP/version and team maintenance constraints.
- ADR: document storage/retention and backup target.

## 12. Forbidden shortcuts

- Storing official business data in Hermes session/memory.
- Direct ERP database writes.
- Prompt-only authorization.
- Auto-selecting PT TKH/PPN/account from natural language without policy proof.
- Shared admin API credentials across all workflows.
- Hard-deleting posted financial records.
- Claiming backup readiness without restore evidence.
