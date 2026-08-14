"""Idempotency key generation and validation.

Implements R-007 (idempotent duplicate/retried requests) with namespaced
SHA-256 hashing. All keys are synthetic and credential-safe.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from src.domain.errors import InvalidDomainValue


_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_CREDENTIAL_PREFIXES = ("sk-", "pk-", "api-", "key-", "secret-", "token-", "pass-")


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """A validated, namespaced idempotency key."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("value must be str")
        if _CONTROL_CHARS.search(self.value):
            raise InvalidDomainValue("key contains control characters")
        if not _KEY_PATTERN.fullmatch(self.value):
            raise InvalidDomainValue("key must be namespace:hash")
        # Check for credential-like material in the hash portion
        hash_part = self.value.split(":", 1)[1].lower()
        if any(hash_part.startswith(prefix) for prefix in _CREDENTIAL_PREFIXES):
            raise InvalidDomainValue("key resembles credential material")

    @classmethod
    def derive(
        cls,
        namespace: str,
        action: str,
        payload: dict[str, object],
        *,
        canonicalization_version: int = 1,
    ) -> "IdempotencyKey":
        """Derive a deterministic namespaced key from action and payload.

        The canonicalization version is part of the key identity: bumping it
        intentionally changes every derived key so cross-version claims can
        never alias.
        """
        if not isinstance(canonicalization_version, int) or isinstance(canonicalization_version, bool):
            raise InvalidDomainValue("canonicalization_version must be int")
        if canonicalization_version <= 0:
            raise InvalidDomainValue("canonicalization_version must be positive")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        material = f"v{canonicalization_version}:{namespace}:{action}:{canonical}"
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return cls(f"sha256:{digest}")

    def to_canonical_payload(self) -> dict[str, str]:
        return {"key": self.value}
