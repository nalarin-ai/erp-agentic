"""RED tests closing the two surviving remediation mutants.

- Survivor A: durable claim must reject a fencing token LOWER than the stored
  owner token even when the presented lease object is otherwise valid.
- Survivor B: the in-memory claim must serialize concurrent same-key claims
  under contention (lock removal must be observable).
"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc)


class TestDurableLowerTokenRejected(unittest.TestCase):
    def test_lower_token_rejected_with_live_stored_lease(self) -> None:
        import tempfile
        from pathlib import Path

        from src.mutations.claim_store import ClaimStatus
        from src.mutations.durable_store import DurableMutationStore
        from src.mutations.lease import MutationLease

        with tempfile.TemporaryDirectory() as tmp:
            store = DurableMutationStore(Path(tmp) / "m.sqlite3")
            key = "sha256:" + "a" * 64
            # Owner claims with a high token and a long-lived lease
            owner = MutationLease(key, 100, _now(), timedelta(seconds=300))
            first = store.claim(key, "ph", 1, owner, 100, _now())
            self.assertEqual(first.status, ClaimStatus.ACQUIRED)

            # A stale worker replays with a lower token while the owner's
            # lease is still live: must be rejected as STALE_FENCING.
            stale = MutationLease(key, 99, _now(), timedelta(seconds=300))
            result = store.claim(key, "ph", 1, stale, 99, _now())
            self.assertEqual(result.status, ClaimStatus.STALE_FENCING)
            self.assertEqual(store.current_fencing_token(key), 100)
            store.close()

    def test_lower_token_rejected_after_stored_lease_expired(self) -> None:
        """Only the explicit lower-token branch can catch this case: the
        stored lease HAS expired, so the expiry guard alone would allow a
        token decrease (non-monotonic fencing regression)."""
        import tempfile
        from pathlib import Path

        from src.mutations.claim_store import ClaimStatus
        from src.mutations.durable_store import DurableMutationStore
        from src.mutations.lease import MutationLease

        with tempfile.TemporaryDirectory() as tmp:
            store = DurableMutationStore(Path(tmp) / "m.sqlite3")
            key = "sha256:" + "b" * 64
            # Owner claims with a high token and a SHORT lease
            owner = MutationLease(key, 100, _now(), timedelta(seconds=30))
            store.claim(key, "ph", 1, owner, 100, _now())
            later = _now() + timedelta(seconds=31)  # stored lease expired
            # Stale replay with a LOWER token after expiry must still be
            # rejected: fencing tokens are monotonic per key, forever.
            stale = MutationLease(key, 99, later, timedelta(seconds=30))
            result = store.claim(key, "ph", 1, stale, 99, later)
            self.assertEqual(result.status, ClaimStatus.STALE_FENCING)
            self.assertEqual(store.current_fencing_token(key), 100)
            store.close()

    def test_higher_token_rejected_while_stored_lease_live(self) -> None:
        import tempfile
        from pathlib import Path

        from src.mutations.claim_store import ClaimStatus
        from src.mutations.durable_store import DurableMutationStore
        from src.mutations.lease import MutationLease

        with tempfile.TemporaryDirectory() as tmp:
            store = DurableMutationStore(Path(tmp) / "m.sqlite3")
            key = "sha256:" + "c" * 64
            owner = MutationLease(key, 100, _now(), timedelta(seconds=300))
            store.claim(key, "ph", 1, owner, 100, _now())
            # Even a NEWER token cannot take over before the stored lease expiry
            challenger = MutationLease(key, 101, _now(), timedelta(seconds=300))
            result = store.claim(key, "ph", 1, challenger, 101, _now())
            self.assertEqual(result.status, ClaimStatus.STALE_FENCING)
            self.assertEqual(store.current_fencing_token(key), 100)
            store.close()


class TestInMemoryClaimSerialization(unittest.TestCase):
    def test_claim_critical_section_uses_lock(self) -> None:
        """Structural invariant: claim() must hold the store lock.

        A mutant that removes `with self._lock` leaves _lock unused for the
        claim path; this test fails for that mutant without relying on
        GIL-timing luck."""
        import inspect

        from src.mutations.store import InMemoryMutationStore

        source = inspect.getsource(InMemoryMutationStore.claim)
        self.assertIn("self._lock", source, "claim() must serialize via self._lock")

    def test_concurrent_same_key_claim_single_creator(self) -> None:
        """Under contention, exactly one caller observes created=True."""
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        key = "sha256:" + "c" * 64
        created_count = 0
        conflicts = 0
        lock = threading.Lock()
        barrier = threading.Barrier(32)

        def worker() -> None:
            nonlocal created_count, conflicts
            barrier.wait()  # maximize contention on the critical section
            outcome = store.claim(key, "ph")
            with lock:
                if outcome.created:
                    created_count += 1

        threads = [threading.Thread(target=worker) for _ in range(32)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(created_count, 1, f"exactly one creator, got {created_count}")
        self.assertEqual(conflicts, 0)

    def test_claim_conflict_is_atomic_under_contention(self) -> None:
        """A conflicting payload never partially overwrites the claim."""
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        key = "sha256:" + "d" * 64
        store.claim(key, "ph-good")
        conflicts = 0
        lock = threading.Lock()

        def worker() -> None:
            nonlocal conflicts
            try:
                store.claim(key, "ph-bad")
            except ValueError:
                with lock:
                    conflicts += 1

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(conflicts, 16)
        self.assertEqual(store.get(key).payload_hash, "ph-good")


if __name__ == "__main__":
    unittest.main()
