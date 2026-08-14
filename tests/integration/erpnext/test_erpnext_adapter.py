"""Integration tests for ERPNext adapter (ADP-002).

These tests run the provider-neutral contract suite against the isolated
ERPNext instance (EVAL-002). They require the ERPNext pilot environment
to be running (./start.sh in environments/erpnext-pilot/).

All tests use synthetic opaque refs only. No live data, no production.
"""
from __future__ import annotations

import os
import unittest
from decimal import Decimal

from src.adapters.erpnext import ErpNextAdapter, ErpNextConfig
from src.contracts.erp_port import (
    DocumentRejected,
    DraftInvoiceCommand,
    DraftPaymentCommand,
    InvoiceLine,
    PostingOutcome,
    ReversalCommand,
    UncertainOutcome,
)
from src.contracts.financial_identity import FinancialIdentity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _config() -> ErpNextConfig:
    """Build config from environment (synthetic secrets only)."""
    return ErpNextConfig(
        base_url=os.environ.get("ERPNEXT_URL", "http://127.0.0.1:18080"),
        site_name=os.environ.get("ERPNEXT_SITE", "erpnext-pilot.localhost"),
        admin_password=os.environ.get("ERPNEXT_ADMIN_PASSWORD", "2be0d0946a2e3d841301c45fb19dde011d179fdcc044b3a74893071eac314090"),
        timeout_seconds=30,
    )


def _identity(unit: str = "UNIT-BM") -> FinancialIdentity:
    return FinancialIdentity(
        operating_unit_ref=unit,
        legal_issuer_ref="ISSUER-CV",
        tax_profile_ref="TAX-NONPPN",
        invoice_series_ref="SERIES-INV",
        receivable_ledger_ref="LEDGER-AR",
        destination_account_alias="ACC-OPERASIONAL",
    )


def _line(quantity: str = "1", price: str = "1000000", service: str = "SVC-ADS") -> InvoiceLine:
    return InvoiceLine(
        service_ref=service,
        description="Layanan sintetis",
        quantity=quantity,
        unit_price_amount=price,
        currency="IDR",
    )


def _command(**overrides) -> DraftInvoiceCommand:
    params = {
        "customer_ref": "CUST-ALPHA",
        "identity": _identity(),
        "lines": (_line(),),
        "issued_on": "2026-08-01",
        "due_on": "2026-08-31",
    }
    params.update(overrides)
    return DraftInvoiceCommand(**params)


def _money(amount: str) -> Decimal:
    return Decimal(amount)


# ---------------------------------------------------------------------------
# Contract test mixin (same as fixture adapter)
# ---------------------------------------------------------------------------


class ErpNextContractMixin:
    """Mixin: subclasses provide make_adapter and namespace."""

    def make_adapter(self) -> ErpNextAdapter:  # pragma: no cover - abstract
        raise NotImplementedError

    def setUp(self) -> None:
        self.adapter = self.make_adapter()

    # -- draft creation ---------------------------------------------------

    def test_draft_creation_reserves_no_official_number(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.assertTrue(draft_ref)
        record = self.adapter.read_invoice(draft_ref)
        self.assertEqual(record.status, "DRAFT")
        self.assertEqual(_money(record.total_amount), _money("1000000"))
        self.assertEqual(record.currency, "IDR")
        self.assertEqual(record.open_amount, record.total_amount)

    # -- post / read-back ---------------------------------------------------

    def test_post_invoice_assigns_official_reference(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.POSTED)
        self.assertIsNotNone(result.reference)
        # Official reference should be different from draft handle
        self.assertNotEqual(result.reference, draft_ref)
        # Read-back confirms POSTED
        record = self.adapter.read_invoice(result.reference)
        self.assertEqual(record.status, "POSTED")

    def test_post_invoice_idempotent(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result1 = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result1.outcome, PostingOutcome.POSTED)
        # Post same draft again — should be idempotent
        result2 = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result2.outcome, PostingOutcome.POSTED)
        self.assertEqual(result1.reference, result2.reference)

    def test_read_invoice_unknown_ref_fails(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.read_invoice("NONEXISTENT-INV-999")

    # -- payment ------------------------------------------------------------

    def test_record_payment_requires_evidence(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.POSTED)

        # Payment without evidence should fail
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(
                DraftPaymentCommand(
                    invoice_ref=result.reference,
                    amount="1000000",
                    currency="IDR",
                    evidence_ref="",  # Empty evidence
                    destination_account_alias="ACC-OPERASIONAL",
                )
            )

    def test_record_payment_success(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.POSTED)

        pay_ref = self.adapter.record_payment(
            DraftPaymentCommand(
                invoice_ref=result.reference,
                amount="1000000",
                currency="IDR",
                evidence_ref="EVI-001",
                destination_account_alias="ACC-OPERASIONAL",
            )
        )
        self.assertTrue(pay_ref)

        # Read-back payment
        payment = self.adapter.read_payment(pay_ref)
        self.assertEqual(payment.amount, "1000000")
        self.assertEqual(payment.evidence_ref, "EVI-001")

        # Invoice should be fully paid
        invoice = self.adapter.read_invoice(result.reference)
        self.assertEqual(_money(invoice.open_amount), _money("0"))

    def test_duplicate_evidence_ref_rejected(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.POSTED)

        # First payment with EVI-001
        pay_ref1 = self.adapter.record_payment(
            DraftPaymentCommand(
                invoice_ref=result.reference,
                amount="500000",
                currency="IDR",
                evidence_ref="EVI-001",
                destination_account_alias="ACC-OPERASIONAL",
            )
        )
        self.assertTrue(pay_ref1)

        # Second payment with same evidence ref should fail
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(
                DraftPaymentCommand(
                    invoice_ref=result.reference,
                    amount="500000",
                    currency="IDR",
                    evidence_ref="EVI-001",
                    destination_account_alias="ACC-OPERASIONAL",
                )
            )

    def test_overpayment_rejected(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.POSTED)

        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(
                DraftPaymentCommand(
                    invoice_ref=result.reference,
                    amount="2000000",  # More than total
                    currency="IDR",
                    evidence_ref="EVI-002",
                    destination_account_alias="ACC-OPERASIONAL",
                )
            )

    # -- reversal -----------------------------------------------------------

    def test_reverse_payment_creates_compensating_record(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.POSTED)

        pay_ref = self.adapter.record_payment(
            DraftPaymentCommand(
                invoice_ref=result.reference,
                amount="1000000",
                currency="IDR",
                evidence_ref="EVI-001",
                destination_account_alias="ACC-OPERASIONAL",
            )
        )

        # Reverse the payment
        rev_ref = self.adapter.reverse_payment(
            ReversalCommand(payment_ref=pay_ref, reason="Test reversal")
        )
        self.assertTrue(rev_ref)

        # Invoice should be open again
        invoice = self.adapter.read_invoice(result.reference)
        self.assertEqual(_money(invoice.open_amount), _money("1000000"))

    # -- cancellation ---------------------------------------------------------

    def test_cancel_draft_invoice(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.cancel_invoice(draft_ref)
        with self.assertRaises(DocumentRejected):
            self.adapter.read_invoice(draft_ref)

    def test_cancel_posted_invoice_reopens_nothing(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.POSTED)

        self.adapter.cancel_invoice(result.reference)
        invoice = self.adapter.read_invoice(result.reference)
        self.assertEqual(invoice.status, "CANCELLED")

    # -- query ----------------------------------------------------------------

    def test_query_invoices_scoped(self) -> None:
        # Create draft for UNIT-BM
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.post_invoice(draft_ref)

        # Query with correct scope
        result = self.adapter.query_invoices(operating_unit_ref="UNIT-BM")
        self.assertTrue(result.scoped)
        self.assertGreaterEqual(result.total, 1)

        # Query with wrong scope — should return empty
        result_wrong = self.adapter.query_invoices(operating_unit_ref="UNIT-XX")
        self.assertTrue(result_wrong.scoped)
        self.assertEqual(result_wrong.total, 0)

    # -- ping -----------------------------------------------------------------

    def test_ping(self) -> None:
        self.assertTrue(self.adapter.ping())

    # -- reconciliation ---------------------------------------------------------

    def test_reconcile_post_unknown_draft(self) -> None:
        result = self.adapter.reconcile_post("NONEXISTENT-DRAFT-999")
        self.assertEqual(result.outcome, PostingOutcome.REJECTED)

    def test_reconcile_payment_unknown_evidence(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.reconcile_payment("EVI-NONEXISTENT")

    def test_known_draft_refs(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        refs = self.adapter.known_draft_refs()
        self.assertIn(draft_ref, refs)

    def test_payment_evidence_index(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.POSTED)

        self.adapter.record_payment(
            DraftPaymentCommand(
                invoice_ref=result.reference,
                amount="1000000",
                currency="IDR",
                evidence_ref="EVI-001",
                destination_account_alias="ACC-OPERASIONAL",
            )
        )

        index = self.adapter.payment_evidence_index()
        evidence_refs = [ev for _, ev in index]
        self.assertIn("EVI-001", evidence_refs)


# ---------------------------------------------------------------------------
# Concrete test class
# ---------------------------------------------------------------------------


class TestErpNextAdapter(ErpNextContractMixin, unittest.TestCase):
    """Run contract suite against ERPNext adapter."""

    def make_adapter(self) -> ErpNextAdapter:
        config = _config()
        scope = frozenset({"UNIT-BM", "UNIT-PR1ME", "UNIT-KTR", "UNIT-BAL"})
        return ErpNextAdapter(config, scope)

    @classmethod
    def setUpClass(cls) -> None:
        """Verify ERPNext is running before tests."""
        config = _config()
        adapter = ErpNextAdapter(config, frozenset({"UNIT-BM"}))
        try:
            if not adapter.ping():
                raise unittest.SkipTest("ERPNext pilot not running")
        except UncertainOutcome as e:
            raise unittest.SkipTest(f"ERPNext pilot not running: {e}")


# ---------------------------------------------------------------------------
# Scope isolation tests
# ---------------------------------------------------------------------------


class TestErpNextScopeIsolation(unittest.TestCase):
    """Test that scope enforcement prevents cross-unit access."""

    def setUp(self) -> None:
        config = _config()
        # Adapter scoped to UNIT-BM only
        self.adapter_bm = ErpNextAdapter(config, frozenset({"UNIT-BM"}))
        # Adapter scoped to UNIT-PR1ME only
        self.adapter_pr1me = ErpNextAdapter(config, frozenset({"UNIT-PR1ME"}))

    def test_scoped_adapter_cannot_create_for_other_unit(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter_bm.create_draft_invoice(
                _command(identity=_identity("UNIT-PR1ME"))
            )

    def test_scoped_adapter_query_empty_for_other_unit(self) -> None:
        result = self.adapter_bm.query_invoices(operating_unit_ref="UNIT-PR1ME")
        self.assertTrue(result.scoped)
        self.assertEqual(result.total, 0)


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErpNextErrorHandling(unittest.TestCase):
    """Test error handling and edge cases."""

    def setUp(self) -> None:
        config = _config()
        self.adapter = ErpNextAdapter(config, frozenset({"UNIT-BM"}))

    def test_connection_error_raises_uncertain(self) -> None:
        # Use bad URL
        bad_config = ErpNextConfig(
            base_url="http://127.0.0.1:99999",
            site_name="test",
            admin_password="test",
            timeout_seconds=1,
        )
        adapter = ErpNextAdapter(bad_config, frozenset({"UNIT-BM"}))
        with self.assertRaises(UncertainOutcome):
            adapter.ping()


if __name__ == "__main__":
    unittest.main()
