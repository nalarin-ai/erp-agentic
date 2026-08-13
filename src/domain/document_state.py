from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PostingStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    REVIEWED = "REVIEWED"
    POSTING = "POSTING"
    POSTED = "POSTED"
    ABANDONED = "ABANDONED"
    CANCELLATION_PENDING = "CANCELLATION_PENDING"
    CANCELLED = "CANCELLED"
    AMENDMENT_REQUIRED = "AMENDMENT_REQUIRED"


class DeliveryStatus(StrEnum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class ReceivableStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class RecoveryStatus(StrEnum):
    NONE = "NONE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    RECONCILING = "RECONCILING"
    RESOLVED_PRESENT = "RESOLVED_PRESENT"
    RESOLVED_ABSENT = "RESOLVED_ABSENT"
    MANUAL_ESCALATION = "MANUAL_ESCALATION"


@dataclass(frozen=True, slots=True)
class DocumentState:
    posting: PostingStatus
    delivery: DeliveryStatus
    receivable: ReceivableStatus
    recovery: RecoveryStatus

    def __post_init__(self) -> None:
        expected_types = {
            "posting": PostingStatus,
            "delivery": DeliveryStatus,
            "receivable": ReceivableStatus,
            "recovery": RecoveryStatus,
        }
        for name, expected_type in expected_types.items():
            if type(getattr(self, name)) is not expected_type:
                raise TypeError(f"{name} must be {expected_type.__name__}")

    def to_canonical_payload(self) -> dict[str, str]:
        return {
            "delivery_status": self.delivery.value,
            "posting_status": self.posting.value,
            "receivable_status": self.receivable.value,
            "recovery_status": self.recovery.value,
        }
