"""Invoice review and posting workflow (FLOW-002).

R-004: review separation — post requires a different actor/reviewer role than
the draft opener (re-authorizes at post time with INVOICE_POST action).
R-005/R-006/R-007: fenced post/readback, immutable branding/config snapshot,
and unit-template PDF reference while financial identity remains
provider/policy-derived.
R-008: separately idempotent delivery outbox state.
R-016/R-017/R-019: issuer/tax/series/ledger/account resolve from FND-003
policy — never from branding/settings.
R-020: branding (template/logo) frozen at post time; later settings changes
do not rewrite historical PDFs.
R-021: posting scoped to the authorized unit; cross-unit denied.
R-022: configuration-version conflicts fail closed; stale preview blocks post.

Official number exists only after verified post and delivery remains
orthogonal.

Independent QA round remediations:
- F-01: caller-supplied Preview is never trusted — every protected field and
  the preview_hash are recomputed from current draft state + active settings
  + resolved policy identity before any provider write.
- F-02: the draft opener may never post their own draft (SELF_POST_DENIED),
  even if they hold a FINANCE-POSTER role on the unit.
- F-03: a draft with a pending UNCERTAIN post blocks re-post until
  reconciliation classifies it (no duplicate provider drafts).
- F-04: reconcile_post refuses a stale configuration version.
- F-05: due_on derives from the unit's payment_terms_days setting.
- F-06: adapter contract exceptions are translated into WorkflowBlocked /
  UNCERTAIN outcomes; raw DocumentRejected/UncertainOutcome never escape.
- F-07: a REJECTED post cleans up the orphaned provider draft best-effort.
- F-09: channel_ref is a required parameter on every mutating entry point.
- F-10: the selected assignment is resolved and recorded in the audit trail.
- F-12: REJECTED/UNCERTAIN audit entries carry the provider_draft_ref.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import threading
from typing import Any, Iterable

from src.authz.access import (
    AccessDecision,
    ActorUnitAssignment,
    AuthorizationRequest,
    IdentityBinding,
    PreviewBinding,
    authorize,
)
from src.contracts.erp_port import (
    DocumentRejected,
    ProviderContractError,
    UncertainOutcome,
)
from src.domain.errors import InvalidDomainValue
from src.policy.financial_identity import (
    FinancialPolicyResolver,
    PolicyResolutionError,
    PolicyResolutionRequest,
    PostedFinancialSnapshot,
)
from src.units.registry import UnitRegistry
from src.units.settings import UnitSettingsStore


class WorkflowDenied(ValueError):
    """Safe denial; message never discloses protected data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("Request cannot be authorized.")


class WorkflowBlocked(ValueError):
    """Precise, safe blocker (missing data / state conflict)."""


@dataclass(frozen=True, slots=True)
class PostResult:
    """Outcome of a fenced post attempt."""

    outcome: str  # POSTED | REJECTED | UNCERTAIN
    official_ref: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class PostedInvoiceRecord:
    """Immutable read model for a posted invoice."""

    official_ref: str
    draft_id: str
    unit_ref: str
    customer_ref: str
    status: str
    total_amount: str
    currency: str
    # Frozen branding/config snapshot
    invoice_template_ref: str
    logo_asset_ref: str | None
    configuration_version: int
    # Financial identity from policy (never branding)
    legal_issuer_ref: str
    tax_profile_ref: str
    invoice_series_ref: str
    receivable_ledger_ref: str
    destination_account_alias: str
    policy_ref: str
    policy_version: int
    # PDF reference derived from frozen template
    pdf_reference: str


@dataclass(slots=True)
class _PostedState:
    official_ref: str
    draft_id: str
    unit_ref: str
    customer_ref: str
    status: str  # POSTED | CANCELLED
    total_amount: str
    currency: str
    invoice_template_ref: str
    logo_asset_ref: str | None
    configuration_version: int
    snapshot: PostedFinancialSnapshot
    pdf_reference: str
    posted_at: datetime
    posted_by: str


# Preview fields that must match the authoritative recomputation (F-01).
_PREVIEW_PROTECTED_FIELDS = (
    "draft_id",
    "unit_ref",
    "customer_ref",
    "currency",
    "total_amount",
    "invoice_template_ref",
    "logo_asset_ref",
    "configuration_version",
    "legal_issuer_ref",
    "tax_profile_ref",
    "invoice_series_ref",
    "receivable_ledger_ref",
    "destination_account_alias",
    "preview_hash",
)


class InvoicePostWorkflow:
    """One-writer review/post workflow over fixture dependencies."""

    def __init__(
        self,
        *,
        registry: UnitRegistry,
        settings: UnitSettingsStore,
        resolver: FinancialPolicyResolver,
        adapter: Any,
        draft_workflow: Any,  # InvoiceDraftWorkflow for line lookup
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._resolver = resolver
        self._adapter = adapter
        self._draft_workflow = draft_workflow
        self._posted: dict[str, _PostedState] = {}
        self._by_draft_id: dict[str, str] = {}  # draft_id -> official_ref
        # F-03: drafts with a pending UNCERTAIN post, draft_id -> provider ref.
        self._pending_uncertain: dict[str, str] = {}
        self._audit: dict[str, list[dict[str, Any]]] = {}
        self._denied: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    # -- audit ---------------------------------------------------------------

    def _log(self, invoice_id: str, action: str, actor_ref: str, at: datetime,
             detail: dict[str, Any] | None = None) -> None:
        entry: dict[str, Any] = {
            "action": action,
            "actor_ref": actor_ref,
            "at": at.astimezone(timezone.utc).isoformat(),
        }
        if detail:
            entry.update(detail)
        self._audit.setdefault(invoice_id, []).append(entry)

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
        expected_assignment_revision: int | None = None,
        preview: PreviewBinding | None = None,
    ) -> AccessDecision:
        try:
            request = AuthorizationRequest(
                actor_ref=actor_ref,
                channel_ref=channel_ref,
                action=action,
                selected_unit_ref=selected_unit_ref,
                requested_at=at,
                expected_assignment_revision=expected_assignment_revision,
                preview=preview,
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

    def _unit_code_for_ref(self, unit_ref: str) -> str:
        for spec in self._registry.all():
            if f"UNIT-{spec.code}" == unit_ref:
                return spec.code
        raise WorkflowBlocked("unknown operating unit")

    # -- F-01: preview authenticity -------------------------------------------

    def _verify_preview_authentic(self, preview: Any, *, action: str,
                                  actor_ref: str, at: datetime) -> None:
        """Recompute the authoritative preview and require exact equality.

        A caller-supplied Preview is just a dataclass — nothing stops a caller
        from forging totals, templates, identity fields, or the hash itself.
        The draft workflow re-derives every protected field from the CURRENT
        draft state, active settings, and resolved policy identity; any drift
        is a forgery and denied.
        """
        expected = self._draft_workflow.recompute_preview_expectation(
            preview.draft_id, at=at,
        )
        forged = any(
            getattr(preview, field, object()) != expected[field]
            for field in _PREVIEW_PROTECTED_FIELDS
        )
        if forged:
            self._log_denied(action, actor_ref, at, "PREVIEW_HASH_MISMATCH")
            raise WorkflowDenied("PREVIEW_HASH_MISMATCH")

    def _assert_not_self_post(self, preview: Any, *, action: str,
                              actor_ref: str, at: datetime) -> None:
        """F-02: the draft opener may never post/reconcile their own draft."""
        opener = self._draft_workflow.get_draft_opener(preview.draft_id)
        if actor_ref == opener:
            self._log_denied(action, actor_ref, at, "SELF_POST_DENIED")
            raise WorkflowDenied("SELF_POST_DENIED")

    # -- commands ---------------------------------------------------------------

    def post(
        self,
        preview: Any,  # Preview from invoice_draft.workflow
        *,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        channel_ref: str,
    ) -> PostResult:
        """Fenced post: requires INVOICE_POST action, validates preview freshness,
        posts via adapter, and freezes branding/config snapshot on success."""
        with self._lock:
            # R-004: review separation — re-authorize with INVOICE_POST action
            try:
                decision = self._authorize(
                    actor_ref=actor_ref, channel_ref=channel_ref,
                    action="INVOICE_POST", binding=binding, assignments=assignments,
                    selected_unit_ref=preview.unit_ref, at=at,
                )
            except WorkflowDenied as exc:
                self._log_denied("post", actor_ref, at, exc.code)
                raise
            # F-10: resolve the selected assignment for the audit trail.
            assignment = self._selected_assignment(
                actor_ref, preview.unit_ref, assignments, at,
            )

            # F-02: review separation also means no self-post, role or not.
            self._assert_not_self_post(preview, action="post",
                                       actor_ref=actor_ref, at=at)

            # R-022: configuration version conflict — preview must match active.
            # Runs BEFORE the authenticity check: the hash binds the config
            # version, so a stale preview would otherwise be reported as a
            # forgery instead of the precise staleness blocker.
            unit_code = self._unit_code_for_ref(preview.unit_ref)
            active = self._settings.get_active(unit_code, at=at)
            if active.configuration_version != preview.configuration_version:
                self._log_denied("post", actor_ref, at, "STALE_PREVIEW")
                raise WorkflowBlocked(
                    "configuration version conflict: preview is stale"
                )

            # F-01: never trust the caller-supplied preview.
            self._verify_preview_authentic(preview, action="post",
                                           actor_ref=actor_ref, at=at)

            # F-03: a pending UNCERTAIN post blocks any blind re-post.
            if preview.draft_id in self._pending_uncertain:
                self._log_denied("post", actor_ref, at, "INVALID_STATE")
                raise WorkflowBlocked("post is pending reconciliation")

            # State transition guard: one terminal state per draft
            existing = self._by_draft_id.get(preview.draft_id)
            if existing is not None:
                prior = self._posted.get(existing)
                if prior is not None and prior.status == "CANCELLED":
                    self._log_denied("post", actor_ref, at, "INVALID_STATE")
                    raise WorkflowBlocked("cannot post a cancelled invoice")
                if prior is not None and prior.status == "POSTED":
                    self._log_denied("post", actor_ref, at, "INVALID_STATE")
                    raise WorkflowBlocked("invoice is already posted")

            # R-016/R-017/R-019: resolve financial identity from policy
            resolved = self._resolve_identity(preview.unit_ref, preview.currency, at)

            # Build provider draft command from preview-bound state
            from src.contracts.erp_port import DraftInvoiceCommand, InvoiceLine
            draft_snapshot = self._draft_workflow.get_draft(preview.draft_id)
            lines = tuple(
                InvoiceLine(
                    service_ref=line["service_ref"],
                    description=line.get("description", ""),
                    quantity=line["quantity"],
                    unit_price_amount=line["unit_price_amount"],
                    currency=line["currency"],
                )
                for line in draft_snapshot.lines
            )
            # F-05: due date derives from the unit's payment terms.
            payment_terms_days = int(active.settings.get("payment_terms_days", 0))
            due_on = (at.date() + timedelta(days=payment_terms_days)).isoformat()
            command = DraftInvoiceCommand(
                customer_ref=preview.customer_ref,
                identity=resolved.identity,
                lines=lines,
                issued_on=at.date().isoformat(),
                due_on=due_on,
            )
            try:
                provider_draft_ref = self._adapter.create_draft_invoice(command)
            except (DocumentRejected, ProviderContractError) as exc:
                self._log(preview.draft_id, "post_blocked", actor_ref, at,
                          {"reason": "provider rejected draft"})
                raise WorkflowBlocked("provider rejected invoice draft") from exc

            # Call adapter post_invoice (fenced, outcome-explicit)
            try:
                result = self._adapter.post_invoice(provider_draft_ref)
            except UncertainOutcome as exc:
                # F-06: a raised UncertainOutcome is the UNCERTAIN path.
                self._pending_uncertain[preview.draft_id] = provider_draft_ref
                self._log(preview.draft_id, "post_uncertain", actor_ref, at,
                          {"reason": "outcome unknown",
                           "provider_draft_ref": provider_draft_ref,
                           "assignment_ref": assignment.assignment_ref})
                return PostResult("UNCERTAIN", None, "outcome unknown")
            except (DocumentRejected, ProviderContractError) as exc:
                self._log(preview.draft_id, "post_blocked", actor_ref, at,
                          {"reason": "provider rejected post",
                           "provider_draft_ref": provider_draft_ref})
                raise WorkflowBlocked("provider rejected invoice post") from exc

            if result.outcome == "REJECTED":
                # F-07: clean up the orphaned provider draft best-effort so a
                # rejected attempt never leaks a dangling DRAFT at the provider.
                try:
                    self._adapter.cancel_invoice(provider_draft_ref)
                except Exception:
                    pass  # cleanup failure must never mask the rejection
                self._log(preview.draft_id, "post_rejected", actor_ref, at,
                          {"reason": result.reason,
                           "provider_draft_ref": provider_draft_ref,
                           "assignment_ref": assignment.assignment_ref})
                return PostResult("REJECTED", None, result.reason)

            if result.outcome == "UNCERTAIN":
                self._pending_uncertain[preview.draft_id] = provider_draft_ref
                self._log(preview.draft_id, "post_uncertain", actor_ref, at,
                          {"reason": result.reason,
                           "provider_draft_ref": provider_draft_ref,
                           "assignment_ref": assignment.assignment_ref})
                return PostResult("UNCERTAIN", None, result.reason)

            # POSTED: freeze immutable snapshot
            official_ref = result.reference
            snapshot = resolved.to_posted_snapshot()
            pdf_reference = self._render_pdf_reference(
                preview.invoice_template_ref, official_ref, snapshot,
            )

            posted_state = _PostedState(
                official_ref=official_ref,
                draft_id=preview.draft_id,
                unit_ref=preview.unit_ref,
                customer_ref=preview.customer_ref,
                status="POSTED",
                total_amount=preview.total_amount,
                currency=preview.currency,
                invoice_template_ref=preview.invoice_template_ref,
                logo_asset_ref=preview.logo_asset_ref,
                configuration_version=preview.configuration_version,
                snapshot=snapshot,
                pdf_reference=pdf_reference,
                posted_at=at,
                posted_by=actor_ref,
            )
            self._posted[official_ref] = posted_state
            self._by_draft_id[preview.draft_id] = official_ref
            self._log(official_ref, "post", actor_ref, at,
                      {"draft_id": preview.draft_id,
                       "configuration_version": preview.configuration_version,
                       "assignment_ref": assignment.assignment_ref})
            return PostResult("POSTED", official_ref, None)

    def reconcile_post(
        self,
        preview: Any,
        *,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        channel_ref: str,
    ) -> PostResult:
        """Classify an UNCERTAIN post via authoritative read-back. Never blind retry."""
        with self._lock:
            try:
                decision = self._authorize(
                    actor_ref=actor_ref, channel_ref=channel_ref,
                    action="INVOICE_POST", binding=binding, assignments=assignments,
                    selected_unit_ref=preview.unit_ref, at=at,
                )
            except WorkflowDenied as exc:
                self._log_denied("reconcile_post", actor_ref, at, exc.code)
                raise
            assignment = self._selected_assignment(
                actor_ref, preview.unit_ref, assignments, at,
            )

            # F-02: the opener cannot reconcile their own post either.
            self._assert_not_self_post(preview, action="reconcile_post",
                                       actor_ref=actor_ref, at=at)

            # F-04: reconciling freezes the snapshot; a stale preview would
            # freeze yesterday's branding/config onto today's document. Runs
            # before authenticity for the same reason as in post().
            unit_code = self._unit_code_for_ref(preview.unit_ref)
            active = self._settings.get_active(unit_code, at=at)
            if active.configuration_version != preview.configuration_version:
                self._log_denied("reconcile_post", actor_ref, at, "STALE_PREVIEW")
                raise WorkflowBlocked(
                    "configuration version conflict: preview is stale"
                )

            # F-01: the presented preview must still be authentic.
            self._verify_preview_authentic(preview, action="reconcile_post",
                                           actor_ref=actor_ref, at=at)

            # Use the provider draft ref stored during the UNCERTAIN post
            provider_draft_ref = self._pending_uncertain.get(preview.draft_id)
            if provider_draft_ref is None:
                raise WorkflowBlocked("no pending uncertain post for this draft")

            try:
                result = self._adapter.reconcile_post(provider_draft_ref)
            except UncertainOutcome as exc:
                self._log(preview.draft_id, "reconcile_uncertain", actor_ref, at,
                          {"reason": "outcome still unknown",
                           "provider_draft_ref": provider_draft_ref})
                return PostResult("UNCERTAIN", None, "outcome unknown")
            except (DocumentRejected, ProviderContractError) as exc:
                self._log(preview.draft_id, "reconcile_blocked", actor_ref, at,
                          {"reason": "provider rejected reconcile",
                           "provider_draft_ref": provider_draft_ref})
                raise WorkflowBlocked("provider rejected reconciliation") from exc

            if result.outcome == "POSTED":
                # Freeze snapshot now that we know the official ref
                resolved = self._resolve_identity(preview.unit_ref, preview.currency, at)
                snapshot = resolved.to_posted_snapshot()
                pdf_reference = self._render_pdf_reference(
                    preview.invoice_template_ref, result.reference, snapshot,
                )
                posted_state = _PostedState(
                    official_ref=result.reference,
                    draft_id=preview.draft_id,
                    unit_ref=preview.unit_ref,
                    customer_ref=preview.customer_ref,
                    status="POSTED",
                    total_amount=preview.total_amount,
                    currency=preview.currency,
                    invoice_template_ref=preview.invoice_template_ref,
                    logo_asset_ref=preview.logo_asset_ref,
                    configuration_version=preview.configuration_version,
                    snapshot=snapshot,
                    pdf_reference=pdf_reference,
                    posted_at=at,
                    posted_by=actor_ref,
                )
                self._posted[result.reference] = posted_state
                self._by_draft_id[preview.draft_id] = result.reference
                # F-03: the pending uncertainty is resolved.
                self._pending_uncertain.pop(preview.draft_id, None)
                self._log(result.reference, "reconcile_post", actor_ref, at,
                          {"draft_id": preview.draft_id,
                           "provider_draft_ref": provider_draft_ref,
                           "assignment_ref": assignment.assignment_ref})
                return PostResult("POSTED", result.reference, None)

            if result.outcome == "REJECTED":
                # Provider confirms nothing was posted; release the pending
                # marker so the caller may re-post with a fresh preview.
                self._pending_uncertain.pop(preview.draft_id, None)
                try:
                    self._adapter.cancel_invoice(provider_draft_ref)
                except Exception:
                    pass
            self._log(preview.draft_id, "reconcile_failed", actor_ref, at,
                      {"reason": result.reason,
                       "provider_draft_ref": provider_draft_ref,
                       "assignment_ref": assignment.assignment_ref})
            return PostResult(result.outcome, None, result.reason)

    def cancel_posted(
        self,
        official_ref: str,
        *,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        channel_ref: str,
    ) -> None:
        """Compensating cancel for POSTED unpaid invoice. Paid invoice is rejected."""
        with self._lock:
            state = self._posted.get(official_ref)
            if state is None:
                raise WorkflowBlocked("unknown posted invoice")
            if state.status == "CANCELLED":
                # F-08: explicit, safe blocker instead of a silent no-op.
                raise WorkflowBlocked("invoice already cancelled")
            try:
                decision = self._authorize(
                    actor_ref=actor_ref, channel_ref=channel_ref,
                    action="INVOICE_POST", binding=binding, assignments=assignments,
                    selected_unit_ref=state.unit_ref, at=at,
                )
            except WorkflowDenied as exc:
                self._log_denied("cancel_posted", actor_ref, at, exc.code)
                raise
            assignment = self._selected_assignment(
                actor_ref, state.unit_ref, assignments, at,
            )

            try:
                self._adapter.cancel_invoice(official_ref)
            except (DocumentRejected, ProviderContractError) as exc:
                self._log(official_ref, "cancel_blocked", actor_ref, at,
                          {"reason": "provider rejected cancel"})
                raise WorkflowBlocked("provider rejected cancellation") from exc
            state.status = "CANCELLED"
            self._log(official_ref, "cancel_posted", actor_ref, at,
                      {"assignment_ref": assignment.assignment_ref})

    def enqueue_delivery(
        self,
        official_ref: str,
        *,
        channel_ref: str,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
    ) -> Any:
        """Idempotent delivery outbox enqueue; orthogonal to post state."""
        with self._lock:
            state = self._posted.get(official_ref)
            if state is None:
                raise WorkflowBlocked("unknown posted invoice")
            try:
                decision = self._authorize(
                    actor_ref=actor_ref, channel_ref=channel_ref,
                    action="INVOICE_POST", binding=binding, assignments=assignments,
                    selected_unit_ref=state.unit_ref, at=at,
                )
            except WorkflowDenied as exc:
                self._log_denied("enqueue_delivery", actor_ref, at, exc.code)
                raise

            try:
                record = self._adapter.enqueue_delivery(official_ref, channel_ref=channel_ref)
            except (DocumentRejected, ProviderContractError) as exc:
                self._log(official_ref, "delivery_blocked", actor_ref, at,
                          {"reason": "provider rejected delivery enqueue"})
                raise WorkflowBlocked("provider rejected delivery enqueue") from exc
            self._log(official_ref, "enqueue_delivery", actor_ref, at,
                      {"channel_ref": channel_ref, "delivery_status": record.status})
            return record

    # -- queries ---------------------------------------------------------------

    def get_posted_invoice(self, official_ref: str) -> PostedInvoiceRecord:
        with self._lock:
            state = self._posted.get(official_ref)
            if state is None:
                raise WorkflowBlocked("unknown posted invoice")
            return PostedInvoiceRecord(
                official_ref=state.official_ref,
                draft_id=state.draft_id,
                unit_ref=state.unit_ref,
                customer_ref=state.customer_ref,
                status=state.status,
                total_amount=state.total_amount,
                currency=state.currency,
                invoice_template_ref=state.invoice_template_ref,
                logo_asset_ref=state.logo_asset_ref,
                configuration_version=state.configuration_version,
                legal_issuer_ref=state.snapshot.identity.legal_issuer_ref,
                tax_profile_ref=state.snapshot.identity.tax_profile_ref,
                invoice_series_ref=state.snapshot.identity.invoice_series_ref,
                receivable_ledger_ref=state.snapshot.identity.receivable_ledger_ref,
                destination_account_alias=state.snapshot.identity.destination_account_alias,
                policy_ref=state.snapshot.policy_ref,
                policy_version=state.snapshot.policy_version,
                pdf_reference=state.pdf_reference,
            )

    def audit_events(self, invoice_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._audit.get(invoice_id, []))

    def denied_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._denied)

    # -- helpers ---------------------------------------------------------------

    def _resolve_identity(self, unit_ref: str, currency: str, at: datetime):
        try:
            return self._resolver.resolve(PolicyResolutionRequest(
                operating_unit_ref=unit_ref, currency=currency, effective_at=at,
            ))
        except PolicyResolutionError as exc:
            raise WorkflowBlocked(f"financial identity unavailable: {exc.code}") from exc

    @staticmethod
    def _render_pdf_reference(template_ref: str, official_ref: str,
                              snapshot: PostedFinancialSnapshot) -> str:
        """Safe template substitution: only official_ref and policy identity
        fields are interpolated; no raw placeholder injection into financial fields."""
        # The template_ref is an opaque token like "tpl_banyu_v1"; the PDF
        # reference binds it to the official document number and policy hash.
        material = repr((
            template_ref,
            official_ref,
            snapshot.policy_ref,
            snapshot.policy_version,
            snapshot.identity.legal_issuer_ref,
            snapshot.identity.invoice_series_ref,
        ))
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
        return f"PDF-{template_ref}-{official_ref}-{digest}"
