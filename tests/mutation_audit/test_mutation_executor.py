"""Tests for crash-safe mutation executor.

Covers R-007/R-008: crash boundaries, terminal audit failure, reconnect,
provider collision, storage-full, fencing/lease enforcement, actor identity,
and one-mutation-under-retry semantics.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.domain.errors import InvalidDomainValue


def _now() -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc)


def _lease(key: str = "key") -> "MutationLease":
    from src.mutations.lease import MutationLease

    return MutationLease.claim(key, _now(), timedelta(seconds=30))


class TestMutationExecutor(unittest.TestCase):
    def test_rejects_stale_fencing_token(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.lease import MutationLease, StaleFencingTokenError
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "a" * 64

        # Claim lease, then present a stale token
        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
        stale_token = lease.fencing_token - 1

        def provider(payload: dict) -> str:
            return "EXT-REF-123"

        with self.assertRaises(StaleFencingTokenError):
            executor.execute(key, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease, presented_fencing_token=stale_token)

    def test_rejects_expired_lease(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.lease import MutationLease
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "a" * 64

        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
        after_expiry = _now() + timedelta(seconds=31)

        def provider(payload: dict) -> str:
            return "EXT-REF-123"

        with self.assertRaisesRegex(Exception, "lease expired"):
            executor.execute(key, "MUTATION", {"amount": 100}, provider, after_expiry, actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)

    def test_storage_full_blocks_mutation(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.store import InMemoryMutationStore, StorageFullError

        store = InMemoryMutationStore(capacity=1)
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key1 = "sha256:" + "a" * 64
        key2 = "sha256:" + "b" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-123"

        lease1 = _lease(key1)
        executor.execute(key1, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease1, presented_fencing_token=lease1.fencing_token)
        with self.assertRaises(StorageFullError):
            lease2 = _lease(key2)
            executor.execute(key2, "MUTATION", {"amount": 200}, provider, _now(), actor="alice", lease=lease2, presented_fencing_token=lease2.fencing_token)

    def test_failed_before_provider_marks_failed_no_mutation(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "a" * 64

        def failing_provider(payload: dict) -> str:
            raise RuntimeError("provider down")

        lease = _lease(key)
        with self.assertRaises(RuntimeError):
            executor.execute(key, "MUTATION", {"amount": 100}, failing_provider, _now(), actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)
        outcome = store.get(key)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.status, MutationStatus.FAILED_NO_MUTATION)
        # Verify failure was audited
        self.assertEqual(len(audit), 2)  # pre_mutation + provider_failed

    def test_provider_success_local_write_failure_marks_uncertain(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "b" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-123"

        # Force local write failure after provider success
        store.fail_next_write = True
        lease = _lease(key)
        with self.assertRaises(RuntimeError):
            executor.execute(key, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)
        outcome = store.get(key)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.status, MutationStatus.UNCERTAIN)
        # Verify uncertainty was audited
        self.assertEqual(len(audit), 2)  # pre_mutation + local_write_failed

    def test_same_key_same_payload_returns_same_result(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "c" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-456"

        lease = _lease(key)
        result1 = executor.execute(key, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)
        result2 = executor.execute(key, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)
        self.assertEqual(result1, result2)
        self.assertEqual(store.write_count, 1)

    def test_same_key_different_payload_raises_conflict(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "d" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-789"

        lease = _lease(key)
        executor.execute(key, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)
        with self.assertRaisesRegex(Exception, "payload conflict"):
            executor.execute(key, "MUTATION", {"amount": 200}, provider, _now(), actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)

    def test_provider_external_reference_collision_detected(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key1 = "sha256:" + "e" * 64
        key2 = "sha256:" + "f" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-COLLIDE"

        lease1 = _lease(key1)
        executor.execute(key1, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease1, presented_fencing_token=lease1.fencing_token)
        with self.assertRaisesRegex(Exception, "external reference collision"):
            lease2 = _lease(key2)
            executor.execute(key2, "MUTATION", {"amount": 200}, provider, _now(), actor="alice", lease=lease2, presented_fencing_token=lease2.fencing_token)

    def test_terminal_audit_failure_blocks_mutation(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        audit = AuditChain()
        audit.fail_next_append = True
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "0" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-000"

        lease = _lease(key)
        with self.assertRaises(RuntimeError):
            executor.execute(key, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)
        self.assertIsNone(store.get(key))

    def test_reconnect_after_crash_recovers_pending_state(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "1" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-CRASH"

        lease = _lease(key)
        # Simulate crash after provider success but before local write
        store.fail_next_write = True
        with self.assertRaises(RuntimeError):
            executor.execute(key, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)

        # New executor instance reconnects and sees UNCERTAIN state
        executor2 = MutationExecutor(store, audit)
        outcome = store.get(key)
        self.assertEqual(outcome.status, MutationStatus.UNCERTAIN)
        # Recovery path resolves to RESOLVED_PRESENT after read-back; the
        # recovering worker must present the current fencing token.
        resolved = executor2.recover(
            key, _now(), actor="alice",
            lease=lease, presented_fencing_token=lease.fencing_token,
        )
        self.assertEqual(resolved.status, MutationStatus.RESOLVED_PRESENT)
        # Verify recovery was audited
        self.assertEqual(len(audit), 3)  # pre_mutation + local_write_failed + recovered

    def test_audit_carries_actor_identity(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.store import InMemoryMutationStore

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "2" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-ACTOR"

        lease = _lease(key)
        executor.execute(key, "MUTATION", {"amount": 100}, provider, _now(), actor="alice", lease=lease, presented_fencing_token=lease.fencing_token)
        # Check that all audit records carry the actor
        for record in audit._records:
            self.assertEqual(record.actor, "alice")


if __name__ == "__main__":
    unittest.main()
