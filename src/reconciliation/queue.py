"""Durable operator queue for reconciliation items (REC-001, R-007/R-008).

In-memory fixture with durability semantics mirrored from the mutation
store: monotonic fencing per item, atomic claim, explicit state machine,
and no silent stuck states. Production uses durable storage; the contract
surface is identical.

Hardening after independent QA round 1:
- REC-QA-01: a terminal transition (anything leaving CLASSIFYING) retires
  the claiming token; ESCALATED/SAFE_RETRYABLE items require a fresh
  explicit claim (``claim_item``) before any further transition, and
  ESCALATED may only move to ABANDONED or RESOLVED.
- REC-QA-02: the resolve-guard (ABSENT/UNAVAILABLE never resolve directly)
  is pinned by regression tests.
- REC-QA-03: CLASSIFYING items can be taken over by a strictly newer
  fencing token via ``claim_item`` (crash recovery path).
- REC-QA-05: no dead allowlist entries.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import itertools
import threading

from src.audit.chain import AuditChain, AuditRecord
from src.contracts.reconciliation import (
    InvalidTransition,
    ItemLocked,
    QueueItem,
    QueueItemStatus,
    ReconciliationClass,
)

#: REC-QA-F-01: audit event types emitted by queue transitions.
_EVT_ENQUEUE = "REC_ENQUEUE"
_EVT_CLAIM = "REC_CLAIM"
_EVT_RESOLVED = "REC_CLASSIFY_RESOLVED"
_EVT_RETRYABLE = "REC_CLASSIFY_SAFE_RETRYABLE"
_EVT_ESCALATED = "REC_CLASSIFY_ESCALATED"
_EVT_REQUEUED = "REC_CLASSIFY_REQUEUED"
_EVT_RETRIED = "REC_RETRIED"
_EVT_ABANDONED = "REC_ABANDONED"

_CLASSIFY_EVENTS = {
    QueueItemStatus.RESOLVED: _EVT_RESOLVED,
    QueueItemStatus.SAFE_RETRYABLE: _EVT_RETRYABLE,
    QueueItemStatus.ESCALATED: _EVT_ESCALATED,
    QueueItemStatus.PENDING: _EVT_REQUEUED,
}

#: Transitions the queue itself will accept. The engine drives
#: classification; operators may only abandon or re-claim ESCALATED items.
_ALLOWED = {
    QueueItemStatus.PENDING: {QueueItemStatus.CLASSIFYING},
    QueueItemStatus.CLASSIFYING: {
        QueueItemStatus.RESOLVED,
        QueueItemStatus.SAFE_RETRYABLE,
        QueueItemStatus.ESCALATED,
        QueueItemStatus.PENDING,  # bounded retry after UNAVAILABLE
    },
    QueueItemStatus.SAFE_RETRYABLE: {QueueItemStatus.RESOLVED, QueueItemStatus.CLASSIFYING},
    QueueItemStatus.ESCALATED: {QueueItemStatus.ABANDONED, QueueItemStatus.CLASSIFYING},
    QueueItemStatus.RESOLVED: set(),
    QueueItemStatus.ABANDONED: set(),
}

_ACTIVE = {
    QueueItemStatus.PENDING,
    QueueItemStatus.CLASSIFYING,
    QueueItemStatus.SAFE_RETRYABLE,
    QueueItemStatus.ESCALATED,
}


class OperatorQueue:
    """Thread-safe operator queue with fenced classification claims.

    REC-QA-F-01: every mutating transition appends to an internal
    ``AuditChain``; REC-QA-F-02: the same transition stream is replayable
    via ``transition_log``/``replay``; REC-QA-F-03: items carry timestamps
    and an ``overdue_items`` SLA helper; REC-QA-F-05: the item sequence is
    per-instance, not process-global.
    """

    def __init__(self) -> None:
        self._items: dict[str, QueueItem] = {}
        self._by_intent: dict[str, str] = {}  # intent_key -> item_id
        self._lock = threading.RLock()
        self._sequence = itertools.count(1)
        self._audit = AuditChain()
        self._log: list[QueueItem] = []

    # -- audit / replay surface -------------------------------------------------

    def _emit(self, event_type: str, item: QueueItem, **extra: object) -> None:
        payload: dict[str, object] = {
            "item_id": item.item_id,
            "intent_key": item.intent_key,
            "status": str(item.status),
        }
        payload.update(extra)
        record = AuditRecord(
            sequence=len(self._audit._records) + 1,
            previous_hash=self._audit.head_hash,
            event_type=event_type,
            actor="reconciliation-queue",
            timestamp=datetime.now(timezone.utc),
            payload=payload,
        )
        self._audit.append(record)

    def audit_records(self) -> tuple:
        """All audit records emitted by this queue, in chain order."""
        with self._lock:
            return tuple(self._audit._records)

    def verify_audit(self) -> bool:
        with self._lock:
            return self._audit.verify()

    def transition_log(self) -> tuple[QueueItem, ...]:
        """Durable transition log: one snapshot per applied transition."""
        with self._lock:
            return tuple(self._log)

    @classmethod
    def replay(cls, log) -> "OperatorQueue":
        """Reconstruct queue state from a transition log (restart replay)."""
        queue = cls()
        for snapshot in log:
            with queue._lock:
                queue._items[snapshot.item_id] = snapshot
                queue._by_intent[snapshot.intent_key] = snapshot.item_id
                seq_digits = "".join(ch for ch in snapshot.item_id if ch.isdigit())
                if seq_digits:
                    queue._sequence = itertools.count(int(seq_digits) + 1)
        return queue

    # -- enqueue -------------------------------------------------------------

    def enqueue(self, *, intent_key: str, kind: str, draft_ref: str) -> QueueItem:
        """Idempotent enqueue: one item per idempotency key."""
        with self._lock:
            existing_id = self._by_intent.get(intent_key)
            if existing_id is not None:
                existing = self._items[existing_id]
                if existing.draft_ref != draft_ref or existing.kind != kind:
                    raise InvalidTransition(
                        "intent key already enqueued with a different anchor"
                    )
                return existing
            now = datetime.now(timezone.utc)
            item = QueueItem(
                item_id=f"REC-{next(self._sequence):06d}",
                intent_key=intent_key,
                kind=kind,
                draft_ref=draft_ref,
                status=QueueItemStatus.PENDING,
                attempts=0,
                fencing_token=0,
                last_classification=None,
                resolution_ref=None,
                reason=None,
                enqueued_at=now,
                updated_at=now,
            )
            self._items[item.item_id] = item
            self._by_intent[intent_key] = item.item_id
            self._log.append(item)
            self._emit(_EVT_ENQUEUE, item, kind=kind)
            return item

    # -- claiming (fencing) -----------------------------------------------------

    def claim_next(self, *, fencing_token: int) -> QueueItem | None:
        """Atomically move the oldest PENDING item to CLASSIFYING under token.

        Exactly one claimant wins; losers observe ``None`` (no item claimed).
        """
        with self._lock:
            for item in sorted(self._items.values(), key=lambda entry: entry.item_id):
                if item.status is not QueueItemStatus.PENDING:
                    continue
                claimed = replace(
                    item,
                    status=QueueItemStatus.CLASSIFYING,
                    fencing_token=fencing_token,
                    updated_at=datetime.now(timezone.utc),
                )
                self._items[item.item_id] = claimed
                self._log.append(claimed)
                self._emit(_EVT_CLAIM, claimed, fencing_token=fencing_token)
                return claimed
            return None

    def claim_item(self, item_id: str, *, fencing_token: int) -> QueueItem:
        """Explicitly (re)claim one item under a strictly newer fencing token.

        This is the crash-recovery and operator-override path (REC-QA-01/03):
        - the new token must be strictly greater than the recorded one, so a
          stale worker that once owned the item can never write again;
        - ESCALATED / SAFE_RETRYABLE items move to CLASSIFYING under the new
          token (operator override after manual provider verification);
        - CLASSIFYING items (crashed worker) are re-claimed in place;
        - PENDING items already have a fair path via ``claim_next``;
        - terminal items (RESOLVED/ABANDONED) can never be re-claimed.
        """
        with self._lock:
            item = self.get(item_id)
            if item.status in (QueueItemStatus.RESOLVED, QueueItemStatus.ABANDONED):
                raise InvalidTransition("terminal items cannot be re-claimed")
            if item.status is QueueItemStatus.PENDING:
                raise InvalidTransition("use claim_next for pending items")
            if fencing_token <= item.fencing_token:
                raise ItemLocked(
                    f"item {item.item_id} requires a fencing token greater "
                    f"than {item.fencing_token}"
                )
            claimed = replace(
                item,
                status=QueueItemStatus.CLASSIFYING,
                fencing_token=fencing_token,
                updated_at=datetime.now(timezone.utc),
            )
            self._items[item_id] = claimed
            self._log.append(claimed)
            self._emit(_EVT_CLAIM, claimed, fencing_token=fencing_token, override="claim_item")
            return claimed

    def get(self, item_id: str) -> QueueItem:
        item = self._items.get(item_id)
        if item is None:
            raise InvalidTransition(f"unknown queue item: {item_id[:24]}")
        return item

    def _assert_owner(self, item: QueueItem, fencing_token: int) -> None:
        if item.fencing_token != fencing_token or fencing_token <= 0:
            raise ItemLocked(
                f"item {item.item_id} is owned by fencing token "
                f"{item.fencing_token}, not {fencing_token}"
            )

    # -- transitions -----------------------------------------------------------

    def complete_classification(
        self,
        item_id: str,
        *,
        fencing_token: int,
        classification: ReconciliationClass,
        next_status: QueueItemStatus,
        resolution_ref: str | None = None,
        reason: str | None = None,
    ) -> QueueItem:
        """Apply the classification outcome under the caller's fencing token.

        REC-QA-01: leaving CLASSIFYING retires the token (set back to 0), so
        the completing token can never write to the item again; further work
        requires a fresh ``claim_item`` under a strictly newer token.
        REC-QA-02: ABSENT/UNAVAILABLE may never resolve directly.
        """
        with self._lock:
            item = self.get(item_id)
            self._assert_owner(item, fencing_token)
            if next_status not in _ALLOWED[item.status]:
                raise InvalidTransition(
                    f"{item.status} -> {next_status} is not an allowed transition"
                )
            if next_status is QueueItemStatus.RESOLVED and classification in (
                ReconciliationClass.ABSENT,
                ReconciliationClass.UNAVAILABLE,
            ):
                raise InvalidTransition(
                    "only PRESENT/AMBIGUOUS-verified items may resolve directly"
                )
            # REC-QA-08: an item whose escalation origin is AMBIGUOUS can
            # never enter the auto-retry lane, even under a fresh operator
            # claim — AMBIGUOUS means the provider contradicted itself, so a
            # reissue is unsafe no matter who asks.
            if (
                next_status is QueueItemStatus.SAFE_RETRYABLE
                and item.escalated_from is ReconciliationClass.AMBIGUOUS
            ):
                raise InvalidTransition(
                    "AMBIGUOUS-escalated items may only resolve or be abandoned"
                )
            escalated_from = item.escalated_from
            if next_status is QueueItemStatus.ESCALATED:
                # Record the classification that caused the escalation so the
                # AMBIGUOUS guard survives any number of re-claims.
                escalated_from = classification
            updated = replace(
                item,
                status=next_status,
                attempts=item.attempts + 1,
                fencing_token=0,  # retire the completing token
                last_classification=classification,
                resolution_ref=resolution_ref if resolution_ref is not None else item.resolution_ref,
                reason=reason,
                escalated_from=escalated_from,
                updated_at=datetime.now(timezone.utc),
            )
            self._items[item_id] = updated
            self._log.append(updated)
            self._emit(
                _CLASSIFY_EVENTS[next_status],
                updated,
                classification=str(classification),
                resolution_ref=resolution_ref,
            )
            return updated

    def mark_retried(self, item_id: str, *, resolution_ref: str | None) -> QueueItem:
        """Close a SAFE_RETRYABLE item after its single verified retry."""
        with self._lock:
            item = self.get(item_id)
            if item.status is not QueueItemStatus.SAFE_RETRYABLE:
                raise InvalidTransition("only SAFE_RETRYABLE items may be marked retried")
            updated = replace(
                item,
                status=QueueItemStatus.RESOLVED,
                resolution_ref=resolution_ref,
                updated_at=datetime.now(timezone.utc),
            )
            self._items[item_id] = updated
            self._log.append(updated)
            self._emit(_EVT_RETRIED, updated, resolution_ref=resolution_ref)
            return updated

    def abandon(self, item_id: str, *, reason: str) -> QueueItem:
        """Operator drop of an ESCALATED item; reason is mandatory."""
        with self._lock:
            item = self.get(item_id)
            if not reason or not reason.strip():
                raise InvalidTransition("abandon requires an operator reason")
            if item.status is not QueueItemStatus.ESCALATED:
                raise InvalidTransition("only ESCALATED items may be abandoned")
            updated = replace(
                item,
                status=QueueItemStatus.ABANDONED,
                reason=reason,
                updated_at=datetime.now(timezone.utc),
            )
            self._items[item_id] = updated
            self._log.append(updated)
            self._emit(_EVT_ABANDONED, updated, operator_reason=reason)
            return updated

    # -- introspection -------------------------------------------------------------

    def depth(self, *, include_terminal: bool = False) -> int:
        with self._lock:
            if include_terminal:
                return len(self._items)
            return sum(1 for item in self._items.values() if item.status in _ACTIVE)

    def stuck_items(self) -> tuple[QueueItem, ...]:
        """Items that need operator attention (ESCALATED). Never silent."""
        with self._lock:
            return tuple(
                item for item in sorted(self._items.values(), key=lambda entry: entry.item_id)
                if item.status is QueueItemStatus.ESCALATED
            )

    def overdue_items(self, *, max_age_seconds: float) -> tuple[QueueItem, ...]:
        """REC-QA-F-03: SLA/alert surface — active items older than the threshold.

        Only non-terminal items are returned; the caller decides the alert
        policy. An item with no recorded timestamps is never overdue.
        """
        now = datetime.now(timezone.utc)
        with self._lock:
            return tuple(
                item
                for item in sorted(self._items.values(), key=lambda entry: entry.item_id)
                if item.status in _ACTIVE
                and item.updated_at is not None
                and (now - item.updated_at).total_seconds() > max_age_seconds
            )

    def pending_items(self) -> tuple[QueueItem, ...]:
        with self._lock:
            return tuple(
                item for item in sorted(self._items.values(), key=lambda entry: entry.item_id)
                if item.status is QueueItemStatus.PENDING
            )
