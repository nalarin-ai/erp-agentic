"""ISOFIX-001 live requalification: gateway surfaces functional + scoped.

The final architecture must leave unit actors fully functional through the
gateway layer (CRM port / ERP port) while scope enforcement stays
fail-closed. These tests run the proven adapters against the isolated
pilot and record final-architecture probes:

- CRM search per unit returns only in-unit markers;
- cross-unit reads/searches are denied or marker-free;
- ERP port payment evidence index carries no cross-unit refs;
- unassigned / cross-unit access is CrmDenied (fail-closed).

Assertions never weaken: a cross-unit leak here fails the suite.
"""
from __future__ import annotations

import os
import unittest

from src.adapters.erpnext import ErpNextConfig
from src.crm.port import CrmDenied, CrmIdentity, CrmQuery, ExportRequest

from tests.security.isolation_final import _harness as fh
from tests.security.isolation_final.seed_final import ensure_final_architecture_seeded
from tests.security.native_erp import _harness as h


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


def _adapter(scope: frozenset[str]):
    from src.adapters.erpnext_crm import ErpNextCrmAdapter

    return ErpNextCrmAdapter(
        _config(),
        authorized_scope=scope,
        assignments={
            "iso-sales-bm": frozenset({"UNIT-BM"}),
            "iso-sales-p1": frozenset({"UNIT-PR1ME"}),
            "iso-owner": frozenset({"UNIT-BM", "UNIT-PR1ME"}),
        },
    )


class TestFinalGatewayFunctional(unittest.TestCase):
    """Gateway layer remains functional and fail-closed on final architecture."""

    @classmethod
    def setUpClass(cls) -> None:
        h.ensure_all_seeded()
        ensure_final_architecture_seeded()

    def test_gateway_search_bm_excludes_p1_markers(self) -> None:
        adapter = _adapter(frozenset({"UNIT-BM"}))
        identity = CrmIdentity(actor_ref="iso-sales-bm", operating_unit_ref="UNIT-BM")
        page = adapter.search_leads(CrmQuery(identity=identity, text="ISO"))
        body = " ".join(page.references)
        leaks = h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_BM))
        fh.record_probe(
            "final-gateway-crm", "iso-sales-bm", "search_leads txt='ISO'",
            "in-unit only; zero P1 markers", 200, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_BM),
            detail=f"items={len(page.references)} total={page.total}",
        )
        self.assertEqual(leaks, [], f"cross-unit leak via gateway search: {leaks}")

    def test_gateway_search_p1_excludes_bm_markers(self) -> None:
        adapter = _adapter(frozenset({"UNIT-PR1ME"}))
        identity = CrmIdentity(actor_ref="iso-sales-p1", operating_unit_ref="UNIT-PR1ME")
        page = adapter.search_leads(CrmQuery(identity=identity, text="ISO"))
        body = " ".join(page.references)
        leaks = h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_P1))
        fh.record_probe(
            "final-gateway-crm", "iso-sales-p1", "search_leads txt='ISO'",
            "in-unit only; zero BM markers", 200, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_P1),
            detail=f"items={len(page.references)} total={page.total}",
        )
        self.assertEqual(leaks, [], f"cross-unit leak via gateway search: {leaks}")

    def test_gateway_read_cross_unit_lead_denied(self) -> None:
        adapter = _adapter(frozenset({"UNIT-BM"}))
        identity = CrmIdentity(actor_ref="iso-sales-bm", operating_unit_ref="UNIT-BM")
        p1_lead = h.find_lead_name_by_marker(h.MARKER_P1)
        self.assertIsNotNone(p1_lead, "ISO-001 P1 lead marker must exist")
        denied = False
        try:
            adapter.read_lead(identity, p1_lead)  # type: ignore[arg-type]
        except (CrmDenied, Exception) as exc:  # noqa: BLE001 - classified below
            denied = isinstance(exc, CrmDenied) or type(exc).__name__ in {
                "CrmDenied", "CrmNotFound",
            }
        fh.record_probe(
            "final-gateway-crm", "iso-sales-bm",
            f"read_lead cross-unit {p1_lead}", "denied fail-closed",
            403 if denied else 200, p1_lead or "",
            tokens=h.cross_unit_tokens(h.USER_SALES_BM),
            detail=f"denied={denied}",
        )
        self.assertTrue(denied, "cross-unit lead read must be denied fail-closed")

    def test_gateway_unassigned_unit_denied(self) -> None:
        adapter = _adapter(frozenset({"UNIT-BM"}))
        identity = CrmIdentity(actor_ref="iso-sales-bm", operating_unit_ref="UNIT-PR1ME")
        with self.assertRaises(CrmDenied):
            adapter.search_leads(CrmQuery(identity=identity, text="ISO"))
        fh.record_probe(
            "final-gateway-crm", "iso-sales-bm",
            "search_leads unassigned unit UNIT-PR1ME", "CrmDenied fail-closed",
            403, "", tokens=(), detail="CrmDenied raised",
        )

    def test_gateway_export_scope_bounded(self) -> None:
        adapter = _adapter(frozenset({"UNIT-PR1ME"}))
        identity = CrmIdentity(actor_ref="iso-sales-p1", operating_unit_ref="UNIT-PR1ME")
        result = adapter.export(
            ExportRequest(identity=identity, kind="LEAD", evidence_ref="EVI-ISOFIX-001", max_rows=100)
        )
        rows_text = str(result.rows)
        leaks = h.scan_markers(rows_text, tokens=h.cross_unit_tokens(h.USER_SALES_P1))
        fh.record_probe(
            "final-gateway-crm", "iso-sales-p1", "export max_rows=100",
            "zero BM markers in export rows", 200, rows_text[:2000],
            tokens=h.cross_unit_tokens(h.USER_SALES_P1),
            detail=f"rows={result.row_count} evidence={result.evidence_ref}",
        )
        self.assertEqual(leaks, [], f"cross-unit leak via gateway export: {leaks}")

    def test_gateway_erp_port_evidence_index_scope_bounded(self) -> None:
        from src.adapters.erpnext import ErpNextAdapter

        adapter = ErpNextAdapter(_config(), authorized_scope=frozenset({"UNIT-PR1ME"}))
        index = adapter.payment_evidence_index()
        refs = " ".join(f"{a} {b}" for a, b in index)
        leaks = h.scan_markers(refs, tokens=(h.CUSTOMER_BM, h.MARKER_BM))
        fh.record_probe(
            "final-gateway-erp", "iso-sales-p1", "payment_evidence_index",
            "zero BM refs in evidence index", 200, refs[:2000],
            tokens=(h.CUSTOMER_BM, h.MARKER_BM),
            detail=f"entries={len(index)}",
        )
        self.assertEqual(leaks, [], f"cross-unit leak via ERP port index: {leaks}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
