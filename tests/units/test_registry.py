"""RED-first tests for UNIT-001: unit registry and onboarding schema.

Covers (slice 1): registered unit catalog, opaque IDs, no credential/raw
account material, shared-account mapping rule (Heavy Equipment shares the
Contractor account alias), PT_TKH_OPS as PPN issuer, and the
no-hardcode-onboarding invariant (Balonesia + a synthetic extra unit come
from fixtures, not source branches).
"""
from __future__ import annotations

import unittest


class TestUnitRegistry(unittest.TestCase):
    def test_catalog_contains_all_confirmed_units(self) -> None:
        from src.units.registry import UnitRegistry

        registry = UnitRegistry.default()
        codes = {unit.code for unit in registry.all()}
        self.assertEqual(
            codes,
            {"BANYUMEDIA", "PR1ME", "CONTRACTOR", "HEAVY_EQUIPMENT", "PT_TKH_OPS", "BALONESIA"},
        )

    def test_unit_ids_are_opaque_and_stable(self) -> None:
        from src.units.registry import UnitRegistry

        registry = UnitRegistry.default()
        for unit in registry.all():
            self.assertTrue(unit.unit_id.startswith("unit_"), unit.unit_id)
            self.assertNotIn(" ", unit.unit_id)
        # Stable across registry instances
        again = UnitRegistry.default()
        self.assertEqual(
            {u.code: u.unit_id for u in registry.all()},
            {u.code: u.unit_id for u in again.all()},
        )

    def test_heavy_equipment_shares_contractor_account_alias(self) -> None:
        from src.units.registry import UnitRegistry

        registry = UnitRegistry.default()
        heavy = registry.get("HEAVY_EQUIPMENT")
        contractor = registry.get("CONTRACTOR")
        self.assertEqual(heavy.account_alias, contractor.account_alias)
        # But they remain distinct ledgers/units
        self.assertNotEqual(heavy.unit_id, contractor.unit_id)

    def test_other_units_have_distinct_account_aliases(self) -> None:
        from src.units.registry import UnitRegistry

        registry = UnitRegistry.default()
        aliases = {}
        for code in ("BANYUMEDIA", "PR1ME", "CONTRACTOR", "BALONESIA", "PT_TKH_OPS"):
            alias = registry.get(code).account_alias
            self.assertNotIn(alias, aliases, f"alias collision at {code}")
            aliases[alias] = code

    def test_pt_tkh_ops_is_the_ppn_issuer(self) -> None:
        from src.units.registry import UnitRegistry

        registry = UnitRegistry.default()
        ppn_issuers = [u.code for u in registry.all() if u.issues_ppn]
        self.assertEqual(ppn_issuers, ["PT_TKH_OPS"])

    def test_no_raw_account_numbers_or_credentials(self) -> None:
        import re

        from src.units.registry import UnitRegistry

        registry = UnitRegistry.default()
        digit_run = re.compile(r"\d{8,}")
        for unit in registry.all():
            blob = repr(unit)
            self.assertIsNone(digit_run.search(blob), f"raw number-like material in {unit.code}")
            lowered = blob.lower()
            for marker in ("password", "secret", "token", "api_key", "sk-"):
                self.assertNotIn(marker, lowered)

    def test_unknown_unit_fails_closed(self) -> None:
        from src.domain.errors import InvalidDomainValue
        from src.units.registry import UnitRegistry

        registry = UnitRegistry.default()
        with self.assertRaises((InvalidDomainValue, KeyError, LookupError)):
            registry.get("UNKNOWN_UNIT")

    def test_balonesia_onboarding_is_fixture_driven(self) -> None:
        """Balonesia exists purely via fixture registration; adding a new
        synthetic unit requires no source change beyond fixture data."""
        from src.units.registry import UnitRegistry, UnitSpec

        registry = UnitRegistry.default()
        before = len(registry.all())
        synthetic = UnitSpec(
            code="SYNTHX",
            display_name="Synthetic X",
            account_alias="acct_synthx",
            issues_ppn=False,
            service_categories=("testing",),
        )
        extended = registry.with_unit(synthetic)
        self.assertEqual(len(extended.all()), before + 1)
        self.assertEqual(extended.get("SYNTHX").display_name, "Synthetic X")
        # Original registry unchanged (immutability)
        with self.assertRaises((KeyError, LookupError, Exception)):
            registry.get("SYNTHX")


if __name__ == "__main__":
    unittest.main()
