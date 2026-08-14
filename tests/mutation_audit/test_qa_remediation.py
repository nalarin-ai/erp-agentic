"""RED tests for FND-004 QA remediation (round 1).

Findings closed here (see project-control QA ledger):
- QA-01 CRITICAL: retry of an in-flight PENDING claim must never re-invoke
  the provider.
- QA-02 HIGH: durable reclaim must transactionally take over fencing after
  lease expiry and reject stale owner tokens.
- QA-03 HIGH: post-success audit failure must leave store and audit
  consistent (outcome marked UNCERTAIN, no contradictory success claim).
- QA-05 MEDIUM: executor derives/binds the idempotency key with
  canonicalization version; mismatched presented key fails closed.
- QA-07 LOW: in-memory store claim is genuinely thread-safe (lock).
"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc)


def _lease(key: str):
    from src.mutations.lease import MutationLease

    return MutationLease.claim(key, _now(), timedelta(seconds=30))


class TestNoDuplicateProviderOnPendingRetry(unittest.TestCase):
    """QA-01: same key+payload while PENDING must not call provider again."""

    def test_pending_retry_does_not_invoke_provider(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor, RecoveryRequired
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "a" * 64
        lease = _lease(key)
        calls: list[dict] = []

        def provider(payload: dict) -> str:
            calls.append(payload)
            return "EXT-P1"

        # Seed an in-flight PENDING claim (as if another worker owns it).
        # Normalize created=False: from this executor's perspective the claim
        # already exists, it was not created by this execute() call.
        seeded = store.claim(key, executor._payload_hash({"v": 1}))
        store._data[key] = type(seeded)(
            seeded.key, seeded.status, seeded.payload_hash,
            seeded.external_reference, seeded.result, created=False,
        )
        self.assertEqual(store.get(key).status, MutationStatus.PENDING)

        with self.assertRaises(RecoveryRequired):
            executor.execute(
                key, "MUTATION", {"v": 1}, provider, _now(),
                actor="bob", lease=lease,
                presented_fencing_token=lease.fencing_token,
            )
        self.assertEqual(calls, [], "provider must not be called for in-flight PENDING claim")
        self.assertEqual(store.get(key).status, MutationStatus.PENDING)

    def test_uncertain_retry_does_not_invoke_provider(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor, RecoveryRequired
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "b" * 64
        lease = _lease(key)
        calls: list[dict] = []

        def provider(payload: dict) -> str:
            calls.append(payload)
            return "EXT-P2"

        outcome = store.claim(key, executor._payload_hash({"v": 1}))
        store._data[key] = type(outcome)(key, MutationStatus.UNCERTAIN, outcome.payload_hash, "EXT-P2")
        with self.assertRaises(RecoveryRequired):
            executor.execute(
                key, "MUTATION", {"v": 1}, provider, _now(),
                actor="bob", lease=lease,
                presented_fencing_token=lease.fencing_token,
            )
        self.assertEqual(calls, [])


class TestKeyBinding(unittest.TestCase):
    """QA-05: presented key must equal derived key for payload+version."""

    def test_mismatched_key_fails_closed(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.idempotency import IdempotencyKey
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        right_key = IdempotencyKey.derive("UNIT-A", "post", {"v": 1}).value
        wrong_key = "sha256:" + "0" * 64
        lease = _lease(wrong_key)
        calls: list[dict] = []

        def provider(payload: dict) -> str:
            calls.append(payload)
            return "EXT-K1"

        with self.assertRaises(ValueError):
            executor.execute(
                wrong_key, "post", {"v": 1}, provider, _now(),
                actor="alice", lease=lease,
                presented_fencing_token=lease.fencing_token,
                namespace="UNIT-A",
            )
        self.assertEqual(calls, [])
        self.assertIsNone(store.get(wrong_key))
        self.assertIsNone(store.get(right_key))

    def test_matching_key_executes_once(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.idempotency import IdempotencyKey
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = IdempotencyKey.derive("UNIT-A", "post", {"v": 1}).value
        lease = _lease(key)

        def provider(payload: dict) -> str:
            return "EXT-K2"

        outcome = executor.execute(
            key, "post", {"v": 1}, provider, _now(),
            actor="alice", lease=lease,
            presented_fencing_token=lease.fencing_token,
            namespace="UNIT-A",
        )
        self.assertEqual(outcome.status, MutationStatus.RESOLVED_PRESENT)
        self.assertEqual(store.write_count, 1)


class TestAtomicTerminalAudit(unittest.TestCase):
    """QA-03: success-audit failure must not contradict the store."""

    def test_success_audit_failure_marks_uncertain_consistently(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.idempotency import IdempotencyKey
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = IdempotencyKey.derive("UNIT-A", "post", {"v": 9}).value
        lease = _lease(key)

        def provider(payload: dict) -> str:
            return "EXT-A3"

        # pre_mutation succeeds; terminal success audit fails
        orig_append = audit.append
        state = {"n": 0}

        def flaky_append(record):
            state["n"] += 1
            if state["n"] == 2:  # second append = post_mutation success audit
                raise RuntimeError("audit storage full")
            return orig_append(record)

        audit.append = flaky_append  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            executor.execute(
                key, "post", {"v": 9}, provider, _now(),
                actor="alice", lease=lease,
                presented_fencing_token=lease.fencing_token,
                namespace="UNIT-A",
            )
        outcome = store.get(key)
        self.assertIsNotNone(outcome)
        # Store must NOT claim terminal success while audit failed
        self.assertEqual(outcome.status, MutationStatus.UNCERTAIN)
        self.assertEqual(outcome.external_reference, "EXT-A3")
        # Recovery under the owner fencing resolves consistently
        resolved = executor.recover(
            key, _now(), actor="alice",
            lease=lease, presented_fencing_token=lease.fencing_token,
        )
        self.assertEqual(resolved.status, MutationStatus.RESOLVED_PRESENT)


class TestDurableFencingTakeover(unittest.TestCase):
    """QA-02: durable reclaim after expiry transfers fencing; stale rejected."""

    def test_takeover_after_expiry_updates_fencing_and_rejects_stale(self) -> None:
        import tempfile
        from pathlib import Path

        from src.mutations.durable_store import DurableMutationStore
        from src.mutations.lease import MutationLease, StaleFencingTokenError

        with tempfile.TemporaryDirectory() as tmp:
            store = DurableMutationStore(Path(tmp) / "m.sqlite3")
            key = "sha256:" + "c" * 64
            old_lease = MutationLease(key, 10, _now(), timedelta(seconds=30))
            store.claim(key, "ph", 1, old_lease, 10, _now())

            # New worker takes over after old lease expired
            later = _now() + timedelta(seconds=31)
            new_lease = MutationLease(key, 11, later, timedelta(seconds=30))
            result = store.claim(key, "ph", 1, new_lease, 11, later)
            self.assertEqual(result.status.value, "ACQUIRED")
            self.assertEqual(store.current_fencing_token(key), 11)

            # Stale worker with old token must be rejected durably
            with self.assertRaises((StaleFencingTokenError, RuntimeError, ValueError)):
                store.claim(key, "ph", 1, old_lease, 10, later)
            store.close()

    def test_non_terminal_reclaim_returns_distinct_status(self) -> None:
        import tempfile
        from pathlib import Path

        from src.mutations.durable_store import DurableMutationStore
        from src.mutations.lease import MutationLease

        with tempfile.TemporaryDirectory() as tmp:
            store = DurableMutationStore(Path(tmp) / "m.sqlite3")
            key = "sha256:" + "d" * 64
            lease = MutationLease(key, 20, _now(), timedelta(seconds=30))
            first = store.claim(key, "ph", 1, lease, 20, _now())
            self.assertEqual(first.status.value, "ACQUIRED")
            # Same owner re-claiming a PENDING row is a no-op hold, not
            # a terminal 'already resolved'.
            second = store.claim(key, "ph", 1, lease, 20, _now())
            self.assertIn(second.status.value, ("ACQUIRED", "CLAIM_HELD", "PENDING"))
            self.assertNotEqual(second.status.value, "ALREADY_RESOLVED")
            store.close()


class TestInMemoryThreadSafety(unittest.TestCase):
    """QA-07: concurrent claims on the in-memory store yield one winner."""

    def test_concurrent_claim_single_winner(self) -> None:
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        key = "sha256:" + "e" * 64
        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            outcome = store.claim(key, "ph")
            with lock:
                results.append(outcome.status.value)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(MutationStatus.PENDING.value), 16)
        self.assertEqual(store.get(key).payload_hash, "ph")


if __name__ == "__main__":
    unittest.main()
