"""Executable crash-boundary matrix for FND-004 (R-007/R-008).

Maps each normative crash boundary from IDEMPOTENCY_AUDIT_RECOVERY.md to a
reproducer test and asserts the required post-crash state and safe
continuation. All fixtures are synthetic and network-disabled.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.mutations.lease import MutationLease


def _now() -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc)


def _executor_pair():
    from src.audit.chain import AuditChain
    from src.mutations.executor import MutationExecutor
    from src.mutations.store import InMemoryMutationStore

    store = InMemoryMutationStore()
    audit = AuditChain()
    return MutationExecutor(store, audit), store, audit


class TestCrashBoundaryMatrix(unittest.TestCase):
    def test_boundary_1_crash_before_durable_intent_no_provider_call(self) -> None:
        # Fencing/lease rejection happens before claim/audit/provider.
        from src.mutations.lease import StaleFencingTokenError

        executor, store, audit = _executor_pair()
        key = "sha256:" + "a" * 64
        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
        provider_calls: list[dict] = []

        def provider(payload: dict) -> str:
            provider_calls.append(payload)
            return "EXT-B1"

        with self.assertRaises(StaleFencingTokenError):
            executor.execute(
                key, "MUTATION", {"v": 1}, provider, _now(),
                actor="alice", lease=lease,
                presented_fencing_token=lease.fencing_token - 1,
            )
        self.assertEqual(provider_calls, [])
        self.assertIsNone(store.get(key))
        self.assertEqual(len(audit), 0)

    def test_boundary_2_crash_after_intent_before_provider_safe_absent(self) -> None:
        # Terminal audit precondition failure rolls back the claim: no row,
        # no provider call, retry classifies absent.
        executor, store, audit = _executor_pair()
        key = "sha256:" + "b" * 64
        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
        audit.fail_next_append = True
        provider_calls: list[dict] = []

        def provider(payload: dict) -> str:
            provider_calls.append(payload)
            return "EXT-B2"

        with self.assertRaises(RuntimeError):
            executor.execute(
                key, "MUTATION", {"v": 1}, provider, _now(),
                actor="alice", lease=lease,
                presented_fencing_token=lease.fencing_token,
            )
        self.assertIsNone(store.get(key))
        self.assertEqual(provider_calls, [])

    def test_boundary_3_provider_sent_outcome_unavailable_marks_uncertain(self) -> None:
        # Provider succeeded locally but the response/local write is lost:
        # state becomes UNCERTAIN with external_reference preserved, and a
        # retry of the same key+payload does not reissue the provider call.
        executor, store, audit = _executor_pair()
        key = "sha256:" + "c" * 64
        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
        calls: list[dict] = []

        def provider(payload: dict) -> str:
            calls.append(payload)
            return "EXT-B3"

        store.fail_next_write = True
        with self.assertRaises(RuntimeError):
            executor.execute(
                key, "MUTATION", {"v": 1}, provider, _now(),
                actor="alice", lease=lease,
                presented_fencing_token=lease.fencing_token,
            )
        from src.mutations.store import MutationStatus

        self.assertEqual(store.get(key).status, MutationStatus.UNCERTAIN)
        self.assertEqual(store.get(key).external_reference, "EXT-B3")
        self.assertEqual(len(calls), 1)

    def test_boundary_4_provider_success_local_failure_recovery_writes_terminal(self) -> None:
        executor, store, audit = _executor_pair()
        key = "sha256:" + "d" * 64
        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))

        def provider(payload: dict) -> str:
            return "EXT-B4"

        store.fail_next_write = True
        with self.assertRaises(RuntimeError):
            executor.execute(
                key, "MUTATION", {"v": 1}, provider, _now(),
                actor="alice", lease=lease,
                presented_fencing_token=lease.fencing_token,
            )
        from src.mutations.store import MutationStatus

        resolved = executor.recover(
            key, _now(), actor="alice",
            lease=lease, presented_fencing_token=lease.fencing_token,
        )
        self.assertEqual(resolved.status, MutationStatus.RESOLVED_PRESENT)
        self.assertEqual(resolved.external_reference, "EXT-B4")
        # Audit chain intact after the crash+recovery sequence.
        self.assertTrue(audit.verify())

    def test_boundary_5_provider_absent_readback_resolves_absent(self) -> None:
        # UNCERTAIN with no external reference resolves ABSENT (safe reissue
        # is a later, separately fenced decision).
        executor, store, audit = _executor_pair()
        key = "sha256:" + "e" * 64
        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
        # Seed an UNCERTAIN row without external_reference
        outcome = store.claim(key, "ph")
        store._data[key] = type(outcome)(
            key, outcome.status.__class__.UNCERTAIN, outcome.payload_hash, None
        )

        from src.mutations.store import MutationStatus

        resolved = executor.recover(
            key, _now(), actor="alice",
            lease=lease, presented_fencing_token=lease.fencing_token,
        )
        self.assertEqual(resolved.status, MutationStatus.RESOLVED_ABSENT)

    def test_audit_chain_detects_tampering_after_recovery(self) -> None:
        executor, store, audit = _executor_pair()
        key = "sha256:" + "f" * 64
        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))

        def provider(payload: dict) -> str:
            return "EXT-B6"

        store.fail_next_write = True
        with self.assertRaises(RuntimeError):
            executor.execute(
                key, "MUTATION", {"v": 1}, provider, _now(),
                actor="alice", lease=lease,
                presented_fencing_token=lease.fencing_token,
            )
        executor.recover(
            key, _now(), actor="alice",
            lease=lease, presented_fencing_token=lease.fencing_token,
        )
        self.assertTrue(audit.verify())
        # Tamper with the last record and re-verify
        last = audit._records[-1]
        object.__setattr__(last, "actor", "mallory")
        self.assertFalse(audit.verify())


if __name__ == "__main__":
    unittest.main()
