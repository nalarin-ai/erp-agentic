"""Payment evidence and receivables workflow (FLOW-003).

R-006/R-007: every payment is bound to a mandatory opaque EVI-* evidence
reference — chat text alone can NEVER confirm a payment. Recording is
idempotent per (actor, idempotency key) with payload-conflict detection, in
a namespace distinct from invoice posting.
R-008/R-017: reversal is a compensating provider record only; the receivable
state is always recomputed from accepted payment/reversal records, never
overwritten directly.
R-013/R-019: the destination account alias must match the invoice unit's
active financial policy; wrong-account attempts are denied before any
provider mutation.
R-017 (concurrency): a shared CAS-style claim under one lock guarantees a
concurrent duplicate race results in exactly one provider mutation.

UNCERTAIN outcomes enqueue reconciliation (REC-001) and block any blind
retry of the same evidence reference until classification completes.
Provider contract exceptions are translated into WorkflowBlocked / UNCERTAIN
outcomes; raw DocumentRejected/UncertainOutcome never escape.

Privacy: no raw chat text, no full account numbers, and no credentials ever
enter state, audit, or error messages — opaque refs and aliases only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import re
import threading
from typing import Any, Iterable

from src.authz.access import (
    AccessDecision,
    ActorUnitAssignment,
    AuthorizationRequest,
    IdentityBinding,
    authorize,
)
from src.contracts.erp_port import (
    DocumentRejected,
    DraftPaymentCommand,
    ProviderContractError,
    ReversalCommand,
    UncertainOutcome,
)
from src.domain.document_state import ReceivableStatus
from src.policy.financial_identity import (
    FinancialPolicyResolver,
    PolicyResolutionError,
    PolicyResolutionRequest,
)
from src.units.registry import UnitRegistry

_REF = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
_DECIMAL_TEXT = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class WorkflowDenied(ValueError):
    """Safe denial; message never discloses protected data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("Request cannot be authorized.")


class WorkflowBlocked(ValueError):
    """Precise, safe blocker (missing data / state conflict)."""


@dataclass(frozen=True, slots=True)
class PaymentResult:
    """Outcome of a fenced payment recording attempt."""

    outcome: str  # RECORDED | REJECTED | UNCERTAIN
    payment_ref: str | None
    receivable_status: str | None  # recomputed OPEN | PARTIALLY_PAID | PAID
    reason: str | None


@dataclass(slots=True)
class _ClaimState:
    """Durable intent claim for one idempotency key."""

    payload_hash: str
    outcome: str  # PENDING | RECORDED | REJECTED | UNCERTAIN
    payment_ref: str | None = None
    invoice_ref: str | None = None  # scope anchor for UNCERTAIN claims


class PaymentWorkflow:
    """One-writer payment/reversal workflow over fixture dependencies.

    Idempotency namespace is distinct from invoice posting: claims are keyed
    on (actor_ref, idempotency_key) with a SHA-256 payload hash so a replayed
    key with a different payload is an IDEMPOTENCY_CONFLICT, never a second
    provider write.
    """

    def __init__(
        self,
        *,
        registry: UnitRegistry,
        resolver: FinancialPolicyResolver,
        adapter: Any,
        reconciliation: Any,  # ReconciliationEngine
    ) -> None:
        self._registry = registry
        self._resolver = resolver
        self._adapter = adapter
        self._reconciliation = reconciliation
        self._claims: dict[tuple[str, str], _ClaimState] = {}
        self._by_evidence_ref: dict[str, str] = {}  # evidence_ref -> payment_ref
        self._pending_uncertain: set[str] = set()  # evidence refs awaiting reconcile
        self._reversed: set[str] = set()  # payment refs already reversed (workflow view)
        self._audit: dict[str, list[dict[str, Any]]] = {}
        self._denied: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    # -- audit ---------------------------------------------------------------

    def _log(self, anchor: str, action: str, actor_ref: str, at: datetime,
             detail: dict[str, Any] | None = None) -> None:
        entry: dict[str, Any] = {
            "action": action,
            "actor_ref": actor_ref,
            "at": at.astimezone(timezone.utc).isoformat(),
        }
        if detail:
            entry.update(detail)
        self._audit.setdefault(anchor, []).append(entry)

    def _log_denied(self, action: str, actor_ref: str, at: datetime, code: str) -> None:
        self._denied.append({
            "action": action,
            "actor_ref": actor_ref,
            "code": code,
            "at": at.astimezone(timezone.utc).isoformat(),
        })

    # -- authorization ---------------------------------------------------------

    def _authorize(
        self,
        *,
        actor_ref: str,
        channel_ref: str,
        action: str,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        selected_unit_ref: str | None,
        at: datetime,
    ) -> AccessDecision:
        try:
            request = AuthorizationRequest(
                actor_ref=actor_ref,
                channel_ref=channel_ref,
                action=action,
                selected_unit_ref=selected_unit_ref,
                requested_at=at,
            )
            decision = authorize(request=request, binding=binding, assignments=assignments)
        except (TypeError, ValueError):
            raise WorkflowDenied("INVALID_INPUT") from None
        if not decision.allowed:
            raise WorkflowDenied(decision.code)
        return decision

    def _selected_assignment(
        self,
        actor_ref: str,
        unit_ref: str,
        assignments: Iterable[ActorUnitAssignment],
        at: datetime,
    ) -> ActorUnitAssignment:
        for assignment in assignments:
            if (
                assignment.actor_ref == actor_ref
                and assignment.unit_ref == unit_ref
                and assignment.active
                and (assignment.effective_from is None or assignment.effective_from <= at)
                and (assignment.effective_until is None or at < assignment.effective_until)
            ):
                return assignment
        raise WorkflowDenied("PERMISSION_DENIED")

    # -- validation helpers ------------------------------------------------------

    @staticmethod
    def _require_ref(value: object, prefix: str, name: str) -> None:
        if type(value) is not str or _REF.fullmatch(value) is None \
                or not value.startswith(prefix):
            raise WorkflowBlocked(f"{name} must be a canonical {prefix.removesuffix('-')} reference")

    @staticmethod
    def _payload_hash(*, invoice_ref: str, amount: str, currency: str,
                      evidence_ref: str, destination_account_alias: str) -> str:
        material = repr((invoice_ref, amount, currency, evidence_ref,
                         destination_account_alias))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _resolve_unit_ref(self, invoice_ref: str) -> tuple[str, Any]:
        """Read the invoice back and derive its operating unit from policy data."""
        try:
            invoice = self._adapter.read_invoice(invoice_ref)
        except (DocumentRejected, ProviderContractError) as exc:
            raise WorkflowBlocked("unknown posted invoice") from exc
        unit_ref = invoice.payload.get("identity", {}).get("operating_unit_ref")
        if type(unit_ref) is not str or _REF.fullmatch(unit_ref) is None:
            raise WorkflowBlocked("invoice has no resolvable operating unit")
        return unit_ref, invoice

    def _validate_account_alias(
        self, *, unit_ref: str, currency: str, alias: str, at: datetime,
        action: str, actor_ref: str,
    ) -> None:
        """R-013/R-019: destination account must match the unit's policy."""
        try:
            resolved = self._resolver.resolve(PolicyResolutionRequest(
                operating_unit_ref=unit_ref, currency=currency, effective_at=at,
            ))
        except PolicyResolutionError as exc:
            self._log_denied(action, actor_ref, at, "POLICY_UNRESOLVED")
            raise WorkflowBlocked("financial identity unavailable") from exc
        if alias != resolved.identity.destination_account_alias:
            self._log_denied(action, actor_ref, at, "WRONG_ACCOUNT")
            raise WorkflowDenied("WRONG_ACCOUNT")

    def _receivable_status(self, invoice: Any) -> str:
        """Recompute receivable state from the authoritative read-back (R-017)."""
        total = Decimal(invoice.total_amount)
        open_amount = Decimal(invoice.open_amount)
        if open_amount == 0:
            return ReceivableStatus.PAID.value
        if open_amount < total:
            return ReceivableStatus.PARTIALLY_PAID.value
        return ReceivableStatus.OPEN.value

    # -- commands ----------------------------------------------------------------

    def record_payment(
        self,
        *,
        invoice_ref: str,
        amount: str,
        currency: str,
        evidence_ref: str,
        destination_account_alias: str,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        channel_ref: str,
        idempotency_key: str | None = None,
    ) -> PaymentResult:
        """Record a payment against a POSTED invoice.

        Guard order: input validation -> evidence mandate -> provider
        read-back -> authz -> account/policy validation -> idempotency claim
        -> provider mutation -> read-back -> terminal outcome.
        """
        with self._lock:
            # R-006: the EVI-* evidence reference is mandatory — chat text
            # alone can never confirm a payment.
            if type(evidence_ref) is not str or not evidence_ref.startswith("EVI-") \
                    or _REF.fullmatch(evidence_ref) is None:
                self._log_denied("record_payment", actor_ref, at, "INVALID_INPUT")
                raise WorkflowBlocked("payment requires an EVI-* evidence reference")
            self._require_ref(invoice_ref, "INV-", "invoice_ref")
            self._require_ref(destination_account_alias, "ACC-",
                              "destination_account_alias")
            if type(amount) is not str or _DECIMAL_TEXT.fullmatch(amount) is None \
                    or Decimal(amount) <= 0:
                self._log_denied("record_payment", actor_ref, at, "INVALID_INPUT")
                raise WorkflowBlocked("payment amount must be a positive decimal")
            if type(currency) is not str or len(currency) != 3 or not currency.isupper():
                self._log_denied("record_payment", actor_ref, at, "INVALID_INPUT")
                raise WorkflowBlocked("currency must be ISO-4217 uppercase")

            # A pending UNCERTAIN payment blocks any blind retry of the same
            # evidence ref until reconciliation classifies it.
            if evidence_ref in self._pending_uncertain:
                self._log_denied("record_payment", actor_ref, at, "INVALID_STATE")
                raise WorkflowBlocked("payment is pending reconciliation")

            # Read back the invoice and derive the owning unit from provider
            # state — never from the caller.
            unit_ref, invoice = self._resolve_unit_ref(invoice_ref)
            if invoice.status != "POSTED":
                self._log_denied("record_payment", actor_ref, at, "INVALID_STATE")
                raise WorkflowBlocked("payments require a POSTED invoice")

            try:
                decision = self._authorize(
                    actor_ref=actor_ref, channel_ref=channel_ref,
                    action="PAYMENT_RECORD", binding=binding, assignments=assignments,
                    selected_unit_ref=unit_ref, at=at,
                )
            except WorkflowDenied as exc:
                self._log_denied("record_payment", actor_ref, at, exc.code)
                raise
            assignment = self._selected_assignment(
                actor_ref, decision.unit_ref, assignments, at,
            )

            # R-013/R-019: wrong-account attempts denied before mutation.
            self._validate_account_alias(
                unit_ref=unit_ref, currency=invoice.currency,
                alias=destination_account_alias, at=at,
                action="record_payment", actor_ref=actor_ref,
            )
            if currency != invoice.currency:
                self._log_denied("record_payment", actor_ref, at, "INVALID_INPUT")
                raise WorkflowBlocked("payment currency does not match invoice")

            # Idempotency claim (namespace distinct from invoice posting):
            # same key + same payload -> replay; same key + different payload
            # -> conflict; no key -> derive a stable claim anchor. The claim
            # check runs BEFORE the overpay guard so replaying a completed
            # key returns the recorded result even after the invoice closed.
            claim_key = idempotency_key or evidence_ref
            payload_hash = self._payload_hash(
                invoice_ref=invoice_ref, amount=amount, currency=currency,
                evidence_ref=evidence_ref,
                destination_account_alias=destination_account_alias,
            )
            scoped = (actor_ref, claim_key)
            existing = self._claims.get(scoped)
            if existing is not None:
                if existing.payload_hash != payload_hash:
                    self._log_denied("record_payment", actor_ref, at,
                                     "IDEMPOTENCY_CONFLICT")
                    raise WorkflowBlocked(
                        "idempotency key conflict: payload differs from the original request"
                    )
                if existing.outcome == "RECORDED":
                    # Replay: re-read the invoice so the reported receivable
                    # status is fresh, never a stale snapshot.
                    _, refreshed = self._resolve_unit_ref(invoice_ref)
                    return PaymentResult("RECORDED", existing.payment_ref,
                                         self._receivable_status(refreshed), None)
                if existing.outcome == "UNCERTAIN":
                    self._log_denied("record_payment", actor_ref, at, "INVALID_STATE")
                    raise WorkflowBlocked("payment is pending reconciliation")
                # REJECTED/PENDING re-claim falls through to a fresh attempt.

            # Overpay guard: the provider also enforces this, but denying
            # before the provider call keeps the failure audit local and
            # avoids any chance of a partial provider mutation.
            if Decimal(amount) > Decimal(invoice.open_amount):
                self._log_denied("record_payment", actor_ref, at, "OVERPAYMENT")
                raise WorkflowBlocked("payment exceeds open amount")

            # Duplicate evidence ref with a different claim key still cannot
            # double-apply: the provider rejects it; we detect it cheaply here.
            if evidence_ref in self._by_evidence_ref:
                known_payment = self._by_evidence_ref[evidence_ref]
                if existing is None or existing.payment_ref != known_payment:
                    self._log_denied("record_payment", actor_ref, at,
                                     "IDEMPOTENCY_CONFLICT")
                    raise WorkflowBlocked("evidence reference already recorded")

            self._claims[scoped] = _ClaimState(payload_hash, "PENDING")
            command = DraftPaymentCommand(
                invoice_ref=invoice_ref,
                amount=amount,
                currency=currency,
                evidence_ref=evidence_ref,
                destination_account_alias=destination_account_alias,
            )
            try:
                payment_ref = self._adapter.record_payment(command)
            except UncertainOutcome:
                # REC-001: enqueue for fenced classification; block blind retry.
                # The invoice scope is anchored on the claim so reconcile can
                # authorize against it before any classification leaks.
                self._claims[scoped] = _ClaimState(payload_hash, "UNCERTAIN",
                                                   invoice_ref=invoice_ref)
                self._pending_uncertain.add(evidence_ref)
                self._reconciliation.enqueue_uncertain_payment(
                    intent_key=f"payment:{actor_ref}:{claim_key}",
                    evidence_ref=evidence_ref,
                )
                self._log(invoice_ref, "payment_uncertain", actor_ref, at,
                          {"evidence_ref": evidence_ref,
                           "assignment_ref": assignment.assignment_ref})
                return PaymentResult("UNCERTAIN", None, None, "outcome unknown")
            except (DocumentRejected, ProviderContractError) as exc:
                self._claims[scoped] = _ClaimState(payload_hash, "REJECTED")
                self._log(invoice_ref, "payment_rejected", actor_ref, at,
                          {"reason": "provider rejected payment",
                           "evidence_ref": evidence_ref})
                raise WorkflowBlocked("provider rejected payment") from exc

            # Read-back: the receivable state derives from provider records.
            try:
                record = self._adapter.read_payment(payment_ref)
                refreshed = self._adapter.read_invoice(invoice_ref)
            except (DocumentRejected, ProviderContractError) as exc:
                # QA-R2-F-01: read-back failure after a successful provider
                # record must NOT orphan the claim — follow the same recovery
                # path as UncertainOutcome: persist full linkage, mark
                # pending-uncertain, enqueue reconciliation, audit, and
                # block any blind retry until classification completes.
                self._claims[scoped] = _ClaimState(payload_hash, "UNCERTAIN",
                                                   payment_ref,
                                                   invoice_ref=invoice_ref)
                self._pending_uncertain.add(evidence_ref)
                self._reconciliation.enqueue_uncertain_payment(
                    intent_key=f"payment:{actor_ref}:{claim_key}",
                    evidence_ref=evidence_ref,
                )
                self._log(invoice_ref, "payment_uncertain", actor_ref, at,
                          {"evidence_ref": evidence_ref,
                           "payment_ref": payment_ref,
                           "assignment_ref": assignment.assignment_ref,
                           "reason": "read-back failed"})
                raise WorkflowBlocked(
                    "payment read-back failed; pending reconciliation"
                ) from exc
            if record.evidence_ref != evidence_ref or record.invoice_ref != invoice_ref:
                # QA-R2-F-01: read-back mismatch is the same recovery path —
                # an actually-executed provider payment must remain
                # reconcilable, never an unreconcilable orphan.
                self._claims[scoped] = _ClaimState(payload_hash, "UNCERTAIN",
                                                   payment_ref,
                                                   invoice_ref=invoice_ref)
                self._pending_uncertain.add(evidence_ref)
                self._reconciliation.enqueue_uncertain_payment(
                    intent_key=f"payment:{actor_ref}:{claim_key}",
                    evidence_ref=evidence_ref,
                )
                self._log(invoice_ref, "payment_uncertain", actor_ref, at,
                          {"evidence_ref": evidence_ref,
                           "payment_ref": payment_ref,
                           "assignment_ref": assignment.assignment_ref,
                           "reason": "read-back mismatch"})
                raise WorkflowBlocked(
                    "payment read-back mismatch; pending reconciliation")
            self._claims[scoped] = _ClaimState(payload_hash, "RECORDED", payment_ref)
            self._by_evidence_ref[evidence_ref] = payment_ref
            status = self._receivable_status(refreshed)
            self._log(invoice_ref, "payment_recorded", actor_ref, at,
                      {"payment_ref": payment_ref, "evidence_ref": evidence_ref,
                       "receivable_status": status,
                       "assignment_ref": assignment.assignment_ref})
            return PaymentResult("RECORDED", payment_ref, status, None)

    def reconcile_payment(
        self,
        *,
        evidence_ref: str,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        channel_ref: str,
    ) -> PaymentResult:
        """Classify a pending UNCERTAIN payment via authoritative read-back.

        Authorization runs BEFORE any classification/resolution: the unit is
        resolved from the pending claim's stored invoice scope (never from
        caller-supplied data), and only claims inside the caller's authorized
        scope are resolved — no cross-actor/cross-unit resolution.
        """
        with self._lock:
            if evidence_ref not in self._pending_uncertain:
                # QA-R2-F-03: early-deny paths audit like every other denial.
                self._log_denied("reconcile_payment", actor_ref, at, "INVALID_STATE")
                raise WorkflowBlocked("no pending uncertain payment for this evidence")

            # Resolve the unit from the pending claim OWNING this evidence
            # ref — never from caller-supplied data, and never from arbitrary
            # iteration over all pending claims (set/dict scan order is
            # hash-dependent, so anchoring on "any" pending claim is
            # non-deterministic). Claims are keyed (actor_ref, claim_key)
            # with claim_key defaulting to the evidence ref at record time,
            # so the anchor is a deterministic exact-key lookup first; a
            # claim recorded under an explicit idempotency key still anchors
            # via the actor's pending claims. The workflow enqueues an
            # UNCERTAIN claim for the evidence ref's invoice before the
            # evidence lands in _pending_uncertain, so a scope anchor always
            # exists; its absence is a state violation, not an authz pass.
            def _anchor_invoice() -> str | None:
                exact: str | None = None
                actor_pending: list[str] = []
                for (claim_actor, claim_key), claim in self._claims.items():
                    if claim.outcome != "UNCERTAIN" or claim.invoice_ref is None:
                        continue
                    if claim_key == evidence_ref:
                        # Deterministic owner: the claim recorded for this
                        # exact evidence ref (prefer the caller's own claim).
                        if claim_actor == actor_ref:
                            return claim.invoice_ref
                        exact = claim.invoice_ref
                    elif claim_actor == actor_ref:
                        actor_pending.append(claim.invoice_ref)
                if exact is not None:
                    # Cross-actor reconcile of another actor's claim: anchor
                    # on the true owning unit so authorization denies it.
                    return exact
                if len(actor_pending) == 1:
                    # Explicit idempotency-key claim: the evidence ref is the
                    # actor's only pending payment, so it must be the one.
                    return actor_pending[0]
                return None

            anchor_invoice_ref = _anchor_invoice()
            unit_ref: str | None = None
            if anchor_invoice_ref is not None:
                unit_ref, _ = self._resolve_unit_ref(anchor_invoice_ref)
            if unit_ref is None:
                self._log_denied("reconcile_payment", actor_ref, at, "INVALID_STATE")
                raise WorkflowBlocked("no pending uncertain payment for this evidence")
            try:
                decision = self._authorize(
                    actor_ref=actor_ref, channel_ref=channel_ref,
                    action="PAYMENT_RECORD", binding=binding, assignments=assignments,
                    selected_unit_ref=unit_ref, at=at,
                )
            except WorkflowDenied as exc:
                self._log_denied("reconcile_payment", actor_ref, at, exc.code)
                raise
            assignment = self._selected_assignment(
                actor_ref, unit_ref, assignments, at,
            )

            try:
                record = self._adapter.reconcile_payment(evidence_ref)
            except UncertainOutcome:
                self._log(evidence_ref, "reconcile_uncertain", actor_ref, at,
                          {"reason": "outcome still unknown"})
                return PaymentResult("UNCERTAIN", None, None, "outcome unknown")
            except (DocumentRejected, ProviderContractError):
                # Provider has no such evidence: safe to retry with a fresh
                # attempt — release the pending marker and claims. Only
                # claims inside the caller's authorized unit scope are
                # resolved (QA-R2-F-02: same scope intersection as PRESENT);
                # cross-unit claims remain UNCERTAIN and undisclosed.
                self._pending_uncertain.discard(evidence_ref)
                for scoped, claim in list(self._claims.items()):
                    if claim.outcome != "UNCERTAIN":
                        continue
                    if claim.invoice_ref is not None:
                        claim_unit, _ = self._resolve_unit_ref(claim.invoice_ref)
                        if claim_unit != decision.unit_ref:
                            continue  # cross-unit claim: never resolve it here
                    self._claims[scoped] = _ClaimState(
                        claim.payload_hash, "REJECTED",
                        invoice_ref=claim.invoice_ref)
                self._log(evidence_ref, "reconcile_absent", actor_ref, at)
                return PaymentResult("REJECTED", None, None, "provider has no such payment")
            # PRESENT: resolve claims and index the evidence ref. Only claims
            # inside the caller's authorized unit scope are resolved.
            self._pending_uncertain.discard(evidence_ref)
            for scoped, claim in list(self._claims.items()):
                if claim.outcome != "UNCERTAIN":
                    continue
                if claim.invoice_ref is not None:
                    claim_unit, _ = self._resolve_unit_ref(claim.invoice_ref)
                    if claim_unit != decision.unit_ref:
                        continue  # cross-unit claim: never resolve it here
                self._claims[scoped] = _ClaimState(
                    claim.payload_hash, "RECORDED", record.reference,
                    invoice_ref=claim.invoice_ref)
            self._by_evidence_ref[evidence_ref] = record.reference
            _, invoice = self._resolve_unit_ref(record.invoice_ref)
            status = self._receivable_status(invoice)
            self._log(record.invoice_ref, "reconcile_payment", actor_ref, at,
                      {"payment_ref": record.reference,
                       "evidence_ref": evidence_ref,
                       "receivable_status": status,
                       "assignment_ref": assignment.assignment_ref})
            return PaymentResult("RECORDED", record.reference, status, None)

    def reverse_payment(
        self,
        *,
        payment_ref: str,
        reason: str,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        channel_ref: str,
    ) -> PaymentResult:
        """Compensating reversal; recomputes receivable state from records."""
        with self._lock:
            self._require_ref(payment_ref, "PAY-", "payment_ref")
            if type(reason) is not str or not reason.strip():
                self._log_denied("reverse_payment", actor_ref, at, "INVALID_INPUT")
                raise WorkflowBlocked("reversal requires a reason")
            try:
                payment = self._adapter.read_payment(payment_ref)
            except (DocumentRejected, ProviderContractError) as exc:
                self._log_denied("reverse_payment", actor_ref, at, "INVALID_STATE")
                raise WorkflowBlocked("unknown payment") from exc
            if payment.reversal_of is not None:
                self._log_denied("reverse_payment", actor_ref, at, "INVALID_STATE")
                raise WorkflowBlocked("cannot reverse a reversal record")
            if payment_ref in self._reversed:
                self._log_denied("reverse_payment", actor_ref, at, "INVALID_STATE")
                raise WorkflowBlocked("payment is already reversed")

            unit_ref, _ = self._resolve_unit_ref(payment.invoice_ref)
            try:
                decision = self._authorize(
                    actor_ref=actor_ref, channel_ref=channel_ref,
                    action="PAYMENT_RECORD", binding=binding, assignments=assignments,
                    selected_unit_ref=unit_ref, at=at,
                )
            except WorkflowDenied as exc:
                self._log_denied("reverse_payment", actor_ref, at, exc.code)
                raise
            assignment = self._selected_assignment(
                actor_ref, decision.unit_ref, assignments, at,
            )

            try:
                reversal_ref = self._adapter.reverse_payment(
                    ReversalCommand(payment_ref=payment_ref, reason=reason))
            except (DocumentRejected, ProviderContractError) as exc:
                self._log_denied("reverse_payment", actor_ref, at, "INVALID_STATE")
                raise WorkflowBlocked("provider rejected reversal") from exc
            self._reversed.add(payment_ref)
            _, invoice = self._resolve_unit_ref(payment.invoice_ref)
            status = self._receivable_status(invoice)
            self._log(payment.invoice_ref, "payment_reversed", actor_ref, at,
                      {"payment_ref": payment_ref, "reversal_ref": reversal_ref,
                       "receivable_status": status,
                       "assignment_ref": assignment.assignment_ref})
            return PaymentResult("RECORDED", reversal_ref, status, None)

    # -- queries ---------------------------------------------------------------

    def audit_events(self, anchor: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._audit.get(anchor, []))

    def denied_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._denied)
