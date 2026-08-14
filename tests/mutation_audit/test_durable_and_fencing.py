"""RED-first tests for FND-004 contract gaps.

Covers the normative `IDEMPOTENCY_AUDIT_RECOVERY.md` requirements not yet
evidenced by the initial slice:
- cross-process concurrent CAS claims on one durable store;
- fencing/lease enforcement on recovery (stale worker cannot finalize);
- canonicalization version bound into the claim identity;
- durable SQLite-backed claim store surviving reconnect;
- migration DDL artifact presence and shape.
"""
from __future__ import annotations

import sqlite3
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _now() -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc)


class TestCanonicalizationVersion(unittest.TestCase):
    def test_key_identity_includes_canonicalization_version(self) -> None:
        from src.mutations.idempotency import IdempotencyKey

        payload = {"amount": "1000.00"}
        key_v1 = IdempotencyKey.derive("UNIT-A", "invoice-post", payload)
        key_v2 = IdempotencyKey.derive("UNIT-A", "invoice-post", payload, canonicalization_version=2)
        self.assertNotEqual(key_v1.value, key_v2.value)
        self.assertTrue(key_v1.value.startswith("sha256:"))
        self.assertTrue(key_v2.value.startswith("sha256:"))

    def test_default_canonicalization_version_is_one(self) -> None:
        from src.mutations.idempotency import IdempotencyKey

        explicit = IdempotencyKey.derive("UNIT-A", "act", {"x": 1}, canonicalization_version=1)
        default = IdempotencyKey.derive("UNIT-A", "act", {"x": 1})
        self.assertEqual(explicit.value, default.value)


class TestDurableClaimStore(unittest.TestCase):
    def _open(self, db_path: Path):
        from src.mutations.durable_store import DurableMutationStore

        return DurableMutationStore(db_path)

    def test_durable_claim_survives_reconnect(self) -> None:
        from src.mutations.lease import MutationLease

        with self.subTest("claim then reconnect"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "mutations.sqlite3"
                store = self._open(db)
                lease = MutationLease.claim("sha256:" + "a" * 64, _now(), timedelta(seconds=30))
                result = store.claim(
                    "sha256:" + "a" * 64, "ph", 1, lease, lease.fencing_token, _now()
                )
                self.assertEqual(result.status.value, "ACQUIRED")
                store.close()

                store2 = self._open(db)
                outcome = store2.get("sha256:" + "a" * 64)
                self.assertIsNotNone(outcome)
                self.assertEqual(outcome.status.value, "PENDING")
                self.assertEqual(store2.current_fencing_token("sha256:" + "a" * 64), lease.fencing_token)
                store2.close()

    def test_cross_process_concurrent_claim_single_winner(self) -> None:
        import tempfile

        from src.mutations.lease import MutationLease

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mutations.sqlite3"
            self._open(db).close()  # initialize schema
            key = "sha256:" + "c" * 64
            acquired: list[str] = []
            errors: list[BaseException] = []
            lock = threading.Lock()

            def worker(name: str) -> None:
                try:
                    store = self._open(db)
                    lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
                    result = store.claim(key, "ph", 1, lease, lease.fencing_token, _now())
                    with lock:
                        if result.status.value == "ACQUIRED":
                            acquired.append(name)
                    store.close()
                except BaseException as exc:  # noqa: BLE001 - collected for assertion
                    with lock:
                        errors.append(exc)

            threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(acquired), 1, f"exactly one winner expected, got {acquired}")

    def test_stale_fencing_rejected_on_durable_claim(self) -> None:
        import tempfile

        from src.mutations.lease import MutationLease, StaleFencingTokenError

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mutations.sqlite3"
            store = self._open(db)
            key = "sha256:" + "d" * 64
            lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
            store.claim(key, "ph", 1, lease, lease.fencing_token, _now())
            with self.assertRaises(StaleFencingTokenError):
                store.claim(key, "ph", 1, lease, lease.fencing_token - 1, _now())
            store.close()

    def test_durable_payload_conflict_fails_closed(self) -> None:
        import tempfile

        from src.mutations.lease import MutationLease
        from src.mutations.store import MutationStatus

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mutations.sqlite3"
            store = self._open(db)
            key = "sha256:" + "e" * 64
            lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
            store.claim(key, "ph-1", 1, lease, lease.fencing_token, _now())
            result = store.claim(key, "ph-2", 1, lease, lease.fencing_token, _now())
            self.assertEqual(result.status.value, "PAYLOAD_CONFLICT")
            outcome = store.get(key)
            self.assertEqual(outcome.status, MutationStatus.PENDING)
            store.close()

    def test_durable_canonicalization_version_conflict(self) -> None:
        import tempfile

        from src.mutations.lease import MutationLease

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mutations.sqlite3"
            store = self._open(db)
            key = "sha256:" + "f" * 64
            lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
            store.claim(key, "ph", 1, lease, lease.fencing_token, _now())
            result = store.claim(key, "ph", 2, lease, lease.fencing_token, _now())
            self.assertEqual(result.status.value, "PAYLOAD_CONFLICT")
            store.close()

    def test_expired_lease_rejected_on_durable_claim(self) -> None:
        import tempfile

        from src.mutations.lease import LeaseExpiredError, MutationLease

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mutations.sqlite3"
            store = self._open(db)
            key = "sha256:" + "0" * 64
            lease = MutationLease(key, 5, _now(), timedelta(seconds=30))
            after = _now() + timedelta(seconds=31)
            with self.assertRaises(LeaseExpiredError):
                store.claim(key, "ph", 1, lease, 5, after)
            store.close()


class TestRecoveryFencing(unittest.TestCase):
    def test_recover_requires_matching_fencing_token(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.lease import MutationLease, StaleFencingTokenError
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "3" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-FENCE"

        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
        store.fail_next_write = True
        with self.assertRaises(RuntimeError):
            executor.execute(
                key, "MUTATION", {"amount": 1}, provider, _now(),
                actor="alice", lease=lease, presented_fencing_token=lease.fencing_token,
            )
        self.assertEqual(store.get(key).status, MutationStatus.UNCERTAIN)

        stale = MutationLease(key, lease.fencing_token + 1, _now(), timedelta(seconds=30))
        with self.assertRaises((StaleFencingTokenError, ValueError, RuntimeError)):
            executor.recover(
                key, _now(), actor="mallory",
                lease=stale, presented_fencing_token=stale.fencing_token,
            )
        # State must remain UNCERTAIN after rejected recovery
        self.assertEqual(store.get(key).status, MutationStatus.UNCERTAIN)

    def test_recover_with_current_fencing_succeeds(self) -> None:
        from src.audit.chain import AuditChain
        from src.mutations.executor import MutationExecutor
        from src.mutations.lease import MutationLease
        from src.mutations.store import InMemoryMutationStore, MutationStatus

        store = InMemoryMutationStore()
        audit = AuditChain()
        executor = MutationExecutor(store, audit)
        key = "sha256:" + "4" * 64

        def provider(payload: dict) -> str:
            return "EXT-REF-OK"

        lease = MutationLease.claim(key, _now(), timedelta(seconds=30))
        store.fail_next_write = True
        with self.assertRaises(RuntimeError):
            executor.execute(
                key, "MUTATION", {"amount": 1}, provider, _now(),
                actor="alice", lease=lease, presented_fencing_token=lease.fencing_token,
            )
        resolved = executor.recover(
            key, _now(), actor="alice",
            lease=lease, presented_fencing_token=lease.fencing_token,
        )
        self.assertEqual(resolved.status, MutationStatus.RESOLVED_PRESENT)


class TestMigrationArtifact(unittest.TestCase):
    def test_migration_ddl_exists_and_creates_required_tables(self) -> None:
        migrations = sorted(
            Path("db/migrations/mutation_audit").glob("*.sql")
        )
        self.assertTrue(migrations, "no migration SQL under db/migrations/mutation_audit")
        ddl = "\n".join(path.read_text() for path in migrations)
        for needle in ("mutation_outcome", "audit_event", "fencing_token", "payload_hash", "canonicalization_version"):
            self.assertIn(needle, ddl)

    def test_migration_applies_to_empty_sqlite(self) -> None:
        import tempfile

        migrations = sorted(Path("db/migrations/mutation_audit").glob("*.sql"))
        self.assertTrue(migrations)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "m.sqlite3"
            conn = sqlite3.connect(db)
            try:
                for path in migrations:
                    conn.executescript(path.read_text())
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertIn("mutation_outcome", tables)
                self.assertIn("audit_event", tables)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
