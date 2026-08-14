"""In-memory mutation store for testing.

Implements R-007/R-008: CAS claim, payload conflict detection, external
reference uniqueness, storage-full simulation, and a monotonic fencing
registry. This is a test fixture; production uses durable storage.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import threading
from typing import Any


class MutationStatus(StrEnum):
    PENDING = "PENDING"
    FAILED_NO_MUTATION = "FAILED_NO_MUTATION"
    UNCERTAIN = "UNCERTAIN"
    RESOLVED_PRESENT = "RESOLVED_PRESENT"
    RESOLVED_ABSENT = "RESOLVED_ABSENT"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class MutationOutcome:
    key: str
    status: MutationStatus
    payload_hash: str
    external_reference: str | None
    result: Any = None
    created: bool = False  # True only on the freshly-created PENDING claim


class InMemoryMutationStore:
    """Thread-safe in-memory store for mutation outcomes (test fixture)."""

    def __init__(self, capacity: int = 1000) -> None:
        self._data: dict[str, MutationOutcome] = {}
        self._external_refs: dict[str, str] = {}  # external_ref -> key
        self._fencing: dict[str, int] = {}  # key -> highest fencing token
        self._capacity = capacity
        self._lock = threading.Lock()
        self.fail_next_write = False
        self.write_count = 0

    def _check_capacity(self, *, for_update: bool = False) -> None:
        if for_update:
            # Updates to existing keys don't consume new capacity
            return
        if len(self._data) >= self._capacity:
            raise StorageFullError("mutation store is full")

    def get(self, key: str) -> MutationOutcome | None:
        return self._data.get(key)

    def claim(self, key: str, payload_hash: str) -> MutationOutcome:
        """CAS claim: returns existing outcome or creates PENDING.

        The freshly-created PENDING outcome carries created=True exactly once;
        a retry of an existing claim returns created=False so the executor can
        refuse to re-invoke the provider.
        """
        with self._lock:
            self._check_capacity()
            if key in self._data:
                existing = self._data[key]
                if existing.payload_hash != payload_hash:
                    raise ValueError("payload conflict")
                # Re-claims of an existing row are never the creator.
                if existing.created:
                    existing = MutationOutcome(
                        existing.key, existing.status, existing.payload_hash,
                        existing.external_reference, existing.result, created=False,
                    )
                    self._data[key] = existing
                return existing
            outcome = MutationOutcome(key, MutationStatus.PENDING, payload_hash, None, created=True)
            self._data[key] = outcome
            return outcome

    def write_success(self, key: str, external_reference: str, result: Any) -> MutationOutcome:
        """Record successful provider mutation."""
        self._check_capacity(for_update=True)
        if self.fail_next_write:
            self.fail_next_write = False
            # Preserve external_reference so recovery can read it back
            outcome = MutationOutcome(key, MutationStatus.UNCERTAIN, self._data[key].payload_hash, external_reference)
            self._data[key] = outcome
            self._external_refs[external_reference] = key
            raise RuntimeError("local write failed after provider success")
        if external_reference in self._external_refs:
            existing_key = self._external_refs[external_reference]
            if existing_key != key:
                raise ValueError("external reference collision")
        self._external_refs[external_reference] = key
        outcome = MutationOutcome(key, MutationStatus.RESOLVED_PRESENT, self._data[key].payload_hash, external_reference, result)
        self._data[key] = outcome
        self.write_count += 1
        return outcome

    def rollback_claim(self, key: str) -> None:
        """Remove a pending claim if it exists (used on audit failure)."""
        if key in self._data and self._data[key].status == MutationStatus.PENDING:
            del self._data[key]

    def write_failure(self, key: str, status: MutationStatus) -> MutationOutcome:
        """Record pre-provider failure."""
        self._check_capacity()
        outcome = MutationOutcome(key, status, self._data[key].payload_hash, None)
        self._data[key] = outcome
        return outcome

    def resolve(self, key: str, status: MutationStatus, external_reference: str | None = None) -> MutationOutcome:
        """Resolve an uncertain outcome with proper bookkeeping."""
        self._check_capacity()
        outcome = MutationOutcome(key, status, self._data[key].payload_hash, external_reference)
        self._data[key] = outcome
        if external_reference is not None:
            self._external_refs[external_reference] = key
        return outcome

    # -- fencing registry ---------------------------------------------------

    def register_fencing(self, key: str, fencing_token: int) -> None:
        """Record the highest fencing token issued for key (monotonic)."""
        current = self._fencing.get(key, 0)
        if fencing_token > current:
            self._fencing[key] = fencing_token

    def current_fencing_token(self, key: str) -> int:
        """Return the highest fencing token ever registered for key."""
        return self._fencing.get(key, 0)


class StorageFullError(RuntimeError):
    """Raised when local persistence is exhausted."""
