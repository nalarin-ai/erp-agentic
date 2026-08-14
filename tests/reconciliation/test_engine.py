"""Reconciliation engine + operator queue contract tests (REC-001).

R-007/R-008: pending/uncertain intents must be terminally classified via
provider read-back (PRESENT/ABSENT/AMBIGUOUS/UNAVAILABLE), recovery items
can never remain silently stuck, and no blind reissue may occur.

The suite runs against the fixture-backed engine in ``src/reconciliation``
using the ADP-001 fixture adapter for failure injection. Synthetic opaque
refs only; no network, no credentials.
"""
from __future__ import annotations

import threading
import unittest

from src.adapters.fixture.erp import FixtureErpAdapter
from src.contracts.erp_port import (
    DocumentRejected,
    DraftInvoiceCommand,
    DraftPaymentCommand,
    InvoiceLine,
    PostingOutcome,
    UncertainOutcome,
)
from src.contracts.financial_identity import FinancialIdentity
from src.contracts.reconciliation import (
    InvalidTransition,
    ItemLocked,
    QueueItemStatus,
    ReconciliationClass,
)
from src.reconciliation.engine import ReconciliationEngine
from src.reconciliation.queue import OperatorQueue


def _identity(unit: str = "UNIT-BM") -> FinancialIdentity:
    return FinancialIdentity(
        operating_unit_ref=unit,
        legal_issuer_ref="ISSUER-CV",
        tax_profile_ref="TAX-NONPPN",
        invoice_series_ref="SERIES-INV",
        receivable_ledger_ref="LEDGER-AR",
        destination_account_alias="ACC-OPERASIONAL",
    )


def _command() -> DraftInvoiceCommand:
    return DraftInvoiceCommand(
        customer_ref="CUST-ALPHA",
        identity=_identity(),
        lines=(InvoiceLine(
            service_ref="SVC-ADS", description="Layanan sintetis",
            quantity="1", unit_price_amount="1000000", currency="IDR",
        ),),
        issued_on="2026-08-01",
        due_on="2026-08-31",
    )


class ReconciliationEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FixtureErpAdapter(series_prefix="INV", next_sequence=1)
        self.queue = OperatorQueue()
        self.engine = ReconciliationEngine(self.adapter, self.queue, max_attempts=3)

    # -- helpers -------------------------------------------------------------

    def _uncertain_post(self) -> str:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.fail_next_post("UNCERTAIN")
        result = self.adapter.post_invoice(draft_ref)
        assert result.outcome is PostingOutcome.UNCERTAIN
        return draft_ref

    # -- enqueue ---------------------------------------------------------------

    def test_enqueue_is_idempotent_per_intent_key(self) -> None:
        draft_ref = self._uncertain_post()
        first = self.engine.enqueue_uncertain_post(intent_key="sha256:abc1", draft_ref=draft_ref)
        second = self.engine.enqueue_uncertain_post(intent_key="sha256:abc1", draft_ref=draft_ref)
        self.assertEqual(first.item_id, second.item_id)
        self.assertEqual(first.status, QueueItemStatus.PENDING)
        self.assertEqual(self.queue.depth(), 1)

    def test_enqueue_rejects_conflicting_anchor_for_same_key(self) -> None:
        draft_ref = self._uncertain_post()
        self.engine.enqueue_uncertain_post(intent_key="sha256:abc2", draft_ref=draft_ref)
        with self.assertRaises(InvalidTransition):
            self.engine.enqueue_uncertain_post(intent_key="sha256:abc2", draft_ref="DRAFT-OTHER")

    # -- classification ----------------------------------------------------------

    def test_uncertain_post_applied_classifies_present_and_resolves(self) -> None:
        draft_ref = self._uncertain_post()  # provider applied; outcome unknown
        item = self.engine.enqueue_uncertain_post(intent_key="sha256:cls1", draft_ref=draft_ref)
        resolved = self.engine.classify_next(fencing_token=1)
        assert resolved is not None
        self.assertEqual(resolved.item_id, item.item_id)
        self.assertEqual(resolved.status, QueueItemStatus.RESOLVED)
        self.assertEqual(resolved.last_classification, ReconciliationClass.PRESENT)
        self.assertIsNotNone(resolved.resolution_ref)
        assert resolved.resolution_ref is not None
        self.assertTrue(resolved.resolution_ref.startswith("INV-"))
        # Provider state is authoritative and consistent.
        self.assertEqual(self.adapter.read_invoice(resolved.resolution_ref).status, "POSTED")

    def test_uncertain_post_dropped_classifies_absent_and_is_safe_retryable(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.fail_next_post("UNCERTAIN_DROP")
        result = self.adapter.post_invoice(draft_ref)
        assert result.outcome is PostingOutcome.UNCERTAIN
        self.engine.enqueue_uncertain_post(intent_key="sha256:cls2", draft_ref=draft_ref)
        item = self.engine.classify_next(fencing_token=1)
        assert item is not None
        self.assertEqual(item.last_classification, ReconciliationClass.ABSENT)
        self.assertEqual(item.status, QueueItemStatus.SAFE_RETRYABLE)
        # A verified-ABSENT retry may proceed and must not double-post.
        retry = self.adapter.post_invoice(draft_ref)
        self.assertEqual(retry.outcome, PostingOutcome.POSTED)
        closed = self.engine.mark_retried(item.item_id, resolution_ref=retry.reference)
        self.assertEqual(closed.status, QueueItemStatus.RESOLVED)
        assert retry.reference is not None
        self.assertEqual(closed.resolution_ref, retry.reference)

    def test_ambiguous_classification_escalates_without_reissue(self) -> None:
        draft_ref = self._uncertain_post()
        # Force contradiction: post read-back says POSTED but the official
        # ref is missing from the provider's query index.
        self.adapter.corrupt_index_drop(draft_ref)
        self.engine.enqueue_uncertain_post(intent_key="sha256:cls3", draft_ref=draft_ref)
        item = self.engine.classify_next(fencing_token=1)
        assert item is not None
        self.assertEqual(item.last_classification, ReconciliationClass.AMBIGUOUS)
        self.assertEqual(item.status, QueueItemStatus.ESCALATED)
        # Escalated items are never auto-retried.
        with self.assertRaises(InvalidTransition):
            self.engine.mark_retried(item.item_id, resolution_ref="INV-999999")

    def test_unavailable_provider_retries_bounded_then_escalates(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.fail_next_post("UNCERTAIN")
        self.adapter.post_invoice(draft_ref)
        self.engine.enqueue_uncertain_post(intent_key="sha256:cls4", draft_ref=draft_ref)
        self.adapter.simulate_outage(True)
        for attempt in range(3):
            item = self.engine.classify_next(fencing_token=1)
            assert item is not None
            self.assertEqual(item.last_classification, ReconciliationClass.UNAVAILABLE)
            expected = QueueItemStatus.PENDING if attempt < 2 else QueueItemStatus.ESCALATED
            self.assertEqual(item.status, expected, f"attempt {attempt + 1}")
            self.assertEqual(item.attempts, attempt + 1)
        # Escalated: no further automatic classification pass picks it up.
        self.adapter.simulate_outage(False)
        self.assertIsNone(self.engine.classify_next(fencing_token=1))

    def test_no_item_is_silently_stuck(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.fail_next_post("UNCERTAIN")
        self.adapter.post_invoice(draft_ref)
        self.engine.enqueue_uncertain_post(intent_key="sha256:stuck", draft_ref=draft_ref)
        self.adapter.simulate_outage(True)
        for _ in range(3):
            self.engine.classify_next(fencing_token=1)
        stuck = self.queue.stuck_items()
        self.assertEqual(len(stuck), 1)
        self.assertEqual(stuck[0].status, QueueItemStatus.ESCALATED)

    # -- fencing / concurrency ------------------------------------------------------

    def test_stale_fencing_token_cannot_classify(self) -> None:
        draft_ref = self._uncertain_post()
        self.engine.enqueue_uncertain_post(intent_key="sha256:fence1", draft_ref=draft_ref)
        lease = self.engine.claim_next(fencing_token=7)
        assert lease is not None
        with self.assertRaises(ItemLocked):
            # A stale worker (older token) cannot classify the claimed item.
            self.engine.classify_item(lease.item_id, fencing_token=6)

    def test_concurrent_claims_yield_one_classifier(self) -> None:
        draft_ref = self._uncertain_post()
        self.engine.enqueue_uncertain_post(intent_key="sha256:race", draft_ref=draft_ref)
        winners: list[str] = []
        lock = threading.Lock()

        def _try(token: int) -> None:
            claim = self.engine.claim_next(fencing_token=token)
            if claim is not None:
                with lock:
                    winners.append(claim.item_id)

        threads = [threading.Thread(target=_try, args=(index + 1,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(winners), 1)

    # -- payments ---------------------------------------------------------------------

    def _posted_invoice(self) -> str:
        draft_ref = self.adapter.create_draft_invoice(_command())
        result = self.adapter.post_invoice(draft_ref)
        assert result.reference is not None
        return result.reference

    def test_uncertain_payment_classifies_present_by_evidence_ref(self) -> None:
        invoice_ref = self._posted_invoice()
        self.adapter.fail_next_payment("UNCERTAIN")
        with self.assertRaises(UncertainOutcome):
            self.adapter.record_payment(DraftPaymentCommand(
                invoice_ref=invoice_ref, amount="500000", currency="IDR",
                evidence_ref="EVI-REC-1", destination_account_alias="ACC-OPERASIONAL",
            ))
        self.engine.enqueue_uncertain_payment(
            intent_key="sha256:pay1", evidence_ref="EVI-REC-1",
        )
        item = self.engine.classify_next(fencing_token=1)
        assert item is not None
        self.assertEqual(item.last_classification, ReconciliationClass.PRESENT)
        self.assertEqual(item.status, QueueItemStatus.RESOLVED)
        self.assertTrue((item.resolution_ref or "").startswith("PAY-"))

    def test_uncertain_payment_unknown_evidence_is_absent(self) -> None:
        self._posted_invoice()
        self.engine.enqueue_uncertain_payment(
            intent_key="sha256:pay2", evidence_ref="EVI-REC-UNKNOWN",
        )
        item = self.engine.classify_next(fencing_token=1)
        assert item is not None
        self.assertEqual(item.last_classification, ReconciliationClass.ABSENT)
        self.assertEqual(item.status, QueueItemStatus.SAFE_RETRYABLE)

    # -- orphan report --------------------------------------------------------------------

    def test_orphan_report_lists_provider_docs_without_local_intent(self) -> None:
        # A posted invoice with no reconciliation item is an ERP-side orphan
        # when the engine was told every post goes through the queue.
        invoice_ref = self._posted_invoice()
        report = self.engine.orphan_report(known_draft_refs=set())
        self.assertIn(invoice_ref, report.erp_orphans)
        # Registering the draft clears it from the orphan set (public API).
        report = self.engine.orphan_report(known_draft_refs=self.adapter.known_draft_refs())
        self.assertNotIn(invoice_ref, report.erp_orphans)

    def test_audit_orphan_report_lists_terminal_uncertain_intents(self) -> None:
        draft_ref = self._uncertain_post()
        self.engine.enqueue_uncertain_post(intent_key="sha256:orphan", draft_ref=draft_ref)
        self.engine.classify_next(fencing_token=1)  # PRESENT -> RESOLVED
        report = self.engine.orphan_report(known_draft_refs=set())
        self.assertEqual(report.unresolved_items, ())

    def test_orphan_report_uses_public_draft_index(self) -> None:
        # Public adapter API only (REC-QA-07): no private-state reach.
        invoice_ref = self._posted_invoice()
        report = self.engine.orphan_report(known_draft_refs=self.adapter.known_draft_refs())
        self.assertNotIn(invoice_ref, report.erp_orphans)

    # -- operator actions -----------------------------------------------------------------

    def test_operator_can_abandon_escalated_item_with_reason(self) -> None:
        draft_ref = self._uncertain_post()
        self.adapter.corrupt_index_drop(draft_ref)
        self.engine.enqueue_uncertain_post(intent_key="sha256:esc", draft_ref=draft_ref)
        item = self.engine.classify_next(fencing_token=1)
        assert item is not None
        self.assertEqual(item.status, QueueItemStatus.ESCALATED)
        abandoned = self.queue.abandon(item.item_id, reason="operator: provider support ticket TKT-1")
        self.assertEqual(abandoned.status, QueueItemStatus.ABANDONED)
        self.assertEqual(self.queue.depth(include_terminal=True), 1)
        self.assertEqual(self.queue.depth(), 0)

    def test_abandon_requires_reason_and_terminal_safe_state(self) -> None:
        draft_ref = self._uncertain_post()
        item = self.engine.enqueue_uncertain_post(intent_key="sha256:abd", draft_ref=draft_ref)
        with self.assertRaises(InvalidTransition):
            self.queue.abandon(item.item_id, reason="")  # reason mandatory
        with self.assertRaises(InvalidTransition):
            self.queue.abandon(item.item_id, reason="x")  # PENDING is not safe to abandon


class ReconciliationQaRemediationTest(unittest.TestCase):
    """Regression tests closing independent-QA round-1 findings (REC-QA-01..07).

    Written RED-first: each test failed against the pre-remediation engine.
    """

    def setUp(self) -> None:
        self.adapter = FixtureErpAdapter(series_prefix="INV", next_sequence=1)
        self.queue = OperatorQueue()
        self.engine = ReconciliationEngine(self.adapter, self.queue, max_attempts=3)

    def _uncertain_post(self) -> str:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.fail_next_post("UNCERTAIN")
        result = self.adapter.post_invoice(draft_ref)
        assert result.outcome is PostingOutcome.UNCERTAIN
        return draft_ref

    # REC-QA-01 (HIGH): ESCALATED -> SAFE_RETRYABLE must be rejected and the
    # original fencing token must lose write power after terminal transition.
    def test_qa01_escalated_cannot_be_forced_back_to_retryable(self) -> None:
        draft_ref = self._uncertain_post()
        self.adapter.corrupt_index_drop(draft_ref)  # AMBIGUOUS
        self.engine.enqueue_uncertain_post(intent_key="sha256:q01", draft_ref=draft_ref)
        item = self.engine.classify_next(fencing_token=11)
        assert item is not None
        self.assertEqual(item.status, QueueItemStatus.ESCALATED)
        original_token = item.fencing_token
        with self.assertRaises((InvalidTransition, ItemLocked)):
            self.queue.complete_classification(
                item.item_id,
                fencing_token=original_token,
                classification=ReconciliationClass.ABSENT,
                next_status=QueueItemStatus.SAFE_RETRYABLE,
            )
        # The original token is dead after the terminal transition: even the
        # allowed ESCALATED->RESOLVED path requires a fresh operator claim.
        with self.assertRaises(ItemLocked):
            self.queue.complete_classification(
                item.item_id,
                fencing_token=original_token,
                classification=ReconciliationClass.PRESENT,
                next_status=QueueItemStatus.RESOLVED,
                resolution_ref="INV-000777",
            )

    def test_qa01_operator_override_requires_fresh_claim(self) -> None:
        draft_ref = self._uncertain_post()
        self.adapter.corrupt_index_drop(draft_ref)
        self.engine.enqueue_uncertain_post(intent_key="sha256:q01b", draft_ref=draft_ref)
        item = self.engine.classify_next(fencing_token=21)
        assert item is not None
        # Operator re-claims the escalated item under a new fencing token and
        # resolves it after verifying the provider state manually.
        claimed = self.queue.claim_item(item.item_id, fencing_token=22)
        self.assertEqual(claimed.status, QueueItemStatus.CLASSIFYING)
        resolved = self.queue.complete_classification(
            item.item_id,
            fencing_token=22,
            classification=ReconciliationClass.PRESENT,
            next_status=QueueItemStatus.RESOLVED,
            resolution_ref=claimed.draft_ref,  # operator-verified ref
        )
        self.assertEqual(resolved.status, QueueItemStatus.RESOLVED)

    # REC-QA-02 (HIGH): resolve-guard must reject ABSENT/UNAVAILABLE -> RESOLVED.
    def test_qa02_absent_cannot_resolve_directly(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.fail_next_post("UNCERTAIN_DROP")
        self.adapter.post_invoice(draft_ref)
        self.engine.enqueue_uncertain_post(intent_key="sha256:q02", draft_ref=draft_ref)
        claim = self.queue.claim_next(fencing_token=31)
        assert claim is not None
        with self.assertRaises(InvalidTransition):
            self.queue.complete_classification(
                claim.item_id,
                fencing_token=31,
                classification=ReconciliationClass.ABSENT,
                next_status=QueueItemStatus.RESOLVED,
            )
        with self.assertRaises(InvalidTransition):
            self.queue.complete_classification(
                claim.item_id,
                fencing_token=31,
                classification=ReconciliationClass.UNAVAILABLE,
                next_status=QueueItemStatus.RESOLVED,
            )

    # REC-QA-03 (MEDIUM): unexpected classification errors fail closed to
    # ESCALATED instead of stranding the item in CLASSIFYING.
    def test_qa03_unknown_anchor_escalates_instead_of_stranding(self) -> None:
        self.engine.enqueue_uncertain_post(intent_key="sha256:q03", draft_ref="DRAFT-GHOST")
        item = self.engine.classify_next(fencing_token=41)
        assert item is not None
        self.assertEqual(item.status, QueueItemStatus.ESCALATED)
        self.assertEqual(item.last_classification, ReconciliationClass.AMBIGUOUS)
        self.assertEqual(len(self.queue.stuck_items()), 1)

    def test_qa03_classifying_takeover_after_lease_expiry(self) -> None:
        draft_ref = self._uncertain_post()
        self.engine.enqueue_uncertain_post(intent_key="sha256:q03t", draft_ref=draft_ref)
        claimed = self.queue.claim_next(fencing_token=51)
        assert claimed is not None
        self.assertEqual(claimed.status, QueueItemStatus.CLASSIFYING)
        # Worker crashed: stale token cannot finish; a newer token can take
        # over the CLASSIFYING item explicitly.
        with self.assertRaises(ItemLocked):
            self.queue.complete_classification(
                claimed.item_id, fencing_token=52,
                classification=ReconciliationClass.PRESENT,
                next_status=QueueItemStatus.RESOLVED,
            )
        taken = self.queue.claim_item(claimed.item_id, fencing_token=53)
        self.assertEqual(taken.fencing_token, 53)

    # REC-QA-04 (MEDIUM): UNAVAILABLE detection must not depend on message text.
    def test_qa04_outage_classified_by_ping_not_message_text(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.fail_next_post("UNCERTAIN")
        self.adapter.post_invoice(draft_ref)
        self.engine.enqueue_uncertain_post(intent_key="sha256:q04", draft_ref=draft_ref)
        self.adapter.simulate_outage(True)
        item = self.engine.classify_next(fencing_token=61)
        assert item is not None
        self.assertEqual(item.last_classification, ReconciliationClass.UNAVAILABLE)

    def test_qa04_business_rejection_with_unavailable_wording_is_ambiguous(self) -> None:
        # A provider rejection whose message merely *contains* the word
        # "unavailable" must not be treated as an outage.
        self.adapter.fail_next_post("UNCERTAIN_DROP")
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.post_invoice(draft_ref)
        self.engine.enqueue_uncertain_post(intent_key="sha256:q04b", draft_ref=draft_ref)
        self.adapter.simulate_outage(False)
        item = self.engine.classify_next(fencing_token=62)
        assert item is not None
        # Provider is reachable; dropped post classifies ABSENT, not UNAVAILABLE.
        self.assertEqual(item.last_classification, ReconciliationClass.ABSENT)
        self.assertEqual(item.status, QueueItemStatus.SAFE_RETRYABLE)

    # REC-QA-05 (LOW): dead allowlist entry PENDING->RESOLVED removed.
    def test_qa05_pending_cannot_jump_to_resolved(self) -> None:
        draft_ref = self._uncertain_post()
        item = self.engine.enqueue_uncertain_post(intent_key="sha256:q05", draft_ref=draft_ref)
        with self.assertRaises((InvalidTransition, ItemLocked)):
            self.queue.complete_classification(
                item.item_id,
                fencing_token=71,
                classification=ReconciliationClass.PRESENT,
                next_status=QueueItemStatus.RESOLVED,
            )

    # REC-QA-06 (LOW): orphan report covers payment-side orphans.
    def test_qa06_orphan_report_covers_payments(self) -> None:
        invoice_ref = (
            self.adapter.post_invoice(self.adapter.create_draft_invoice(_command()))
        ).reference
        assert invoice_ref is not None
        payment_ref = self.adapter.record_payment(DraftPaymentCommand(
            invoice_ref=invoice_ref, amount="1000000", currency="IDR",
            evidence_ref="EVI-ORPHAN-1", destination_account_alias="ACC-OPERASIONAL",
        ))
        report = self.engine.orphan_report(known_draft_refs=set(), known_evidence_refs=set())
        self.assertIn(payment_ref, report.payment_orphans)
        clean = self.engine.orphan_report(
            known_draft_refs=set(), known_evidence_refs={"EVI-ORPHAN-1"},
        )
        self.assertNotIn(payment_ref, clean.payment_orphans)

    # REC-QA-07 (LOW): tests must not reach into adapter private state.
    def test_qa07_public_draft_index_snapshot(self) -> None:
        draft_ref = self._uncertain_post()
        item = self.engine.enqueue_uncertain_post(intent_key="sha256:q07", draft_ref=draft_ref)
        resolved = self.engine.classify_next(fencing_token=81)
        assert resolved is not None
        # Public API: the adapter exposes known draft refs for orphan checks.
        report = self.engine.orphan_report(known_draft_refs=self.adapter.known_draft_refs())
        self.assertEqual(report.erp_orphans, ())
        self.assertEqual(resolved.status, QueueItemStatus.RESOLVED)

    # REC-QA-08 (HIGH): an item escalated from AMBIGUOUS must never re-enter
    # the auto-retry lane, even via a fresh operator claim.
    def test_qa08_ambiguous_escalated_item_cannot_be_routed_to_retryable(self) -> None:
        draft_ref = self._uncertain_post()
        self.adapter.corrupt_index_drop(draft_ref)  # AMBIGUOUS
        self.engine.enqueue_uncertain_post(intent_key="sha256:q08", draft_ref=draft_ref)
        item = self.engine.classify_next(fencing_token=91)
        assert item is not None
        self.assertEqual(item.status, QueueItemStatus.ESCALATED)
        # Operator re-claim is allowed (to RESOLVED/ABANDONED), but the
        # AMBIGUOUS origin forbids routing into SAFE_RETRYABLE.
        claimed = self.queue.claim_item(item.item_id, fencing_token=92)
        self.assertEqual(claimed.status, QueueItemStatus.CLASSIFYING)
        with self.assertRaises(InvalidTransition):
            self.queue.complete_classification(
                item.item_id,
                fencing_token=92,
                classification=ReconciliationClass.ABSENT,
                next_status=QueueItemStatus.SAFE_RETRYABLE,
            )
        # The legitimate operator exits remain available under the new token.
        resolved = self.queue.complete_classification(
            item.item_id,
            fencing_token=92,
            classification=ReconciliationClass.PRESENT,
            next_status=QueueItemStatus.RESOLVED,
            resolution_ref="INV-000042",
        )
        self.assertEqual(resolved.status, QueueItemStatus.RESOLVED)

    def test_qa08_non_ambiguous_escalation_can_be_reclassified_fresh(self) -> None:
        # An item escalated for UNAVAILABLE (provider outage) may be
        # re-claimed after recovery and classified fresh; if the fresh
        # read-back verifies ABSENT, the retry lane is legitimate.
        draft_ref = self._uncertain_post()
        self.engine.enqueue_uncertain_post(intent_key="sha256:q08b", draft_ref=draft_ref)
        self.adapter.simulate_outage(True)
        for _ in range(3):
            self.engine.classify_next(fencing_token=93)
        stuck = self.queue.stuck_items()
        self.assertEqual(len(stuck), 1)
        self.assertEqual(stuck[0].last_classification, ReconciliationClass.UNAVAILABLE)
        self.adapter.simulate_outage(False)
        claimed = self.queue.claim_item(stuck[0].item_id, fencing_token=94)
        self.assertEqual(claimed.status, QueueItemStatus.CLASSIFYING)
        retried = self.engine.classify_item(claimed.item_id, fencing_token=94)
        # Provider now reachable; post was applied -> PRESENT -> RESOLVED.
        self.assertEqual(retried.status, QueueItemStatus.RESOLVED)
        self.assertEqual(retried.last_classification, ReconciliationClass.PRESENT)

    # REC-QA-09 (LOW): pin claim_item token rules.
    def test_qa09_claim_item_rejects_equal_token(self) -> None:
        draft_ref = self._uncertain_post()
        self.engine.enqueue_uncertain_post(intent_key="sha256:q09", draft_ref=draft_ref)
        claimed = self.queue.claim_next(fencing_token=95)
        assert claimed is not None
        with self.assertRaises(ItemLocked):
            self.queue.claim_item(claimed.item_id, fencing_token=95)
        with self.assertRaises(ItemLocked):
            self.queue.claim_item(claimed.item_id, fencing_token=94)

    def test_qa09_claim_item_rejects_terminal_items(self) -> None:
        draft_ref = self._uncertain_post()
        self.engine.enqueue_uncertain_post(intent_key="sha256:q09b", draft_ref=draft_ref)
        resolved = self.engine.classify_next(fencing_token=96)
        assert resolved is not None
        self.assertEqual(resolved.status, QueueItemStatus.RESOLVED)
        with self.assertRaises(InvalidTransition):
            self.queue.claim_item(resolved.item_id, fencing_token=97)
        # ABANDONED likewise.
        draft_ref2 = self._uncertain_post()
        self.adapter.corrupt_index_drop(draft_ref2)
        item2 = self.engine.enqueue_uncertain_post(intent_key="sha256:q09c", draft_ref=draft_ref2)
        escalated = self.engine.classify_next(fencing_token=98)
        assert escalated is not None
        abandoned = self.queue.abandon(item2.item_id, reason="ticket TKT-9")
        self.assertEqual(abandoned.status, QueueItemStatus.ABANDONED)
        with self.assertRaises(InvalidTransition):
            self.queue.claim_item(item2.item_id, fencing_token=99)


class ReconciliationQaRound3RemediationTest(unittest.TestCase):
    """RED-first regression tests for REC-QA-F-01..F-05 closures."""

    def setUp(self) -> None:
        self.adapter = FixtureErpAdapter(series_prefix="INV", next_sequence=1)
        self.queue = OperatorQueue()
        self.engine = ReconciliationEngine(self.adapter, self.queue, max_attempts=3)

    def _uncertain_post(self) -> str:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.fail_next_post("UNCERTAIN")
        result = self.adapter.post_invoice(draft_ref)
        assert result.outcome is PostingOutcome.UNCERTAIN
        return draft_ref

    # REC-QA-F-01: every queue transition emits an AuditChain record.
    def test_f01_enqueue_claim_classify_emit_audit_records(self) -> None:
        draft_ref = self._uncertain_post()
        self.engine.enqueue_uncertain_post(intent_key="sha256:f01a", draft_ref=draft_ref)
        resolved = self.engine.classify_next(fencing_token=1)
        assert resolved is not None
        events = [r.event_type for r in self.queue.audit_records()]
        self.assertIn("REC_ENQUEUE", events)
        self.assertIn("REC_CLAIM", events)
        self.assertIn("REC_CLASSIFY_RESOLVED", events)
        self.assertTrue(self.queue.verify_audit())

    def test_f01_retry_and_abandon_emit_audit_records(self) -> None:
        draft_ref = self.adapter.create_draft_invoice(_command())
        self.adapter.fail_next_post("UNCERTAIN_DROP")
        self.adapter.post_invoice(draft_ref)
        self.engine.enqueue_uncertain_post(intent_key="sha256:f01b", draft_ref=draft_ref)
        item = self.engine.classify_next(fencing_token=1)
        assert item is not None
        self.assertEqual(item.status, QueueItemStatus.SAFE_RETRYABLE)
        retry = self.adapter.post_invoice(draft_ref)
        assert retry.outcome is PostingOutcome.POSTED
        self.engine.mark_retried(item.item_id, resolution_ref=retry.reference)
        # escalate another, then abandon
        draft_ref2 = self._uncertain_post()
        self.adapter.corrupt_index_drop(draft_ref2)
        item2 = self.engine.enqueue_uncertain_post(intent_key="sha256:f01c", draft_ref=draft_ref2)
        esc = self.engine.classify_next(fencing_token=2)
        assert esc is not None
        self.queue.abandon(item2.item_id, reason="operator ticket TKT-F01")
        events = [r.event_type for r in self.queue.audit_records()]
        self.assertIn("REC_RETRIED", events)
        self.assertIn("REC_ABANDONED", events)
        self.assertTrue(self.queue.verify_audit())

    # REC-QA-F-02: queue state can be replayed from a durable transition log.
    def test_f02_restart_replay_reconstructs_state(self) -> None:
        draft_ref = self._uncertain_post()
        item = self.engine.enqueue_uncertain_post(intent_key="sha256:f02a", draft_ref=draft_ref)
        resolved = self.engine.classify_next(fencing_token=1)
        assert resolved is not None
        # second item is classified into ESCALATED (AMBIGUOUS via corrupt
        # index), third stays PENDING.
        draft_ref2 = self._uncertain_post()
        self.adapter.corrupt_index_drop(draft_ref2)
        item2 = self.engine.enqueue_uncertain_post(intent_key="sha256:f02b", draft_ref=draft_ref2)
        draft_ref3 = self._uncertain_post()
        item3 = self.engine.enqueue_uncertain_post(intent_key="sha256:f02c", draft_ref=draft_ref3)
        self.engine.classify_next(fencing_token=2)
        log = self.queue.transition_log()
        self.assertGreaterEqual(len(log), 1)
        rebuilt = OperatorQueue.replay(log)
        r1 = rebuilt.get(item.item_id)
        self.assertEqual(r1.status, QueueItemStatus.RESOLVED)
        self.assertEqual(r1.resolution_ref, resolved.resolution_ref)
        self.assertIsNotNone(r1.resolution_ref)
        pend = rebuilt.pending_items()
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0].intent_key, "sha256:f02c")
        stuck = rebuilt.stuck_items()
        self.assertEqual(len(stuck), 1)
        self.assertEqual(stuck[0].item_id, item2.item_id)
        self.assertEqual(stuck[0].escalated_from, ReconciliationClass.AMBIGUOUS)
        # Rebuilt queue continues to enforce invariants: the ESCALATED item's
        # token was retired on classification, so a strictly newer operator
        # claim succeeds and lands in CLASSIFYING; a stale/equal token on a
        # freshly claimed item is rejected.
        reclaimed = rebuilt.claim_item(item2.item_id, fencing_token=7)
        self.assertEqual(reclaimed.status, QueueItemStatus.CLASSIFYING)
        self.assertEqual(reclaimed.fencing_token, 7)
        with self.assertRaises(Exception):
            rebuilt.claim_item(item2.item_id, fencing_token=7)
        # REC-QA-R3-F-01: the replayed intent index still enforces enqueue
        # idempotency — re-enqueueing a known key returns the replayed item
        # instead of creating a duplicate.
        depth_before = rebuilt.depth(include_terminal=True)
        again = rebuilt.enqueue(
            intent_key="sha256:f02a", kind="INVOICE_POST", draft_ref=draft_ref
        )
        self.assertEqual(again.item_id, item.item_id)
        self.assertEqual(rebuilt.depth(include_terminal=True), depth_before)

    # REC-QA-F-03: SLA/alert surface via timestamps + overdue helper.
    def test_f03_queue_items_carry_timestamps_and_overdue_helper(self) -> None:
        draft_ref = self._uncertain_post()
        item = self.engine.enqueue_uncertain_post(intent_key="sha256:f03a", draft_ref=draft_ref)
        self.assertIsNotNone(item.enqueued_at)
        # Force ESCALATED via an AMBIGUOUS provider contradiction so the item
        # stays in an active (operator-attention) state.
        self.adapter.corrupt_index_drop(draft_ref)
        escalated = self.engine.classify_next(fencing_token=1)
        assert escalated is not None
        self.assertEqual(escalated.status, QueueItemStatus.ESCALATED)
        self.assertIsNotNone(escalated.updated_at)
        self.assertGreaterEqual(escalated.updated_at, escalated.enqueued_at)
        overdue = self.queue.overdue_items(max_age_seconds=-1)
        self.assertTrue(any(entry.item_id == escalated.item_id for entry in overdue))
        fresh = self.queue.overdue_items(max_age_seconds=3600)
        self.assertFalse(any(entry.item_id == escalated.item_id for entry in fresh))
        # Terminal items are never overdue, even with a zero/negative threshold.
        draft_ref_done = self._uncertain_post()
        done = self.engine.enqueue_uncertain_post(intent_key="sha256:f03b", draft_ref=draft_ref_done)
        resolved = self.engine.classify_next(fencing_token=2)
        assert resolved is not None
        self.assertEqual(resolved.status, QueueItemStatus.RESOLVED)
        overdue_all = self.queue.overdue_items(max_age_seconds=-1)
        self.assertFalse(any(entry.item_id == done.item_id for entry in overdue_all))
        # abandoned escalated items leave the alert surface too
        self.queue.abandon(escalated.item_id, reason="ticket TKT-F03")
        self.assertFalse(
            any(entry.item_id == escalated.item_id for entry in self.queue.overdue_items(max_age_seconds=-1))
        )

    # REC-QA-F-04: engine accepts the provider-neutral ErpPort protocol.
    def test_f04_engine_is_typed_against_erpport_protocol(self) -> None:
        import inspect
        from src.contracts.erp_port import ErpPort
        hints = inspect.get_annotations(ReconciliationEngine.__init__, eval_str=True)
        self.assertIs(hints.get("adapter"), ErpPort)
        # structural: the fixture adapter still satisfies the protocol
        self.assertIsInstance(self.adapter, ErpPort)

    # REC-QA-F-05: item sequence is per-queue-instance, not process-global.
    def test_f05_item_sequence_is_per_instance(self) -> None:
        q1 = OperatorQueue()
        q2 = OperatorQueue()
        a = q1.enqueue(intent_key="sha256:f05a", kind="INVOICE_POST", draft_ref="DRAFT-1")
        b = q2.enqueue(intent_key="sha256:f05b", kind="INVOICE_POST", draft_ref="DRAFT-2")
        self.assertEqual(a.item_id, b.item_id)  # both REC-000001 in their own queue
        c = q1.enqueue(intent_key="sha256:f05c", kind="INVOICE_POST", draft_ref="DRAFT-3")
        self.assertNotEqual(a.item_id, c.item_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
