"""MVP-AC-13: distinct unit logo/template + immutable posted branding snapshot.

Criteria (TRACEABILITY_MATRIX.md section D; R-020):
- Each unit renders its own versioned logo/template (distinct per unit).
- Posted invoices freeze the branding/config snapshot: later settings
  changes do NOT rewrite historical posted records (no historical rewrite).
- Financial identity on the posted record always comes from FND-003 policy,
  never from branding/settings (settings schema has no such keys).
"""
from __future__ import annotations

import unittest

from tests.e2e.pilot._harness import (
    PilotHarness,
    UNIT_BANYUMEDIA,
    UNIT_CONTRACTOR,
)


class TestAc13BrandingSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PilotHarness.build()

    def test_units_have_distinct_templates_and_logos(self) -> None:
        h = self.harness
        preview_b = self._preview(h.banyumedia_requester, UNIT_BANYUMEDIA,
                                  "CUST-BR-1")
        preview_c = self._preview(h.contractor_requester, UNIT_CONTRACTOR,
                                  "CUST-BR-2")
        self.assertNotEqual(preview_b.invoice_template_ref,
                            preview_c.invoice_template_ref)
        self.assertNotEqual(preview_b.logo_asset_ref, preview_c.logo_asset_ref)
        self.assertEqual(preview_b.invoice_template_ref, "tpl_banyu_v1")
        self.assertEqual(preview_c.invoice_template_ref, "tpl_contractor_v1")

    def test_posted_invoice_freezes_branding_snapshot(self) -> None:
        h = self.harness
        preview, result = h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref="CUST-BR-3",
        )
        self.assertEqual(result.outcome, "POSTED")
        record = h.get_posted_invoice(result.official_ref or "")
        self.assertEqual(record.invoice_template_ref, preview.invoice_template_ref)
        self.assertEqual(record.logo_asset_ref, preview.logo_asset_ref)
        self.assertEqual(record.configuration_version,
                         preview.configuration_version)
        self.assertTrue(record.pdf_reference.startswith(
            f"PDF-{preview.invoice_template_ref}-{record.official_ref}-"
        ))

    def test_later_branding_change_does_not_rewrite_posted_record(self) -> None:
        """Immutable posted branding: activate a new settings version with a
        different template/logo AFTER posting; the historical posted record
        must still show the frozen snapshot and the same pdf_reference."""
        h = self.harness
        preview, result = h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref="CUST-BR-4", at_minutes=10,
        )
        official_ref = result.official_ref or ""
        before = h.get_posted_invoice(official_ref)

        h.change_branding(
            "BANYUMEDIA",
            invoice_template_ref="tpl_banyu_v2",
            logo_asset_ref="logo_banyu_v2",
            at_minutes=30,
        )
        after = h.get_posted_invoice(official_ref)
        self.assertEqual(after.invoice_template_ref, before.invoice_template_ref)
        self.assertEqual(after.logo_asset_ref, before.logo_asset_ref)
        self.assertEqual(after.configuration_version, before.configuration_version)
        self.assertEqual(after.pdf_reference, before.pdf_reference)
        # New previews pick up the NEW branding (fresh version active).
        new_preview = self._preview(h.banyumedia_requester, UNIT_BANYUMEDIA,
                                    "CUST-BR-5", at_minutes=40)
        self.assertEqual(new_preview.invoice_template_ref, "tpl_banyu_v2")
        self.assertNotEqual(new_preview.preview_hash, preview.preview_hash)

    def test_financial_identity_never_comes_from_branding(self) -> None:
        """R-020: posted identity fields are policy-derived; the unit settings
        schema contains NO financial-identity keys, so branding cannot
        override issuer/tax/series/ledger/account even maliciously."""
        h = self.harness
        from src.domain.errors import InvalidDomainValue
        with self.assertRaises(InvalidDomainValue):
            h.settings.draft(
                "BANYUMEDIA",
                {"legal_issuer_ref": "ISSUER-ATTACKER"},  # unknown key
                author="mallory", at=__import__(
                    "tests.e2e.pilot._harness", fromlist=["at"]).at(50),
            )
        # Posted record still binds the policy identity.
        _preview, result = h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref="CUST-BR-6", at_minutes=55,
        )
        record = h.get_posted_invoice(result.official_ref or "")
        self.assertEqual(record.legal_issuer_ref, "ISSUER-BANYUMEDIA")
        self.assertEqual(record.policy_ref, "POLICY-BANYUMEDIA-1")

    # -- helpers -----------------------------------------------------------------

    def _preview(self, requester, unit_ref, customer_ref, at_minutes: int = 10):
        h = self.harness
        handle = h.open_draft(requester, unit_ref, customer_ref=customer_ref,
                              at_minutes=at_minutes)
        h.set_lines(requester, handle.draft_id, h.standard_lines(),
                    at_minutes=at_minutes + 1)
        return h.preview(requester, handle.draft_id, at_minutes=at_minutes + 2)


if __name__ == "__main__":
    unittest.main()
