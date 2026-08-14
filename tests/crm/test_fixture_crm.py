"""Behavioral tests for the in-memory fixture CRM adapter (CRM-001) — RED first.

These tests drive real behavior: lead lifecycle, fail-closed scope isolation,
transfer audit, search scope intersection, export bounding, and
privacy-preserving conflict checks. The fixture adapter is network-disabled
and deterministic, like the ADP-001 fixture ERP adapter.
"""
from __future__ import annotations

import unittest

from src.crm.port import (
    ConflictVerdict,
    CrmDenied,
    CrmIdentity,
    CrmNotFound,
    CrmQuery,
    ExportRequest,
    LeadCommand,
)


def _identity(unit: str = "UNIT-BM", actor: str = "USR-SALES-1") -> CrmIdentity:
    return CrmIdentity(actor_ref=actor, operating_unit_ref=unit)


def _lead_cmd(unit: str = "UNIT-BM", handle: str = "+62-SYNTH-001") -> LeadCommand:
    return LeadCommand(
        identity=_identity(unit),
        display_name="PT Sintetis Alfa",
        contact_channel="WHATSAPP",
        contact_handle=handle,
        source="ADS-SYNTH",
    )


class TestFixtureCrmLeadLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        from src.adapters.fixture_crm import FixtureCrmAdapter

        self.adapter = FixtureCrmAdapter(
            assignments={"USR-SALES-1": frozenset({"UNIT-BM", "UNIT-PR1ME"})}
        )

    def test_create_and_read_lead_in_scope(self) -> None:
        ref = self.adapter.create_lead(_lead_cmd())
        record = self.adapter.read_lead(_identity(), ref)
        self.assertEqual(record.reference, ref)
        self.assertEqual(record.operating_unit_ref, "UNIT-BM")
        self.assertEqual(record.status, "NEW")
        self.assertEqual(record.owner_actor_ref, "USR-SALES-1")

    def test_create_lead_denied_for_unassigned_unit(self) -> None:
        with self.assertRaises(CrmDenied):
            self.adapter.create_lead(_lead_cmd("UNIT-KTR"))

    def test_read_lead_cross_unit_is_not_found(self) -> None:
        """Cross-unit reads must look like absence — existence must not leak."""
        ref = self.adapter.create_lead(_lead_cmd("UNIT-BM"))
        with self.assertRaises(CrmNotFound):
            self.adapter.read_lead(_identity("UNIT-PR1ME"), ref)

    def test_archive_lead_scoped(self) -> None:
        ref = self.adapter.create_lead(_lead_cmd())
        self.adapter.archive_lead(_identity(), ref)
        self.assertEqual(self.adapter.read_lead(_identity(), ref).status, "ARCHIVED")
        with self.assertRaises(CrmNotFound):
            self.adapter.archive_lead(_identity("UNIT-PR1ME"), ref)


class TestFixtureCrmTransfer(unittest.TestCase):
    def setUp(self) -> None:
        from src.adapters.fixture_crm import FixtureCrmAdapter

        self.adapter = FixtureCrmAdapter(
            assignments={
                "USR-SALES-1": frozenset({"UNIT-BM"}),
                "USR-SALES-2": frozenset({"UNIT-BM", "UNIT-PR1ME"}),
            }
        )

    def test_transfer_lead_changes_controller(self) -> None:
        ref = self.adapter.create_lead(_lead_cmd())
        self.adapter.transfer_lead(
            _identity(), ref, new_owner_actor_ref="USR-SALES-2"
        )
        self.assertEqual(
            self.adapter.read_lead(_identity(), ref).owner_actor_ref, "USR-SALES-2"
        )

    def test_transfer_lead_to_unassigned_actor_denied(self) -> None:
        ref = self.adapter.create_lead(_lead_cmd())
        with self.assertRaises(CrmDenied):
            self.adapter.transfer_lead(
                _identity(), ref, new_owner_actor_ref="USR-GHOST"
            )


class TestFixtureCrmSearchAndExport(unittest.TestCase):
    def setUp(self) -> None:
        from src.adapters.fixture_crm import FixtureCrmAdapter

        self.adapter = FixtureCrmAdapter(
            assignments={"USR-SALES-1": frozenset({"UNIT-BM", "UNIT-PR1ME"})}
        )
        self.ref_bm = self.adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-BM"))
        self.ref_pr1me = self.adapter.create_lead(_lead_cmd("UNIT-PR1ME", "+62-SYNTH-P1"))

    def test_search_intersects_active_unit_scope(self) -> None:
        page_bm = self.adapter.search_leads(CrmQuery(identity=_identity("UNIT-BM")))
        self.assertTrue(page_bm.scoped)
        self.assertIn(self.ref_bm, page_bm.references)
        self.assertNotIn(self.ref_pr1me, page_bm.references)

    def test_search_cursor_is_scope_bound(self) -> None:
        page = self.adapter.search_leads(
            CrmQuery(identity=_identity("UNIT-BM"), limit=1)
        )
        if page.next_cursor is not None:
            with self.assertRaises(CrmDenied):
                self.adapter.search_leads(
                    CrmQuery(identity=_identity("UNIT-PR1ME"), cursor=page.next_cursor)
                )

    def test_export_is_scope_bounded_with_evidence(self) -> None:
        result = self.adapter.export(
            ExportRequest(
                identity=_identity("UNIT-BM"), kind="LEAD", evidence_ref="EVI-EXP-1"
            )
        )
        self.assertEqual(result.operating_unit_ref, "UNIT-BM")
        self.assertEqual(result.evidence_ref, "EVI-EXP-1")
        for row in result.rows:
            self.assertNotIn("+62-SYNTH-P1", str(row))


class TestFixtureCrmConflictPrivacy(unittest.TestCase):
    def setUp(self) -> None:
        from src.adapters.fixture_crm import FixtureCrmAdapter

        self.adapter = FixtureCrmAdapter(
            assignments={"USR-SALES-1": frozenset({"UNIT-BM", "UNIT-PR1ME"})}
        )

    def test_conflict_check_only_reports_in_scope(self) -> None:
        self.adapter.create_lead(_lead_cmd("UNIT-PR1ME", "+62-SYNTH-X"))
        # Same handle exists in UNIT-PR1ME; asking from UNIT-BM must be CLEAR.
        verdict = self.adapter.check_customer_conflict(
            _identity("UNIT-BM"), "WHATSAPP", "+62-SYNTH-X"
        )
        self.assertEqual(verdict, ConflictVerdict.CLEAR)
        # Asking from UNIT-PR1ME reports the in-scope conflict.
        verdict_p1 = self.adapter.check_customer_conflict(
            _identity("UNIT-PR1ME"), "WHATSAPP", "+62-SYNTH-X"
        )
        self.assertEqual(verdict_p1, ConflictVerdict.CONFLICT_IN_SCOPE)


if __name__ == "__main__":
    unittest.main()
