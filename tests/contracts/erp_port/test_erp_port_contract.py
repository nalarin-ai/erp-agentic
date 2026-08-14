"""Contract test suite for the provider-neutral ERP port (ADP-001).

Runs the identical suite against every registered adapter implementation
(currently only the fixture adapter; ADP-002 will add ERPNext).

The suite proves, with synthetic opaque refs only:
- draft creation reserves nothing (no official number before verified post);
- post → read-back yields the official reference and OPEN receivable;
- payment recording requires evidence; duplicate evidence references are
  rejected; unknown invoice/payment refs fail closed;
- overpayment is rejected; partial payments sum to open amount;
- reversal is a compensating record, never a destructive edit; a reversed
  payment restores the open amount and the invoice status;
- cancelling a DRAFT works; cancelling a POSTED invoice is a compensating
  path and reopens nothing;
- queries intersect server-side scope (``scoped=True``) and never disclose
  other units' references;
- failure injection maps to REJECTED / UNCERTAIN semantics; the network
  must never be used by the fixture adapter;
- reconciliation: an UNCERTAIN post can be classified by reading back the
  external reference (no blind reissue).
"""
from __future__ import annotations

from decimal import Decimal
import socket
import unittest

from src.contracts.erp_port import (
    DocumentRejected,
    DraftInvoiceCommand,
    DraftPaymentCommand,
    ErpPort,
    InvoiceLine,
    PostingOutcome,
    ReversalCommand,
    UncertainOutcome,
)
from src.contracts.financial_identity import FinancialIdentity


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


class ErpPortContractMixin:
    """Mixin: subclasses provide ``make_adapter`` and ``namespace``."""

    def make_adapter(self) -> ErpPort:  # pragma: no cover - abstract
        raise NotImplementedError

    def setUp(self) -> None:
        self.adapter = self.make_adapter()

    # -- draft creation ---------------------------------------------------

    def test_draft_creation_reserves_no_official_number(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.assertTrue(draft_ref)
        record = self.adapter.read_invoice(draft_ref)
        self.assertEqual(record.status, "DRAFT")
        # The official reference must differ from any draft handle: the
        # fixture encodes drafts as DRAFT-* and official numbers as INV-*.
        self.assertTrue(draft_ref.startswith("DRAFT-"))
        self.assertEqual(_money(record.total_amount), _money("1000000"))
        self.assertEqual(record.currency, "IDR")
        self.assertEqual(record.open_amount, record.total_amount)

    def test_draft_total_reconciles_lines(self) -> None:
        command = _command(lines=(
            _line(quantity="2", price="1000000", service="SVC-ADS"),
            _line(quantity="1.5", price="400000", service="SVC-PROD"),
        ))
        draft_ref = self.adapter.create_draft_invoice(command)
        record = self.adapter.read_invoice(draft_ref)
        # 2*1000000 + 1.5*400000 = 2600000
        self.assertEqual(_money(record.total_amount), _money("2600000"))

    def test_draft_rejects_invalid_dates(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.create_draft_invoice(_command(issued_on="2026-08-31", due_on="2026-08-01"))

    def test_draft_rejects_empty_lines(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.create_draft_invoice(_command(lines=()))

    def test_draft_rejects_zero_or_negative_line_amounts(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.create_draft_invoice(_command(lines=(_line(price="0"),)))
        with self.assertRaises(DocumentRejected):
            self.adapter.create_draft_invoice(_command(lines=(_line(quantity="-1"),)))

    def test_draft_payload_carries_opaque_identity(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        record = self.adapter.read_invoice(draft_ref)
        identity = record.payload["identity"]
        self.assertEqual(identity["operating_unit_ref"], "UNIT-BM")
        self.assertEqual(identity["legal_issuer_ref"], "ISSUER-CV")
        self.assertEqual(identity["destination_account_alias"], "ACC-OPERASIONAL")

    # -- posting ------------------------------------------------------------

    def test_post_assigns_official_reference_and_opens_receivable(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.POSTED)
        self.assertIsNotNone(result.reference)
        assert result.reference is not None
        self.assertTrue(result.reference.startswith("INV-"))
        record = self.adapter.read_invoice(result.reference)
        self.assertEqual(record.status, "POSTED")
        self.assertEqual(record.open_amount, record.total_amount)

    def test_post_is_idempotent_per_draft(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        first = self.adapter.post_invoice(draft_ref)
        second = self.adapter.post_invoice(draft_ref)
        self.assertEqual(first.outcome, PostingOutcome.POSTED)
        self.assertEqual(second.outcome, PostingOutcome.POSTED)
        self.assertEqual(first.reference, second.reference)
        # Exactly one POSTED invoice exists for this draft.
        query = self.adapter.query_invoices(status="POSTED")
        self.assertEqual(query.references.count(first.reference), 1)

    def test_post_unknown_reference_fails_closed(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.post_invoice("DRAFT-NOPE")

    def test_official_sequence_is_monotonic_per_series(self) -> None:
        first = self.adapter.post_invoice(self.adapter.create_draft_invoice(_command()))
        second = self.adapter.post_invoice(self.adapter.create_draft_invoice(_command()))
        assert first.reference is not None and second.reference is not None
        first_seq = int(first.reference.rsplit("-", 1)[1])
        second_seq = int(second.reference.rsplit("-", 1)[1])
        self.assertGreater(second_seq, first_seq)

    # -- payments -----------------------------------------------------------

    def _posted_invoice(self) -> str:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        assert result.reference is not None
        return result.reference

    def test_payment_requires_evidence_reference(self) -> None:
        invoice_ref = self._posted_invoice()
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=invoice_ref, amount="1000000", currency="IDR",
                evidence_ref="", destination_account_alias="ACC-OPERASIONAL",
            ))

    def test_payment_reduces_open_amount_and_marks_paid(self) -> None:
        invoice_ref = self._posted_invoice()
        payment_ref = self.adapter.record_payment(DraftPaymentCommand(
            invoice_ref=invoice_ref, amount="400000", currency="IDR",
            evidence_ref="EVI-TF-001", destination_account_alias="ACC-OPERASIONAL",
        ))
        record = self.adapter.read_invoice(invoice_ref)
        self.assertEqual(_money(record.open_amount), _money("600000"))
        self.assertEqual(record.status, "POSTED")  # partially paid remains POSTED
        payment = self.adapter.read_payment(payment_ref)
        self.assertEqual(payment.evidence_ref, "EVI-TF-001")
        self.assertIsNone(payment.reversal_of)
        self.adapter.record_payment(DraftPaymentCommand(
            invoice_ref=invoice_ref, amount="600000", currency="IDR",
            evidence_ref="EVI-TF-002", destination_account_alias="ACC-OPERASIONAL",
        ))
        self.assertEqual(_money(self.adapter.read_invoice(invoice_ref).open_amount), _money("0"))

    def test_overpayment_rejected(self) -> None:
        invoice_ref = self._posted_invoice()
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=invoice_ref, amount="1000001", currency="IDR",
                evidence_ref="EVI-TF-003", destination_account_alias="ACC-OPERASIONAL",
            ))

    def test_payment_rejects_currency_mismatch(self) -> None:
        invoice_ref = self._posted_invoice()
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=invoice_ref, amount="100", currency="USD",
                evidence_ref="EVI-TF-004", destination_account_alias="ACC-OPERASIONAL",
            ))

    def test_payment_unknown_invoice_fails_closed(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref="INV-NOPE", amount="100", currency="IDR",
                evidence_ref="EVI-TF-005", destination_account_alias="ACC-OPERASIONAL",
            ))

    def test_duplicate_evidence_reference_rejected(self) -> None:
        invoice_ref = self._posted_invoice()
        self.adapter.record_payment(DraftPaymentCommand(
            invoice_ref=invoice_ref, amount="100000", currency="IDR",
            evidence_ref="EVI-DUP-1", destination_account_alias="ACC-OPERASIONAL",
        ))
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=invoice_ref, amount="100000", currency="IDR",
                evidence_ref="EVI-DUP-1", destination_account_alias="ACC-OPERASIONAL",
            ))

    def test_payment_on_unposted_draft_rejected(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=draft_ref, amount="100", currency="IDR",
                evidence_ref="EVI-TF-006", destination_account_alias="ACC-OPERASIONAL",
            ))

    # -- reversal -----------------------------------------------------------

    def test_reversal_is_compensating_and_restores_open_amount(self) -> None:
        invoice_ref = self._posted_invoice()
        payment_ref = self.adapter.record_payment(DraftPaymentCommand(
            invoice_ref=invoice_ref, amount="1000000", currency="IDR",
            evidence_ref="EVI-TF-010", destination_account_alias="ACC-OPERASIONAL",
        ))
        self.assertEqual(_money(self.adapter.read_invoice(invoice_ref).open_amount), _money("0"))
        reversal_ref = self.adapter.reverse_payment(ReversalCommand(
            payment_ref=payment_ref, reason="double transfer",
        ))
        reversal = self.adapter.read_payment(reversal_ref)
        self.assertEqual(reversal.reversal_of, payment_ref)
        # Original payment remains intact (no destructive edit).
        original = self.adapter.read_payment(payment_ref)
        self.assertIsNone(original.reversal_of)
        self.assertEqual(_money(original.amount), _money("1000000"))
        # Open amount restored.
        self.assertEqual(_money(self.adapter.read_invoice(invoice_ref).open_amount), _money("1000000"))

    def test_reversal_of_reversal_rejected(self) -> None:
        invoice_ref = self._posted_invoice()
        payment_ref = self.adapter.record_payment(DraftPaymentCommand(
            invoice_ref=invoice_ref, amount="1000000", currency="IDR",
            evidence_ref="EVI-TF-011", destination_account_alias="ACC-OPERASIONAL",
        ))
        reversal_ref = self.adapter.reverse_payment(ReversalCommand(
            payment_ref=payment_ref, reason="refund",
        ))
        with self.assertRaises(DocumentRejected):
            self.adapter.reverse_payment(ReversalCommand(
                payment_ref=reversal_ref, reason="double reversal",
            ))

    def test_double_reversal_of_same_payment_rejected(self) -> None:
        invoice_ref = self._posted_invoice()
        payment_ref = self.adapter.record_payment(DraftPaymentCommand(
            invoice_ref=invoice_ref, amount="1000000", currency="IDR",
            evidence_ref="EVI-TF-012", destination_account_alias="ACC-OPERASIONAL",
        ))
        self.adapter.reverse_payment(ReversalCommand(payment_ref=payment_ref, reason="r1"))
        with self.assertRaises(DocumentRejected):
            self.adapter.reverse_payment(ReversalCommand(payment_ref=payment_ref, reason="r2"))

    def test_reversal_unknown_payment_fails_closed(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.reverse_payment(ReversalCommand(payment_ref="PAY-NOPE", reason="x"))

    # -- cancellation ---------------------------------------------------------

    def test_cancel_draft_succeeds_and_blocks_post(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.cancel_invoice(draft_ref)
        record = self.adapter.read_invoice(draft_ref)
        self.assertEqual(record.status, "CANCELLED")
        with self.assertRaises(DocumentRejected):
            self.adapter.post_invoice(draft_ref)

    def test_cancel_posted_invoice_is_compensating_path(self) -> None:
        invoice_ref = self._posted_invoice()
        self.adapter.cancel_invoice(invoice_ref)
        record = self.adapter.read_invoice(invoice_ref)
        self.assertEqual(record.status, "CANCELLED")
        # A cancelled posted invoice keeps its official reference for audit;
        # the open receivable is closed by the cancellation.
        self.assertTrue(record.reference.startswith("INV-"))
        self.assertEqual(_money(record.open_amount), _money("0"))

    def test_cancel_paid_invoice_rejected(self) -> None:
        invoice_ref = self._posted_invoice()
        self.adapter.record_payment(DraftPaymentCommand(
            invoice_ref=invoice_ref, amount="1000000", currency="IDR",
            evidence_ref="EVI-TF-020", destination_account_alias="ACC-OPERASIONAL",
        ))
        with self.assertRaises(DocumentRejected):
            self.adapter.cancel_invoice(invoice_ref)

    # -- query / scope --------------------------------------------------------

    def test_query_reports_server_side_scope(self) -> None:
        self.adapter.create_draft_invoice(_command())
        self._posted_invoice()
        result = self.adapter.query_invoices(status="POSTED")
        # A status-only filter carries no authorization scope (ADP-QA-05):
        # the fixture must not claim server-side scope was applied.
        self.assertFalse(result.scoped)
        self.assertEqual(result.total, len(result.references))
        self.assertGreaterEqual(result.total, 1)
        scoped = self.adapter.query_invoices(status="POSTED", operating_unit_ref="UNIT-BM")
        self.assertTrue(scoped.scoped)
        self.assertEqual(scoped.total, 1)

    def test_query_filter_by_unit_never_leaks_other_units(self) -> None:
        self.adapter.create_draft_invoice(_command(identity=_identity("UNIT-BM")))
        self.adapter.create_draft_invoice(_command(identity=_identity("UNIT-P1")))
        bm = self.adapter.query_invoices(operating_unit_ref="UNIT-BM")
        self.assertTrue(bm.scoped)
        self.assertEqual(bm.total, 1)
        for ref in bm.references:
            record = self.adapter.read_invoice(ref)
            self.assertEqual(record.payload["identity"]["operating_unit_ref"], "UNIT-BM")

    def test_query_unknown_status_returns_empty(self) -> None:
        result = self.adapter.query_invoices(status="POSTED")
        self.assertEqual(result.total, 0)
        self.assertEqual(result.references, ())


class FixtureAdapterContractTest(ErpPortContractMixin, unittest.TestCase):
    """Bind the contract suite to the deterministic fixture adapter."""

    def make_adapter(self) -> ErpPort:
        from src.adapters.fixture.erp import FixtureErpAdapter

        return FixtureErpAdapter(series_prefix="INV", next_sequence=1)

    # -- fixture-specific behaviour -----------------------------------------

    def test_fixture_never_uses_network(self) -> None:
        def _explode(*args, **kwargs):  # pragma: no cover - guard
            raise AssertionError("fixture adapter must not open sockets")

        original = socket.socket
        socket.socket = _explode  # type: ignore[assignment]
        try:
            draft_ref = self.adapter.create_draft_invoice(_command())
            result = self.adapter.post_invoice(draft_ref)
            self.assertEqual(result.outcome, PostingOutcome.POSTED)
        finally:
            socket.socket = original  # type: ignore[assignment]

    def test_failure_injection_rejected_maps_to_verified_no_mutation(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        draft_ref = adapter.create_draft_invoice(_command())
        adapter.fail_next_post("REJECTED")
        result = adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.REJECTED)
        self.assertIsNone(result.reference)
        # Verified: the draft remains a draft, no official number was burned.
        self.assertEqual(adapter.read_invoice(draft_ref).status, "DRAFT")
        query = adapter.query_invoices(status="POSTED")
        self.assertEqual(query.total, 0)

    def test_failure_injection_uncertain_requires_reconciliation_not_blind_retry(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        draft_ref = adapter.create_draft_invoice(_command())
        adapter.fail_next_post("UNCERTAIN")
        result = adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.UNCERTAIN)
        self.assertIsNone(result.reference)
        # Blind retry is forbidden while uncertain: classification first.
        with self.assertRaises(UncertainOutcome):
            adapter.post_invoice(draft_ref)
        # Reconciliation read-back: the provider actually applied the post,
        # so the classification resolves to the official reference.
        resolved = adapter.reconcile_post(draft_ref)
        self.assertEqual(resolved.outcome, PostingOutcome.POSTED)
        assert resolved.reference is not None
        self.assertTrue(resolved.reference.startswith("INV-"))
        # After resolution, posting the same draft is the idempotent no-op.
        again = adapter.post_invoice(draft_ref)
        self.assertEqual(again.outcome, PostingOutcome.POSTED)
        self.assertEqual(again.reference, resolved.reference)

    def test_uncertain_payment_never_duplicates_after_reconcile(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        invoice_ref = self._posted_invoice()
        adapter.fail_next_payment("UNCERTAIN")
        with self.assertRaises(UncertainOutcome):
            adapter.record_payment(DraftPaymentCommand(
                invoice_ref=invoice_ref, amount="500000", currency="IDR",
                evidence_ref="EVI-TF-030", destination_account_alias="ACC-OPERASIONAL",
            ))
        # The evidence ref is now reserved; blind retry with same evidence fails.
        with self.assertRaises(DocumentRejected):
            adapter.record_payment(DraftPaymentCommand(
                invoice_ref=invoice_ref, amount="500000", currency="IDR",
                evidence_ref="EVI-TF-030", destination_account_alias="ACC-OPERASIONAL",
            ))
        resolved = adapter.reconcile_payment("EVI-TF-030")
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(_money(adapter.read_invoice(invoice_ref).open_amount), _money("500000"))

    def test_outbox_delivery_is_orthogonal_to_posting(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        draft_ref = adapter.create_draft_invoice(_command())
        result = adapter.post_invoice(draft_ref)
        assert result.reference is not None
        # Delivery starts NOT_READY / unsent and can fail independently
        # without invalidating the posted document.
        adapter.fail_next_delivery()
        delivery = adapter.enqueue_delivery(result.reference, channel_ref="CHAN-OPS")
        self.assertEqual(delivery.status, "FAILED_RETRYABLE")
        self.assertEqual(adapter.read_invoice(result.reference).status, "POSTED")
        retry = adapter.enqueue_delivery(result.reference, channel_ref="CHAN-OPS")
        self.assertEqual(retry.status, "SENT")
        # Exactly one logical outbox entry per (document, channel).
        self.assertEqual(delivery.reference, retry.reference)

    def test_ping_false_when_adapter_unavailable(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        self.assertTrue(adapter.ping())
        adapter.simulate_outage(True)
        self.assertFalse(adapter.ping())
        with self.assertRaises(DocumentRejected):
            adapter.create_draft_invoice(_command())
        adapter.simulate_outage(False)
        self.assertTrue(adapter.ping())

    def test_adapter_rejects_non_canonical_amount(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.create_draft_invoice(_command(lines=(_line(price="1.0.0"),)))
        with self.assertRaises(DocumentRejected):
            self.adapter.create_draft_invoice(_command(lines=(_line(price="abc"),)))

    def test_reconcile_unknown_post_is_absent_not_present(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        draft_ref = adapter.create_draft_invoice(_command())
        adapter.fail_next_post("UNCERTAIN_DROP")  # provider never applied it
        result = adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.UNCERTAIN)
        resolved = adapter.reconcile_post(draft_ref)
        self.assertEqual(resolved.outcome, PostingOutcome.REJECTED)
        # Safe to retry after classification: the draft posts normally.
        retry = adapter.post_invoice(draft_ref)
        self.assertEqual(retry.outcome, PostingOutcome.POSTED)


class FixtureAdapterQaRemediationTest(unittest.TestCase):
    """Regression tests closing independent-QA round-1 findings (ADP-QA-01..08).

    Written RED-first: every test failed against the pre-remediation adapter.
    """

    def make_adapter(self) -> ErpPort:
        from src.adapters.fixture.erp import FixtureErpAdapter

        return FixtureErpAdapter(series_prefix="INV", next_sequence=1)

    def setUp(self) -> None:
        self.adapter = self.make_adapter()

    # ADP-QA-01 (HIGH): currency must be validated as ISO-4217 uppercase.
    def test_qa01_draft_rejects_lowercase_currency(self) -> None:
        with self.assertRaises(DocumentRejected):
            self.adapter.create_draft_invoice(_command(lines=(
                InvoiceLine(service_ref="SVC-ADS", description="x", quantity="1",
                            unit_price_amount="100", currency="idr"),
            )))
        with self.assertRaises(DocumentRejected):
            self.adapter.create_draft_invoice(_command(lines=(
                InvoiceLine(service_ref="SVC-ADS", description="x", quantity="1",
                            unit_price_amount="100", currency="IDRS"),
            )))
        with self.assertRaises(DocumentRejected):
            self.adapter.create_draft_invoice(_command(lines=(
                InvoiceLine(service_ref="SVC-ADS", description="x", quantity="1",
                            unit_price_amount="100", currency="I1R"),
            )))

    def test_qa01_payment_rejects_lowercase_currency(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        assert result.reference is not None
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=result.reference, amount="100", currency="idr",
                evidence_ref="EVI-QA-01", destination_account_alias="ACC-OPERASIONAL",
            ))

    # ADP-QA-02 (HIGH): whitespace-only evidence refs are not evidence.
    def test_qa02_payment_rejects_whitespace_evidence(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        assert result.reference is not None
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=result.reference, amount="100", currency="IDR",
                evidence_ref="   ", destination_account_alias="ACC-OPERASIONAL",
            ))
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=result.reference, amount="100", currency="IDR",
                evidence_ref="\t\n", destination_account_alias="ACC-OPERASIONAL",
            ))

    # ADP-QA-03 (HIGH): UNCERTAIN post must not leak the official reference.
    def test_qa03_uncertain_post_reason_does_not_leak_official_ref(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        draft_ref = adapter.create_draft_invoice(_command())
        adapter.fail_next_post("UNCERTAIN")
        result = adapter.post_invoice(draft_ref)
        self.assertEqual(result.outcome, PostingOutcome.UNCERTAIN)
        self.assertIsNone(result.reference)
        self.assertNotIn("INV-", result.reason or "")
        # The only way to learn the reference is reconciliation.
        resolved = adapter.reconcile_post(draft_ref)
        self.assertEqual(resolved.outcome, PostingOutcome.POSTED)
        self.assertTrue((resolved.reference or "").startswith("INV-"))

    # ADP-QA-04 (MEDIUM): reads during outage are non-authoritative; fail closed.
    def test_qa04_reads_fail_closed_during_outage(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        draft_ref = adapter.create_draft_invoice(_command())
        result = adapter.post_invoice(draft_ref)
        assert result.reference is not None
        payment_ref = adapter.record_payment(DraftPaymentCommand(
            invoice_ref=result.reference, amount="100", currency="IDR",
            evidence_ref="EVI-QA-04", destination_account_alias="ACC-OPERASIONAL",
        ))
        adapter.simulate_outage(True)
        with self.assertRaises(DocumentRejected):
            adapter.read_invoice(result.reference)
        with self.assertRaises(DocumentRejected):
            adapter.read_payment(payment_ref)
        adapter.simulate_outage(False)
        self.assertEqual(adapter.read_invoice(result.reference).status, "POSTED")

    # ADP-QA-05 (MEDIUM): unscoped query must not claim scoped=True silently.
    def test_qa05_unscoped_query_is_explicitly_flagged(self) -> None:
        self.adapter.create_draft_invoice(_command(identity=_identity("UNIT-BM")))
        self.adapter.create_draft_invoice(_command(identity=_identity("UNIT-P1")))
        unscoped = self.adapter.query_invoices()
        # The fixture has no caller context, so an unscoped query must not
        # claim that server-side scope was applied.
        self.assertFalse(unscoped.scoped)
        scoped = self.adapter.query_invoices(operating_unit_ref="UNIT-BM")
        self.assertTrue(scoped.scoped)
        self.assertEqual(scoped.total, 1)

    # ADP-QA-06 (MEDIUM): reconcile_payment on unknown evidence fails closed.
    def test_qa06_reconcile_unknown_payment_evidence_raises(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        with self.assertRaises(DocumentRejected):
            adapter.reconcile_payment("EVI-NOPE")

    # ADP-QA-07 (LOW): reversal evidence refs are namespaced, never concatenated.
    def test_qa07_reversal_evidence_ref_is_namespaced(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        assert result.reference is not None
        payment_ref = self.adapter.record_payment(DraftPaymentCommand(
            invoice_ref=result.reference, amount="1000000", currency="IDR",
            evidence_ref="EVI-QA-07", destination_account_alias="ACC-OPERASIONAL",
        ))
        reversal_ref = self.adapter.reverse_payment(ReversalCommand(
            payment_ref=payment_ref, reason="correction",
        ))
        reversal = self.adapter.read_payment(reversal_ref)
        self.assertTrue(reversal.evidence_ref.startswith("EVI-REV-"))
        self.assertNotEqual(reversal.evidence_ref, "EVI-QA-07-REV")

    # ADP-QA-08 (LOW): concurrent posting yields unique monotonic references.
    def test_qa08_concurrent_posts_are_unique_and_monotonic(self) -> None:
        import threading

        results: list[str] = []
        errors: list[BaseException] = []

        def _post_one() -> None:
            try:
                draft_ref = self.adapter.create_draft_invoice(_command())
                posted = self.adapter.post_invoice(draft_ref)
                assert posted.reference is not None
                results.append(posted.reference)
            except BaseException as exc:  # pragma: no cover - defensive
                errors.append(exc)

        threads = [threading.Thread(target=_post_one) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 16)
        self.assertEqual(len(set(results)), 16)
        sequences = sorted(int(ref.rsplit("-", 1)[1]) for ref in results)
        self.assertEqual(sequences, list(range(1, 17)))

    # ADP-QA-09 (LOW): caller evidence refs must not collide with the reserved
    # reversal namespace, and reversal refs are reserved upon creation.
    def test_qa09_caller_cannot_reserve_reversal_namespace(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        assert result.reference is not None
        with self.assertRaises(DocumentRejected):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=result.reference, amount="100", currency="IDR",
                evidence_ref="EVI-REV-PAY-000001",
                destination_account_alias="ACC-OPERASIONAL",
            ))

    def test_qa09_reversal_ref_is_reserved_and_reconcile_is_unambiguous(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        draft_ref = adapter.create_draft_invoice(_command())
        result = adapter.post_invoice(draft_ref)
        assert result.reference is not None
        payment_ref = adapter.record_payment(DraftPaymentCommand(
            invoice_ref=result.reference, amount="1000000", currency="IDR",
            evidence_ref="EVI-QA-09", destination_account_alias="ACC-OPERASIONAL",
        ))
        reversal_ref = adapter.reverse_payment(ReversalCommand(
            payment_ref=payment_ref, reason="correction",
        ))
        reversal = adapter.read_payment(reversal_ref)
        # The reversal evidence ref is reserved: no later payment can reuse it.
        other_ref = adapter.post_invoice(adapter.create_draft_invoice(_command()))
        assert other_ref.reference is not None
        with self.assertRaises(DocumentRejected):
            adapter.record_payment(DraftPaymentCommand(
                invoice_ref=other_ref.reference, amount="100", currency="IDR",
                evidence_ref=reversal.evidence_ref,
                destination_account_alias="ACC-OPERASIONAL",
            ))
        # Reconciliation by the reversal evidence ref resolves to the reversal.
        resolved = adapter.reconcile_payment(reversal.evidence_ref)
        self.assertEqual(resolved.reference, reversal_ref)

    # ADP-QA-10 (LOW): payment-path UncertainOutcome must not leak internal refs.
    def test_qa10_uncertain_payment_error_does_not_leak_internal_ref(self) -> None:
        from src.adapters.fixture.erp import FixtureErpAdapter

        adapter: FixtureErpAdapter = self.adapter  # type: ignore[assignment]
        draft_ref = adapter.create_draft_invoice(_command())
        result = adapter.post_invoice(draft_ref)
        assert result.reference is not None
        adapter.fail_next_payment("UNCERTAIN")
        with self.assertRaises(UncertainOutcome) as caught:
            adapter.record_payment(DraftPaymentCommand(
                invoice_ref=result.reference, amount="500000", currency="IDR",
                evidence_ref="EVI-QA-10", destination_account_alias="ACC-OPERASIONAL",
            ))
        self.assertNotIn("PAY-", str(caught.exception))
        # The reserved evidence ref still protects against blind retry.
        with self.assertRaises(DocumentRejected):
            adapter.record_payment(DraftPaymentCommand(
                invoice_ref=result.reference, amount="500000", currency="IDR",
                evidence_ref="EVI-QA-10", destination_account_alias="ACC-OPERASIONAL",
            ))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
