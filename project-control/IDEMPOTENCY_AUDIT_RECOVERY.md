# Idempotency, Audit, and Reconciliation Contract

- Status: `NORMATIVE_DRAFT`

## Idempotency namespace

Unique identity:

```text
(schema/canonicalization version,
 operating unit or accounting tenant,
 action class,
 source platform,
 source external reference)
```

The canonical payload hash includes all material financial identity fields. Same key + same hash returns/reconciles the existing result. Same key + different hash is `IDEMPOTENCY_CONFLICT` without provider write. Actor changes do not create a new financial action; authorization is re-evaluated before existing-result disclosure.

## Durable claim and fencing

- Claim is a transactional compare-and-set in durable persistence.
- Claim records owner, monotonic fencing token, acquired/heartbeat/expiry timestamps, canonicalization version, and payload hash.
- A stale worker cannot finalize or invoke a new provider operation after a newer fencing token owns recovery.
- Lease expiry permits reconciliation takeover, not blind mutation replay.
- ERP external reference is unique where the provider permits; otherwise adapter must prove equivalent deduplication or the candidate fails the hard gate.

## Crash boundaries

1. Before durable intent: no provider call.
2. After intent/before provider: safe to classify absent; retry only under owned fencing token.
3. Provider request sent/outcome unavailable: `RECOVERY_REQUIRED`; query provider by external reference.
4. Provider success/local terminal write failure: recovery discovers provider record and writes verified terminal outcome.
5. Provider absent after authoritative query: safe reissue only under new fenced recovery attempt and same external reference.
6. Multiple/ambiguous provider matches: manual escalation; no reissue.

## Audit durability and integrity

- Mutation fails closed before provider call if durable intent/audit precondition cannot commit.
- Intent, claim, and precondition audit use one local transaction.
- Terminal outcome/read-back audit commits atomically with local terminal state where possible.
- Post-provider local failure enters detectable recovery; success is never claimed from provider response alone.
- Append-only writer permissions; normal app cannot update/delete audit rows.
- Events include previous-event hash/checkpoint or equivalent integrity control, periodic signed/checksummed export, retention, and off-host backup.
- Alert on storage pressure, failed audit write, orphan ERP external reference, stale recovery lease, and reconciliation SLA breach.

## Reconciliation engine

A durable worker/operator command:

1. claims recovery item with fencing;
2. looks up ERP by external reference and immutable attributes;
3. classifies `PRESENT_VALID`, `ABSENT_PROVEN`, `AMBIGUOUS`, or `PROVIDER_UNAVAILABLE`;
4. verifies issuer/unit/currency/total/account/ledger and provider state;
5. finalizes existing result, safely reissues only after proven absence, or escalates;
6. appends terminal audit and exposes operator-safe queue/status;
7. resumes after restart without duplicate action.

Live writes require this engine, operator runbook, alert/SLA, and tested crash matrix.

## Required tests

- Simultaneous claims across processes and reconnects.
- Same key/hash, same key/different hash, different actor, stale worker.
- Crash at every boundary.
- Provider success/lost response.
- Lease expiry/takeover and fencing rejection.
- ERP external-reference collision.
- Audit storage full/precondition failure/terminal failure.
- Reconciliation present/absent/ambiguous/unavailable.
- ERP↔audit orphan reconciliation report.
