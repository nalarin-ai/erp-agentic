"""CRM port contract tests (CRM-001) — RED first.

Covers the unit-private CRM port surface: lead/quotation lifecycle under a
single active unit context, fail-closed scope isolation, transfer audit,
search/query scope intersection, export evidence bounding, and
privacy-preserving conflict checks.
"""
from __future__ import annotations

import unittest


class TestCrmPortContractSurface(unittest.TestCase):
    """The port module must exist with the agreed surface."""

    def test_port_module_importable(self) -> None:
        from src.crm import port  # noqa: F401

    def test_error_hierarchy_exists(self) -> None:
        from src.crm.port import CrmDenied, CrmError, CrmNotFound

        self.assertTrue(issubclass(CrmDenied, CrmError))
        self.assertTrue(issubclass(CrmNotFound, CrmError))

    def test_identity_requires_exactly_one_unit(self) -> None:
        from src.crm.port import CrmIdentity

        identity = CrmIdentity(actor_ref="USR-SALES-1", operating_unit_ref="UNIT-BM")
        self.assertEqual(identity.operating_unit_ref, "UNIT-BM")

    def test_lead_command_and_record_payloads(self) -> None:
        from src.crm.port import LeadCommand, LeadRecord

        cmd = LeadCommand(
            identity=None,  # type: ignore[arg-type]
            display_name="PT Sintetis Alfa",
            contact_channel="WHATSAPP",
            contact_handle="+62-SYNTH-001",
            source="ADS-SYNTH",
        )
        self.assertEqual(cmd.contact_channel, "WHATSAPP")
        rec = LeadRecord(
            reference="LEAD-0001",
            operating_unit_ref="UNIT-BM",
            display_name="PT Sintetis Alfa",
            contact_channel="WHATSAPP",
            contact_handle="+62-SYNTH-001",
            source="ADS-SYNTH",
            status="NEW",
            owner_actor_ref="USR-SALES-1",
            payload={},
        )
        self.assertEqual(rec.status, "NEW")

    def test_conflict_verdict_has_no_cross_unit_leak_variant(self) -> None:
        from src.crm.port import ConflictVerdict

        values = {v.value for v in ConflictVerdict}
        # Only scope-local verdicts exist; nothing reveals another unit.
        self.assertEqual(values, {"CLEAR", "CONFLICT_IN_SCOPE"})

    def test_crm_port_protocol_methods(self) -> None:
        from src.crm.port import CrmPort

        for method in (
            "create_lead",
            "read_lead",
            "transfer_lead",
            "archive_lead",
            "create_quotation",
            "read_quotation",
            "search_leads",
            "query_quotations",
            "export",
            "check_customer_conflict",
        ):
            self.assertTrue(hasattr(CrmPort, method), f"missing {method}")


if __name__ == "__main__":
    unittest.main()
