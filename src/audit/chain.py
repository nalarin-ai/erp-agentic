"""Append-only audit chain with integrity metadata.

Implements R-007/R-008: monotonic sequence, hash chain, redaction, and
fail-closed durability before mutation. This is an in-memory test fixture;
production uses durable storage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from src.domain.errors import InvalidDomainValue


_SENSITIVE_KEYS = {"password", "secret", "token", "key", "credential", "auth"}


@dataclass(frozen=True, slots=True)
class AuditRecord:
    sequence: int
    previous_hash: str
    event_type: str
    actor: str
    timestamp: datetime
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise InvalidDomainValue("sequence must be positive")
        if not self.previous_hash:
            raise InvalidDomainValue("previous_hash is required")
        if not self.previous_hash.startswith("sha256:") or len(self.previous_hash) != 71:
            raise InvalidDomainValue("previous_hash must be sha256:hex64")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise InvalidDomainValue("timestamp must be timezone-aware")
        # Redact sensitive payload keys
        redacted = {k: ("[REDACTED]" if k.lower() in _SENSITIVE_KEYS else v) for k, v in self.payload.items()}
        object.__setattr__(self, "payload", redacted)

    def compute_hash(self) -> str:
        """Compute this record's hash over the chain."""
        material = f"{self.sequence}:{self.previous_hash}:{self.event_type}:{self.actor}:{self.timestamp.isoformat()}:{json.dumps(self.payload, sort_keys=True)}"
        return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditChain:
    """Append-only chain with integrity verification."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._hashes: list[str] = []
        self.fail_next_append = False

    @property
    def head_hash(self) -> str:
        if not self._hashes:
            return "sha256:" + "0" * 64
        return self._hashes[-1]

    def append(self, record: AuditRecord) -> str:
        """Append a record and return its hash. Raises on invalid sequence/hash."""
        if self.fail_next_append:
            self.fail_next_append = False
            raise RuntimeError("audit append failed")
        expected_seq = len(self._records) + 1
        if record.sequence != expected_seq:
            raise InvalidDomainValue(f"sequence must be {expected_seq}")
        if record.previous_hash != self.head_hash:
            raise InvalidDomainValue("previous_hash does not match chain head")
        record_hash = record.compute_hash()
        self._records.append(record)
        self._hashes.append(record_hash)
        return record_hash

    def verify(self) -> bool:
        """Verify the entire chain."""
        for i, record in enumerate(self._records):
            expected_seq = i + 1
            if record.sequence != expected_seq:
                return False
            expected_prev = self._hashes[i - 1] if i > 0 else "sha256:" + "0" * 64
            if record.previous_hash != expected_prev:
                return False
            if record.compute_hash() != self._hashes[i]:
                return False
        return True

    def __len__(self) -> int:
        return len(self._records)
