"""Provider-neutral ERP port contracts (R-005, R-006, R-007, R-008, R-017).

This module defines the typed port that every ERP adapter (fixture, ERPNext)
must satisfy. It is deliberately free of provider SDKs and performs no I/O.
Deterministic offline implementations (fixture adapter) and live adapters
(ERPNext) are driven by the same contract suite in ``tests/contracts/erp_port``.

Design rules:
- Every reference is an opaque synthetic ref; the port never sees credentials,
  raw account numbers, or provider connection details.
- Amounts are canonical decimal strings + ISO-4217 currency (no float).
- Draft creation reserves nothing: no official numbers before verified post.
- Posting is outcome-explicit: POSTED / REJECTED (verified no mutation) /
  UNCERTAIN (requires reconciliation; blind retry is forbidden).
- Payments carry mandatory evidence references; reversals are compensating
  records, never destructive edits.
- Query results carry a ``scoped`` flag proving authorization scope was
  intersected server-side.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ProviderContractError(RuntimeError):
    """Base error for provider port violations (fail-closed)."""


class DocumentRejected(ProviderContractError):
    """The provider rejected a document before any mutation occurred."""


class UncertainOutcome(ProviderContractError):
    """The provider outcome is uncertain; a fenced reconciliation pass is
    required before any reissue. Never retry blindly."""


class ContractNotSupported(ProviderContractError):
    """The provider does not support the requested contract surface."""


# ---------------------------------------------------------------------------
# Command payloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    service_ref: str          # ITEM-* / SVC-* style opaque catalog ref
    description: str
    quantity: str             # canonical decimal string
    unit_price_amount: str    # canonical decimal string
    currency: str             # ISO-4217 uppercase


@dataclass(frozen=True, slots=True)
class DraftInvoiceCommand:
    customer_ref: str         # CUST-* opaque ref
    identity: Any             # src.contracts.financial_identity.FinancialIdentity
    lines: tuple[InvoiceLine, ...]
    issued_on: str            # ISO-8601 date (YYYY-MM-DD)
    due_on: str               # ISO-8601 date


@dataclass(frozen=True, slots=True)
class DraftPaymentCommand:
    invoice_ref: str          # provider document reference
    amount: str               # canonical decimal string
    currency: str
    evidence_ref: str         # EVI-* opaque evidence reference (mandatory)
    destination_account_alias: str  # ACC-* alias


@dataclass(frozen=True, slots=True)
class ReversalCommand:
    payment_ref: str
    reason: str


class PostingOutcome(StrEnum):
    POSTED = "POSTED"                    # provider assigned official reference
    REJECTED = "REJECTED"                # verified: zero provider mutation
    UNCERTAIN = "UNCERTAIN"              # unknown: reconciliation required


# ---------------------------------------------------------------------------
# Provider records (read-back)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InvoiceRecord:
    reference: str            # provider-assigned reference (draft or official)
    status: str               # DRAFT | POSTED | CANCELLED
    total_amount: str         # canonical decimal string
    currency: str
    open_amount: str          # canonical decimal string
    issued_on: str
    due_on: str
    payload: dict[str, Any]   # provider-normalized detail (opaque refs only)


@dataclass(frozen=True, slots=True)
class PaymentRecord:
    reference: str
    invoice_ref: str
    amount: str
    currency: str
    evidence_ref: str
    destination_account_alias: str
    reversal_of: str | None   # set on compensating reversal records


@dataclass(frozen=True, slots=True)
class QueryResult:
    kind: str                             # e.g. "INVOICE", "PAYMENT"
    references: tuple[str, ...]
    scoped: bool                          # True only when server-side scope applied
    total: int


@dataclass(frozen=True, slots=True)
class PostingResult:
    outcome: PostingOutcome
    reference: str | None     # official reference when POSTED, else None
    reason: str | None        # rejection/uncertainty reason (redacted)


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


@runtime_checkable
class ErpPort(Protocol):
    """Provider-neutral ERP port.

    Implementations MUST NOT use the network in the fixture variant and MUST
    honour the following invariants:

    1. ``create_draft_invoice`` never assigns or reserves an official number.
    2. ``post_invoice`` is idempotent on the caller's idempotency handling;
       posting the same draft twice must not create two posted documents.
    3. ``read_invoice`` and ``read_payment`` are authoritative read-backs.
    4. ``record_payment`` requires a non-empty evidence reference.
    5. ``reverse_payment`` creates a compensating record; it never deletes or
       mutates the original payment.
    6. ``query_invoices`` always intersects the requested filter with the
       caller's authorized scope and reports ``scoped=True``.
    """

    def create_draft_invoice(self, command: DraftInvoiceCommand) -> str:
        """Create a draft document; returns a draft reference. Reserves nothing."""
        ...

    def read_invoice(self, reference: str) -> InvoiceRecord:
        """Read back a document by reference."""
        ...

    def post_invoice(self, reference: str) -> PostingResult:
        """Post a draft document; assigns the official reference."""
        ...

    def record_payment(self, command: DraftPaymentCommand) -> str:
        """Record a payment with mandatory evidence; returns payment reference."""
        ...

    def read_payment(self, reference: str) -> PaymentRecord:
        """Read back a payment by reference."""
        ...

    def reverse_payment(self, command: ReversalCommand) -> str:
        """Create a compensating reversal; returns the reversal reference."""
        ...

    def cancel_invoice(self, reference: str) -> None:
        """Cancel a document through its supported cancellation path."""
        ...

    def query_invoices(
        self,
        *,
        status: str | None = None,
        operating_unit_ref: str | None = None,
        customer_ref: str | None = None,
    ) -> QueryResult:
        """Query documents with server-side scope intersection."""
        ...

    def ping(self) -> bool:
        """Liveness probe (fixture: always True unless failure injected)."""
        ...
