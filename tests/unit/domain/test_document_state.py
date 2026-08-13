from dataclasses import FrozenInstanceError
import unittest

from src.domain.document_state import (
    DeliveryStatus,
    DocumentState,
    PostingStatus,
    ReceivableStatus,
    RecoveryStatus,
)


class DocumentStateTest(unittest.TestCase):
    def test_state_dimensions_are_explicit_orthogonal_and_immutable(self) -> None:
        state = DocumentState(
            posting=PostingStatus.POSTED,
            delivery=DeliveryStatus.FAILED_RETRYABLE,
            receivable=ReceivableStatus.PARTIALLY_PAID,
            recovery=RecoveryStatus.NONE,
        )

        self.assertEqual(
            state.to_canonical_payload(),
            {
                "delivery_status": "FAILED_RETRYABLE",
                "posting_status": "POSTED",
                "receivable_status": "PARTIALLY_PAID",
                "recovery_status": "NONE",
            },
        )
        with self.assertRaises(FrozenInstanceError):
            state.delivery = DeliveryStatus.SENT  # type: ignore[misc]

    def test_constructor_rejects_cross_dimension_and_untyped_statuses(self) -> None:
        valid = {
            "posting": PostingStatus.POSTED,
            "delivery": DeliveryStatus.SENT,
            "receivable": ReceivableStatus.OPEN,
            "recovery": RecoveryStatus.NONE,
        }
        invalid_values = {
            "posting": DeliveryStatus.SENT,
            "delivery": PostingStatus.POSTED,
            "receivable": "OPEN",
            "recovery": None,
        }

        for field, invalid in invalid_values.items():
            with self.subTest(field=field):
                with self.assertRaises(TypeError):
                    DocumentState(**{**valid, field: invalid})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
