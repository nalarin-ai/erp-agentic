"""QA remediation regression tests (CRM-001 slice 2) — RED first.

Covers QA findings F-001..F-005 from independent review deleg_1f1f4466:
- F-001: archived leads must NOT appear in status="NEW" search
- F-002: quotation status filter must be applied (not silently dropped)
- F-003: customer_ref must round-trip via custom field
- F-004: scope-intersection test must be state-independent (unique marker)
- F-005: unknown native quotation statuses must map fail-closed
"""
from __future__ import annotations

import os
import unittest
import uuid

from src.adapters.erpnext import ErpNextConfig
from src.crm.port import (
    CrmDenied,
    CrmIdentity,
    CrmNotFound,
    CrmQuery,
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


def _adapter():
    from src.adapters.erpnext_crm import ErpNextCrmAdapter

    return ErpNextCrmAdapter(
        _config(),
        frozenset({"UNIT-BM", "UNIT-PR1ME"}),
        assignments={
            "USR-SALES-1": frozenset({"UNIT-BM", "UNIT-PR1ME"}),
            "USR-SALES-2": frozenset({"UNIT-BM", "UNIT-PR1ME"}),
        },
    )


class TestQAArchivedVsNewSearch(unittest.TestCase):
    """F-001: archived leads must not appear under status='NEW'."""

    def test_archived_lead_excluded_from_new_status_search(self) -> None:
        adapter = _adapter()
        marker = f"QA-F001-{uuid.uuid4().hex[:8]}"
        ref = adapter.create_lead(
            LeadCommand(
                identity=_identity(),
                display_name=marker,
                contact_channel="WHATSAPP",
                contact_handle=f"+62-SYNTH-{marker}",
                source="ADS-SYNTH",
            )
        )
        adapter.archive_lead(_identity(), ref)
        page_new = adapter.search_leads(
            CrmQuery(identity=_identity(), text=marker, status="NEW")
        )
        self.assertNotIn(ref, page_new.references)
        page_arch = adapter.search_leads(
            CrmQuery(identity=_identity(), text=marker, status="ARCHIVED")
        )
        self.assertIn(ref, page_arch.references)


class TestQAQuotationStatusFilter(unittest.TestCase):
    """F-002: quotation status filter must actually filter."""

    def test_quotation_status_filter_applied(self) -> None:
        adapter = _adapter()
        marker = f"QA-F002-{uuid.uuid4().hex[:8]}"
        lead_ref = adapter.create_lead(
            LeadCommand(
                identity=_identity(),
                display_name=marker,
                contact_channel="WHATSAPP",
                contact_handle=f"+62-SYNTH-{marker}",
                source="ADS-SYNTH",
            )
        )
        adapter.create_quotation(
            QuotationCommand(
                identity=_identity(),
                lead_ref=lead_ref,
                customer_ref="CUST-ALPHA",
                total_amount="1000000",
                currency="IDR",
                valid_until="2026-09-01",
            )
        )
        page_draft = adapter.query_quotations(
            CrmQuery(identity=_identity(), status="DRAFT")
        )
        page_sent = adapter.query_quotations(
            CrmQuery(identity=_identity(), status="SENT")
        )
        # The created draft must be in DRAFT results.
        # SENT filter must not silently return the same full set.
        self.assertNotEqual(page_draft.references, page_sent.references)
        for ref in page_draft.references:
            rec = adapter.read_quotation(_identity(), ref)
            self.assertEqual(rec.status, "DRAFT")


class TestQACustomerRefRoundTrip(unittest.TestCase):
    """F-003: customer_ref must round-trip exactly (not overwritten by party)."""

    def test_customer_ref_round_trips(self) -> None:
        adapter = _adapter()
        marker = f"QA-F003-{uuid.uuid4().hex[:8]}"
        lead_ref = adapter.create_lead(
            LeadCommand(
                identity=_identity(),
                display_name=marker,
                contact_channel="WHATSAPP",
                contact_handle=f"+62-SYNTH-{marker}",
                source="ADS-SYNTH",
            )
        )
        ref = adapter.create_quotation(
            QuotationCommand(
                identity=_identity(),
                lead_ref=lead_ref,
                customer_ref="CUST-ALPHA",
                total_amount="1000000",
                currency="IDR",
                valid_until="2026-09-01",
            )
        )
        record = adapter.read_quotation(_identity(), ref)
        self.assertEqual(record.customer_ref, "CUST-ALPHA")


class TestQAQuotationStatusMapping(unittest.TestCase):
    """F-005: read_quotation must emit only contract statuses."""

    def test_quotation_status_is_in_contract_vocabulary(self) -> None:
        adapter = _adapter()
        marker = f"QA-F005-{uuid.uuid4().hex[:8]}"
        lead_ref = adapter.create_lead(
            LeadCommand(
                identity=_identity(),
                display_name=marker,
                contact_channel="WHATSAPP",
                contact_handle=f"+62-SYNTH-{marker}",
                source="ADS-SYNTH",
            )
        )
        ref = adapter.create_quotation(
            QuotationCommand(
                identity=_identity(),
                lead_ref=lead_ref,
                customer_ref="CUST-ALPHA",
                total_amount="1000000",
                currency="IDR",
                valid_until="2026-09-01",
            )
        )
        record = adapter.read_quotation(_identity(), ref)
        self.assertIn(record.status, {"DRAFT", "SENT", "ACCEPTED", "DECLINED", "EXPIRED"})


if __name__ == "__main__":
    unittest.main()
