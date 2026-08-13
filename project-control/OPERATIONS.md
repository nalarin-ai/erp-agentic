# Operations, Backup, and Recovery Plan

- Status: `DRAFT`
- Production values such as RPO/RTO, hosts, domains, and backup target remain open.

## Environments

- `fixture`: network-disabled provider simulation.
- `erp-pilot`: isolated synthetic ERPNext.
- `erpclaw-comparator`: optional, separate synthetic environment.
- `staging`: later, sanitized/rehearsal data.
- `production`: prohibited until readiness decision.

Environment credentials are unique and entered locally. Never copy active FULL_AUTO records, sessions, memory, or channel credentials between nodes.

## Health model

Report separately:

- application/gateway process;
- persistence/database;
- ERP API/auth/permission;
- audit/idempotency persistence;
- outbox/channel delivery;
- document storage;
- backup freshness and last restore proof.

A green channel connection does not prove ERP mutation or delivery success.

## Backup inventory

- ERP database.
- ERP private/public files as required.
- custom app/integration source and pinned configuration.
- policy/config masters excluding secret values from repository.
- integration audit/idempotency/recovery state.
- runbooks and version manifest.

## Backup controls

- one backup-set manifest binds database, private files, integration audit/idempotency state, outbox, policy/configuration revision, custom app revision, ERP version, and consistency timestamp;
- application-aware quiesce/consistent dump or a documented point-in-time recovery mechanism; independent file/database copies without a consistency point do not count;
- encryption and restricted access, with recoverable key escrow/rotation and separation of duties; the backup host must not be the sole holder of its decryption key;
- checksums, immutable/off-host copy, retention, expiry, and verified deletion procedure;
- monitoring for completion, size anomalies, and age;
- no secret values in delivered reports.

## Restore drill

1. Provision a separate isolated target.
2. Verify backup-set manifest, checksum, decryption/key recovery, and version compatibility.
3. Restore DB/files/config/audit/outbox state and re-provision environment-specific secrets instead of restoring live channel credentials.
4. Start services on an isolated identity/network that cannot send customer messages or mutate production.
5. Verify schema/version, cross-store consistency point, record counts, sample PDFs/evidence, roles, unit/ledger/account policies, balances, outbox, idempotency/recovery records.
6. Record duration, issues, and exact evidence.
7. Destroy test target safely after evidence retention.

## Incident/recovery cases

- ERP unavailable before mutation.
- Timeout/connection loss during mutation.
- ERP success but audit outcome write failure.
- Invoice posted but Telegram delivery failed.
- Wrong configuration detected before post.
- Incorrect posted invoice requiring supported cancel/reversal.
- Credential compromise/revocation.
- Corrupted/failed backup.
- Complete loss of the primary host and local keys.
- Unauthorized access attempt/cross-unit disclosure.

Each runbook must define detect, contain, verify state, recover, communicate, and prevent recurrence.

## Update and rollback

Pin versions, read release/migration notes, back up and restore-test, deploy to pilot/staging, run contract/E2E/security checks, then promote. Keep a tested rollback/restore path. Never auto-update production ERP or database without compatibility proof.

## Production readiness evidence

- Qualified finance/tax configuration review.
- Access review and negative authorization matrix.
- Backup and independent restore proof.
- Idempotency/recovery drill.
- Monitoring/alert delivery proof.
- Capacity/performance measurement.
- User training and support/incident ownership.
- Explicit go/no-go record.
