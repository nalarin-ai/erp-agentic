"""CRM-001 QA remediation tests (deleg_a7a09d16 F-001..F-007) — RED first."""
from __future__ import annotations

import unittest

from src.crm.port import (
    CrmDenied,
    CrmError,
    CrmIdentity,
    CrmNotFound,
    CrmQuery,
    ExportRequest,
)
from tests.crm.test_fixture_crm import _identity, _lead_cmd


def _adapter_with_two_units():
    from src.adapters.fixture_crm import FixtureCrmAdapter

    return FixtureCrmAdapter(
        assignments={
            "USR-SALES-1": frozenset({"UNIT-BM", "UNIT-PR1ME"}),
            "USR-SALES-2": frozenset({"UNIT-PR1ME"}),
        }
    )


class TestF001CursorScopeBound(unittest.TestCase):
    """F-001: cursor scope test must actually execute (next_cursor present)."""

    def test_cursor_from_other_unit_denied(self) -> None:
        adapter = _adapter_with_two_units()
        adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-B1"))
        adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-B2"))
        page = adapter.search_leads(CrmQuery(identity=_identity("UNIT-BM"), limit=1))
        self.assertIsNotNone(page.next_cursor)  # cursor must exist for test to matter
        with self.assertRaises(CrmDenied):
            adapter.search_leads(
                CrmQuery(identity=_identity("UNIT-PR1ME"), cursor=page.next_cursor)
            )


class TestF002ExportNoLeak(unittest.TestCase):
    """F-002: export must provably exclude other units' rows."""

    def test_export_excludes_other_unit_rows(self) -> None:
        adapter = _adapter_with_two_units()
        ref_bm = adapter.create_lead(
            _lead_cmd("UNIT-BM", "+62-SYNTH-BM")
        )
        # Distinct display name so leakage is detectable.
        from src.crm.port import LeadCommand

        adapter.create_lead(
            LeadCommand(
                identity=_identity("UNIT-PR1ME"),
                display_name="PT Pr1me Rahasia",
                contact_channel="WHATSAPP",
                contact_handle="+62-SYNTH-P1",
                source="ORGANIC",
            )
        )
        result = adapter.export(
            ExportRequest(
                identity=_identity("UNIT-BM"), kind="LEAD", evidence_ref="EVI-EXP-2"
            )
        )
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.rows[0]["reference"], ref_bm)
        self.assertNotIn("Pr1me", str(result.rows))


class TestF003TransferCrossUnitSemantics(unittest.TestCase):
    """F-003: lock intended cross-unit controller transfer behavior."""

    def test_transfer_to_other_unit_allowed_with_assigned_owner(self) -> None:
        adapter = _adapter_with_two_units()
        ref = adapter.create_lead(_lead_cmd("UNIT-BM"))
        adapter.transfer_lead(
            _identity("UNIT-BM"),
            ref,
            new_owner_actor_ref="USR-SALES-2",
            new_unit_ref="UNIT-PR1ME",
        )
        # After transfer out, source unit can no longer read it (no read-back leak).
        with self.assertRaises(CrmNotFound):
            adapter.read_lead(_identity("UNIT-BM"), ref)
        # Destination owner can read it in the destination unit context.
        rec = adapter.read_lead(_identity("UNIT-PR1ME", "USR-SALES-2"), ref)
        self.assertEqual(rec.operating_unit_ref, "UNIT-PR1ME")


class TestF005F006PaginationAndExportBounds(unittest.TestCase):
    """F-005/F-006: limit/max_rows/cursor must be fail-closed and monotone."""

    def setUp(self) -> None:
        self.adapter = _adapter_with_two_units()
        self.adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-B1"))

    def test_search_limit_must_be_positive(self) -> None:
        with self.assertRaises(CrmError):
            self.adapter.search_leads(CrmQuery(identity=_identity("UNIT-BM"), limit=0))
        with self.assertRaises(CrmError):
            self.adapter.search_leads(CrmQuery(identity=_identity("UNIT-BM"), limit=-1))

    def test_export_max_rows_must_be_positive(self) -> None:
        with self.assertRaises(CrmError):
            self.adapter.export(
                ExportRequest(
                    identity=_identity("UNIT-BM"),
                    kind="LEAD",
                    evidence_ref="EVI-EXP-3",
                    max_rows=0,
                )
            )

    def test_malformed_cursor_denied_not_valueerror(self) -> None:
        for bad in ("UNIT-BM:abc", "UNIT-BM:1:2", "UNIT-BM:", "UNIT-BM:-1", "junk"):
            with self.assertRaises(CrmDenied, msg=f"cursor {bad!r}"):
                self.adapter.search_leads(
                    CrmQuery(identity=_identity("UNIT-BM"), cursor=bad)
                )


class TestF007QuotationLeadRefValidation(unittest.TestCase):
    """F-007: quotation must not reference a lead outside the active unit."""

    def test_quotation_rejects_cross_unit_lead_ref(self) -> None:
        adapter = _adapter_with_two_units()
        lead_bm = adapter.create_lead(_lead_cmd("UNIT-BM"))
        from src.crm.port import QuotationCommand

        with self.assertRaises(CrmError):
            adapter.create_quotation(
                QuotationCommand(
                    identity=_identity("UNIT-PR1ME"),
                    lead_ref=lead_bm,
                    customer_ref="CUST-ALPHA",
                    total_amount="1000",
                    currency="IDR",
                    valid_until="2026-09-01",
                )
            )

    def test_quotation_rejects_unknown_lead_ref(self) -> None:
        adapter = _adapter_with_two_units()
        from src.crm.port import QuotationCommand

        with self.assertRaises(CrmError):
            adapter.create_quotation(
                QuotationCommand(
                    identity=_identity("UNIT-PR1ME"),
                    lead_ref="LEAD-FICTION",
                    customer_ref="CUST-ALPHA",
                    total_amount="1000",
                    currency="IDR",
                    valid_until="2026-09-01",
                )
            )


if __name__ == "__main__":
    unittest.main()
