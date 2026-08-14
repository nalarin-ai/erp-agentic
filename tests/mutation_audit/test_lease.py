"""Tests for mutation lease fencing.

Covers R-007/R-008: stale worker rejection, CAS claim, expiry, and fencing token
monotonicity.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.domain.errors import InvalidDomainValue


def _now() -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc)


class TestMutationLease(unittest.TestCase):
    def test_rejects_non_positive_tokens(self) -> None:
        from src.mutations.lease import MutationLease

        with self.assertRaises(InvalidDomainValue):
            MutationLease("key", 0, _now(), timedelta(seconds=30))
        with self.assertRaises(InvalidDomainValue):
            MutationLease("key", -1, _now(), timedelta(seconds=30))

    def test_rejects_non_aware_timestamps(self) -> None:
        from src.mutations.lease import MutationLease

        naive = datetime(2026, 8, 14, 0, 0, 0)
        with self.assertRaises(InvalidDomainValue):
            MutationLease("key", 1, naive, timedelta(seconds=30))

    def test_rejects_non_positive_ttl(self) -> None:
        from src.mutations.lease import MutationLease

        with self.assertRaises(InvalidDomainValue):
            MutationLease("key", 1, _now(), timedelta(seconds=0))
        with self.assertRaises(InvalidDomainValue):
            MutationLease("key", 1, _now(), timedelta(seconds=-1))

    def test_fencing_token_rejects_stale_writer(self) -> None:
        from src.mutations.lease import MutationLease

        lease = MutationLease("key", 1, _now(), timedelta(seconds=30))
        with self.assertRaisesRegex(Exception, "stale fencing token"):
            lease.assert_fresh(0, _now())

    def test_fencing_token_rejects_future_writer(self) -> None:
        from src.mutations.lease import MutationLease

        lease = MutationLease("key", 1, _now(), timedelta(seconds=30))
        with self.assertRaisesRegex(Exception, "stale fencing token"):
            lease.assert_fresh(2, _now())

    def test_fencing_token_rejects_expired_lease(self) -> None:
        from src.mutations.lease import MutationLease

        lease = MutationLease("key", 1, _now(), timedelta(seconds=30))
        after_expiry = _now() + timedelta(seconds=31)
        with self.assertRaisesRegex(Exception, "lease expired"):
            lease.assert_fresh(1, after_expiry)

    def test_fencing_token_accepts_current_writer(self) -> None:
        from src.mutations.lease import MutationLease

        lease = MutationLease("key", 1, _now(), timedelta(seconds=30))
        lease.assert_fresh(1, _now())  # no raise

    def test_cas_claim_generates_monotonic_tokens(self) -> None:
        from src.mutations.lease import MutationLease

        lease1 = MutationLease.claim("key", _now(), timedelta(seconds=30))
        lease2 = MutationLease.claim("key", _now(), timedelta(seconds=30))
        self.assertLess(lease1.fencing_token, lease2.fencing_token)


if __name__ == "__main__":
    unittest.main()
