"""CRM-001 slice 2 — quotation lifecycle + assignment lifecycle tests (RED first)."""
from __future__ import annotations

import unittest

from src.crm.port import (
    CrmDenied,
    CrmIdentity,
    CrmNotFound,
    CrmQuery,
    QuotationCommand,
)
from tests.crm.test_fixture_crm import _identity, _lead_cmd


def _quo_cmd(unit: str, lead_ref: str) -> QuotationCommand:
    return QuotationCommand(
        identity=_identity(unit),
        lead_ref=lead_ref,
        customer_ref="CUST-ALPHA",
        total_amount="2500000",
        currency="IDR",
        valid_until="2026-09-01",
    )


class TestFixtureCrmQuotationLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        from src.adapters.fixture_crm import FixtureCrmAdapter

        self.adapter = FixtureCrmAdapter(
            assignments={"USR-SALES-1": frozenset({"UNIT-BM", "UNIT-PR1ME"})}
        )
        self.lead_bm = self.adapter.create_lead(_lead_cmd("UNIT-BM"))

    def test_create_and_read_quotation(self) -> None:
        ref = self.adapter.create_quotation(_quo_cmd("UNIT-BM", self.lead_bm))
        rec = self.adapter.read_quotation(_identity("UNIT-BM"), ref)
        self.assertEqual(rec.status, "DRAFT")
        self.assertEqual(rec.lead_ref, self.lead_bm)
        self.assertEqual(rec.total_amount, "2500000")

    def test_read_quotation_cross_unit_not_found(self) -> None:
        ref = self.adapter.create_quotation(_quo_cmd("UNIT-BM", self.lead_bm))
        with self.assertRaises(CrmNotFound):
            self.adapter.read_quotation(_identity("UNIT-PR1ME"), ref)

    def test_query_quotations_scoped_with_status_filter(self) -> None:
        ref = self.adapter.create_quotation(_quo_cmd("UNIT-BM", self.lead_bm))
        page = self.adapter.query_quotations(
            CrmQuery(identity=_identity("UNIT-BM"), status="DRAFT")
        )
        self.assertTrue(page.scoped)
        self.assertIn(ref, page.references)
        page_other = self.adapter.query_quotations(
            CrmQuery(identity=_identity("UNIT-PR1ME"), status="DRAFT")
        )
        self.assertNotIn(ref, page_other.references)


class TestFixtureCrmAssignmentLifecycle(unittest.TestCase):
    """R-021: unassigned/inactive/stale/revoked contexts must be denied."""

    def test_revoked_assignment_denies_further_actions(self) -> None:
        from src.adapters.fixture_crm import FixtureCrmAdapter

        assignments = {"USR-SALES-1": frozenset({"UNIT-BM"})}
        adapter = FixtureCrmAdapter(assignments=assignments)
        ref = adapter.create_lead(_lead_cmd("UNIT-BM"))
        # Revoke assignment (simulate expiry/revocation by mutating roster).
        assignments["USR-SALES-1"] = frozenset()
        with self.assertRaises(CrmDenied):
            adapter.read_lead(_identity("UNIT-BM"), ref)

    def test_zero_assignment_actor_denied_everywhere(self) -> None:
        from src.adapters.fixture_crm import FixtureCrmAdapter

        adapter = FixtureCrmAdapter(assignments={})
        with self.assertRaises(CrmDenied):
            adapter.create_lead(_lead_cmd("UNIT-BM"))

    def test_multi_unit_actor_must_choose_context(self) -> None:
        """Actions always carry exactly one active unit; data stays partitioned."""
        from src.adapters.fixture_crm import FixtureCrmAdapter

        adapter = FixtureCrmAdapter(
            assignments={"USR-SALES-1": frozenset({"UNIT-BM", "UNIT-PR1ME"})}
        )
        ref_bm = adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-MB"))
        ref_p1 = adapter.create_lead(_lead_cmd("UNIT-PR1ME", "+62-SYNTH-MP"))
        # Same actor, two contexts — each context sees only its own unit.
        page_bm = adapter.search_leads(CrmQuery(identity=_identity("UNIT-BM")))
        page_p1 = adapter.search_leads(CrmQuery(identity=_identity("UNIT-PR1ME")))
        self.assertEqual(set(page_bm.references), {ref_bm})
        self.assertEqual(set(page_p1.references), {ref_p1})


if __name__ == "__main__":
    unittest.main()
