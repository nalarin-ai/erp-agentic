"""Deterministic, network-disabled fixture ERP adapter (ADP-001).

Implements ``src.contracts.erp_port.ErpPort`` against in-memory state so the
provider contract suite runs fully offline with synthetic opaque refs only.

Contract guarantees implemented here:
- Drafts reserve nothing; official numbers (``<SERIES>-NNNNNN``) are issued
  only at verified post time from a per-series monotonic counter.
- Posting is idempotent per draft; an UNCERTAIN post cannot be blindly
  retried — it must be classified via ``reconcile_post`` first.
- Payments require evidence refs, are validated against status/currency/
  open amount, and duplicate evidence refs are rejected. A payment whose
  outcome is injected as UNCERTAIN reserves its evidence ref so a blind
  retry cannot double-apply; ``reconcile_payment`` classifies it.
- Reversals are compensating records; the original payment is never
  mutated or deleted; reversing a reversal or double-reversing is denied.
- Cancelling a DRAFT is direct; cancelling a POSTED (unpaid) invoice is a
  compensating path that closes the receivable while keeping the official
  reference for audit; cancelling a PAID invoice is rejected (payments
  must be reversed first).
- Queries always intersect the requested filter with stored scope and
  report ``scoped=True``.
- Delivery outbox is orthogonal to posting: a failed delivery never
  invalidates a POSTED document and retries reuse one logical entry per
  (document, channel).
- The fixture opens no sockets; the contract suite enforces this by
  patching ``socket.socket`` during a live exercise.

Failure injection (test-only): ``fail_next_post``, ``fail_next_payment``,
``fail_next_delivery``, ``simulate_outage``. These never leak into
production paths because this module is only imported by tests and by the
fixture wiring selected explicitly in configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import itertools
import re
import threading

from src.contracts.erp_port import (
    DocumentRejected,
    DraftInvoiceCommand,
    DraftPaymentCommand,
    InvoiceRecord,
    PaymentRecord,
    PostingOutcome,
    PostingResult,
    QueryResult,
    ReversalCommand,
    UncertainOutcome,
)

_DECIMAL_TEXT = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_money(amount: str) -> Decimal:
    if not isinstance(amount, str) or _DECIMAL_TEXT.fullmatch(amount) is None:
        raise DocumentRejected("amount is not a canonical decimal string")
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise DocumentRejected("amount is not a valid decimal string") from exc
    if not value.is_finite():
        raise DocumentRejected("amount must be finite")
    return value


def _parse_currency(currency: str) -> str:
    """Validate an ISO-4217 uppercase currency code (fail closed)."""
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or not currency.isupper()
    ):
        raise DocumentRejected("currency must be a three-letter uppercase ISO-4217 code")
    return currency


def _parse_date(value: str, field: str) -> date:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        raise DocumentRejected(f"{field} must be ISO-8601 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DocumentRejected(f"{field} is not a valid calendar date") from exc


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    reference: str
    document_ref: str
    channel_ref: str
    status: str  # QUEUED | SENT | FAILED_RETRYABLE


@dataclass(slots=True)
class _InvoiceState:
    draft_ref: str
    official_ref: str | None
    status: str  # DRAFT | POSTED | CANCELLED
    total: Decimal
    open_amount: Decimal
    currency: str
    issued_on: str
    due_on: str
    payload: dict
    post_uncertain: bool = False  # True while outcome UNCERTAIN
    paid: bool = False


@dataclass(slots=True)
class _PaymentState:
    reference: str
    invoice_ref: str
    amount: Decimal
    currency: str
    evidence_ref: str
    destination_account_alias: str
    reversal_of: str | None
    reversed: bool = False
    uncertain: bool = False


class FixtureErpAdapter:
    """In-memory deterministic ``ErpPort`` implementation (test fixture)."""

    def __init__(self, *, series_prefix: str = "INV", next_sequence: int = 1) -> None:
        if not isinstance(series_prefix, str) or not re.fullmatch(r"[A-Z][A-Z0-9]*", series_prefix):
            raise ValueError("series_prefix must be an uppercase opaque token")
        if not isinstance(next_sequence, int) or isinstance(next_sequence, bool) or next_sequence <= 0:
            raise ValueError("next_sequence must be a positive int")
        self._series_prefix = series_prefix
        self._sequence = itertools.count(next_sequence)
        self._draft_sequence = itertools.count(1)
        self._payment_sequence = itertools.count(1)
        self._delivery_sequence = itertools.count(1)
        self._invoices: dict[str, _InvoiceState] = {}
        self._payments: dict[str, _PaymentState] = {}
        self._evidence_refs: set[str] = set()
        self._deliveries: dict[tuple[str, str], DeliveryRecord] = {}
        self._lock = threading.RLock()
        # Failure injection (test-only knobs)
        self._fail_next_post: str | None = None
        self._fail_next_payment: str | None = None
        self._fail_next_delivery = False
        self._outage = False

    # -- failure injection (test-only) --------------------------------------

    def fail_next_post(self, mode: str) -> None:
        """Inject a post failure: REJECTED (no mutation), UNCERTAIN (applied
        but unknown), or UNCERTAIN_DROP (never applied)."""
        if mode not in {"REJECTED", "UNCERTAIN", "UNCERTAIN_DROP"}:
            raise ValueError("unknown failure mode")
        self._fail_next_post = mode

    def fail_next_payment(self, mode: str) -> None:
        if mode not in {"REJECTED", "UNCERTAIN"}:
            raise ValueError("unknown failure mode")
        self._fail_next_payment = mode

    def fail_next_delivery(self) -> None:
        self._fail_next_delivery = True

    def simulate_outage(self, unavailable: bool) -> None:
        self._outage = bool(unavailable)

    def _assert_available(self) -> None:
        if self._outage:
            raise DocumentRejected("provider unavailable")

    # -- drafts / posting -----------------------------------------------------

    def create_draft_invoice(self, command: DraftInvoiceCommand) -> str:
        with self._lock:
            self._assert_available()
            if not command.lines:
                raise DocumentRejected("invoice must contain at least one line")
            issued = _parse_date(command.issued_on, "issued_on")
            due = _parse_date(command.due_on, "due_on")
            if due < issued:
                raise DocumentRejected("due_on cannot precede issued_on")
            currency = _parse_currency(command.lines[0].currency)
            total = Decimal(0)
            normalized_lines = []
            for line in command.lines:
                quantity = _parse_money(line.quantity)
                price = _parse_money(line.unit_price_amount)
                if quantity <= 0:
                    raise DocumentRejected("line quantity must be positive")
                if price <= 0:
                    raise DocumentRejected("line unit price must be positive")
                if _parse_currency(line.currency) != currency:
                    raise DocumentRejected("mixed currencies in one invoice are not supported")
                total += quantity * price
                normalized_lines.append({
                    "service_ref": line.service_ref,
                    "description": line.description,
                    "quantity": format(quantity, "f"),
                    "unit_price_amount": format(price, "f"),
                })
            identity = command.identity.to_canonical_payload()
            draft_ref = f"DRAFT-{next(self._draft_sequence):06d}"
            self._invoices[draft_ref] = _InvoiceState(
                draft_ref=draft_ref,
                official_ref=None,
                status="DRAFT",
                total=total,
                open_amount=total,
                currency=currency,
                issued_on=command.issued_on,
                due_on=command.due_on,
                payload={
                    "customer_ref": command.customer_ref,
                    "identity": identity,
                    "lines": normalized_lines,
                },
            )
            return draft_ref

    def _lookup_invoice(self, reference: str) -> _InvoiceState:
        state = self._invoices.get(reference)
        if state is None:
            raise DocumentRejected(f"unknown invoice reference: {reference[:24]}")
        return state

    def read_invoice(self, reference: str) -> InvoiceRecord:
        with self._lock:
            self._assert_available()  # reads are non-authoritative during outage
            state = self._lookup_invoice(reference)
            return self._to_record(state)

    @staticmethod
    def _to_record(state: _InvoiceState) -> InvoiceRecord:
        return InvoiceRecord(
            reference=state.official_ref or state.draft_ref,
            status=state.status,
            total_amount=format(state.total, "f"),
            currency=state.currency,
            open_amount=format(state.open_amount, "f"),
            issued_on=state.issued_on,
            due_on=state.due_on,
            payload=dict(state.payload),
        )

    def post_invoice(self, reference: str) -> PostingResult:
        with self._lock:
            self._assert_available()
            state = self._invoices.get(reference)
            if state is None:
                # Posting always addresses the draft handle.
                for candidate in self._invoices.values():
                    if candidate.official_ref == reference:
                        state = candidate
                        break
            if state is None:
                raise DocumentRejected(f"unknown invoice reference: {reference[:24]}")
            if state.post_uncertain:
                # Blind retry while uncertain is forbidden.
                raise UncertainOutcome("post outcome uncertain; reconcile before retry")
            if state.status == "POSTED":
                # Idempotent no-op: return the already-assigned reference.
                return PostingResult(PostingOutcome.POSTED, state.official_ref, None)
            if state.status == "CANCELLED":
                raise DocumentRejected("cannot post a cancelled draft")

            failure = self._fail_next_post
            self._fail_next_post = None
            if failure == "REJECTED":
                return PostingResult(PostingOutcome.REJECTED, None, "provider rejected post")
            if failure == "UNCERTAIN":
                # The provider applied the mutation but the outcome is unknown.
                # The caller must NOT learn the official reference before
                # reconciliation verifies it (ADP-QA-03).
                self._assign_official(state)
                state.post_uncertain = True
                return PostingResult(PostingOutcome.UNCERTAIN, None, "outcome unknown")
            if failure == "UNCERTAIN_DROP":
                state.post_uncertain = True
                return PostingResult(PostingOutcome.UNCERTAIN, None, "outcome unknown")

            official = self._assign_official(state)
            return PostingResult(PostingOutcome.POSTED, official, None)

    def _assign_official(self, state: _InvoiceState) -> str:
        official = f"{self._series_prefix}-{next(self._sequence):06d}"
        state.official_ref = official
        state.status = "POSTED"
        # The official handle replaces the draft handle for subsequent reads.
        self._invoices[official] = state
        return official

    def reconcile_post(self, draft_reference: str) -> PostingResult:
        """Classify an UNCERTAIN post via read-back. Never a blind reissue."""
        with self._lock:
            state = self._invoices.get(draft_reference)
            if state is None:
                raise DocumentRejected(f"unknown invoice reference: {draft_reference[:24]}")
            if not state.post_uncertain:
                if state.status == "POSTED":
                    return PostingResult(PostingOutcome.POSTED, state.official_ref, None)
                return PostingResult(PostingOutcome.REJECTED, None, "not pending reconciliation")
            state.post_uncertain = False
            if state.status == "POSTED" and state.official_ref is not None:
                return PostingResult(PostingOutcome.POSTED, state.official_ref, None)
            return PostingResult(PostingOutcome.REJECTED, None, "provider has no such document")

    # -- payments -------------------------------------------------------------

    def record_payment(self, command: DraftPaymentCommand) -> str:
        with self._lock:
            self._assert_available()
            if not command.evidence_ref or not command.evidence_ref.strip():
                raise DocumentRejected("payment requires an evidence reference")
            _parse_currency(command.currency)
            # ADP-QA-09: the reversal namespace (EVI-REV-*) is reserved by the
            # provider; callers may not claim it for ordinary payments.
            if command.evidence_ref.startswith("EVI-REV-"):
                raise DocumentRejected("evidence reference uses the reserved reversal namespace")
            if command.evidence_ref in self._evidence_refs:
                raise DocumentRejected("evidence reference already recorded")
            state = self._invoices.get(command.invoice_ref)
            if state is None or state.status != "POSTED":
                raise DocumentRejected("payments require a POSTED invoice")
            amount = _parse_money(command.amount)
            if amount <= 0:
                raise DocumentRejected("payment amount must be positive")
            if command.currency != state.currency:
                raise DocumentRejected("payment currency mismatch")
            if amount > state.open_amount:
                raise DocumentRejected("payment exceeds open amount")

            failure = self._fail_next_payment
            self._fail_next_payment = None
            if failure == "REJECTED":
                raise DocumentRejected("provider rejected payment")
            if failure == "UNCERTAIN":
                # Apply the mutation, reserve the evidence ref, and report
                # uncertainty so reconciliation (not blind retry) classifies.
                # The internal payment ref is NOT leaked (ADP-QA-10); the
                # caller reconciles via the evidence ref it already holds.
                payment_ref = self._apply_payment(state, command, amount, reversal_of=None)
                payment = self._payments[payment_ref]
                payment.uncertain = True
                raise UncertainOutcome("payment outcome unknown; reconcile via evidence reference")
            return self._apply_payment(state, command, amount, reversal_of=None)

    def _apply_payment(
        self,
        state: _InvoiceState,
        command: DraftPaymentCommand,
        amount: Decimal,
        *,
        reversal_of: str | None,
    ) -> str:
        payment_ref = f"PAY-{next(self._payment_sequence):06d}"
        self._payments[payment_ref] = _PaymentState(
            reference=payment_ref,
            invoice_ref=state.official_ref or state.draft_ref,
            amount=amount,
            currency=command.currency,
            evidence_ref=command.evidence_ref,
            destination_account_alias=command.destination_account_alias,
            reversal_of=reversal_of,
        )
        self._evidence_refs.add(command.evidence_ref)
        state.open_amount -= amount
        if state.open_amount == 0:
            state.paid = True
        return payment_ref

    def read_payment(self, reference: str) -> PaymentRecord:
        with self._lock:
            self._assert_available()  # reads are non-authoritative during outage
            payment = self._payments.get(reference)
            if payment is None:
                raise DocumentRejected(f"unknown payment reference: {reference[:24]}")
            return self._to_payment_record(payment)

    @staticmethod
    def _to_payment_record(payment: _PaymentState) -> PaymentRecord:
        return PaymentRecord(
            reference=payment.reference,
            invoice_ref=payment.invoice_ref,
            amount=format(payment.amount, "f"),
            currency=payment.currency,
            evidence_ref=payment.evidence_ref,
            destination_account_alias=payment.destination_account_alias,
            reversal_of=payment.reversal_of,
        )

    def reconcile_payment(self, evidence_ref: str) -> PaymentRecord:
        """Classify an uncertain payment by its reserved evidence reference.

        Fails closed on unknown evidence (ADP-QA-06): callers must not handle
        both ``None`` and exceptions; an unknown ref is a contract violation.
        """
        with self._lock:
            if evidence_ref not in self._evidence_refs:
                raise DocumentRejected(f"unknown evidence reference: {evidence_ref[:24]}")
            for payment in self._payments.values():
                if payment.evidence_ref == evidence_ref:
                    payment.uncertain = False
                    return self._to_payment_record(payment)
            raise DocumentRejected(f"unknown evidence reference: {evidence_ref[:24]}")

    # -- reversal -------------------------------------------------------------

    def reverse_payment(self, command: ReversalCommand) -> str:
        with self._lock:
            self._assert_available()
            if not command.reason or not command.reason.strip():
                raise DocumentRejected("reversal requires a reason")
            payment = self._payments.get(command.payment_ref)
            if payment is None:
                raise DocumentRejected(f"unknown payment reference: {command.payment_ref[:24]}")
            if payment.reversal_of is not None:
                raise DocumentRejected("cannot reverse a reversal record")
            if payment.reversed:
                raise DocumentRejected("payment is already reversed")
            state = self._invoices.get(payment.invoice_ref)
            if state is None:
                raise DocumentRejected("payment references a missing invoice")
            if state.status == "CANCELLED":
                raise DocumentRejected("cannot reverse a payment on a cancelled invoice")
            reversal_ref = f"PAY-{next(self._payment_sequence):06d}"
            reversal_evidence_ref = f"EVI-REV-{payment.reference}"
            self._payments[reversal_ref] = _PaymentState(
                reference=reversal_ref,
                invoice_ref=payment.invoice_ref,
                amount=-payment.amount,
                currency=payment.currency,
                evidence_ref=reversal_evidence_ref,
                destination_account_alias=payment.destination_account_alias,
                reversal_of=payment.reference,
            )
            # ADP-QA-09: reserve the reversal evidence ref so no later payment
            # can collide with it and reconciliation stays unambiguous.
            self._evidence_refs.add(reversal_evidence_ref)
            payment.reversed = True
            state.open_amount += payment.amount
            state.paid = False
            return reversal_ref

    # -- cancellation -----------------------------------------------------------

    def cancel_invoice(self, reference: str) -> None:
        with self._lock:
            self._assert_available()
            state = self._lookup_invoice(reference)
            if state.status == "CANCELLED":
                return
            if state.status == "DRAFT":
                state.status = "CANCELLED"
                state.open_amount = Decimal(0)
                return
            # POSTED: compensating path — only when no unreversed payments
            # remain (a paid invoice must be reversed first, never erased).
            outstanding = [
                payment for payment in self._payments.values()
                if payment.invoice_ref == state.official_ref
                and payment.reversal_of is None
                and not payment.reversed
            ]
            if outstanding:
                raise DocumentRejected("cannot cancel a paid invoice; reverse payments first")
            state.status = "CANCELLED"
            state.open_amount = Decimal(0)

    # -- queries ----------------------------------------------------------------

    def query_invoices(
        self,
        *,
        status: str | None = None,
        operating_unit_ref: str | None = None,
        customer_ref: str | None = None,
    ) -> QueryResult:
        with self._lock:
            self._assert_available()
            references: list[str] = []
            seen: set[str] = set()
            for state in self._invoices.values():
                ref = state.official_ref or state.draft_ref
                if ref in seen:
                    continue
                if status is not None and state.status != status:
                    continue
                if operating_unit_ref is not None and (
                    state.payload["identity"]["operating_unit_ref"] != operating_unit_ref
                ):
                    continue
                if customer_ref is not None and state.payload["customer_ref"] != customer_ref:
                    continue
                seen.add(ref)
                references.append(ref)
            references.sort()
            # ADP-QA-05: the fixture has no caller authz context. A query that
            # provides no explicit scope filter must not claim that
            # server-side scope intersection was applied.
            scope_applied = operating_unit_ref is not None
            return QueryResult(
                kind="INVOICE",
                references=tuple(references),
                scoped=scope_applied,
                total=len(references),
            )

    # -- delivery outbox (orthogonal to posting) --------------------------------

    def enqueue_delivery(self, document_ref: str, *, channel_ref: str) -> DeliveryRecord:
        with self._lock:
            self._assert_available()
            state = self._lookup_invoice(document_ref)
            if state.status != "POSTED":
                raise DocumentRejected("only POSTED documents can be delivered")
            key = (state.official_ref or state.draft_ref, channel_ref)
            existing = self._deliveries.get(key)
            if existing is not None and existing.status == "SENT":
                return existing
            if existing is not None and existing.status == "FAILED_RETRYABLE":
                # Retry the same logical outbox entry.
                if self._fail_next_delivery:
                    self._fail_next_delivery = False
                    return existing
                delivered = DeliveryRecord(existing.reference, existing.document_ref, channel_ref, "SENT")
                self._deliveries[key] = delivered
                return delivered
            reference = f"OUT-{next(self._delivery_sequence):06d}"
            if self._fail_next_delivery:
                self._fail_next_delivery = False
                record = DeliveryRecord(reference, key[0], channel_ref, "FAILED_RETRYABLE")
            else:
                record = DeliveryRecord(reference, key[0], channel_ref, "SENT")
            self._deliveries[key] = record
            return record

    # -- liveness -----------------------------------------------------------------

    def ping(self) -> bool:
        return not self._outage
