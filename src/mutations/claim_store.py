"""Durable CAS claim protocol for mutation outcomes (R-007/R-008).

Defines the storage contract every durable implementation must satisfy:
monotonic fencing tokens, atomic compare-and-set, payload conflict
detection, and stale-writer rejection. In-memory fixture first; durable
SQLite implementation is added under TDD with a shared contract suite.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from src.mutations.lease import MutationLease


class ClaimStatus(StrEnum):
    ACQUIRED = "ACQUIRED"
    CLAIM_HELD = "CLAIM_HELD"  # idempotent re-claim of a non-terminal row by owner
    ALREADY_RESOLVED = "ALREADY_RESOLVED"
    PAYLOAD_CONFLICT = "PAYLOAD_CONFLICT"
    STALE_FENCING = "STALE_FENCING"
    LEASE_EXPIRED = "LEASE_EXPIRED"


@dataclass(frozen=True, slots=True)
class ClaimResult:
    status: ClaimStatus
    outcome: Any = None


@runtime_checkable
class MutationClaimStore(Protocol):
    """Durable, atomic claim store contract."""

    def claim(
        self,
        key: str,
        payload_hash: str,
        canonicalization_version: int,
        lease: MutationLease,
        presented_fencing_token: int,
        at: datetime,
    ) -> ClaimResult:
        """Atomically claim a mutation key.

        Must be a transactional compare-and-set:
        - rejects a presented fencing token that is not the current owner token;
        - rejects an expired lease;
        - returns the existing outcome unchanged when key + payload_hash match;
        - fails closed with PAYLOAD_CONFLICT when the key exists with a
          different payload hash or canonicalization version;
        - creates a PENDING outcome bound to the lease on first claim.
        """
        ...

    def get(self, key: str) -> Any:
        """Return the stored outcome for key, or None."""
        ...

    def current_fencing_token(self, key: str) -> int:
        """Return the highest fencing token ever issued for key (0 if none)."""
        ...
