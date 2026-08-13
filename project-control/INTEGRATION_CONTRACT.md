# Hermes–ERP Integration Contract

- Status: `DRAFT`
- Boundary: conversational interpretation is untrusted until deterministic validation.

## Command envelope

```json
{
  "schema_version": 1,
  "correlation_id": "uuid",
  "idempotency_key": "opaque-stable-key",
  "actor_ref": "opaque-actor",
  "channel_ref": "opaque-chat",
  "action": "INVOICE_PREVIEW|INVOICE_POST|PAYMENT_RECORD|QUERY_RECEIVABLE",
  "operating_unit": "unit-code",
  "payload": {},
  "requested_at": "UTC timestamp"
}
```

No credential, full account number, taxpayer secret, or unrestricted raw chat transcript belongs in the envelope.

## Processing contract

1. Validate schema/version/size.
2. Resolve verified actor and chat mapping.
3. Authorize action and record scope.
4. Resolve/validate unit, issuer, tax, series, and account policy.
5. Canonicalize payload and bind idempotency/action hash.
6. For preview/dry-run, return before→after intent and perform zero ERP mutations.
7. For mutation, durably claim intent and append precondition audit.
8. Invoke least-privilege ERP adapter.
9. Read result back using immutable provider reference.
10. Persist terminal or `RECOVERY_REQUIRED` outcome.
11. Return redacted result; enqueue channel delivery separately.

## Error contract

| Code | Meaning | Provider mutation |
|---|---|---|
| `INVALID_INPUT` | Missing/invalid field | none |
| `IDENTITY_UNVERIFIED` | Actor/chat unknown | none |
| `PERMISSION_DENIED` | Action/scope denied | none; no protected data disclosure |
| `POLICY_UNRESOLVED` | Issuer/tax/account cannot be determined | none |
| `STALE_PREVIEW` | Material data/policy changed | none |
| `IDEMPOTENCY_CONFLICT` | Same key, different canonical payload | none |
| `PROVIDER_REJECTED` | ERP rejected before known mutation | none/verified none |
| `RECOVERY_REQUIRED` | Provider outcome uncertain | do not retry blindly |
| `DELIVERY_FAILED` | ERP succeeded, channel delivery failed | ERP result remains valid; retry delivery |

## Preview response

Returns action hash/version, expiry, normalized fields, safe totals, unit, issuer, PPN state, invoice series category, and masked/alias account. It never reserves or invents an official invoice number unless the ERP's documented preview mechanism does so safely.

## Mutation response

`SUCCEEDED` requires provider record ID, read-back verification, audit outcome, and reconciliation descriptor. A worker exit code or agent statement is not success evidence.

## Query contract

Every filter is intersected with server-derived scope. Client/channel-supplied unit IDs never expand authorization. Counts/search/error behavior must avoid cross-unit side channels where practical.

## Versioning

- Additive fields are optional with explicit defaults.
- Breaking changes require a new schema version and compatibility tests.
- Policy/config version is recorded per action.
- ERP adapter revision/version is evidence metadata.
