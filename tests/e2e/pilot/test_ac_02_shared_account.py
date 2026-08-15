"""MVP-AC-02: Heavy Equipment -> Contractor shared account; other account denied.

Criteria (TRACEABILITY_MATRIX.md section D):
- Heavy Equipment shares ONLY the approved Contractor destination account
  (R-015): policy resolution for HEAVYEQUIPMENT yields ACC-CONTRACTOR.
- Any other account for Heavy Equipment is denied fail-closed.
- Cross-sales isolation between Contractor and Heavy Equipment sales holds.
"""
from __future__ import annotations

import unittest

from src.policy.financial_identity import (
    PolicyResolutionRequest,
    RequestedFinancialIdentity,
)

from tests.e2e.pilot._harness import (
    PilotHarness,
    UNIT_CONTRACTOR,
    UNIT_HEAVY_EQUIPMENT,
    at,
)


class TestAc02HeavyEquipmentSharedAccount(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = PilotHarness.build()

    def test_heavy_equipment_resolves_contractor_shared_account(self) -> None:
        h = self.harness
        resolved = h.resolver.resolve(PolicyResolutionRequest(
            operating_unit_ref=UNIT_HEAVY_EQUIPMENT,
            currency="IDR",
            effective_at=at(10),
        ))
        self.assertEqual(
            resolved.identity.destination_account_alias, "ACC-CONTRACTOR"
        )
        self.assertEqual(resolved.identity.operating_unit_ref, UNIT_HEAVY_EQUIPMENT)
        # The Heavy Equipment ledger/series stay unit-private; only the
        # destination account is shared (R-015).
        self.assertEqual(resolved.identity.receivable_ledger_ref, "LEDGER-HEQ")
        self.assertEqual(resolved.identity.invoice_series_ref, "SERIES-HEQ")

    def test_contractor_resolves_own_account(self) -> None:
        h = self.harness
        resolved = h.resolver.resolve(PolicyResolutionRequest(
            operating_unit_ref=UNIT_CONTRACTOR,
            currency="IDR",
            effective_at=at(10),
        ))
        self.assertEqual(
            resolved.identity.destination_account_alias, "ACC-CONTRACTOR"
        )

    def test_heavy_equipment_requesting_other_account_denied(self) -> None:
        """An override request binding a non-approved account must fail closed.

        Without a trusted override authorization, ANY requested identity is
        denied (OVERRIDE_AUTHORIZATION_REQUIRED); even with a structurally
        plausible request, a non-shared account (ACC-BANYUMEDIA) can never
        match an active policy (POLICY_NOT_FOUND on the override path).
        """
        from src.policy.financial_identity import PolicyResolutionError

        h = self.harness
        foreign = RequestedFinancialIdentity(
            legal_issuer_ref="ISSUER-HEAVY-EQUIPMENT",
            tax_profile_ref="TAX-NONPPN",
            invoice_series_ref="SERIES-HEQ",
            receivable_ledger_ref="LEDGER-HEQ",
            destination_account_alias="ACC-BANYUMEDIA",  # not approved for HE
        )
        with self.assertRaises(PolicyResolutionError) as ctx:
            h.resolver.resolve(PolicyResolutionRequest(
                operating_unit_ref=UNIT_HEAVY_EQUIPMENT,
                currency="IDR",
                effective_at=at(10),
                requested_identity=foreign,
            ))
        self.assertEqual(ctx.exception.code, "OVERRIDE_AUTHORIZATION_REQUIRED")

    def test_heavy_equipment_invoice_post_binds_contractor_account(self) -> None:
        """End-to-end: a posted HE invoice freezes ACC-CONTRACTOR in the
        immutable snapshot and the provider record's financial identity."""
        h = self.harness
        preview, result = h.post_invoice_for_unit(
            h.heavy_equipment_requester, h.heavy_equipment_poster,
            UNIT_HEAVY_EQUIPMENT, customer_ref="CUST-HEQ-1",
        )
        self.assertEqual(result.outcome, "POSTED")
        self.assertIsNotNone(result.official_ref)
        record = h.get_posted_invoice(result.official_ref or "")
        self.assertEqual(record.destination_account_alias, "ACC-CONTRACTOR")
        self.assertEqual(record.unit_ref, UNIT_HEAVY_EQUIPMENT)
        # Preview is redacted; the posted record carries the alias (opaque).
        self.assertEqual(preview.destination_account_alias, "ACC-[REDACTED]")

    def test_heavy_equipment_sales_isolated_from_contractor_sales(self) -> None:
        """Shared account does NOT imply shared pipeline: cross-sales lead
        access between HE and Contractor stays denied (R-015 boundary)."""
        h = self.harness
        he_lead = h.create_lead(h.heavy_equipment_sales, UNIT_HEAVY_EQUIPMENT,
                                display_name="PT Alat Berat Sintetis",
                                contact_handle="+62-800-SYN-0102")
        with self.assertRaises(Exception) as ctx:
            h.read_lead(h.contractor_sales, UNIT_CONTRACTOR, he_lead)
        self.assertNotIn("HEAVY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
