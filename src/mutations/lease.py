"""Mutation lease with fencing tokens for stale-worker rejection.

Implements R-007/R-008: CAS claim, monotonic fencing, and expiry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import itertools

from src.domain.errors import InvalidDomainValue


_token_counter = itertools.count(1)


class LeaseError(RuntimeError):
    """Base for lease violations."""


class StaleFencingTokenError(LeaseError):
    """Writer presented an outdated fencing token."""


class LeaseExpiredError(LeaseError):
    """Writer presented an expired lease."""


@dataclass(frozen=True, slots=True)
class MutationLease:
    """A fencing-token lease for one mutation key."""

    key: str
    fencing_token: int
    claimed_at: datetime
    ttl: timedelta

    def __post_init__(self) -> None:
        if self.fencing_token <= 0:
            raise InvalidDomainValue("fencing_token must be positive")
        if self.claimed_at.tzinfo is None or self.claimed_at.utcoffset() is None:
            raise InvalidDomainValue("claimed_at must be timezone-aware")
        if self.ttl.total_seconds() <= 0:
            raise InvalidDomainValue("ttl must be positive")

    @property
    def expires_at(self) -> datetime:
        return self.claimed_at + self.ttl

    def is_expired(self, at: datetime) -> bool:
        return at >= self.expires_at

    def assert_fresh(self, fencing_token: int, at: datetime) -> None:
        """Raise if the presented token is stale or the lease is expired."""
        if fencing_token != self.fencing_token:
            raise StaleFencingTokenError(f"stale fencing token: {fencing_token} != {self.fencing_token}")
        if self.is_expired(at):
            raise LeaseExpiredError(f"lease expired at {self.expires_at}")

    @classmethod
    def claim(cls, key: str, at: datetime, ttl: timedelta) -> "MutationLease":
        """Generate a new lease with a monotonic fencing token."""
        return cls(key=key, fencing_token=next(_token_counter), claimed_at=at, ttl=ttl)
