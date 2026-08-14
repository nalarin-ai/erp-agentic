"""RED-first tests for UNIT-001 slice 2: versioned unit settings lifecycle.

Covers R-022 (typed versioned settings, draft/validate/preview/activate/
rollback, CAS expected_version, non-overlapping effective intervals, unknown
keys fail closed) and R-020 hooks (branding version reference, protected
financial identity fields cannot be set by branding).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone


def _t(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _store():
    from src.units.settings import UnitSettingsStore
    from src.units.registry import UnitRegistry

    return UnitSettingsStore(UnitRegistry.default())


class TestSettingsSchema(unittest.TestCase):
    def test_unknown_setting_key_fails_closed(self) -> None:
        store = _store()
        with self.assertRaises(Exception) as ctx:
            store.draft("BANYUMEDIA", {"unknown_key": 1}, author="alice", at=_t())
        self.assertIn("unknown", str(ctx.exception).lower())

    def test_wrong_value_type_fails_closed(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.draft("BANYUMEDIA", {"default_currency": 123}, author="alice", at=_t())

    def test_script_like_payload_rejected(self) -> None:
        store = _store()
        with self.assertRaises(Exception):
            store.draft(
                "BANYUMEDIA",
                {"invoice_template_ref": "<script>alert(1)</script>"},
                author="alice", at=_t(),
            )

    def test_protected_financial_fields_not_settable_via_settings(self) -> None:
        """Branding/settings must never override issuer/tax/series/ledger/
        account identity (R-020); those keys are not registered settings."""
        store = _store()
        for protected in ("issuer_name", "tax_id", "invoice_series", "ledger_id", "account_number"):
            with self.subTest(protected=protected), self.assertRaises(Exception):
                store.draft("BANYUMEDIA", {protected: "x"}, author="alice", at=_t())

    def test_registered_settings_accepted(self) -> None:
        store = _store()
        draft = store.draft(
            "BANYUMEDIA",
            {
                "default_currency": "IDR",
                "invoice_template_ref": "tpl_banyumedia_v1",
                "logo_asset_ref": "logo_banyumedia_v1",
                "payment_terms_days": 14,
                "enabled_modules": ("invoicing", "crm"),
            },
            author="alice", at=_t(),
        )
        self.assertEqual(draft.status.value, "DRAFT")
        self.assertEqual(draft.configuration_version, 1)


class TestSettingsLifecycle(unittest.TestCase):
    def test_activate_then_get_active(self) -> None:
        store = _store()
        draft = store.draft("PR1ME", {"default_currency": "IDR"}, author="alice", at=_t())
        activated = store.activate(
            "PR1ME", draft.configuration_version,
            expected_version=0, at=_t(1), actor="bos",
            effective_from=_t(2),
        )
        self.assertEqual(activated.status.value, "ACTIVE")
        active = store.get_active("PR1ME", at=_t(3))
        self.assertEqual(active.configuration_version, 1)
        self.assertEqual(active.settings["default_currency"], "IDR")

    def test_cas_conflict_on_expected_version(self) -> None:
        store = _store()
        d1 = store.draft("CONTRACTOR", {"default_currency": "IDR"}, author="a", at=_t())
        store.activate("CONTRACTOR", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(2))
        d2 = store.draft("CONTRACTOR", {"default_currency": "USD"}, author="a", at=_t(3))
        # Stale expected_version must lose the CAS race
        with self.assertRaises(Exception) as ctx:
            store.activate("CONTRACTOR", d2.configuration_version, expected_version=0, at=_t(4), actor="bos", effective_from=_t(5))
        self.assertIn("version", str(ctx.exception).lower())
        # Correct CAS wins
        ok = store.activate("CONTRACTOR", d2.configuration_version, expected_version=1, at=_t(4), actor="bos", effective_from=_t(5))
        self.assertEqual(ok.status.value, "ACTIVE")

    def test_non_overlapping_effective_intervals(self) -> None:
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        store.activate("BANYUMEDIA", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(10))
        d2 = store.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 30}, author="a", at=_t(11))
        # Overlapping effective_from before the prior version's open end is fine
        # only if activation retires the prior version atomically; query at t=12
        # must return exactly one active version.
        store.activate("BANYUMEDIA", d2.configuration_version, expected_version=1, at=_t(12), actor="bos", effective_from=_t(13))
        active = store.get_active("BANYUMEDIA", at=_t(14))
        self.assertEqual(active.configuration_version, 2)
        # Prior version retired
        self.assertEqual(store.get_version("BANYUMEDIA", 1).status.value, "RETIRED")

    def test_monotonic_version_per_unit(self) -> None:
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        d2 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t(1))
        self.assertLess(d1.configuration_version, d2.configuration_version)

    def test_versions_are_isolated_per_unit(self) -> None:
        store = _store()
        a = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        b = store.draft("PR1ME", {"default_currency": "IDR"}, author="a", at=_t())
        self.assertEqual(a.configuration_version, 1)
        self.assertEqual(b.configuration_version, 1)

    def test_rollback_restores_prior_snapshot_as_new_version(self) -> None:
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 14}, author="a", at=_t())
        store.activate("BANYUMEDIA", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(2))
        d2 = store.draft("BANYUMEDIA", {"default_currency": "IDR", "payment_terms_days": 99}, author="a", at=_t(3))
        store.activate("BANYUMEDIA", d2.configuration_version, expected_version=1, at=_t(4), actor="bos", effective_from=_t(5))
        rolled = store.rollback("BANYUMEDIA", to_version=1, expected_version=2, at=_t(6), actor="bos", effective_from=_t(7), reason="bad terms")
        self.assertEqual(rolled.status.value, "ACTIVE")
        self.assertEqual(rolled.configuration_version, 3)  # new version, not in-place
        self.assertEqual(rolled.settings["payment_terms_days"], 14)
        active = store.get_active("BANYUMEDIA", at=_t(8))
        self.assertEqual(active.configuration_version, 3)

    def test_rollback_to_unknown_version_fails(self) -> None:
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        store.activate("BANYUMEDIA", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(2))
        with self.assertRaises(Exception):
            store.rollback("BANYUMEDIA", to_version=99, expected_version=1, at=_t(2), actor="bos", effective_from=_t(3), reason="x")

    def test_preview_is_read_only(self) -> None:
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="a", at=_t())
        preview = store.preview("BANYUMEDIA", d1.configuration_version)
        self.assertIn("default_currency", preview)
        # Preview must not activate anything
        with self.assertRaises(Exception):
            store.get_active("BANYUMEDIA", at=_t(1))

    def test_every_transition_audited(self) -> None:
        store = _store()
        d1 = store.draft("BANYUMEDIA", {"default_currency": "IDR"}, author="alice", at=_t())
        store.activate("BANYUMEDIA", d1.configuration_version, expected_version=0, at=_t(1), actor="bos", effective_from=_t(2))
        events = store.audit_events("BANYUMEDIA")
        actions = [e["action"] for e in events]
        self.assertEqual(actions, ["draft", "activate"])
        self.assertEqual(events[0]["actor"], "alice")
        self.assertEqual(events[1]["actor"], "bos")


if __name__ == "__main__":
    unittest.main()
