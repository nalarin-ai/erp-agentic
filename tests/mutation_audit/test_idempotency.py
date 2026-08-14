"""Tests for mutation idempotency keys.

Covers R-007 (idempotent duplicate/retried chat requests) and R-008
(durable audit identity, no credentials in evidence).
"""
from __future__ import annotations

import unittest

from src.domain.errors import InvalidDomainValue


class TestIdempotencyKey(unittest.TestCase):
    def test_rejects_wrong_type(self) -> None:
        from src.mutations.idempotency import IdempotencyKey

        with self.assertRaises(TypeError):
            IdempotencyKey(123)  # type: ignore[arg-type]

    def test_rejects_malformed_text(self) -> None:
        from src.mutations.idempotency import IdempotencyKey

        for bad in ["", "no-separator", "unit-only:", ":hash-only", "unit:bad hash!"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidDomainValue):
                IdempotencyKey(bad)

    def test_rejects_control_and_whitespace(self) -> None:
        from src.mutations.idempotency import IdempotencyKey

        for bad in ["unit:hash\nnewline", "unit:hash with space", "unit:\ttab"]:
            with self.subTest(bad=bad), self.assertRaises(InvalidDomainValue):
                IdempotencyKey(bad)

    def test_rejects_credential_like_material(self) -> None:
        from src.mutations.idempotency import IdempotencyKey

        credential_like = "unit:sk-live-abcdefghijklmnop"
        with self.assertRaises(InvalidDomainValue):
            IdempotencyKey(credential_like)

    def test_derives_namespaced_sha256_hex(self) -> None:
        from src.mutations.idempotency import IdempotencyKey

        key1 = IdempotencyKey.derive("UNIT-BANYUMEDIA", "invoice-draft", {"amount": "1000.00"})
        key2 = IdempotencyKey.derive("UNIT-BANYUMEDIA", "invoice-draft", {"amount": "1000.00"})
        key3 = IdempotencyKey.derive("UNIT-PR1ME", "invoice-draft", {"amount": "1000.00"})

        self.assertEqual(key1.value, key2.value)
        self.assertNotEqual(key1.value, key3.value)
        self.assertEqual(len(key1.value), 71)  # "sha256:" + 64 hex chars
        self.assertTrue(key1.value.startswith("sha256:"))

    def test_canonical_payload_is_sorted(self) -> None:
        from src.mutations.idempotency import IdempotencyKey

        key = IdempotencyKey.derive("UNIT-BANYUMEDIA", "action", {"z": 1, "a": 2})
        payload = key.to_canonical_payload()
        self.assertEqual(list(payload.keys()), ["key"])
        self.assertEqual(payload["key"], key.value)


if __name__ == "__main__":
    unittest.main()
