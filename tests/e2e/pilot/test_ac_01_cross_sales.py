"""MVP-AC-01: Banyumedia + Contractor operate; cross-sales access denied.

Criteria (TRACEABILITY_MATRIX.md section D):
- Banyumedia and Contractor units are configured and operable.
- Competing sales actors cannot read/claim each other's pipelines across the
  final (gateway-only) architecture: gateway CRM port denies cross-unit
  read/search/export, and native surfaces are DENIED for unit-scoped roles.

Slice 1 scope: positive Banyumedia+Contractor lead flows, negative cross-unit
lead read via the gateway CRM port, native-surface denial for unit-scoped
roles on the final isolation policy.
"""
from __future__ import annotations

import unittest

from tests.e2e.pilot._harness import PilotHarness


class TestAc01CrossSalesIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = PilotHarness.build()

    def test_banyumedia_sales_creates_and_reads_own_lead(self) -> None:
        h = self.harness
        lead_ref = h.create_lead(h.banyumedia_sales, "UNIT-BANYUMEDIA",
                                 display_name="PT Sintetis Banyu",
                                 contact_handle="+62-800-SYN-0001")
        record = h.read_lead(h.banyumedia_sales, "UNIT-BANYUMEDIA", lead_ref)
        self.assertEqual(record.operating_unit_ref, "UNIT-BANYUMEDIA")

    def test_contractor_sales_creates_and_reads_own_lead(self) -> None:
        h = self.harness
        lead_ref = h.create_lead(h.contractor_sales, "UNIT-CONTRACTOR",
                                 display_name="CV Sintetis Konstruksi",
                                 contact_handle="+62-800-SYN-0002")
        record = h.read_lead(h.contractor_sales, "UNIT-CONTRACTOR", lead_ref)
        self.assertEqual(record.operating_unit_ref, "UNIT-CONTRACTOR")

    def test_banyumedia_sales_cannot_read_contractor_lead(self) -> None:
        h = self.harness
        contractor_lead = h.create_lead(h.contractor_sales, "UNIT-CONTRACTOR",
                                        display_name="CV Lintas Unit",
                                        contact_handle="+62-800-SYN-0003")
        with self.assertRaises(Exception) as ctx:
            h.read_lead(h.banyumedia_sales, "UNIT-BANYUMEDIA", contractor_lead)
        self.assertNotIn("CONTRACTOR", str(ctx.exception))

    def test_contractor_sales_cannot_read_banyumedia_lead(self) -> None:
        h = self.harness
        banyu_lead = h.create_lead(h.banyumedia_sales, "UNIT-BANYUMEDIA",
                                   display_name="PT Lintas Banyu",
                                   contact_handle="+62-800-SYN-0004")
        with self.assertRaises(Exception) as ctx:
            h.read_lead(h.contractor_sales, "UNIT-CONTRACTOR", banyu_lead)
        self.assertNotIn("BANYUMEDIA", str(ctx.exception))

    def test_cross_unit_search_yields_zero_foreign_rows(self) -> None:
        h = self.harness
        h.create_lead(h.banyumedia_sales, "UNIT-BANYUMEDIA",
                      display_name="PT Pencarian Silang",
                      contact_handle="+62-800-SYN-0005")
        page = h.search_leads(h.contractor_sales, "UNIT-CONTRACTOR",
                              text="Pencarian")
        self.assertEqual(page.total, 0)
        self.assertTrue(page.scoped)

    def test_native_surfaces_denied_for_unit_scoped_sales_role(self) -> None:
        h = self.harness
        for surface in h.native_surfaces():
            self.assertFalse(
                h.native_admission_allows("Sales User", surface),
                f"native surface {surface} must be DENIED for unit-scoped role",
            )

    def test_gateway_surfaces_allowed_for_unit_scoped_sales_role(self) -> None:
        h = self.harness
        self.assertTrue(h.native_admission_allows("Sales User", "GATEWAY_CRM_PORT"))
        self.assertTrue(h.native_admission_allows("Sales User", "GATEWAY_ERP_PORT"))

    def test_native_credential_issuance_denied_for_sales_role(self) -> None:
        h = self.harness
        self.assertFalse(
            h.native_credential_issuance_allowed("Sales User", "syn.sales"),
        )


if __name__ == "__main__":
    unittest.main()
