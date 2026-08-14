"""Owner financial roll-up (RPT-001): authorized multi-unit aggregation
WITHOUT ledger merge.

Requirements:
- R-001: owner role-scoped oversight across multiple business units.
- R-011: units are separate commercial entities; no cross-unit leakage by
  default (not via filters, counts, export, or error paths).
- R-021: effective-dated multi-unit assignments; deny unassigned / inactive /
  stale / cross-unit. Each unit's contribution is individually authorized.

Design choices (recorded per task):
- Authorization action: QUERY_RECEIVABLE. ``src/authz/access.py`` is outside
  the owned paths of RPT-001, so no new registered action can be added. The
  OWNER role already holds QUERY_RECEIVABLE; the roll-up is a receivables /
  financial read, so this is the semantically correct authorization action.
  Each per-unit read is authorized separately through ``authorize(...)`` —
  the roll-up never bypasses per-unit authorization.
- Aggregation: per-unit subtotals + an owner-level total. Ledger records are
  NEVER merged across units: each unit's subtotal is computed exclusively
  from an authorized read scoped to that unit.
- Caching: NONE. The service holds no per-unit snapshot cache; every call
  reads the provider. Assignment revocation / expiry takes effect on the
  next call with no invalidation pass required.
- Multi-currency: per-currency subtotals within each unit; the owner-level
  headline total is only reported when exactly one currency is present
  across all contributing units. Currencies are never silently mixed.
- As-of: every per-unit subtotal carries an as-of timestamp (ISO-8601 UTC)
  captured at the moment of its authorized read; the roll-up carries its
  own as-of.
- Fail-closed: zero assignments → deny; unassigned unit contributes NOTHING
  (not even an error that reveals existence); denial messages are generic
  and audited via an in-memory denial log.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import threading
from typing import Any, Iterable

from src.authz.access import (
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


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CurrencySubtotal:
    """Per-currency breakdown within a single unit."""

    currency: str
    open_amount_total: str
    open_invoice_count: int


@dataclass(frozen=True, slots=True)
class UnitSubtotal:
    """Per-unit contribution to the roll-up (authorized scope only)."""

    unit_ref: str
    open_amount_total: str          # canonical decimal string (per currency_seen)
    currency: str | None            # None when unit has zero open invoices
    open_invoice_count: int
    invoice_refs: tuple[str, ...]   # provider refs (scoped to this unit only)
    per_currency: tuple[CurrencySubtotal, ...]
    as_of: str                      # ISO-8601 UTC timestamp of the authorized read


@dataclass(frozen=True, slots=True)
class OwnerRollupResult:
    """Owner roll-up outcome: per-unit subtotals + reconciled owner total."""

    per_unit: tuple[UnitSubtotal, ...]
    owner_open_amount_total: str | None  # None when currencies are mixed
    currency: str | None                 # None when zero or multiple currencies
    as_of: str                           # ISO-8601 UTC of the roll-up
    scoped: bool                         # always True (server-derived scope only)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OwnerRollupReport:
    """Authorized multi-unit owner roll-up over the ERP port.

    Every unit contribution is computed via an individually-authorized
    ``QUERY_RECEIVABLE`` read scoped to that unit. A unit the owner is not
    actively assigned to contributes NOTHING (no rows, no count, no error
    that would reveal existence).
    """

    AUTHORIZATION_ACTION = "QUERY_RECEIVABLE"
    REQUIRED_ROLE = "OWNER"

    def __init__(self, *, adapter: Any) -> None:
        self._adapter = adapter
        self._denied: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _is_valid_at(at: Any) -> bool:
        """``at`` must be a timezone-aware datetime (fail-closed check)."""
        return (
            type(at) is datetime
            and at.tzinfo is not None
            and at.tzinfo.utcoffset(at) is not None
        )

    def _log_denied(self, action: str, actor_ref: str, at: datetime, code: str) -> None:
        at_iso = (
            at.astimezone(timezone.utc).isoformat()
            if self._is_valid_at(at)
            else "INVALID_AT"
        )
        self._denied.append({
            "action": action,
            "actor_ref": actor_ref,
            "code": code,
            "at": at_iso,
        })

    @staticmethod
    def _active_owner_units(
        actor_ref: str,
        at: datetime,
        assignments: tuple[ActorUnitAssignment, ...],
    ) -> tuple[str, ...]:
        """Server-derived active OWNER-role unit scope at ``at``.

        Mirrors ``_assignment_is_effective`` from src/authz/access.py without
        depending on private helpers.
        """
        units: set[str] = set()
        for assignment in assignments:
            if assignment.actor_ref != actor_ref or not assignment.active:
                continue
            if OwnerRollupReport.REQUIRED_ROLE not in assignment.roles:
                continue
            if assignment.effective_from is not None:
                if at < assignment.effective_from.astimezone(timezone.utc):
                    continue
            if assignment.effective_until is not None:
                if at >= assignment.effective_until.astimezone(timezone.utc):
                    continue
            units.add(assignment.unit_ref)
        return tuple(sorted(units))

    def _authorize_unit(
        self,
        *,
        actor_ref: str,
        channel_ref: str,
        binding: IdentityBinding | None,
        assignments: tuple[ActorUnitAssignment, ...],
        unit_ref: str,
        at: datetime,
    ) -> None:
        """Authorize one unit's contribution; raises WorkflowDenied on failure."""
        try:
            request = AuthorizationRequest(
                actor_ref=actor_ref,
                channel_ref=channel_ref,
                action=self.AUTHORIZATION_ACTION,
                selected_unit_ref=unit_ref,
                requested_at=at,
            )
            decision = authorize(request=request, binding=binding, assignments=assignments)
        except (TypeError, ValueError):
            raise WorkflowDenied("INVALID_INPUT") from None
        if not decision.allowed:
            raise WorkflowDenied(decision.code)

    def _read_unit_subtotal(
        self,
        *,
        unit_ref: str,
        customer_ref: str | None,
        at: datetime,
    ) -> UnitSubtotal:
        """Authorized per-unit read; computes subtotal from provider read-backs."""
        as_of = at.astimezone(timezone.utc).isoformat()
        try:
            result = self._adapter.query_invoices(
                status="POSTED",
                operating_unit_ref=unit_ref,
                customer_ref=customer_ref,
            )
        except (DocumentRejected, ProviderContractError) as exc:
            raise WorkflowBlocked("provider rejected receivables query") from exc

        invoice_refs: list[str] = []
        per_currency_open: dict[str, Decimal] = {}
        per_currency_count: dict[str, int] = {}
        for reference in result.references:
            try:
                record = self._adapter.read_invoice(reference)
            except (DocumentRejected, ProviderContractError) as exc:
                raise WorkflowBlocked("provider rejected invoice read-back") from exc
            open_amount = Decimal(record.open_amount)
            if open_amount <= 0:
                continue
            invoice_refs.append(record.reference)
            per_currency_open[record.currency] = (
                per_currency_open.get(record.currency, Decimal(0)) + open_amount
            )
            per_currency_count[record.currency] = (
                per_currency_count.get(record.currency, 0) + 1
            )

        per_currency = tuple(
            CurrencySubtotal(
                currency=currency,
                open_amount_total=format(per_currency_open[currency], "f"),
                open_invoice_count=per_currency_count[currency],
            )
            for currency in sorted(per_currency_open)
        )
        total_open = sum(per_currency_open.values(), Decimal(0))
        currency_seen = (
            per_currency[0].currency if len(per_currency) == 1 else None
        )
        return UnitSubtotal(
            unit_ref=unit_ref,
            open_amount_total=format(total_open, "f"),
            currency=currency_seen,
            open_invoice_count=len(invoice_refs),
            invoice_refs=tuple(invoice_refs),
            per_currency=per_currency,
            as_of=as_of,
        )

    # -- public API ----------------------------------------------------------

    def query_rollup(
        self,
        *,
        actor_ref: str,
        at: datetime,
        binding: IdentityBinding | None,
        assignments: Iterable[ActorUnitAssignment],
        channel_ref: str,
        customer_ref: str | None = None,
    ) -> OwnerRollupResult:
        """Compute the authorized owner roll-up.

        The roll-up spans every unit the owner is ACTIVELY assigned to at
        ``at`` (fail-closed on zero). Each unit's contribution comes from an
        individually-authorized read; unassigned units contribute NOTHING.
        """
        with self._lock:
            if not self._is_valid_at(at):
                self._log_denied("query_rollup", actor_ref, at, "INVALID_INPUT")
                raise WorkflowDenied("INVALID_INPUT")
            try:
                materialized = tuple(assignments)
            except Exception:
                self._log_denied("query_rollup", actor_ref, at, "INVALID_INPUT")
                raise WorkflowDenied("INVALID_INPUT") from None
            if any(type(a) is not ActorUnitAssignment for a in materialized):
                self._log_denied("query_rollup", actor_ref, at, "INVALID_INPUT")
                raise WorkflowDenied("INVALID_INPUT")

            # Identity pre-check: fail fast with a logged denial (mirrors the
            # access layer's IDENTITY_UNVERIFIED semantics).
            if (
                binding is None
                or not binding.active
                or binding.actor_ref != actor_ref
                or binding.channel_ref != channel_ref
            ):
                self._log_denied("query_rollup", actor_ref, at, "IDENTITY_UNVERIFIED")
                raise WorkflowDenied("IDENTITY_UNVERIFIED")

            # Server-derived active OWNER scope at the requested time.
            authorized_units = self._active_owner_units(actor_ref, at, materialized)
            if not authorized_units:
                self._log_denied("query_rollup", actor_ref, at, "PERMISSION_DENIED")
                raise WorkflowDenied("PERMISSION_DENIED")

            # Authorize and read each unit individually. Any authorization
            # failure denies the whole roll-up (fail-closed); we never
            # partially disclose.
            per_unit: list[UnitSubtotal] = []
            for unit_ref in authorized_units:
                try:
                    self._authorize_unit(
                        actor_ref=actor_ref,
                        channel_ref=channel_ref,
                        binding=binding,
                        assignments=materialized,
                        unit_ref=unit_ref,
                        at=at,
                    )
                except WorkflowDenied as exc:
                    self._log_denied("query_rollup", actor_ref, at, exc.code)
                    raise
                per_unit.append(
                    self._read_unit_subtotal(
                        unit_ref=unit_ref, customer_ref=customer_ref, at=at
                    )
                )

            # Owner-level reconciliation: only when one currency across all units.
            currencies = {
                currency.currency
                for unit in per_unit
                for currency in unit.per_currency
            }
            if len(currencies) == 1:
                total = sum(
                    (Decimal(u.open_amount_total) for u in per_unit), Decimal(0)
                )
                owner_total: str | None = format(total, "f")
                owner_currency: str | None = next(iter(currencies))
            elif not currencies:
                owner_total = "0"
                owner_currency = None
            else:
                owner_total = None
                owner_currency = None

            return OwnerRollupResult(
                per_unit=tuple(per_unit),
                owner_open_amount_total=owner_total,
                currency=owner_currency,
                as_of=at.astimezone(timezone.utc).isoformat(),
                scoped=True,
            )

    def denied_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._denied)
