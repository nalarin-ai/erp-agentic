"""Chat invoice draft and preview workflow (FLOW-001).

R-003/R-004: chat channels are interaction surfaces, not the system of record;
every entry point resolves actor→unit authorization before touching data, and
re-authorizes on every mutating call (FLOW-QA-02).
R-006/R-007: draft → preview is idempotent per (actor, client key) and audited;
denial paths are audited too (FLOW-QA-01, FLOW-QA-08).
R-011/R-021: one active unit context; ambiguous/revoked/stale deny safely.
R-016/R-017/R-019: issuer/tax/series/ledger/account resolve from FND-003
policy — never from branding/settings.
R-020: branding (template/logo) comes from the unit's ACTIVE settings version.
R-022: configuration-version conflicts fail closed; preview binds the exact
settings version it resolved.

Preview performs ZERO provider writes. The adapter is held for later FLOW-002
posting; here it is only exposed for test inspection.

Remediations from independent QA round 1:
- FLOW-QA-01: authorization runs BEFORE idempotency lookup; keys are scoped
  per actor; payload mismatch on a reused key raises a conflict.
- FLOW-QA-02: set_lines/cancel re-authorize against binding + assignments.
- FLOW-QA-03: render_for_review requires actor_ref + authorization.
- FLOW-QA-04: get_draft returns an immutable snapshot; internal state never
  escapes the lock.
- FLOW-QA-05: every line's currency must equal the unit's resolved currency;
  currency is bound into the preview hash.
- FLOW-QA-06: line description is bound into the preview hash.
- FLOW-QA-07: a missing invoice_template_ref fails closed as WorkflowBlocked.
- FLOW-QA-08: denied attempts are appended to a workflow-level security audit.
- FLOW-QA-09: preview pins the assignment revision captured at open by default.
- FLOW-QA-10: per-draft action timestamps must be monotonic (>= opened_at).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import itertools
import re
import threading
from types import MappingProxyType
from typing import Any, Iterable

from src.authz.access import (
    AccessDecision,
    ActorUnitAssignment,
    AuthorizationRequest,
    IdentityBinding,
    PreviewBinding,
    authorize,
)
from src.domain.errors import InvalidDomainValue
from src.policy.financial_identity import (
    FinancialPolicyResolver,
    PolicyResolutionError,
    PolicyResolutionRequest,
)
from src.units.registry import UnitRegistry
from src.units.settings import UnitSettingsStore

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
class DraftHandle:
    draft_id: str
    unit_ref: str


@dataclass(frozen=True, slots=True)
class DraftSnapshot:
    """Immutable read model; callers can never mutate internal state (QA-04)."""

    draft_id: str
    unit_ref: str
    customer_ref: str
    status: str
    lines: tuple[MappingProxyType, ...]


@dataclass(frozen=True, slots=True)
class Preview:
    draft_id: str
    unit_ref: str
    customer_ref: str
    currency: str
    total_amount: str
    invoice_template_ref: str
    logo_asset_ref: str | None
    configuration_version: int
    legal_issuer_ref: str
    tax_profile_ref: str
    invoice_series_ref: str
    receivable_ledger_ref: str
    destination_account_alias: str  # always ACC-[REDACTED] on preview
    preview_hash: str


@dataclass(slots=True)
class _DraftState:
    draft_id: str
    actor_ref: str
    channel_ref: str
    unit_ref: str
    assignment_ref: str
    assignment_revision: int
    customer_ref: str
    lines: list[dict[str, str]]
    status: str  # OPEN | CANCELLED
    opened_at: datetime
    last_action_at: datetime
    idempotency_key: str | None


class InvoiceDraftWorkflow:
    """One-writer chat draft workflow over fixture dependencies."""

    def __init__(
        self,
        *,
        registry: UnitRegistry,
        settings: UnitSettingsStore,
        resolver: FinancialPolicyResolver,
        adapter: Any,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._resolver = resolver
        self._adapter = adapter
        self._drafts: dict[str, _DraftState] = {}
        self._by_idempotency_key: dict[tuple[str, str], str] = {}
        self._audit: dict[str, list[dict[str, Any]]] = {}
        self._denied: list[dict[str, Any]] = []
        self._sequence = itertools.count(1)
        self._lock = threading.RLock()

    # -- audit ---------------------------------------------------------------

    def _log(self, draft_id: str, action: str, actor_ref: str, at: datetime,
             detail: dict[str, Any] | None = None) -> None:
        entry: dict[str, Any] = {
            "action": action,
            "actor_ref": actor_ref,
            "at": at.astimezone(timezone.utc).isoformat(),
        }
        if detail:
            entry.update(detail)
        self._audit.setdefault(draft_id, []).append(entry)

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

    def _get(self, draft_id: str) -> _DraftState:
        state = self._drafts.get(draft_id)
        if state is None:
            raise WorkflowBlocked("unknown draft")
        return state

    @staticmethod
    def _assert_monotonic(state: _DraftState, at: datetime) -> None:
        if at < state.opened_at:
            raise InvalidDomainValue("action timestamp precedes draft open")

    def _reauthorize_mutation(
        self,
        state: _DraftState,
        *,
        action: str,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
    ) -> None:
        """Every mutating entry point re-runs full authorization (QA-02)."""
        self._assert_monotonic(state, at)
        decision = self._authorize(
            actor_ref=actor_ref, channel_ref=state.channel_ref, action=action,
            binding=binding, assignments=assignments,
            selected_unit_ref=state.unit_ref, at=at,
            expected_assignment_revision=state.assignment_revision,
            preview=PreviewBinding(
                unit_ref=state.unit_ref,
                assignment_ref=state.assignment_ref,
                assignment_revision=state.assignment_revision,
            ),
        )
        assignment = self._selected_assignment(actor_ref, decision.unit_ref, assignments, at)
        if assignment.assignment_ref != state.assignment_ref:
            raise WorkflowDenied("STALE_CONTEXT")

    # -- commands --------------------------------------------------------------

    def open_draft(
        self,
        *,
        actor_ref: str,
        channel_ref: str,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        customer_ref: str,
        at: datetime,
        selected_unit_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> DraftHandle:
        with self._lock:
            # QA-01: authorize BEFORE the idempotency lookup; the key namespace
            # is scoped per actor so one actor can never replay another's key.
            # QA-08: a failed authorization is still audited as a denial.
            try:
                decision = self._authorize(
                    actor_ref=actor_ref, channel_ref=channel_ref,
                    action="INVOICE_PREVIEW", binding=binding, assignments=assignments,
                    selected_unit_ref=selected_unit_ref, at=at,
                )
            except WorkflowDenied as exc:
                self._log_denied("open", actor_ref, at, exc.code)
                raise
            if type(customer_ref) is not str or _REF.fullmatch(customer_ref) is None \
                    or not customer_ref.startswith("CUST-"):
                raise InvalidDomainValue("customer_ref must be a canonical CUST- reference")
            if idempotency_key is not None:
                scoped = (actor_ref, idempotency_key)
                existing = self._by_idempotency_key.get(scoped)
                if existing is not None:
                    prior = self._drafts[existing]
                    if prior.customer_ref != customer_ref or prior.unit_ref != decision.unit_ref:
                        self._log_denied("open", actor_ref, at, "IDEMPOTENCY_CONFLICT")
                        raise WorkflowBlocked(
                            "idempotency key conflict: payload differs from the original request"
                        )
                    return DraftHandle(draft_id=prior.draft_id, unit_ref=prior.unit_ref)
            assignment = self._selected_assignment(actor_ref, decision.unit_ref, assignments, at)
            draft_id = f"DFT-{next(self._sequence):06d}"
            state = _DraftState(
                draft_id=draft_id,
                actor_ref=actor_ref,
                channel_ref=channel_ref,
                unit_ref=decision.unit_ref,
                assignment_ref=assignment.assignment_ref,
                assignment_revision=assignment.revision,
                customer_ref=customer_ref,
                lines=[],
                status="OPEN",
                opened_at=at,
                last_action_at=at,
                idempotency_key=idempotency_key,
            )
            self._drafts[draft_id] = state
            if idempotency_key is not None:
                self._by_idempotency_key[(actor_ref, idempotency_key)] = draft_id
            self._log(draft_id, "open", actor_ref, at,
                      {"unit_ref": state.unit_ref, "customer_ref": customer_ref})
            return DraftHandle(draft_id=draft_id, unit_ref=state.unit_ref)

    def set_lines(
        self,
        draft_id: str,
        lines: Iterable[dict[str, str]],
        *,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
    ) -> None:
        with self._lock:
            state = self._get(draft_id)
            try:
                self._assert_owner(state, actor_ref)
                self._assert_open(state)
                self._reauthorize_mutation(
                    state, action="INVOICE_PREVIEW", actor_ref=actor_ref, at=at,
                    binding=binding, assignments=assignments,
                )
            except WorkflowDenied as exc:
                self._log_denied("set_lines", actor_ref, at, exc.code)
                raise
            normalized = self._normalize_lines(lines, state, at)
            state.lines = normalized
            state.last_action_at = at
            self._log(draft_id, "set_lines", actor_ref, at,
                      {"line_count": len(normalized)})

    def _normalize_lines(
        self, lines: Iterable[dict[str, str]], state: _DraftState, at: datetime,
    ) -> list[dict[str, str]]:
        unit_code = self._unit_code_for_ref(state.unit_ref)
        active = self._settings.get_active(unit_code, at=at)
        expected_currency = active.settings.get("default_currency", "IDR")
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in lines:
            if type(raw) is not dict:
                raise InvalidDomainValue("line must be a mapping")
            service_ref = raw.get("service_ref")
            description = raw.get("description", "")
            quantity = raw.get("quantity")
            price = raw.get("unit_price_amount")
            currency = raw.get("currency")
            for name, value in (("service_ref", service_ref), ("quantity", quantity),
                                ("unit_price_amount", price), ("currency", currency)):
                if type(value) is not str or not value:
                    raise InvalidDomainValue(f"line {name} is required")
            if _REF.fullmatch(service_ref) is None:
                raise InvalidDomainValue("service_ref must be an opaque reference")
            if _DECIMAL_TEXT.fullmatch(quantity) is None or Decimal(quantity) <= 0:
                raise InvalidDomainValue("line quantity must be a positive decimal")
            if _DECIMAL_TEXT.fullmatch(price) is None or Decimal(price) <= 0:
                raise InvalidDomainValue("line unit price must be a positive decimal")
            if type(currency) is not str or len(currency) != 3 or not currency.isupper():
                raise InvalidDomainValue("currency must be ISO-4217 uppercase")
            # QA-05: single currency per draft, equal to the unit's resolved
            # currency. The preview must never silently relabel a foreign line.
            if currency != expected_currency:
                raise InvalidDomainValue(
                    f"line currency {currency} does not match unit currency {expected_currency}"
                )
            if service_ref in seen:
                raise InvalidDomainValue("duplicate service_ref in one draft")
            seen.add(service_ref)
            normalized.append({
                "service_ref": service_ref,
                "description": str(description)[:200],
                "quantity": quantity,
                "unit_price_amount": price,
                "currency": currency,
            })
        if not normalized:
            raise InvalidDomainValue("draft requires at least one line")
        return normalized

    def cancel(
        self,
        draft_id: str,
        *,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
    ) -> None:
        with self._lock:
            state = self._get(draft_id)
            try:
                self._assert_owner(state, actor_ref)
                if state.status == "CANCELLED":
                    return
                self._reauthorize_mutation(
                    state, action="INVOICE_PREVIEW", actor_ref=actor_ref, at=at,
                    binding=binding, assignments=assignments,
                )
            except WorkflowDenied as exc:
                self._log_denied("cancel", actor_ref, at, exc.code)
                raise
            state.status = "CANCELLED"
            state.lines = []
            state.last_action_at = at
            self._log(draft_id, "cancel", actor_ref, at)

    def _assert_owner(self, state: _DraftState, actor_ref: str) -> None:
        if actor_ref != state.actor_ref:
            raise WorkflowDenied("PERMISSION_DENIED")

    def _assert_open(self, state: _DraftState) -> None:
        if state.status != "OPEN":
            raise WorkflowBlocked("draft is not open")

    # -- preview ---------------------------------------------------------------

    def preview(
        self,
        draft_id: str,
        *,
        actor_ref: str,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        at: datetime,
        expected_assignment_revision: int | None = None,
    ) -> Preview:
        with self._lock:
            state = self._get(draft_id)
            try:
                self._assert_owner(state, actor_ref)
                self._assert_open(state)
                if not state.lines:
                    raise WorkflowBlocked("draft has no lines; add at least one line")
                # QA-09: the assignment revision pinned at open applies unless
                # the caller explicitly volunteers a (stricter) expectation.
                pinned = expected_assignment_revision if expected_assignment_revision is not None \
                    else state.assignment_revision
                decision = self._authorize(
                    actor_ref=actor_ref, channel_ref=state.channel_ref,
                    action="INVOICE_PREVIEW", binding=binding, assignments=assignments,
                    selected_unit_ref=state.unit_ref, at=at,
                    expected_assignment_revision=pinned,
                    preview=PreviewBinding(
                        unit_ref=state.unit_ref,
                        assignment_ref=state.assignment_ref,
                        assignment_revision=state.assignment_revision,
                    ),
                )
            except WorkflowDenied as exc:
                self._log_denied("preview", actor_ref, at, exc.code)
                raise
            self._assert_monotonic(state, at)
            unit_code = self._unit_code_for_ref(decision.unit_ref)
            active = self._settings.get_active(unit_code, at=at)
            currency = active.settings.get("default_currency", "IDR")
            template_ref = active.settings.get("invoice_template_ref")
            if not template_ref:
                # QA-07: fail closed with a safe blocker, never a bare KeyError.
                raise WorkflowBlocked("invoice template not configured for active settings")
            resolved = self._resolve_identity(decision.unit_ref, currency, at)
            total = sum(
                (Decimal(line["quantity"]) * Decimal(line["unit_price_amount"])
                 for line in state.lines),
                Decimal(0),
            )
            descriptor = resolved.to_redacted_descriptor()
            preview_hash = self._hash(state, active.configuration_version, descriptor, total)
            preview = Preview(
                draft_id=state.draft_id,
                unit_ref=state.unit_ref,
                customer_ref=state.customer_ref,
                currency=currency,
                total_amount=self._format_money(total),
                invoice_template_ref=template_ref,
                logo_asset_ref=active.settings.get("logo_asset_ref"),
                configuration_version=active.configuration_version,
                legal_issuer_ref=resolved.identity.legal_issuer_ref,
                tax_profile_ref=resolved.identity.tax_profile_ref,
                invoice_series_ref=resolved.identity.invoice_series_ref,
                receivable_ledger_ref=resolved.identity.receivable_ledger_ref,
                destination_account_alias=descriptor["identity"]["destination_account_alias"],
                preview_hash=preview_hash,
            )
            state.last_action_at = at
            self._log(draft_id, "preview", actor_ref, at,
                      {"configuration_version": active.configuration_version,
                       "preview_hash": preview_hash})
            return preview

    def _resolve_identity(self, unit_ref: str, currency: str, at: datetime):
        try:
            return self._resolver.resolve(PolicyResolutionRequest(
                operating_unit_ref=unit_ref, currency=currency, effective_at=at,
            ))
        except PolicyResolutionError as exc:
            raise WorkflowBlocked(f"financial identity unavailable: {exc.code}") from exc

    @staticmethod
    def _format_money(total: Decimal) -> str:
        text = format(total, "f")
        whole, dot, fraction = text.partition(".")
        fraction = (fraction + "00")[:2] if dot else "00"
        return f"{whole}.{fraction}"

    @staticmethod
    def _hash(state: _DraftState, configuration_version: int,
              descriptor: dict[str, Any], total: Decimal) -> str:
        # QA-05/QA-06: currency AND description are bound into the hash so any
        # material edit invalidates it.
        material = repr((
            state.draft_id, state.unit_ref, state.customer_ref,
            tuple(sorted((line["service_ref"], line["description"], line["quantity"],
                          line["unit_price_amount"], line["currency"])
                         for line in state.lines)),
            configuration_version,
            tuple(sorted(descriptor["identity"].items())),
            format(total, "f"),
        ))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def render_for_review(
        self,
        preview: Preview,
        *,
        at: datetime,
        actor_ref: str,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
    ) -> dict[str, Any]:
        """Bind a preview to the CURRENT active configuration version.

        QA-03: render is actor-scoped and authorized. R-022: a preview rendered
        against settings version N refuses when the active version has moved
        on — reviewers must never approve a stale branding/config snapshot.
        """
        with self._lock:
            state = self._get(preview.draft_id)
            try:
                self._assert_owner(state, actor_ref)
                self._assert_open(state)
                self._authorize(
                    actor_ref=actor_ref, channel_ref=state.channel_ref,
                    action="INVOICE_PREVIEW", binding=binding, assignments=assignments,
                    selected_unit_ref=state.unit_ref, at=at,
                    expected_assignment_revision=state.assignment_revision,
                    preview=PreviewBinding(
                        unit_ref=state.unit_ref,
                        assignment_ref=state.assignment_ref,
                        assignment_revision=state.assignment_revision,
                    ),
                )
            except WorkflowDenied as exc:
                self._log_denied("render_for_review", actor_ref, at, exc.code)
                raise
            self._assert_monotonic(state, at)
            unit_code = self._unit_code_for_ref(preview.unit_ref)
            active = self._settings.get_active(unit_code, at=at)
            if active.configuration_version != preview.configuration_version:
                self._log(preview.draft_id, "render_blocked", actor_ref, at,
                          {"reason": "configuration_version_conflict",
                           "preview_version": preview.configuration_version,
                           "active_version": active.configuration_version})
                raise WorkflowBlocked(
                    "configuration version conflict: preview is stale"
                )
            # FLOW-QA-R2-01: never trust a caller-supplied Preview. Recompute
            # the hash from the CURRENT draft state and the active settings,
            # and require an exact match with the presented preview. Any
            # forged total/template/identity/customer/hash is denied.
            if not state.lines:
                raise WorkflowBlocked("draft has no lines; add at least one line")
            currency = active.settings.get("default_currency", "IDR")
            resolved = self._resolve_identity(preview.unit_ref, currency, at)
            total = sum(
                (Decimal(line["quantity"]) * Decimal(line["unit_price_amount"])
                 for line in state.lines),
                Decimal(0),
            )
            descriptor = resolved.to_redacted_descriptor()
            expected_hash = self._hash(state, active.configuration_version,
                                       descriptor, total)
            expected_template = active.settings.get("invoice_template_ref")
            identity = resolved.identity
            forged = (
                preview.preview_hash != expected_hash
                or preview.total_amount != self._format_money(total)
                or preview.currency != currency
                or preview.invoice_template_ref != expected_template
                or preview.logo_asset_ref != active.settings.get("logo_asset_ref")
                or preview.legal_issuer_ref != identity.legal_issuer_ref
                or preview.tax_profile_ref != identity.tax_profile_ref
                or preview.invoice_series_ref != identity.invoice_series_ref
                or preview.receivable_ledger_ref != identity.receivable_ledger_ref
                or preview.destination_account_alias
                    != descriptor["identity"]["destination_account_alias"]
                or preview.customer_ref != state.customer_ref
                or preview.unit_ref != state.unit_ref
                or preview.draft_id != state.draft_id
            )
            if forged:
                self._log_denied("render_for_review", actor_ref, at,
                                 "PREVIEW_HASH_MISMATCH")
                raise WorkflowDenied("PREVIEW_HASH_MISMATCH")
            payload = {
                "draft_id": preview.draft_id,
                "unit_ref": preview.unit_ref,
                "template_ref": preview.invoice_template_ref,
                "preview_hash": preview.preview_hash,
                "configuration_version": preview.configuration_version,
                "total_amount": preview.total_amount,
                "currency": preview.currency,
            }
            self._log(preview.draft_id, "render_for_review", actor_ref, at,
                      {"configuration_version": preview.configuration_version})
            return payload

    # -- queries ---------------------------------------------------------------

    def get_draft(self, draft_id: str) -> DraftSnapshot:
        """Immutable snapshot; internal mutable state never escapes (QA-04)."""
        with self._lock:
            state = self._get(draft_id)
            return DraftSnapshot(
                draft_id=state.draft_id,
                unit_ref=state.unit_ref,
                customer_ref=state.customer_ref,
                status=state.status,
                lines=tuple(MappingProxyType(dict(line)) for line in state.lines),
            )

    # -- FLOW-002 additive helpers (no behavior change for FLOW-001) ----------

    def get_draft_opener(self, draft_id: str) -> str:
        """Public accessor for the opener's actor_ref (FLOW-002 self-post guard)."""
        with self._lock:
            return self._get(draft_id).actor_ref

    def recompute_preview_expectation(
        self, draft_id: str, *, at: datetime
    ) -> dict[str, Any]:
        """Authoritative re-derivation of every preview field from CURRENT state.

        FLOW-002 F-01: post/reconcile must never trust a caller-supplied
        Preview. This helper re-runs the exact computation ``preview`` used —
        current draft lines, active settings, resolved policy identity — and
        returns the expected field values (including ``preview_hash``) so the
        posting workflow can require exact equality.
        """
        with self._lock:
            state = self._get(draft_id)
            unit_code = self._unit_code_for_ref(state.unit_ref)
            active = self._settings.get_active(unit_code, at=at)
            currency = active.settings.get("default_currency", "IDR")
            template_ref = active.settings.get("invoice_template_ref")
            resolved = self._resolve_identity(state.unit_ref, currency, at)
            total = sum(
                (Decimal(line["quantity"]) * Decimal(line["unit_price_amount"])
                 for line in state.lines),
                Decimal(0),
            )
            descriptor = resolved.to_redacted_descriptor()
            expected_hash = self._hash(state, active.configuration_version,
                                       descriptor, total)
            identity = resolved.identity
            return {
                "draft_id": state.draft_id,
                "unit_ref": state.unit_ref,
                "customer_ref": state.customer_ref,
                "currency": currency,
                "total_amount": self._format_money(total),
                "invoice_template_ref": template_ref,
                "logo_asset_ref": active.settings.get("logo_asset_ref"),
                "configuration_version": active.configuration_version,
                "legal_issuer_ref": identity.legal_issuer_ref,
                "tax_profile_ref": identity.tax_profile_ref,
                "invoice_series_ref": identity.invoice_series_ref,
                "receivable_ledger_ref": identity.receivable_ledger_ref,
                "destination_account_alias": descriptor["identity"]["destination_account_alias"],
                "preview_hash": expected_hash,
            }

    def audit_events(self, draft_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._get(draft_id)
            return list(self._audit.get(draft_id, []))

    def denied_events(self) -> list[dict[str, Any]]:
        """Workflow-level security audit of denied attempts (QA-08)."""
        with self._lock:
            return list(self._denied)
