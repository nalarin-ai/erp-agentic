-- FND-004 durable mutation outcome and audit event schema.
-- Synthetic fixtures only; no live data. SQLite dialect (single-writer WAL).
--
-- Invariants enforced here:
--   * one row per idempotency key (PK);
--   * payload_hash + canonicalization_version bound at claim time;
--   * monotonic fencing token per key (CHECK via trigger is overkill; the
--     store implementation enforces monotonicity transactionally);
--   * external_reference unique where present (provider dedup);
--   * audit_event is append-only (sequence PK, previous_hash chain column).

CREATE TABLE IF NOT EXISTS mutation_outcome (
    key                      TEXT PRIMARY KEY,
    status                   TEXT NOT NULL CHECK (status IN (
                                 'PENDING','FAILED_NO_MUTATION','UNCERTAIN',
                                 'RESOLVED_PRESENT','RESOLVED_ABSENT','CONFLICT')),
    payload_hash             TEXT NOT NULL,
    canonicalization_version INTEGER NOT NULL CHECK (canonicalization_version > 0),
    fencing_token            INTEGER NOT NULL CHECK (fencing_token > 0),
    lease_expires_at         TEXT NOT NULL,
    external_reference       TEXT,
    result_json              TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS mutation_outcome_external_ref
    ON mutation_outcome(external_reference)
    WHERE external_reference IS NOT NULL;

CREATE TABLE IF NOT EXISTS audit_event (
    sequence       INTEGER PRIMARY KEY CHECK (sequence > 0),
    previous_hash  TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    actor          TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    payload_json   TEXT NOT NULL,
    record_hash    TEXT NOT NULL
);
