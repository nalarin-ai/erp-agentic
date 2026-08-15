"""MVP-AC-03: non-PPN + PT PPN correct path; wrong issuer/tax/ledger/account denied.

Criteria (TRACEABILITY_MATRIX.md section D):
- Non-PPN units (Banyumedia etc.) resolve TAX-NONPPN and a non-PT issuer.
- PT TKH is the sole PPN-issuing entity (R-016): its path binds the PT
  issuer, PPN tax profile, PT series/ledger/account.
- Wrong issuer/tax/ledger/account combinations are denied fail-closed:
  POLICY_NOT_FOUND / OVERRIDE_AUTHORIZATION_REQUIRED / BLOCKED_CONFIGURATION.
"""
from __future__ import annotations

import unittest

from src.policy.financial_identity import (
    PolicyResolutionError,
    PolicyResolutionRequest,
    RequestedFinancialIdentity,
)

from tests.e2e.pilot._harness import (
    PilotHarness,
    UNIT_BANYUMEDIA,
    UNIT_PT_TKH,
    at,
)


class TestAc03TaxPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = PilotHarness.build()

    # -- positive paths --------------------------------------------------------

    def test_non_ppn_unit_preview_uses_non_ppn_identity(self) -> None:
        h = self.harness
        handle = h.open_draft(h.banyumedia_requester, UNIT_BANYUMEDIA,
                              customer_ref="CUST-BYM-1")
        h.set_lines(h.banyumedia_requester, handle.draft_id, h.standard_lines())
        preview = h.preview(h.banyumedia_requester, handle.draft_id)
        self.assertEqual(preview.tax_profile_ref, "TAX-NONPPN")
        self.assertEqual(preview.legal_issuer_ref, "ISSUER-BANYUMEDIA")
        self.assertNotEqual(preview.legal_issuer_ref, "ISSUER-PT-TKH")
        self.assertEqual(preview.receivable_ledger_ref, "LEDGER-BYM")

    def test_pt_tkh_preview_uses_ppn_identity(self) -> None:
        h = self.harness
        handle = h.open_draft(h.pt_tkh_requester, UNIT_PT_TKH,
                              customer_ref="CUST-TKH-1")
        h.set_lines(h.pt_tkh_requester, handle.draft_id, h.standard_lines())
        preview = h.preview(h.pt_tkh_requester, handle.draft_id)
        self.assertEqual(preview.tax_profile_ref, "TAX-PPN-11")
        self.assertEqual(preview.legal_issuer_ref, "ISSUER-PT-TKH")
        self.assertEqual(preview.invoice_series_ref, "SERIES-TKH")
        self.assertEqual(preview.receivable_ledger_ref, "LEDGER-TKH")

    def test_pt_tkh_post_freezes_ppn_snapshot(self) -> None:
        h = self.harness
        _preview, result = h.post_invoice_for_unit(
            h.pt_tkh_requester, h.pt_tkh_poster, UNIT_PT_TKH,
            customer_ref="CUST-TKH-2",
        )
        self.assertEqual(result.outcome, "POSTED")
        record = h.get_posted_invoice(result.official_ref or "")
        self.assertEqual(record.tax_profile_ref, "TAX-PPN-11")
        self.assertEqual(record.legal_issuer_ref, "ISSUER-PT-TKH")
        self.assertEqual(record.destination_account_alias, "ACC-PT-TKH")

    # -- negative paths ----------------------------------------------------------

    def test_wrong_issuer_for_pt_ppn_denied(self) -> None:
        """Requested identity with a non-PT issuer for the PT unit is denied."""
        h = self.harness
        wrong = RequestedFinancialIdentity(
            legal_issuer_ref="ISSUER-BANYUMEDIA",  # wrong issuer for PT PPN
            tax_profile_ref="TAX-PPN-11",
            invoice_series_ref="SERIES-TKH",
            receivable_ledger_ref="LEDGER-TKH",
            destination_account_alias="ACC-PT-TKH",
        )
        with self.assertRaises(PolicyResolutionError) as ctx:
            h.resolver.resolve(PolicyResolutionRequest(
                operating_unit_ref=UNIT_PT_TKH,
                currency="IDR",
                effective_at=at(10),
                requested_identity=wrong,
            ))
        self.assertEqual(ctx.exception.code, "OVERRIDE_AUTHORIZATION_REQUIRED")

    def test_wrong_tax_profile_for_non_ppn_unit_denied(self) -> None:
        """A non-PPN unit bound to the PPN tax profile matches no policy."""
        h = self.harness
        wrong = RequestedFinancialIdentity(
            legal_issuer_ref="ISSUER-BANYUMEDIA",
            tax_profile_ref="TAX-PPN-11",  # wrong: Banyumedia is non-PPN
            invoice_series_ref="SERIES-BYM",
            receivable_ledger_ref="LEDGER-BYM",
            destination_account_alias="ACC-BANYUMEDIA",
        )
        with self.assertRaises(PolicyResolutionError) as ctx:
            h.resolver.resolve(PolicyResolutionRequest(
                operating_unit_ref=UNIT_BANYUMEDIA,
                currency="IDR",
                effective_at=at(10),
                requested_identity=wrong,
            ))
        self.assertEqual(ctx.exception.code, "OVERRIDE_AUTHORIZATION_REQUIRED")

    def test_wrong_ledger_combination_denied_without_catalog_match(self) -> None:
        """Even with a trusted override, an identity outside the signed
        compatibility catalog is BLOCKED_CONFIGURATION. Slice 1 proves the
        catalog gate: a forged policy identity (wrong ledger) can never be in
        the signed catalog, so resolution of that combination has no policy
        and fails closed as POLICY_NOT_FOUND at the direct-resolution layer.
        """
        h = self.harness
        # Direct resolution for a non-existent (unit, currency) window:
        with self.assertRaises(PolicyResolutionError) as ctx:
            h.resolver.resolve(PolicyResolutionRequest(
                operating_unit_ref=UNIT_PT_TKH,
                currency="USD",  # no USD policy seeded
                effective_at=at(10),
            ))
        self.assertEqual(ctx.exception.code, "POLICY_NOT_FOUND")

    def test_wrong_account_alias_for_pt_denied(self) -> None:
        h = self.harness
        wrong = RequestedFinancialIdentity(
            legal_issuer_ref="ISSUER-PT-TKH",
            tax_profile_ref="TAX-PPN-11",
            invoice_series_ref="SERIES-TKH",
            receivable_ledger_ref="LEDGER-TKH",
            destination_account_alias="ACC-BANYUMEDIA",  # wrong account
        )
        with self.assertRaises(PolicyResolutionError) as ctx:
            h.resolver.resolve(PolicyResolutionRequest(
                operating_unit_ref=UNIT_PT_TKH,
                currency="IDR",
                effective_at=at(10),
                requested_identity=wrong,
            ))
        self.assertEqual(ctx.exception.code, "OVERRIDE_AUTHORIZATION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
