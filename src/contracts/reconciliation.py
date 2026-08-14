"""Reconciliation engine contract types (REC-001, R-007/R-008).

Provider-neutral classification of pending/uncertain mutation outcomes
against an ``ErpPort`` adapter. The engine never reissues a mutation
blindly: every pending intent is classified first, and only a verified
``ABSENT`` classification permits a safe retry.

All identifiers are synthetic opaque refs; no credentials or live data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReconciliationClass(StrEnum):
    PRESENT = "PRESENT"                # provider has the document/payment
    ABSENT = "ABSENT"                  # verified: provider has no such record
    AMBIGUOUS = "AMBIGUOUS"            # provider state contradicts itself
    UNAVAILABLE = "UNAVAILABLE"        # provider cannot answer authoritatively


class QueueItemStatus(StrEnum):
    PENDING = "PENDING"                # awaiting classification
    CLASSIFYING = "CLASSIFYING"        # fenced worker is classifying now
    SAFE_RETRYABLE = "SAFE_RETRYABLE"  # verified ABSENT; one retry is safe
    ESCALATED = "ESCALATED"            # AMBIGUOUS / repeated UNAVAILABLE
    RESOLVED = "RESOLVED"              # terminally classified + reconciled
    ABANDONED = "ABANDONED"            # operator dropped the intent (audited)


@dataclass(frozen=True, slots=True)
class QueueItem:
    item_id: str                       # REC-* opaque queue item id
    intent_key: str                    # idempotency key under recovery
    kind: str                          # "INVOICE_POST" | "PAYMENT_RECORD"
    draft_ref: str                     # draft handle or evidence ref anchor
    status: QueueItemStatus
    attempts: int
    fencing_token: int
    last_classification: ReconciliationClass | None
    resolution_ref: str | None         # official provider ref once PRESENT
    reason: str | None
    escalated_from: ReconciliationClass | None = None  # classification that escalated
    enqueued_at: datetime | None = None   # REC-QA-F-03: SLA/alert surface
    updated_at: datetime | None = None    # REC-QA-F-03: last transition instant


class ReconciliationError(RuntimeError):
    """Base error for reconciliation contract violations (fail-closed)."""


class ItemLocked(ReconciliationError):
    """Another fenced worker owns the item's classification lease."""


class InvalidTransition(ReconciliationError):
    """The requested queue-item transition violates the state machine."""
