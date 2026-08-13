# RBAC and Business Policy Specification

- Status: `DRAFT`
- Security posture: default deny; role + unit scope + action + legal/tax/account policy all required.

## 1. Authorization decision

An action is allowed only when all are true:

```text
verified actor
AND active channel mapping
AND unit scope
AND effective actor-unit assignment
AND exactly one active unit context for the action
AND role permission
AND record visibility
AND action-specific policy
AND legal issuer/tax/account compatibility
AND required workflow state
```

The LLM may propose intent/fields but cannot grant authorization.

## 2. Permission matrix (initial)

Legend: `Y` allowed within assigned scope; `C` conditional workflow/threshold; `N` denied.

| Action | Unit Sales | Unit Ops | Finance Requester | Finance Reviewer | PT Tax/Finance | Owner |
|---|---:|---:|---:|---:|---:|---:|
| View own-unit leads | Y | C | C | Y | C | Y |
| View other-unit leads/details | N | N | N | C | N | Y |
| Create/update lead | Y | C | N | C | N | Y |
| Create quotation draft | Y | C | Y | Y | C | Y |
| Create invoice draft | C | N | Y | Y | Y | Y |
| Change legal issuer/tax/account | N | N | N | C | Y for PT scope | Y |
| Approve/post invoice | N | N | N | C | C | Y |
| Deliver invoice externally | N | N | N | C | C | Y |
| Record payment draft | N | N | Y | Y | Y | Y |
| Confirm/submit payment | N | N | N | C | C | Y |
| Void/reverse posted record | N | N | N | C | C | Y |
| View unit financial report | N/C | C | C | Y | PT scope | Y |
| Configure unit/role/account policy | N | N | N | N | C for PT | Y/admin |
| Export/backup/restore | N | N | N | N | N/C | Y/admin |

Final thresholds and role assignments remain open; this table is a safe baseline, not production authorization.

## 3. Sales isolation policy

- Unit sales users see only assigned unit/sales scope.
- Cross-unit search never returns protected customer, price, owner, amount, or contact details.
- Duplicate/conflict detection may return `POTENTIAL_CONFLICT_REQUIRES_CONTROLLER`.
- Owner/controller may resolve ownership and record transfer with reason/audit.
- Finance cross-unit visibility is granted only where reconciliation requires it.
- Shared office membership does not grant shared CRM visibility.
- A user/sales actor may hold assignments to multiple units, but authorization is evaluated against exactly one selected active unit per request.
- Unit selectors return only currently assigned active units; they never reveal hidden units or record counts.
- If a multi-unit actor has no unambiguous active context, reads and writes stop at `UNIT_CONTEXT_REQUIRED`.
- Switching unit clears unit-scoped caches/results and invalidates any draft preview/action hash created under the previous unit.
- Revoked/expired assignments deny subsequent access immediately; historical audit attribution remains intact.

## 3A. Branding and template policy

- Logo and document template are selected from the transaction unit's active versioned branding profile.
- Branding configuration is separate from legal issuer, tax profile, invoice series, receivable ledger, and destination account policy.
- Template placeholders are allowlisted; a template cannot inject or override protected financial identity values.
- Branding changes require authorized configuration role, preview, effective date, audit event, and rollback to a prior version.
- Posted PDFs retain the branding snapshot reviewed at posting; later branding changes do not rewrite historical documents.

## 4. Issuer/PPN/account policy

- PT TKH PPN documents require PT TKH issuer, qualified tax profile, PT invoice series, and approved PT account.
- Unit default accounts cannot override issuer compatibility.
- Heavy Equipment is explicitly allowed to use Contractor default account for compatible non-PT path.
- Any override requires an authorized role, selected allowed value, reason, policy version, and audit evidence.
- Unknown tax/issuer state returns `BLOCKED_CONFIGURATION`, not a guessed answer.

## 5. Workflow separation

```text
DRAFTED -> REVIEWED -> POSTED -> DELIVERED
                        |
                        +-> PARTIALLY_PAID -> PAID
                        +-> CANCELLED/REVERSED (supported process)
```

The same actor should not create and finalize sensitive transactions above a configured threshold. Exact thresholds remain O-003/O-004.

## 6. Chat safety

- A group mapping supplies context, not blanket authority.
- Each sender is individually verified and authorized.
- Replies redact fields inappropriate for the source chat.
- Forwarded messages, quoted approvals from another channel, and ambiguous identity are not authority.
- Credentials, OTP/PIN, full account/card details, taxpayer secrets, and banking access are never requested in chat.

## 7. Negative authorization acceptance tests

- Banyumedia sales cannot list/read Pr1me or Contractor leads.
- Heavy Equipment user cannot change shared account mapping.
- Unit requester cannot force PT TKH issuer via prompt.
- Non-PT finance cannot post PT PPN invoice without PT role/workflow.
- Unknown group/user cannot discover whether an invoice/customer exists.
- Draft permission does not imply post, deliver, void, or mark-paid.
- Owner roll-up does not mutate underlying legal ledgers.
- Deactivated assignment denies immediately while preserving audit.
- Multi-unit user cannot query two unit pipelines in one ordinary sales request or reuse a stale preview after switching unit.
- User cannot select an unassigned/inactive unit, and a unit logo/template cannot be used to spoof another legal issuer or account.

## 8. Configuration governance

Role, channel, issuer, tax, account, numbering, and threshold changes are versioned configuration events. Every change has actor, reason, effective date, before/after descriptor, test/preview, and rollback path. Real account identifiers remain in restricted ERP/secret configuration, never planning files.

- Each unit configuration is validated against an allowlisted typed schema; unknown keys and arbitrary scripts are denied.
- Ordinary sales/users may read only the safe effective settings needed for their assigned active unit; they cannot edit policy or see protected references.
- Unit administrators may prepare drafts only within delegated fields; activation of financial identity, issuer/tax/ledger/account, numbering, or approval-policy changes requires the designated controller/finance authority.
- Configuration activation invalidates affected caches/previews and emits a versioned audit event. Historical posted documents retain their configuration and branding snapshots.
- Rollback creates a new audited active version or restores a verified prior version; it never silently rewrites history.
- Validate/activate/rollback commands require the latest `expected_version`. CAS plus an active-effective-interval exclusion constraint allows one winner; activation/retirement/snapshot/audit commit atomically. A loser receives `CONFIG_VERSION_CONFLICT` and no setting, active marker, cache invalidation, or audit-success partial effect.
