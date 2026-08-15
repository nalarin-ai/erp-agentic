"""MVP-AC-15: new unit + variable behavior without hardcode (UNIT-001, UX-001).

Criteria (TRACEABILITY_MATRIX.md section D): a new operating unit onboards
purely through config/settings lifecycle — never via a unit-name source
branch. Unknown/script settings, invalid references, unauthorized
activation, version conflicts, and rollback mismatch all fail closed; a
grep scan proves ``src/`` contains no per-unit-name branch.

Scenarios:
1. Onboard a synthetic new unit end-to-end through the config lifecycle:
   catalog spec → settings draft → activate → behavior resolves → rollback.
2. Unknown setting key is rejected (fail closed).
3. Script-like / forbidden setting value is rejected.
4. Invalid reference shape is rejected.
5. Unauthorized activation (non-draft version / wrong CAS) is rejected.
6. expected_version conflict on activate is rejected (CAS).
7. Rollback mismatch (expected_version drift) is detected and rejected;
   a correct rollback restores the prior snapshot as a NEW version.
8. Source scan: no unit-name branch in src/ logic (BANYUMEDIA|PR1ME|
   CONTRACTOR|HEAVY_EQUIPMENT|PT_TKH) — names live in fixture/config only.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.domain.errors import InvalidDomainValue
from src.units.registry import UnitRegistry, UnitSpec, _load_catalog_from_text
from src.units.settings import UnitSettingsStore

from tests.e2e.pilot._harness import at

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"

# A brand-new synthetic unit that exists ONLY in the test (never in src/ or
# the shipped catalog) — proving onboarding is data-driven.
NEW_UNIT = UnitSpec(
    code="ZEPHYR_LABS",
    display_name="Zephyr Labs",
    account_alias="acct_zephyr_labs",
    issues_ppn=False,
    service_categories=("synthetic_consulting",),
)
NEW_UNIT_SETTINGS = {
    "default_currency": "IDR",
    "invoice_template_ref": "tpl_zephyr_v1",
    "logo_asset_ref": "logo_zephyr_v1",
    "payment_terms_days": 21,
    "enabled_modules": ("invoicing", "crm"),
}


def _store_with_new_unit() -> tuple[UnitRegistry, UnitSettingsStore]:
    registry = UnitRegistry.default().with_unit(NEW_UNIT)
    return registry, UnitSettingsStore(registry)


class TestAc15NoHardcodeOnboarding(unittest.TestCase):
    # -- 1. onboard purely via config lifecycle --------------------------------

    def test_new_unit_onboards_via_config_draft_activate_rollback(self) -> None:
        registry, store = _store_with_new_unit()
        # The new unit resolves from the registry like any catalog row.
        self.assertEqual(registry.get("ZEPHYR_LABS").account_alias,
                         "acct_zephyr_labs")
        # Draft → activate (CAS expected_version=0: nothing active yet).
        drafted = store.draft("ZEPHYR_LABS", dict(NEW_UNIT_SETTINGS),
                              author="onboard-bot", at=at(0))
        self.assertEqual(drafted.configuration_version, 1)
        activated = store.activate(
            "ZEPHYR_LABS", drafted.configuration_version, expected_version=0,
            at=at(0), actor="onboard-bot", effective_from=at(1))
        self.assertEqual(activated.status.value, "ACTIVE")
        # Behavior resolves from ACTIVE settings (variable, not hardcoded).
        active = store.get_active("ZEPHYR_LABS", at=at(5))
        self.assertEqual(active.settings["invoice_template_ref"], "tpl_zephyr_v1")
        self.assertEqual(active.settings["payment_terms_days"], 21)
        # Change behavior via a NEW draft+activate (no source change).
        v2 = store.draft("ZEPHYR_LABS",
                         {**NEW_UNIT_SETTINGS, "payment_terms_days": 45},
                         author="onboard-bot", at=at(10))
        store.activate("ZEPHYR_LABS", v2.configuration_version,
                       expected_version=1, at=at(10), actor="onboard-bot",
                       effective_from=at(11))
        self.assertEqual(store.get_active("ZEPHYR_LABS", at=at(15))
                         .settings["payment_terms_days"], 45)
        # Rollback restores the prior snapshot as a NEW version.
        rolled = store.rollback(
            "ZEPHYR_LABS", to_version=1, expected_version=2, at=at(20),
            actor="onboard-bot", effective_from=at(21),
            reason="revert terms")
        self.assertEqual(rolled.rollback_of, 1)
        self.assertEqual(store.get_active("ZEPHYR_LABS", at=at(25))
                         .settings["payment_terms_days"], 21)
        # The whole lifecycle is audited.
        actions = [e["action"] for e in store.audit_events("ZEPHYR_LABS")]
        self.assertIn("draft", actions)
        self.assertIn("activate", actions)
        self.assertIn("rollback_draft", actions)

    def test_new_unit_catalog_row_parses_as_data(self) -> None:
        """A catalog row is data: the strict parser accepts a valid synthetic
        unit block with no code change."""
        text = (
            "units:\n"
            "  - code: ZEPHYR_LABS\n"
            "    display_name: Zephyr Labs\n"
            "    account_alias: acct_zephyr_labs\n"
            "    issues_ppn: false\n"
            "    service_categories: [synthetic_consulting]\n"
        )
        specs = _load_catalog_from_text(text)
        self.assertEqual(specs[0].code, "ZEPHYR_LABS")
        self.assertFalse(specs[0].issues_ppn)

    # -- 2. unknown setting rejected --------------------------------------------

    def test_unknown_setting_key_rejected(self) -> None:
        _registry, store = _store_with_new_unit()
        with self.assertRaises(InvalidDomainValue):
            store.draft("ZEPHYR_LABS",
                        {**NEW_UNIT_SETTINGS, "tax_profile_ref": "TAX-EVIL"},
                        author="onboard-bot", at=at(0))

    # -- 3. script-like setting rejected ------------------------------------------

    def test_script_like_setting_rejected(self) -> None:
        _registry, store = _store_with_new_unit()
        for hostile in (
            {**NEW_UNIT_SETTINGS, "branding_tagline": "<script>alert(1)</script>"},
            {**NEW_UNIT_SETTINGS, "branding_tagline": "javascript:alert(1)"},
            {**NEW_UNIT_SETTINGS, "invoice_template_ref": "tpl;DROP TABLE"},
        ):
            with self.assertRaises(InvalidDomainValue):
                store.draft("ZEPHYR_LABS", hostile, author="onboard-bot",
                            at=at(0))

    # -- 4. invalid reference rejected ----------------------------------------------

    def test_invalid_reference_shape_rejected(self) -> None:
        _registry, store = _store_with_new_unit()
        with self.assertRaises(InvalidDomainValue):
            store.draft("ZEPHYR_LABS",
                        {**NEW_UNIT_SETTINGS,
                         "invoice_template_ref": "Tpl Zephyr V1!"},  # invalid
                        author="onboard-bot", at=at(0))

    # -- 5. unauthorized activation rejected ------------------------------------------

    def test_activation_of_non_draft_rejected(self) -> None:
        """Only a DRAFT version can be activated; re-activating an ACTIVE
        version (or a bogus one) fails closed."""
        _registry, store = _store_with_new_unit()
        drafted = store.draft("ZEPHYR_LABS", dict(NEW_UNIT_SETTINGS),
                              author="onboard-bot", at=at(0))
        store.activate("ZEPHYR_LABS", 1, expected_version=0, at=at(0),
                       actor="onboard-bot", effective_from=at(1))
        with self.assertRaises(InvalidDomainValue):
            store.activate("ZEPHYR_LABS", 1, expected_version=1, at=at(2),
                           actor="onboard-bot", effective_from=at(3))
        with self.assertRaises(InvalidDomainValue):
            store.activate("ZEPHYR_LABS", 99, expected_version=1, at=at(2),
                           actor="onboard-bot", effective_from=at(3))

    def test_activate_unknown_unit_rejected(self) -> None:
        """Onboarding an unregistered unit fails closed at the registry."""
        _registry, store = _store_with_new_unit()
        with self.assertRaises(InvalidDomainValue):
            store.draft("NOPE_UNIT", dict(NEW_UNIT_SETTINGS),
                        author="onboard-bot", at=at(0))

    # -- 6. expected_version conflict rejected -------------------------------------------

    def test_expected_version_conflict_rejected(self) -> None:
        """CAS: activation with a stale expected_version loses — exactly one
        winner; the loser leaves zero rows."""
        _registry, store = _store_with_new_unit()
        store.draft("ZEPHYR_LABS", dict(NEW_UNIT_SETTINGS),
                    author="onboard-bot", at=at(0))
        store.activate("ZEPHYR_LABS", 1, expected_version=0, at=at(0),
                       actor="onboard-bot", effective_from=at(1))
        v2 = store.draft("ZEPHYR_LABS",
                         {**NEW_UNIT_SETTINGS, "payment_terms_days": 30},
                         author="onboard-bot", at=at(5))
        # Stale CAS: expected 0 but active is already 1.
        with self.assertRaises(InvalidDomainValue) as ctx:
            store.activate("ZEPHYR_LABS", v2.configuration_version,
                           expected_version=0, at=at(6), actor="onboard-bot",
                           effective_from=at(7))
        self.assertIn("version conflict", str(ctx.exception))
        # Denied CAS is audited.
        self.assertTrue(any(
            e["action"] == "activate_denied"
            for e in store.audit_events("ZEPHYR_LABS")))

    # -- 7. rollback mismatch detected ------------------------------------------------------

    def test_rollback_expected_version_mismatch_detected(self) -> None:
        """Rollback CAS is evaluated BEFORE mutation: a stale expected_version
        is detected and rejected, and no rollback row is appended."""
        _registry, store = _store_with_new_unit()
        store.draft("ZEPHYR_LABS", dict(NEW_UNIT_SETTINGS),
                    author="onboard-bot", at=at(0))
        store.activate("ZEPHYR_LABS", 1, expected_version=0, at=at(0),
                       actor="onboard-bot", effective_from=at(1))
        v2 = store.draft("ZEPHYR_LABS",
                         {**NEW_UNIT_SETTINGS, "payment_terms_days": 30},
                         author="onboard-bot", at=at(5))
        store.activate("ZEPHYR_LABS", v2.configuration_version,
                       expected_version=1, at=at(5), actor="onboard-bot",
                       effective_from=at(6))
        versions_before = len(store.audit_events("ZEPHYR_LABS"))
        # Mismatched CAS (expected 1, active 2) → detected, no mutation.
        with self.assertRaises(InvalidDomainValue) as ctx:
            store.rollback("ZEPHYR_LABS", to_version=1, expected_version=1,
                           at=at(10), actor="onboard-bot",
                           effective_from=at(11), reason="stale cas")
        self.assertIn("version conflict", str(ctx.exception))
        # Active settings are untouched by the failed rollback.
        self.assertEqual(store.get_active("ZEPHYR_LABS", at=at(12))
                         .settings["payment_terms_days"], 30)
        self.assertTrue(any(
            e["action"] == "activate_denied"
            for e in store.audit_events("ZEPHYR_LABS")[versions_before:]))

    # -- 8. no per-unit-name source branch ------------------------------------------------------

    def test_src_contains_no_unit_name_branch(self) -> None:
        """UNIT-001: unit behavior is config-driven; ``src/`` logic must not
        branch on a specific unit name. Fixture/config/docs are exempt.

        Scope: only *code* lines are scanned. Docstring/comment prose that
        mentions a unit name is documentation, not a behavior branch — such
        a mention is recorded as a finding in ac-15.md (F-a) but is not a
        logic hardcode. A unit-name hit inside an executable statement
        (assignment/condition/call) WOULD fail here.
        """
        import ast
        pattern = re.compile(
            r"\b(BANYUMEDIA|PR1ME|CONTRACTOR|HEAVY_EQUIPMENT|PT_TKH)\b")
        offenders: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            # Identify docstring/comment line ranges via the AST so prose
            # mentions are exempt while executable statements are caught.
            docstring_lines: set[int] = set()
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(
                        node,
                        (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef),
                    ):
                        body = getattr(node, "body", [])
                        if body and isinstance(body[0], ast.Expr) and isinstance(
                                body[0].value, ast.Constant):
                            for ln in range(body[0].lineno,
                                            (body[0].end_lineno or body[0].lineno) + 1):
                                docstring_lines.add(ln)
            for lineno, line in enumerate(text.splitlines(), 1):
                if lineno in docstring_lines:
                    continue
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if pattern.search(line):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: {stripped}")
        self.assertEqual(
            offenders, [],
            "unit-name branch(es) found in src/ logic:\n" + "\n".join(offenders))

    def test_catalog_is_the_only_unit_source_of_truth(self) -> None:
        """The default registry loads every catalog row as data — no unit is
        special-cased; all six fixture units resolve uniformly."""
        registry = UnitRegistry.default()
        codes = {spec.code for spec in registry.all()}
        self.assertEqual(
            codes,
            {"BANYUMEDIA", "PR1ME", "CONTRACTOR", "HEAVY_EQUIPMENT",
             "PT_TKH_OPS", "BALONESIA"})
        # Exactly one PPN issuer is a catalog invariant, not code.
        self.assertEqual(
            sum(1 for spec in registry.all() if spec.issues_ppn), 1)


if __name__ == "__main__":
    unittest.main()
