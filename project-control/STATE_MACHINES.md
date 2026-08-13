# Financial and Workflow State Machines

- Status: `NORMATIVE_DRAFT`
- Principle: posting, delivery, receivable/payment, and recovery are orthogonal dimensions.

## Commercial document state

### `posting_status`
`DRAFT → PENDING_REVIEW → REVIEWED → POSTING → POSTED`

Alternative terminal paths:

- `DRAFT|PENDING_REVIEW → ABANDONED`
- `POSTED → CANCELLATION_PENDING → CANCELLED`
- `POSTED → AMENDMENT_REQUIRED` followed by supported correction/reversal and replacement

Forbidden: editing issuer, tax, series, ledger, destination account, customer, currency, or totals in place after `POSTED`.

### `delivery_status`
`NOT_READY → READY → QUEUED → SENT`

Failure paths: `QUEUED → FAILED_RETRYABLE → QUEUED`; terminal policy failure → `FAILED_TERMINAL`. Delivery state never changes posting state.

### `receivable_status`
`NOT_APPLICABLE|OPEN → PARTIALLY_PAID → PAID`

Supported reversal may move `PAID/PARTIALLY_PAID` to a recomputed open state through compensating ERP records; never direct status overwrite.

### `recovery_status`
`NONE → RECOVERY_REQUIRED → RECONCILING → RESOLVED_PRESENT|RESOLVED_ABSENT|MANUAL_ESCALATION`

A document can simultaneously be `POSTED + DELIVERY_FAILED_RETRYABLE + PARTIALLY_PAID + NONE`.

## Transition guards

| Transition | Required guard | Persistence/audit | Failure behavior |
|---|---|---|---|
| Draft→Pending review | complete required fields and policy preview | draft version + action hash | preserve draft and field errors |
| Review→Posting | authorized reviewer, fresh action hash, durable mutation intent | CAS claim + audit precondition | zero provider writes if durability fails |
| Posting→Posted | ERP ID plus read-back invariants | terminal audit in same local transaction where possible | otherwise recovery required |
| Ready→Queued delivery | separate delivery permission and destination authorization | outbox event | posting remains posted |
| Open→Partial/Paid | payment evidence/reference and account validation | ERP payment + verified open amount | uncertain state reconciled |
| Posted→Cancelled | supported ERP cancel/reversal permission and reason | immutable before/after + ledger check | never hard delete |

## Concurrency rules

- Material draft change increments version and invalidates previous preview.
- Posting claim uses compare-and-set and fencing token.
- Payment/reversal operations use distinct idempotency namespaces.
- Delivery outbox is independently idempotent.
- Receivable state is computed/read back from accepted payment/reversal records, not trusted from chat.

## Required state tests

- Every allowed and forbidden transition.
- Stale preview and simultaneous post attempts.
- Posted + failed delivery + partial payment coexistence.
- Cancel/reversal while delivery/payment jobs are pending.
- Crash before intent, after intent, during provider call, after provider success, and before terminal audit.
