"""RED-first tests for UNIT-001 QA remediation (deleg_82bd8428 findings).

C1: concurrent rollback must leave zero orphan rows for the CAS loser.
H1: effective_from regression (new < current active) rejected.
H2: issues_ppn bool coercion fail-closed (only exact true/false accepted).
H3: scalar service_categories (str) rejected, never char-split.
H4: unknown catalog keys rejected (strict schema).
M1: registry enforces <=1 PPN issuer and alias sharing must be intentional.
M2: denied CAS activations are audited (activate_denied).
L2: audit_events/preview fail closed on unknown unit.
L4: approval_threshold_amount has a sane upper bound.
"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone


def _t(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _store():
    from src.units.registry import UnitRegistry
    from src.units.settings import UnitSettingsStore

    return UnitSettingsStore(UnitRegistry.default())


class TestConcurrentRollbackNoOrphan(unittest.TestCase):
    def test_concurrent_rollback_loser_leaves_no_row(self) -> None:
        """C1: two racing rollbacks on the same expected_version must produce
        exactly one winner and ZERO orphan DRAFT rows for the loser."""
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 14}, author="a", at=_t())
        store.activate("BANYUMEDIA", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(2))
        d2 = store.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 99}, author="a", at=_t(3))
        store.activate("BANYUMEDIA", d2.configuration_version, expected_version=1, at=_t(4), actor="bos", effective_from=_t(5))

        winners: list[int] = []
        losers: list[Exception] = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def racer(tag: str) -> None:
            barrier.wait()
            try:
                rolled = store.rollback(
                    "BANYUMEDIA", to_version=1, expected_version=2,
                    at=_t(6), actor="bos", effective_from=_t(7), reason=f"race-{tag}",
                )
                with lock:
                    winners.append(rolled.configuration_version)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    losers.append(exc)

        for trial in range(30):
            store2 = _store()
            dd1 = store2.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 14}, author="a", at=_t())
            store2.activate("BANYUMEDIA", dd1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(2))
            dd2 = store2.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 99}, author="a", at=_t(3))
            store2.activate("BANYUMEDIA", dd2.configuration_version, expected_version=1, at=_t(4), actor="bos", effective_from=_t(5))
            winners.clear(); losers.clear()
            barrier = threading.Barrier(2)

            def racer2(tag: str, s=store2, b=barrier) -> None:
                b.wait()
                try:
                    rolled = s.rollback(
                        "BANYUMEDIA", to_version=1, expected_version=2,
                        at=_t(6), actor="bos", effective_from=_t(7), reason=f"race-{tag}",
                    )
                    with lock:
                        winners.append(rolled.configuration_version)
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        losers.append(exc)

            t1 = threading.Thread(target=racer2, args=("x",))
            t2 = threading.Thread(target=racer2, args=("y",))
            t1.start(); t2.start(); t1.join(); t2.join()
            self.assertEqual(len(winners), 1, f"trial {trial}: exactly one winner, got {winners}")
            self.assertEqual(len(losers), 1, f"trial {trial}: exactly one loser")
            versions = [v for v in store2._versions.get("BANYUMEDIA", [])]
            drafts = [v for v in versions if v.status.value == "DRAFT"]
            self.assertEqual(drafts, [], f"trial {trial}: orphan drafts leaked: {[v.configuration_version for v in drafts]}")


class TestEffectiveFromMonotonic(unittest.TestCase):
    def test_effective_from_regression_rejected(self) -> None:
        """H1: activating a new version with effective_from earlier than the
        current active version's effective_from must fail."""
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        store.activate("BANYUMEDIA", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(10))
        d2 = store.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 30}, author="a", at=_t(11))
        with self.assertRaises(Exception) as ctx:
            store.activate("BANYUMEDIA", d2.configuration_version, expected_version=1, at=_t(12), actor="bos", effective_from=_t(5))
        self.assertIn("effective_from", str(ctx.exception).lower())
        # The prior version must still be ACTIVE and servable (no empty gap).
        active = store.get_active("BANYUMEDIA", at=_t(11))
        self.assertEqual(active.configuration_version, 1)


class TestCatalogStrictness(unittest.TestCase):
    def test_issues_ppn_rejects_non_bool_scalar(self) -> None:
        """H2: issues_ppn must come from exact true/false; coercion of '0',
        'off', 'no', 'True' etc. must fail closed."""
        from src.domain.errors import InvalidDomainValue
        from src.units import registry as reg_mod

        for bad in ("0", "off", "no", "True", "yes", "1"):
            with self.subTest(bad=bad), self.assertRaises(InvalidDomainValue):
                reg_mod._load_catalog_from_text(
                    f"units:\n  - code: BADX\n    display_name: Bad\n    account_alias: acct_badx\n    issues_ppn: {bad}\n    service_categories: [x]\n"
                )

    def test_service_categories_scalar_rejected(self) -> None:
        """H3: 'service_categories: seo' (str) must fail, never char-split."""
        from src.domain.errors import InvalidDomainValue
        from src.units import registry as reg_mod

        with self.assertRaises(InvalidDomainValue):
            reg_mod._load_catalog_from_text(
                "units:\n  - code: BADX\n    display_name: Bad\n    account_alias: acct_badx\n    issues_ppn: false\n    service_categories: seo\n"
            )

    def test_unknown_catalog_key_rejected(self) -> None:
        """H4: extra keys in a catalog row must fail closed."""
        from src.domain.errors import InvalidDomainValue
        from src.units import registry as reg_mod

        with self.assertRaises(InvalidDomainValue) as ctx:
            reg_mod._load_catalog_from_text(
                "units:\n  - code: BADX\n    display_name: Bad\n    account_alias: acct_badx\n    issues_ppn: false\n    service_categories: [x]\n    extra_secret: hunter2\n"
            )
        self.assertIn("extra_secret", str(ctx.exception))


class TestRegistryInvariants(unittest.TestCase):
    def test_at_most_one_ppn_issuer(self) -> None:
        """M1: a registry with two PPN-issuing units must fail (R-013)."""
        from src.domain.errors import InvalidDomainValue
        from src.units.registry import UnitRegistry, UnitSpec

        a = UnitSpec(code="AAA", display_name="A", account_alias="acct_aaa", issues_ppn=True, service_categories=("x",))
        b = UnitSpec(code="BBB", display_name="B", account_alias="acct_bbb", issues_ppn=True, service_categories=("y",))
        with self.assertRaises(InvalidDomainValue):
            UnitRegistry((a, b))

    def test_alias_sharing_requires_explicit_marker(self) -> None:
        """M1: alias sharing between unrelated units is rejected unless the
        spec explicitly declares it (shared_with)."""
        from src.domain.errors import InvalidDomainValue
        from src.units.registry import UnitRegistry, UnitSpec

        a = UnitSpec(code="AAA", display_name="A", account_alias="acct_dup", issues_ppn=False, service_categories=("x",))
        b = UnitSpec(code="BBB", display_name="B", account_alias="acct_dup", issues_ppn=False, service_categories=("y",))
        with self.assertRaises(InvalidDomainValue):
            UnitRegistry((a, b))
        # Explicit declaration passes
        a2 = UnitSpec(code="AAA", display_name="A", account_alias="acct_dup", issues_ppn=False, service_categories=("x",), shared_with=("BBB",))
        b2 = UnitSpec(code="BBB", display_name="B", account_alias="acct_dup", issues_ppn=False, service_categories=("y",), shared_with=("AAA",))
        reg = UnitRegistry((a2, b2))
        self.assertEqual(reg.get("AAA").account_alias, "acct_dup")


class TestDeniedActivationAudited(unittest.TestCase):
    def test_cas_denial_logged(self) -> None:
        """M2: a failed CAS activation appends an activate_denied audit entry."""
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        store.activate("BANYUMEDIA", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(2))
        d2 = store.draft("BANYUMEDIA", {"default_currency": "USD"}, author="a", at=_t(3))
        with self.assertRaises(Exception):
            store.activate("BANYUMEDIA", d2.configuration_version, expected_version=0, at=_t(4), actor="bos", effective_from=_t(5))
        actions = [e["action"] for e in store.audit_events("BANYUMEDIA")]
        self.assertIn("activate_denied", actions)


class TestFailClosedQueries(unittest.TestCase):
    def test_audit_events_unknown_unit_fails(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.audit_events("NOSUCHUNIT")

    def test_preview_unknown_unit_fails(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.preview("NOSUCHUNIT", 1)


class TestApprovalThresholdCeiling(unittest.TestCase):
    def test_threshold_upper_bound(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.draft("BANYUMEDIA", {"approval_threshold_amount": 10**30}, author="a", at=_t())


class TestSettingsImmutability(unittest.TestCase):
    def test_settings_dict_not_mutable_post_creation(self) -> None:
        """L1: a stored version's settings must not be mutable via the live
        reference handed out by get_version()/get_active()."""
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        fetched = store.get_version("BANYUMEDIA", d1.configuration_version)
        with self.assertRaises((TypeError, AttributeError)):
            fetched.settings["default_currency"] = "HACKED"  # type: ignore[index]
        # Stored value unchanged
        self.assertEqual(
            store.get_version("BANYUMEDIA", d1.configuration_version).settings["default_currency"],
            "IDR",
        )


if __name__ == "__main__":
    unittest.main()
