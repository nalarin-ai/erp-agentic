"""Durable SQLite-backed mutation claim store (R-007/R-008).

Single-writer WAL SQLite is the durability fixture for the claim contract:
atomic CAS in one transaction, monotonic fencing per key, payload-hash and
canonicalization-version binding, and unique provider external reference.
All data is synthetic; no live financial state is stored here.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.mutations.claim_store import ClaimResult, ClaimStatus
from src.mutations.lease import MutationLease
from src.mutations.store import MutationOutcome, MutationStatus, StorageFullError

_MIGRATION = (
    Path(__file__).resolve().parent.parent.parent
    / "db" / "migrations" / "mutation_audit" / "0001_mutation_audit.sql"
)


class DurableMutationStore:
    """Durable claim store; one instance per connection."""

    def __init__(self, db_path: Path | str, *, capacity: int = 100_000) -> None:
        self._path = str(db_path)
        self._capacity = capacity
        self._conn = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_MIGRATION.read_text(encoding="utf-8"))

    def close(self) -> None:
        self._conn.close()

    # -- read API ---------------------------------------------------------

    def get(self, key: str) -> MutationOutcome | None:
        row = self._conn.execute(
            "SELECT key, status, payload_hash, external_reference, result_json"
            " FROM mutation_outcome WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return MutationOutcome(
            key=row[0],
            status=MutationStatus(row[1]),
            payload_hash=row[2],
            external_reference=row[3],
            result=row[4],
        )

    def current_fencing_token(self, key: str) -> int:
        row = self._conn.execute(
            "SELECT fencing_token FROM mutation_outcome WHERE key = ?", (key,)
        ).fetchone()
        return int(row[0]) if row else 0

    # -- claim ------------------------------------------------------------

    def claim(
        self,
        key: str,
        payload_hash: str,
        canonicalization_version: int,
        lease: MutationLease,
        presented_fencing_token: int,
        at: datetime,
    ) -> ClaimResult:
        """Transactional CAS claim with fencing, expiry, and takeover.

        Semantics:
        - presented token must equal lease.fencing_token and be unexpired;
        - existing row, same payload+version:
            * terminal status            -> ALREADY_RESOLVED (no state change);
            * non-terminal, same token   -> CLAIM_HELD (idempotent re-claim);
            * non-terminal, newer token and stored lease expired
                                         -> transactional takeover (ACQUIRED),
                                            fencing/lease columns updated;
            * otherwise                  -> STALE_FENCING rejection;
        - existing row, different payload/version -> PAYLOAD_CONFLICT;
        - absent row -> INSERT PENDING, ACQUIRED.
        """
        # Fencing/expiry checks run first and fail closed before any write.
        lease.assert_fresh(presented_fencing_token, at)

        now_iso = at.isoformat()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT payload_hash, canonicalization_version, fencing_token,"
                "       status, external_reference, result_json, lease_expires_at"
                " FROM mutation_outcome WHERE key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                (
                    stored_hash, stored_version, stored_token,
                    status, ext_ref, result, lease_expires_iso,
                ) = row
                if stored_hash != payload_hash or stored_version != canonicalization_version:
                    self._conn.execute("ROLLBACK")
                    return ClaimResult(status=ClaimStatus.PAYLOAD_CONFLICT)
                outcome = MutationOutcome(
                    key=key,
                    status=MutationStatus(status),
                    payload_hash=stored_hash,
                    external_reference=ext_ref,
                    result=result,
                )
                terminal = outcome.status in (
                    MutationStatus.RESOLVED_PRESENT,
                    MutationStatus.RESOLVED_ABSENT,
                    MutationStatus.FAILED_NO_MUTATION,
                )
                if terminal:
                    self._conn.execute("COMMIT")
                    return ClaimResult(status=ClaimStatus.ALREADY_RESOLVED, outcome=outcome)

                # Non-terminal row: fencing semantics apply.
                if presented_fencing_token < stored_token:
                    self._conn.execute("ROLLBACK")
                    return ClaimResult(status=ClaimStatus.STALE_FENCING, outcome=outcome)
                if presented_fencing_token == stored_token:
                    # Idempotent re-claim by the current owner.
                    self._conn.execute("COMMIT")
                    return ClaimResult(status=ClaimStatus.CLAIM_HELD, outcome=outcome)

                # Newer token: takeover only once the stored lease has expired.
                stored_expiry = datetime.fromisoformat(lease_expires_iso)
                if at < stored_expiry:
                    self._conn.execute("ROLLBACK")
                    return ClaimResult(status=ClaimStatus.STALE_FENCING, outcome=outcome)
                self._conn.execute(
                    "UPDATE mutation_outcome SET fencing_token = ?, lease_expires_at = ?,"
                    " updated_at = ? WHERE key = ? AND fencing_token = ?",
                    (
                        presented_fencing_token,
                        lease.expires_at.isoformat(),
                        now_iso,
                        key,
                        stored_token,
                    ),
                )
                self._conn.execute("COMMIT")
                return ClaimResult(status=ClaimStatus.ACQUIRED, outcome=outcome)

            count = self._conn.execute("SELECT COUNT(*) FROM mutation_outcome").fetchone()[0]
            if count >= self._capacity:
                self._conn.execute("ROLLBACK")
                raise StorageFullError("durable mutation store is full")

            self._conn.execute(
                "INSERT INTO mutation_outcome (key, status, payload_hash,"
                " canonicalization_version, fencing_token, lease_expires_at,"
                " external_reference, result_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
                (
                    key,
                    MutationStatus.PENDING.value,
                    payload_hash,
                    canonicalization_version,
                    lease.fencing_token,
                    lease.expires_at.isoformat(),
                    now_iso,
                    now_iso,
                ),
            )
            self._conn.execute("COMMIT")
        except StorageFullError:
            raise
        except sqlite3.IntegrityError:
            # Lost a claim race against another connection: re-read and treat
            # as existing claim (or conflict) rather than failing closed.
            self._conn.execute("ROLLBACK")
            existing = self.get(key)
            if existing is None:  # pragma: no cover - defensive
                raise
            if existing.payload_hash != payload_hash:
                return ClaimResult(status=ClaimStatus.PAYLOAD_CONFLICT)
            return ClaimResult(status=ClaimStatus.CLAIM_HELD, outcome=existing)
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        outcome = MutationOutcome(key, MutationStatus.PENDING, payload_hash, None, created=True)
        return ClaimResult(status=ClaimStatus.ACQUIRED, outcome=outcome)

    def register_fencing(self, key: str, fencing_token: int) -> None:
        """Compatibility with the in-memory fixture's fencing registry.

        The durable store binds fencing into the claim row transactionally,
        so this is intentionally a no-op; `current_fencing_token` reads the
        authoritative value from the row.
        """

    def __len__(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM mutation_outcome").fetchone()[0])
