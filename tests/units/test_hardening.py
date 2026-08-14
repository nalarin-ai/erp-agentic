"""RED-first tests for UNIT-001 slice 3: adversarial lifecycle hardening.

- CAS race: two concurrent activations with the same expected_version must
  yield exactly one winner.
- Hostile inputs: oversized payloads, Unicode confusables in keys, negative
  and bool-as-int, unknown modules, empty settings.
- Audit trail integrity: append-only ordering with monotonic versions.
- No-hardcode scan: source must not branch on unit names (Balonesia etc.).
"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _t(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _store():
    from src.units.registry import UnitRegistry
    from src.units.settings import UnitSettingsStore

    return UnitSettingsStore(UnitRegistry.default())


class TestCASSerialization(unittest.TestCase):
    def test_concurrent_activate_single_winner(self) -> None:
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        store.activate("BANYUMEDIA", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(2))
        d2 = store.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 7}, author="a", at=_t(3))
        d3 = store.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 21}, author="a", at=_t(4))

        winners: list[int] = []
        losers: list[Exception] = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def racer(version: int) -> None:
            barrier.wait()
            try:
                store.activate("BANYUMEDIA", version, expected_version=1, at=_t(5), actor="bos", effective_from=_t(6))
                with lock:
                    winners.append(version)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    losers.append(exc)

        t1 = threading.Thread(target=racer, args=(d2.configuration_version,))
        t2 = threading.Thread(target=racer, args=(d3.configuration_version,))
        t1.start(); t2.start(); t1.join(); t2.join()
        self.assertEqual(len(winners), 1, f"exactly one CAS winner, got {winners}")
        self.assertEqual(len(losers), 1)
        active = store.get_active("BANYUMEDIA", at=_t(7))
        self.assertEqual(active.configuration_version, winners[0])


class TestHostileInputs(unittest.TestCase):
    def test_bool_is_not_int(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.draft("BANYUMEDIA", {"payment_terms_days": True}, author="a", at=_t())

    def test_negative_terms_rejected(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.draft("BANYUMEDIA", {"payment_terms_days": -1}, author="a", at=_t())

    def test_unknown_module_rejected(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.draft("BANYUMEDIA", {"enabled_modules": ("invoicing", "crypto_miner")}, author="a", at=_t())

    def test_unicode_confusable_key_rejected(self) -> None:
        store = _store()
        # 'defаult_currency' with Cyrillic 'а'
        with self.assertRaises(Exception):
            store.draft("BANYUMEDIA", {"defаult_currency": "IDR"}, author="a", at=_t())

    def test_empty_settings_rejected(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.draft("BANYUMEDIA", {}, author="a", at=_t())

    def test_oversized_string_rejected(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.draft("BANYUMEDIA", {"invoice_template_ref": "a" * 500}, author="a", at=_t())

    def test_unknown_unit_settings_fail_closed(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.draft("NOSUCHUNIT", {"default_currency": "IDR"}, author="a", at=_t())


class TestAuditTrail(unittest.TestCase):
    def test_audit_is_append_only_and_ordered(self) -> None:
        store = _store()
        d1 = store.draft("PR1ME", {"default_currency": "IDR"}, author="a", at=_t())
        store.activate("PR1ME", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(2))
        store.rollback("PR1ME", to_version=1, expected_version=1, at=_t(3), actor="bos", effective_from=_t(4), reason="revert")
        events = store.audit_events("PR1ME")
        actions = [e["action"] for e in events]
        self.assertEqual(actions, ["draft", "activate", "rollback_draft", "activate"])

    def test_audit_isolated_per_unit(self) -> None:
        store = _store()
        store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        store.draft("PR1ME", {"default_currency": "IDR"}, author="a", at=_t())
        self.assertEqual(len(store.audit_events("BANYUMEDIA")), 1)
        self.assertEqual(len(store.audit_events("PR1ME")), 1)


class TestNoHardcodedUnits(unittest.TestCase):
    def test_source_has_no_unit_name_conditionals(self) -> None:
        """The onboarding invariant: no unit-code branches in src/units."""
        import re

        pattern = re.compile(
            r"(if|elif).*?(BANYUMEDIA|PR1ME|CONTRACTOR|HEAVY_EQUIPMENT|BALONESIA|PT_TKH_OPS)"
        )
        offenders = []
        for path in Path("src/units").rglob("*.py"):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path}:{lineno}:{line.strip()}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
