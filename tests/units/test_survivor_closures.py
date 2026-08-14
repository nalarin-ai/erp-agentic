"""RED tests closing the 3 surviving UNIT-001 mutants.

- M1: unknown settings key must fail even when another valid key is present
  (guards the `_ALLOWED` membership check itself).
- M2: script-like content must fail for each ref-typed setting
  (guards the `_FORBIDDEN_TEXT` scan itself, not only the ref regex).
- M3: duplicate unit codes in a catalog/registry input must fail
  (guards the duplicate check itself).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone


def _t() -> datetime:
    return datetime(2026, 8, 14, tzinfo=timezone.utc)


class TestUnknownKeyGuard(unittest.TestCase):
    def test_unknown_key_rejected_even_with_valid_companion(self) -> None:
        from src.units.registry import UnitRegistry
        from src.units.settings import UnitSettingsStore

        store = UnitSettingsStore(UnitRegistry.default())
        with self.assertRaises(Exception) as ctx:
            store.draft(
                "BANYUMEDIA",
                {"default_currency": "IDR", "stealth_key": "x"},
                author="a", at=_t(),
            )
        self.assertIn("stealth_key", str(ctx.exception))

    def test_unknown_key_rejected_when_value_would_pass_type_checks(self) -> None:
        """Guards `_ALLOWED` membership itself: use an unknown key whose value
        is a plain valid str; only the membership check can reject it.
        Must raise the domain error, not an incidental KeyError."""
        from src.domain.errors import InvalidDomainValue
        from src.units.registry import UnitRegistry
        from src.units.settings import UnitSettingsStore

        store = UnitSettingsStore(UnitRegistry.default())
        with self.assertRaises(InvalidDomainValue) as ctx:
            store.draft("BANYUMEDIA", {"stealth_text": "plainvalue"}, author="a", at=_t())
        self.assertIn("stealth_text", str(ctx.exception))


class TestForbiddenContentGuard(unittest.TestCase):
    def test_script_payload_rejected_in_every_ref_field(self) -> None:
        from src.units.registry import UnitRegistry
        from src.units.settings import UnitSettingsStore

        store = UnitSettingsStore(UnitRegistry.default())
        # Use a payload that PASSES the opaque-ref regex shape except for the
        # forbidden content itself: lowercase base + ';' separator.
        for key in ("invoice_template_ref", "quotation_template_ref", "logo_asset_ref", "numbering_series_ref"):
            with self.subTest(key=key):
                with self.assertRaises(Exception):
                    store.draft("BANYUMEDIA", {key: "abc;<script>x"}, author="a", at=_t())

    def test_forbidden_scan_applies_to_free_text_values(self) -> None:
        """The `_FORBIDDEN_TEXT` scan must fire even when no shape regex would
        reject the value: `enabled_modules` is a tuple, so its elements never
        pass through `_REF`. Only the forbidden-content scan can reject this."""
        from src.units.registry import UnitRegistry
        from src.units.settings import UnitSettingsStore

        store = UnitSettingsStore(UnitRegistry.default())
        with self.assertRaises(Exception) as ctx:
            store.draft(
                "BANYUMEDIA",
                {"enabled_modules": ("invoicing", "crm;<script>")},
                author="a", at=_t(),
            )
        self.assertNotIn("unknown modules", str(ctx.exception))

    def test_forbidden_scan_protects_free_text_tagline(self) -> None:
        """`branding_tagline` is allowlisted free text with no shape regex;
        only the forbidden-content scan can reject hostile content."""
        from src.domain.errors import InvalidDomainValue
        from src.units.registry import UnitRegistry
        from src.units.settings import UnitSettingsStore

        store = UnitSettingsStore(UnitRegistry.default())
        # benign tagline passes
        ok = store.draft("BANYUMEDIA", {"branding_tagline": "Grow your brand"}, author="a", at=_t())
        self.assertEqual(ok.settings["branding_tagline"], "Grow your brand")
        # hostile tagline rejected by the scan alone
        with self.assertRaises(InvalidDomainValue) as ctx:
            store.draft("BANYUMEDIA", {"branding_tagline": "hello;<script>alert(1)</script>"}, author="a", at=_t())
        self.assertIn("forbidden", str(ctx.exception))

    def test_currency_field_rejects_script_too(self) -> None:
        """Currency payloads with forbidden content must raise the domain
        error (layered with the ISO shape check; either guard may fire)."""
        from src.domain.errors import InvalidDomainValue
        from src.units.registry import UnitRegistry
        from src.units.settings import UnitSettingsStore

        store = UnitSettingsStore(UnitRegistry.default())
        with self.assertRaises(InvalidDomainValue):
            store.draft("BANYUMEDIA", {"default_currency": "ID<script>"}, author="a", at=_t())


class TestDuplicateCodeGuard(unittest.TestCase):
    def test_duplicate_unit_code_rejected(self) -> None:
        from src.domain.errors import InvalidDomainValue
        from src.units.registry import UnitRegistry, UnitSpec

        a = UnitSpec(code="DUPX", display_name="A", account_alias="acct_dupa", issues_ppn=False, service_categories=("x",))
        b = UnitSpec(code="DUPX", display_name="B", account_alias="acct_dupb", issues_ppn=False, service_categories=("y",))
        with self.assertRaises(InvalidDomainValue):
            UnitRegistry((a, b))


if __name__ == "__main__":
    unittest.main()
