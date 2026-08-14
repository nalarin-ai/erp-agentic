"""Reconciliation engine (REC-001, R-007/R-008).

Classifies pending/uncertain mutation intents against the provider port
with fencing, bounded retry, and escalation. Rules:

- A pending intent is classified via provider read-back only; the engine
  NEVER reissues a mutation before classification.
- PRESENT  -> item RESOLVED with the official provider reference; local
  outcome is reconciled to the provider state.
- ABSENT   -> item SAFE_RETRYABLE; exactly one verified retry may then be
  performed by the caller and closed via ``mark_retried``.
- AMBIGUOUS (provider contradicts itself) -> ESCALATED; operator action
  required; never auto-retried.
- UNAVAILABLE (provider cannot answer) -> bounded requeue up to
  ``max_attempts``, then ESCALATED. No item remains silently stuck.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.contracts.erp_port import DocumentRejected, ErpPort, PostingOutcome
from src.contracts.reconciliation import (
    InvalidTransition,
    QueueItem,
    QueueItemStatus,
    ReconciliationClass,
)
from src.reconciliation.queue import OperatorQueue


@dataclass(frozen=True, slots=True)
class OrphanReport:
    """Cross-check between provider state and the reconciliation queue."""

    erp_orphans: tuple[str, ...]       # posted provider docs with no known draft
    payment_orphans: tuple[str, ...]   # provider payments with no known evidence ref
    unresolved_items: tuple[str, ...]  # queue items still in a terminal-uncertain state


class ReconciliationEngine:
    """Fenced, bounded classifier over an ``ErpPort`` adapter."""

    def __init__(
        self,
        adapter: ErpPort,
        queue: OperatorQueue,
        *,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._adapter = adapter
        self._queue = queue
        self._max_attempts = max_attempts

    # -- enqueue -----------------------------------------------------------------

    def enqueue_uncertain_post(self, *, intent_key: str, draft_ref: str) -> QueueItem:
        return self._queue.enqueue(
            intent_key=intent_key, kind="INVOICE_POST", draft_ref=draft_ref,
        )

    def enqueue_uncertain_payment(self, *, intent_key: str, evidence_ref: str) -> QueueItem:
        return self._queue.enqueue(
            intent_key=intent_key, kind="PAYMENT_RECORD", draft_ref=evidence_ref,
        )

    # -- claiming -------------------------------------------------------------------

    def claim_next(self, *, fencing_token: int) -> QueueItem | None:
        return self._queue.claim_next(fencing_token=fencing_token)

    # -- classification ---------------------------------------------------------------

    def classify_next(self, *, fencing_token: int) -> QueueItem | None:
        """Claim and classify the next pending item atomically."""
        claim = self._queue.claim_next(fencing_token=fencing_token)
        if claim is None:
            return None
        return self.classify_item(claim.item_id, fencing_token=fencing_token)

    def classify_item(self, item_id: str, *, fencing_token: int) -> QueueItem:
        item = self._queue.get(item_id)
        try:
            classification, resolution_ref = self._classify(item)
        except DocumentRejected:
            # REC-QA-03/04: a read-back rejection while the provider answers
            # is a business-level contradiction (unknown anchor, ghost ref,
            # etc.) — fail closed to ESCALATED, never strand in CLASSIFYING.
            if self._adapter.ping():
                return self._queue.complete_classification(
                    item_id,
                    fencing_token=fencing_token,
                    classification=ReconciliationClass.AMBIGUOUS,
                    next_status=QueueItemStatus.ESCALATED,
                    reason="read-back rejected by reachable provider; operator review required",
                )
            classification, resolution_ref = ReconciliationClass.UNAVAILABLE, None
        if classification is ReconciliationClass.PRESENT:
            return self._queue.complete_classification(
                item_id,
                fencing_token=fencing_token,
                classification=classification,
                next_status=QueueItemStatus.RESOLVED,
                resolution_ref=resolution_ref,
            )
        if classification is ReconciliationClass.ABSENT:
            return self._queue.complete_classification(
                item_id,
                fencing_token=fencing_token,
                classification=classification,
                next_status=QueueItemStatus.SAFE_RETRYABLE,
            )
        if classification is ReconciliationClass.AMBIGUOUS:
            return self._queue.complete_classification(
                item_id,
                fencing_token=fencing_token,
                classification=classification,
                next_status=QueueItemStatus.ESCALATED,
                reason="provider state contradicts itself; operator review required",
            )
        # UNAVAILABLE: bounded requeue, then escalate. Never silently stuck.
        next_status = (
            QueueItemStatus.PENDING
            if item.attempts + 1 < self._max_attempts
            else QueueItemStatus.ESCALATED
        )
        return self._queue.complete_classification(
            item_id,
            fencing_token=fencing_token,
            classification=classification,
            next_status=next_status,
            reason=None if next_status is QueueItemStatus.PENDING else
            f"provider unavailable after {self._max_attempts} attempts",
        )

    def _classify(self, item: QueueItem) -> tuple[ReconciliationClass, str | None]:
        """Read-back classification against the provider. Pure decision."""
        if item.kind == "INVOICE_POST":
            return self._classify_post(item.draft_ref)
        if item.kind == "PAYMENT_RECORD":
            return self._classify_payment(item.draft_ref)
        raise InvalidTransition(f"unknown reconciliation kind: {item.kind}")

    def _classify_post(self, draft_ref: str) -> tuple[ReconciliationClass, str | None]:
        result = self._adapter.reconcile_post(draft_ref)
        if result.outcome is PostingOutcome.POSTED and result.reference:
            # Cross-check against the provider query index: a POSTED document
            # missing from the index is contradictory (AMBIGUOUS).
            index = self._adapter.query_invoices(status="POSTED")
            if result.reference not in index.references:
                return ReconciliationClass.AMBIGUOUS, None
            return ReconciliationClass.PRESENT, result.reference
        return ReconciliationClass.ABSENT, None

    def _classify_payment(self, evidence_ref: str) -> tuple[ReconciliationClass, str | None]:
        try:
            record = self._adapter.reconcile_payment(evidence_ref)
        except DocumentRejected:
            return ReconciliationClass.ABSENT, None
        return ReconciliationClass.PRESENT, record.reference

    # -- retry closure -----------------------------------------------------------------

    def mark_retried(self, item_id: str, *, resolution_ref: str | None) -> QueueItem:
        return self._queue.mark_retried(item_id, resolution_ref=resolution_ref)

    # -- orphan cross-checks ---------------------------------------------------------

    def orphan_report(
        self,
        *,
        known_draft_refs: set[str],
        known_evidence_refs: set[str] | None = None,
    ) -> OrphanReport:
        """Report provider-side orphans and unresolved queue items.

        REC-QA-06: payment records are cross-checked too — a provider-side
        payment whose evidence ref is unknown locally is an orphan.
        """
        posted = self._adapter.query_invoices(status="POSTED")
        orphans = []
        for official_ref in posted.references:
            record = self._adapter.read_invoice(official_ref)
            if record.payload.get("draft_ref") not in known_draft_refs:
                orphans.append(official_ref)
        payment_orphans: list[str] = []
        if known_evidence_refs is not None:
            for payment_ref, evidence_ref in self._adapter.payment_evidence_index():
                if evidence_ref not in known_evidence_refs:
                    payment_orphans.append(payment_ref)
        unresolved = tuple(item.item_id for item in self._queue.stuck_items())
        return OrphanReport(
            erp_orphans=tuple(sorted(orphans)),
            payment_orphans=tuple(sorted(payment_orphans)),
            unresolved_items=unresolved,
        )
