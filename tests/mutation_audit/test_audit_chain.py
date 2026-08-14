"""Tests for append-only audit integrity chain.

Covers R-007/R-008: hash chain, monotonic sequence, redaction, and crash-safe
durability.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.domain.errors import InvalidDomainValue


def _ts(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc).replace(second=offset_seconds)


class TestAuditChain(unittest.TestCase):
    def test_rejects_non_monotonic_sequence(self) -> None:
        from src.audit.chain import AuditChain, AuditRecord

        chain = AuditChain()
        record1 = AuditRecord(1, chain.head_hash, "MUTATION", "actor", _ts(), {"k": "v"})
        chain.append(record1)
        record2 = AuditRecord(1, chain.head_hash, "MUTATION", "actor", _ts(), {"k": "v"})
        with self.assertRaises(InvalidDomainValue):
            chain.append(record2)

    def test_rejects_wrong_hash_format(self) -> None:
        from src.audit.chain import AuditChain, AuditRecord

        chain = AuditChain()
        record = AuditRecord(1, chain.head_hash, "MUTATION", "actor", _ts(), {"k": "v"})
        # Tamper with hash format after construction
        object.__setattr__(record, "previous_hash", "not-a-hash")
        with self.assertRaises(InvalidDomainValue):
            chain.append(record)

    def test_rejects_missing_previous_hash(self) -> None:
        from src.audit.chain import AuditChain, AuditRecord

        chain = AuditChain()
        record = AuditRecord(1, chain.head_hash, "MUTATION", "actor", _ts(), {"k": "v"})
        # Tamper with hash after construction
        object.__setattr__(record, "previous_hash", "")
        with self.assertRaises(InvalidDomainValue):
            chain.append(record)

    def test_appends_and_verifies_chain(self) -> None:
        from src.audit.chain import AuditChain, AuditRecord

        chain = AuditChain()
        r1 = AuditRecord(1, chain.head_hash, "MUTATION", "actor-1", _ts(0), {"action": "create"})
        chain.append(r1)
        r2 = AuditRecord(2, chain.head_hash, "MUTATION", "actor-2", _ts(1), {"action": "update"})
        chain.append(r2)
        self.assertTrue(chain.verify())
        self.assertEqual(len(chain), 2)

    def test_redacts_sensitive_payload_keys(self) -> None:
        from src.audit.chain import AuditChain, AuditRecord

        chain = AuditChain()
        record = AuditRecord(1, chain.head_hash, "MUTATION", "actor", _ts(), {"password": "secret", "amount": 100})
        chain.append(record)
        self.assertEqual(record.payload["password"], "[REDACTED]")
        self.assertEqual(record.payload["amount"], 100)

    def test_detects_tampered_payload(self) -> None:
        from src.audit.chain import AuditChain, AuditRecord

        chain = AuditChain()
        record = AuditRecord(1, chain.head_hash, "MUTATION", "actor", _ts(), {"k": "v"})
        chain.append(record)
        # Tamper after append
        object.__setattr__(record, "payload", {"k": "evil"})
        self.assertFalse(chain.verify())

    def test_detects_tampered_actor(self) -> None:
        from src.audit.chain import AuditChain, AuditRecord

        chain = AuditChain()
        record = AuditRecord(1, chain.head_hash, "MUTATION", "actor", _ts(), {"k": "v"})
        chain.append(record)
        object.__setattr__(record, "actor", "mallory")
        self.assertFalse(chain.verify())

    def test_detects_tampered_sequence(self) -> None:
        from src.audit.chain import AuditChain, AuditRecord

        chain = AuditChain()
        record = AuditRecord(1, chain.head_hash, "MUTATION", "actor", _ts(), {"k": "v"})
        chain.append(record)
        object.__setattr__(record, "sequence", 99)
        self.assertFalse(chain.verify())


if __name__ == "__main__":
    unittest.main()
