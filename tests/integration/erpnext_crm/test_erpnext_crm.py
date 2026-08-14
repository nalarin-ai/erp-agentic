"""Integration tests for the ERPNext CRM adapter (CRM-001 slice 2) — RED first.

Runs the CrmPort contract suite against the isolated ERPNext pilot
(EVAL-002, 127.0.0.1:18080). All refs are synthetic opaque. Scope is
mapped to ERPNext Company (UNIT-BM exists; UNIT-PR1ME may be seeded).

Covers:
- lead lifecycle (create/read/archive) with scope isolation
- transfer semantics (in-unit owner change + cross-unit transfer)
- quotation lifecycle with in-scope lead referential integrity
- search scope intersection + scope-bound opaque cursors + limits
- export bounding with evidence ref
- privacy-preserving conflict check (no cross-unit existence leak)
- fail-closed behavior: unassigned unit, cross-unit reads, empty scope
"""
from __future__ import annotations

import os
import unittest

from src.adapters.erpnext import ErpNextConfig
from src.crm.port import (
    ConflictVerdict,
    CrmDenied,
    CrmIdentity,
    CrmNotFound,
    CrmQuery,
    ExportRequest,
    LeadCommand,
    QuotationCommand,
)


def _config() -> ErpNextConfig:
    return ErpNextConfig(
        base_url=os.environ.get("ERPNEXT_URL", "http://127.0.0.1:18080"),
        site_name=os.environ.get("ERPNEXT_SITE", "erpnext-pilot.localhost"),
        admin_password=os.environ.get(
            "ERPNEXT_ADMIN_PASSWORD",
            "2be0d0946a2e3d841301c45fb19dde011d179fdcc044b3a74893071eac314090",
        ),
        timeout_seconds=30,
    )


def _identity(unit: str = "UNIT-BM", actor: str = "USR-SALES-1") -> CrmIdentity:
    return CrmIdentity(actor_ref=actor, operating_unit_ref=unit)


def _lead_cmd(unit: str = "UNIT-BM", handle: str = "+62-SYNTH-CRM-INT-1") -> LeadCommand:
    return LeadCommand(
        identity=_identity(unit),
        display_name="PT Sintetis Integrasi",
        contact_channel="WHATSAPP",
        contact_handle=handle,
        source="ADS-SYNTH",
    )


def _adapter(scope: frozenset[str]):
    from src.adapters.erpnext_crm import ErpNextCrmAdapter

    return ErpNextCrmAdapter(
        _config(),
        authorized_scope=scope,
        assignments={
            "USR-SALES-1": frozenset({"UNIT-BM", "UNIT-PR1ME"}),
            "USR-SALES-2": frozenset({"UNIT-BM", "UNIT-PR1ME"}),
        },
    )


class TestErpNextCrmLeadLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _adapter(frozenset({"UNIT-BM", "UNIT-PR1ME"}))

    def test_create_and_read_lead_in_scope(self) -> None:
        ref = self.adapter.create_lead(_lead_cmd())
        record = self.adapter.read_lead(_identity(), ref)
        self.assertEqual(record.reference, ref)
        self.assertEqual(record.operating_unit_ref, "UNIT-BM")
        self.assertEqual(record.status, "NEW")
        self.assertEqual(record.owner_actor_ref, "USR-SALES-1")

    def test_create_lead_denied_for_unit_outside_authorized_scope(self) -> None:
        with self.assertRaises(CrmDenied):
            self.adapter.create_lead(_lead_cmd("UNIT-KTR"))

    def test_read_lead_cross_unit_is_not_found(self) -> None:
        """Cross-unit reads must be indistinguishable from absence."""
        ref = self.adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-CRM-INT-2"))
        with self.assertRaises(CrmNotFound):
            self.adapter.read_lead(_identity("UNIT-PR1ME"), ref)

    def test_archive_lead_scoped(self) -> None:
        ref = self.adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-CRM-INT-3"))
        self.adapter.archive_lead(_identity(), ref)
        self.assertEqual(self.adapter.read_lead(_identity(), ref).status, "ARCHIVED")
        with self.assertRaises(CrmNotFound):
            self.adapter.archive_lead(_identity("UNIT-PR1ME"), ref)

    def test_empty_scope_fail_closed(self) -> None:
        adapter = _adapter(frozenset())
        with self.assertRaises(CrmDenied):
            adapter.create_lead(_lead_cmd())


class TestErpNextCrmTransfer(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _adapter(frozenset({"UNIT-BM", "UNIT-PR1ME"}))

    def test_transfer_lead_changes_controller(self) -> None:
        ref = self.adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-CRM-INT-4"))
        self.adapter.transfer_lead(_identity(), ref, new_owner_actor_ref="USR-SALES-2")
        self.assertEqual(
            self.adapter.read_lead(_identity(), ref).owner_actor_ref, "USR-SALES-2"
        )

    def test_transfer_lead_to_unassigned_actor_denied(self) -> None:
        ref = self.adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-CRM-INT-5"))
        with self.assertRaises(CrmDenied):
            self.adapter.transfer_lead(_identity(), ref, new_owner_actor_ref="USR-GHOST")

    def test_transfer_lead_cross_unit_moves_scope(self) -> None:
        ref = self.adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-CRM-INT-6"))
        self.adapter.transfer_lead(
            _identity("UNIT-BM"),
            ref,
            new_owner_actor_ref="USR-SALES-2",
            new_unit_ref="UNIT-PR1ME",
        )
        # Now visible in target unit, absent in source unit.
        moved = self.adapter.read_lead(_identity("UNIT-PR1ME", "USR-SALES-2"), ref)
        self.assertEqual(moved.operating_unit_ref, "UNIT-PR1ME")
        with self.assertRaises(CrmNotFound):
            self.adapter.read_lead(_identity("UNIT-BM"), ref)


class TestErpNextCrmQuotation(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _adapter(frozenset({"UNIT-BM", "UNIT-PR1ME"}))
        self.lead_ref = self.adapter.create_lead(
            _lead_cmd("UNIT-BM", "+62-SYNTH-CRM-INT-7")
        )

    def _quo_cmd(self, unit: str, lead_ref: str) -> QuotationCommand:
        return QuotationCommand(
            identity=_identity(unit),
            lead_ref=lead_ref,
            customer_ref="CUST-ALPHA",
            total_amount="2500000",
            currency="IDR",
            valid_until="2026-09-01",
        )

    def test_create_and_read_quotation_in_scope(self) -> None:
        ref = self.adapter.create_quotation(self._quo_cmd("UNIT-BM", self.lead_ref))
        record = self.adapter.read_quotation(_identity(), ref)
        self.assertEqual(record.reference, ref)
        self.assertEqual(record.operating_unit_ref, "UNIT-BM")
        self.assertEqual(record.status, "DRAFT")
        self.assertEqual(record.lead_ref, self.lead_ref)

    def test_quotation_rejects_cross_unit_lead(self) -> None:
        """A lead from another unit is not usable nor revealed."""
        with self.assertRaises(CrmNotFound):
            self.adapter.create_quotation(self._quo_cmd("UNIT-PR1ME", self.lead_ref))

    def test_read_quotation_cross_unit_is_not_found(self) -> None:
        ref = self.adapter.create_quotation(self._quo_cmd("UNIT-BM", self.lead_ref))
        with self.assertRaises(CrmNotFound):
            self.adapter.read_quotation(_identity("UNIT-PR1ME"), ref)


class TestErpNextCrmSearchAndExport(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _adapter(frozenset({"UNIT-BM", "UNIT-PR1ME"}))
        # Unique per-run marker so scope assertions never collide with
        # accumulated pilot data (F-004).
        import uuid

        self.marker = f"PT-Sintetis-{uuid.uuid4().hex[:8]}"
        self.ref_bm = self.adapter.create_lead(
            LeadCommand(
                identity=_identity("UNIT-BM"),
                display_name=self.marker,
                contact_channel="WHATSAPP",
                contact_handle="+62-SYNTH-CRM-INT-8",
                source="ADS-SYNTH",
            )
        )
        self.ref_p1 = self.adapter.create_lead(
            LeadCommand(
                identity=_identity("UNIT-PR1ME"),
                display_name=self.marker,
                contact_channel="WHATSAPP",
                contact_handle="+62-SYNTH-CRM-INT-9",
                source="ADS-SYNTH",
            )
        )

    def test_search_intersects_active_unit_scope(self) -> None:
        # F-004 remediation: unique per-run marker text filter keeps this
        # assertion independent of accumulated pilot data.
        page_bm = self.adapter.search_leads(
            CrmQuery(identity=_identity("UNIT-BM"), text=self.marker)
        )
        self.assertTrue(page_bm.scoped)
        self.assertIn(self.ref_bm, page_bm.references)
        self.assertNotIn(self.ref_p1, page_bm.references)
        page_p1 = self.adapter.search_leads(
            CrmQuery(identity=_identity("UNIT-PR1ME"), text=self.marker)
        )
        self.assertIn(self.ref_p1, page_p1.references)
        self.assertNotIn(self.ref_bm, page_p1.references)

    def test_search_limit_enforced(self) -> None:
        page = self.adapter.search_leads(CrmQuery(identity=_identity("UNIT-BM"), limit=1))
        self.assertLessEqual(len(page.references), 1)
        if page.next_cursor is not None:
            page2 = self.adapter.search_leads(
                CrmQuery(identity=_identity("UNIT-BM"), limit=1, cursor=page.next_cursor)
            )
            self.assertNotEqual(page.references, page2.references)

    def test_search_cursor_is_scope_bound(self) -> None:
        page = self.adapter.search_leads(CrmQuery(identity=_identity("UNIT-BM"), limit=1))
        if page.next_cursor is not None:
            with self.assertRaises(CrmDenied):
                self.adapter.search_leads(
                    CrmQuery(identity=_identity("UNIT-PR1ME"), cursor=page.next_cursor)
                )

    def test_search_rejects_malformed_cursor(self) -> None:
        with self.assertRaises(CrmDenied):
            self.adapter.search_leads(
                CrmQuery(identity=_identity("UNIT-BM"), cursor="garbage-cursor")
            )

    def test_export_is_scope_bounded_with_evidence(self) -> None:
        result = self.adapter.export(
            ExportRequest(identity=_identity("UNIT-BM"), kind="LEAD", evidence_ref="EVI-CRM-EXP-1")
        )
        self.assertEqual(result.evidence_ref, "EVI-CRM-EXP-1")
        self.assertEqual(result.operating_unit_ref, "UNIT-BM")
        self.assertGreaterEqual(result.row_count, 1)
        refs = {row["reference"] for row in result.rows}
        self.assertIn(self.ref_bm, refs)
        self.assertNotIn(self.ref_p1, refs)

    def test_export_max_rows_enforced(self) -> None:
        result = self.adapter.export(
            ExportRequest(
                identity=_identity("UNIT-BM"),
                kind="LEAD",
                evidence_ref="EVI-CRM-EXP-2",
                max_rows=1,
            )
        )
        self.assertLessEqual(result.row_count, 1)


class TestErpNextCrmConflict(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = _adapter(frozenset({"UNIT-BM", "UNIT-PR1ME"}))

    def test_conflict_detected_in_scope_only(self) -> None:
        self.adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-CRM-INT-10"))
        verdict = self.adapter.check_customer_conflict(
            _identity("UNIT-BM"), "WHATSAPP", "+62-SYNTH-CRM-INT-10"
        )
        self.assertEqual(verdict, ConflictVerdict.CONFLICT_IN_SCOPE)

    def test_no_cross_unit_conflict_leak(self) -> None:
        self.adapter.create_lead(_lead_cmd("UNIT-BM", "+62-SYNTH-CRM-INT-11"))
        verdict = self.adapter.check_customer_conflict(
            _identity("UNIT-PR1ME"), "WHATSAPP", "+62-SYNTH-CRM-INT-11"
        )
        self.assertEqual(verdict, ConflictVerdict.CLEAR)


if __name__ == "__main__":
    unittest.main()
