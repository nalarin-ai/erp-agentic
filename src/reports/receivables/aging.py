"""Receivables aging read model (FLOW-003, QUERY_RECEIVABLE).

R-013/R-017/R-019: balances are computed exclusively from provider read-backs
(invoice open_amount + accepted payment/reversal records) — never from chat
text or caller claims. Query filters are intersected with the server-derived
actor scope; client-supplied unit refs can only ever NARROW the authorized
scope, never expand it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
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
    ProviderContractError,
)


class WorkflowDenied(ValueError):
    """Safe denial; message never discloses protected data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("Request cannot be authorized.")


class WorkflowBlocked(ValueError):
    """Precise, safe blocker (missing data / state conflict)."""


@dataclass(frozen=True, slots=True)
class ReceivableEntry:
    """One receivable line: an open/partially-paid invoice balance."""

    invoice_ref: str
    unit_ref: str
    customer_ref: str
    currency: str
    total_amount: str
    open_amount: str
    receivable_status: str  # OPEN | PARTIALLY_PAID


@dataclass(frozen=True, slots=True)
class AgingResult:
    """Authorized aging query outcome."""

    entries: tuple[ReceivableEntry, ...]
    total_open_amount: str
    currency: str | None
    scoped: bool  # True only when the server-side scope intersection was applied


class ReceivablesAgingReport:
    """Authorized read model over the ERP port (QUERY_RECEIVABLE).

    Scope rule (INTEGRATION_CONTRACT): every query is intersected with the
    server-derived actor scope. An actor authorized for several units may
    narrow via ``unit_ref``; an actor may never reach a unit they hold no
    assignment for — cross-unit access is denied with no data leakage.
    """

    def __init__(self, *, adapter: Any) -> None:
        self._adapter = adapter
        self._denied: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def _log_denied(self, action: str, actor_ref: str, at: datetime, code: str) -> None:
        self._denied.append({
            "action": action,
            "actor_ref": actor_ref,
            "code": code,
            "at": at.astimezone(timezone.utc).isoformat(),
        })

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

    @staticmethod
    def _receivable_status(total: Decimal, open_amount: Decimal) -> str:
        if open_amount == 0:
            return "PAID"
        if open_amount < total:
            return "PARTIALLY_PAID"
        return "OPEN"

    def query_aging(
        self,
        *,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        channel_ref: str,
        unit_ref: str | None = None,
        customer_ref: str | None = None,
    ) -> AgingResult:
        """Aging query intersected with the actor's authorized unit scope.

        The authorized scope derives server-side from ``assignments`` — the
        caller's ``unit_ref`` can only narrow it. Results contain only
        OPEN / PARTIALLY_PAID invoices and the balances reconcile against
        the provider read-back by construction.
        """
        with self._lock:
            materialized = tuple(assignments)
            authorized_units = tuple(sorted({
                assignment.unit_ref
                for assignment in materialized
                if assignment.actor_ref == actor_ref and assignment.active
            }))
            if unit_ref is not None and unit_ref not in authorized_units:
                # Cross-unit access attempt: deny with zero disclosure.
                self._log_denied("query_aging", actor_ref, at, "PERMISSION_DENIED")
                raise WorkflowDenied("PERMISSION_DENIED")
            target_units = (unit_ref,) if unit_ref is not None else authorized_units
            if not target_units:
                self._log_denied("query_aging", actor_ref, at, "PERMISSION_DENIED")
                raise WorkflowDenied("PERMISSION_DENIED")
            try:
                self._authorize(
                    actor_ref=actor_ref, channel_ref=channel_ref,
                    action="QUERY_RECEIVABLE", binding=binding,
                    assignments=materialized,
                    selected_unit_ref=target_units[0], at=at,
                )
            except WorkflowDenied as exc:
                self._log_denied("query_aging", actor_ref, at, exc.code)
                raise

            entries: list[ReceivableEntry] = []
            total_open = Decimal(0)
            currency_seen: str | None = None
            for authorized_unit in target_units:
                try:
                    result = self._adapter.query_invoices(
                        status="POSTED",
                        operating_unit_ref=authorized_unit,
                        customer_ref=customer_ref,
                    )
                except (DocumentRejected, ProviderContractError) as exc:
                    raise WorkflowBlocked("provider rejected receivables query") from exc
                for reference in result.references:
                    try:
                        record = self._adapter.read_invoice(reference)
                    except (DocumentRejected, ProviderContractError) as exc:
                        raise WorkflowBlocked("provider rejected invoice read-back") from exc
                    open_amount = Decimal(record.open_amount)
                    if open_amount <= 0:
                        continue  # PAID invoices leave the aging surface
                    total = Decimal(record.total_amount)
                    entries.append(ReceivableEntry(
                        invoice_ref=record.reference,
                        unit_ref=authorized_unit,
                        customer_ref=record.payload.get("customer_ref", ""),
                        currency=record.currency,
                        total_amount=record.total_amount,
                        open_amount=record.open_amount,
                        receivable_status=self._receivable_status(total, open_amount),
                    ))
                    total_open += open_amount
                    currency_seen = record.currency
            return AgingResult(
                entries=tuple(entries),
                total_open_amount=format(total_open, "f"),
                currency=currency_seen,
                scoped=True,
            )

    def denied_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._denied)
