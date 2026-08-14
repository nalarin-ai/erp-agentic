"""CRM port contracts — unit-private CRM (CRM-001).

R-002/R-003/R-011/R-015/R-021: operating brands share one office but run
commercially competing pipelines. Sales leads, quotations, targets, and
customer visibility MUST NOT leak across units by default. Every CRM action
executes under exactly one active unit context; unassigned, inactive, stale,
or cross-unit access is denied fail-closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class CrmError(RuntimeError):
    """Base error for CRM port violations (fail-closed)."""


class CrmDenied(CrmError):
    """Authorization or scope check failed; nothing was read or mutated."""


class CrmNotFound(CrmError):
    """The referenced object does not exist inside the caller's scope."""


class CrmConflict(CrmError):
    """A uniqueness/ownership conflict prevented the mutation."""


@dataclass(frozen=True, slots=True)
class CrmIdentity:
    """Active unit context for one CRM action: exactly one unit."""

    actor_ref: str            # USR-* opaque actor ref
    operating_unit_ref: str   # UNIT-* — exactly one active unit context


@dataclass(frozen=True, slots=True)
class LeadCommand:
    identity: CrmIdentity
    display_name: str
    contact_channel: str      # WHATSAPP/TELEGRAM/EMAIL/PHONE (opaque)
    contact_handle: str       # opaque handle/number (synthetic)
    source: str               # e.g. ADS-*, REFERRAL-*, ORGANIC


@dataclass(frozen=True, slots=True)
class LeadRecord:
    reference: str
    operating_unit_ref: str
    display_name: str
    contact_channel: str
    contact_handle: str
    source: str
    status: str               # NEW | QUALIFIED | CONVERTED | ARCHIVED
    owner_actor_ref: str      # controlling sales actor
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class QuotationCommand:
    identity: CrmIdentity
    lead_ref: str
    customer_ref: str
    total_amount: str         # canonical decimal string
    currency: str             # ISO-4217 uppercase
    valid_until: str          # ISO-8601 date


@dataclass(frozen=True, slots=True)
class QuotationRecord:
    reference: str
    operating_unit_ref: str
    lead_ref: str
    customer_ref: str
    total_amount: str
    currency: str
    status: str               # DRAFT | SENT | ACCEPTED | DECLINED | EXPIRED
    valid_until: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CrmQuery:
    identity: CrmIdentity
    text: str | None = None
    status: str | None = None
    limit: int = 50
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CrmQueryPage:
    kind: str                 # LEAD | QUOTATION | CUSTOMER
    references: tuple[str, ...]
    scoped: bool              # True only when unit scope was intersected
    total: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ExportRequest:
    identity: CrmIdentity
    kind: str                 # LEAD | QUOTATION | CUSTOMER
    evidence_ref: str         # EVI-* audit token for the export
    max_rows: int = 1000


@dataclass(frozen=True, slots=True)
class ExportResult:
    evidence_ref: str
    operating_unit_ref: str
    row_count: int
    rows: tuple[dict[str, str], ...]  # sanitized, scope-bounded


class ConflictVerdict(StrEnum):
    CLEAR = "CLEAR"
    CONFLICT_IN_SCOPE = "CONFLICT_IN_SCOPE"
    # Deliberately NO "conflict in another unit" verdict — that would leak
    # cross-unit existence.


@runtime_checkable
class CrmPort(Protocol):
    """Provider-neutral unit-private CRM port.

    Invariants:
    1. Every method runs under exactly one active unit context; unassigned,
       stale, or cross-unit contexts are denied fail-closed (CrmDenied)
       before any provider call.
    2. Reads are fail-closed on scope: a reference owned by another unit
       raises CrmNotFound (existence is not leaked).
    3. Search/query/export always intersect the caller's unit scope;
       cursors are opaque and scope-bound.
    4. Conflict checks return only CLEAR or CONFLICT_IN_SCOPE — never
       cross-unit existence.
    """

    def create_lead(self, command: LeadCommand) -> str: ...
    def read_lead(self, identity: CrmIdentity, reference: str) -> LeadRecord: ...
    def transfer_lead(
        self,
        identity: CrmIdentity,
        reference: str,
        *,
        new_owner_actor_ref: str,
        new_unit_ref: str | None = None,
    ) -> None: ...
    def archive_lead(self, identity: CrmIdentity, reference: str) -> None: ...
    def create_quotation(self, command: QuotationCommand) -> str: ...
    def read_quotation(
        self, identity: CrmIdentity, reference: str
    ) -> QuotationRecord: ...
    def search_leads(self, query: CrmQuery) -> CrmQueryPage: ...
    def query_quotations(self, query: CrmQuery) -> CrmQueryPage: ...
    def export(self, request: ExportRequest) -> ExportResult: ...
    def check_customer_conflict(
        self, identity: CrmIdentity, contact_channel: str, contact_handle: str
    ) -> ConflictVerdict: ...
