"""MVP-AC-08: payment evidence + correct AR ledger (FLOW-003).

Criteria (TRACEABILITY_MATRIX.md section D): chat-only / overpay / duplicate
payments are denied; valid evidence reduces outstanding AR on the correct
unit ledger (Heavy Equipment posts to the R-015 shared ACC-CONTRACTOR alias).

Scenarios:
1. Valid evidence payment reduces AR on the correct unit ledger (Heavy
   Equipment → ACC-CONTRACTOR shared alias; read-back via the AR aging
   report + provider invoice state).
2. Chat-only / evidence-less payment is denied (WorkflowBlocked, audited
   INVALID_INPUT).
3. Overpayment is blocked (OVERPAYMENT) before any provider mutation.
4. Duplicate evidence_ref never double-applies.
5. Cross-unit payment (actor without an assignment on the invoice's unit)
   is denied PERMISSION_DENIED.
6. Reversal is a compensating record: AR reopens, audit trail records it.
"""
from __future__ import annotations

import unittest

from src.workflows.payments.workflow import (
    WorkflowBlocked as PaymentBlocked,
    WorkflowDenied as PaymentDenied,
)

from tests.e2e.pilot._harness import (
    PilotHarness,
    UNIT_BANYUMEDIA,
    UNIT_CONTRACTOR,
    UNIT_HEAVY_EQUIPMENT,
)


def _provider_payment_count(h: PilotHarness) -> int:
    return len(h.erp_adapter._payments)  # noqa: SLF001 - test inspection


class TestAc08PaymentsEvidenceAndAr(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PilotHarness.build()

    def _post_heavy_equipment_invoice(self, customer_ref: str) -> str:
        """Heavy Equipment invoice: policy binds the shared Contractor
        destination account alias (R-015)."""
        _, posted = self.harness.post_invoice_for_unit(
            self.harness.heavy_equipment_requester,
            self.harness.heavy_equipment_poster,
            UNIT_HEAVY_EQUIPMENT, customer_ref=customer_ref,
        )
        assert posted.official_ref is not None
        return posted.official_ref

    # -- 1. valid evidence reduces AR on the correct ledger -----------------------

    def test_valid_payment_reduces_ar_on_shared_contractor_alias(self) -> None:
        h = self.harness
        official = self._post_heavy_equipment_invoice("CUST-HEQ-PAY-1")
        # Pre-payment: the full amount is open on the HEQ unit surface.
        self.assertEqual(
            h.receivables_open_amount(h.heavy_equipment_ar_reviewer,
                                      UNIT_HEAVY_EQUIPMENT),
            "1500000",
        )
        result = h.record_payment(
            h.heavy_equipment_requester, official,
            amount="500000.00", evidence_ref="EVI-HEQ-PAY-1",
            destination_account_alias="ACC-CONTRACTOR",
        )
        self.assertEqual(result.outcome, "RECORDED")
        self.assertEqual(result.receivable_status, "PARTIALLY_PAID")
        # AR aging read-back (authoritative provider state) now shows the
        # reduced open amount on the HEAVY EQUIPMENT unit ledger.
        self.assertEqual(
            h.receivables_open_amount(h.heavy_equipment_ar_reviewer,
                                      UNIT_HEAVY_EQUIPMENT),
            "1000000.00",
        )
        # The provider payment record binds the shared Contractor alias
        # (R-015) and the invoice stays attributed to UNIT-HEAVYEQUIPMENT.
        record = h.erp_adapter.read_payment(result.payment_ref)  # type: ignore[arg-type]
        self.assertEqual(record.destination_account_alias, "ACC-CONTRACTOR")
        invoice = h.erp_adapter.read_invoice(official)
        self.assertEqual(
            invoice.payload["identity"]["operating_unit_ref"],
            UNIT_HEAVY_EQUIPMENT,
        )
        self.assertEqual(invoice.open_amount, "1000000.00")
        # Payment is audited on the invoice anchor with the receivable status.
        events = h.payment_workflow.audit_events(official)
        recorded = [e for e in events if e["action"] == "payment_recorded"]
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["receivable_status"], "PARTIALLY_PAID")

    # -- 2. chat-only / no evidence -------------------------------------------------

    def test_chat_only_payment_without_evidence_denied(self) -> None:
        h = self.harness
        official = self._post_heavy_equipment_invoice("CUST-HEQ-PAY-2")
        before = _provider_payment_count(h)
        for bad_evidence in ("", "CHAT-HE-SAID-PAID", "not-a-ref"):
            with self.assertRaises(PaymentBlocked) as ctx:
                h.record_payment(
                    h.heavy_equipment_requester, official,
                    amount="100.00", evidence_ref=bad_evidence,
                    destination_account_alias="ACC-CONTRACTOR",
                )
            self.assertIn("evidence", str(ctx.exception).lower())
        self.assertEqual(_provider_payment_count(h), before)
        codes = [e["code"] for e in h.payment_workflow.denied_events()
                 if e["action"] == "record_payment"]
        self.assertEqual(codes.count("INVALID_INPUT"), 3)

    # -- 3. overpay blocked -----------------------------------------------------------

    def test_overpayment_blocked_before_provider_mutation(self) -> None:
        h = self.harness
        official = self._post_heavy_equipment_invoice("CUST-HEQ-PAY-3")
        before = _provider_payment_count(h)
        with self.assertRaises(PaymentBlocked) as ctx:
            h.record_payment(
                h.heavy_equipment_requester, official,
                amount="1500000.01", evidence_ref="EVI-HEQ-OVER-1",
                destination_account_alias="ACC-CONTRACTOR",
            )
        self.assertIn("exceeds open amount", str(ctx.exception))
        self.assertEqual(_provider_payment_count(h), before)
        invoice = h.erp_adapter.read_invoice(official)
        self.assertEqual(invoice.open_amount, "1500000")
        codes = [e["code"] for e in h.payment_workflow.denied_events()]
        self.assertIn("OVERPAYMENT", codes)

    # -- 4. duplicate evidence never double-applies ------------------------------------

    def test_duplicate_evidence_ref_never_double_applies(self) -> None:
        h = self.harness
        official = self._post_heavy_equipment_invoice("CUST-HEQ-PAY-4")
        first = h.record_payment(
            h.heavy_equipment_requester, official,
            amount="500000.00", evidence_ref="EVI-HEQ-DUP-1",
            destination_account_alias="ACC-CONTRACTOR",
        )
        self.assertEqual(first.outcome, "RECORDED")
        before = _provider_payment_count(h)
        # Replay with the same claim anchor returns the recorded result
        # without a second provider write.
        replay = h.record_payment(
            h.heavy_equipment_requester, official,
            amount="500000.00", evidence_ref="EVI-HEQ-DUP-1",
            destination_account_alias="ACC-CONTRACTOR",
        )
        self.assertEqual(replay.payment_ref, first.payment_ref)
        self.assertEqual(_provider_payment_count(h), before)
        self.assertEqual(
            h.receivables_open_amount(h.heavy_equipment_ar_reviewer,
                                      UNIT_HEAVY_EQUIPMENT),
            "1000000.00",
        )

    # -- 5. cross-unit payment denied ----------------------------------------------------

    def test_cross_unit_payment_denied(self) -> None:
        """The Banyumedia requester holds no Heavy Equipment assignment: a
        payment attempt against a HEQ invoice is denied with zero disclosure
        and zero provider mutation."""
        h = self.harness
        official = self._post_heavy_equipment_invoice("CUST-HEQ-PAY-5")
        before = _provider_payment_count(h)
        with self.assertRaises(PaymentDenied) as ctx:
            h.record_payment(
                h.banyumedia_requester, official,  # cross-unit actor
                amount="100.00", evidence_ref="EVI-XUNIT-1",
                destination_account_alias="ACC-CONTRACTOR",
            )
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        self.assertNotIn("HEAVY", str(ctx.exception))
        self.assertEqual(_provider_payment_count(h), before)

    def test_wrong_account_alias_denied(self) -> None:
        """R-013/R-019: even the unit's own actor cannot steer a payment to a
        foreign account alias."""
        h = self.harness
        official = self._post_heavy_equipment_invoice("CUST-HEQ-PAY-6")
        before = _provider_payment_count(h)
        with self.assertRaises(PaymentDenied) as ctx:
            h.record_payment(
                h.heavy_equipment_requester, official,
                amount="100.00", evidence_ref="EVI-HEQ-WRONGACC-1",
                destination_account_alias="ACC-BANYUMEDIA",  # not HEQ's alias
            )
        self.assertEqual(ctx.exception.code, "WRONG_ACCOUNT")
        self.assertEqual(_provider_payment_count(h), before)

    # -- 6. reversal -----------------------------------------------------------------------

    def test_reversal_reopens_ar_and_is_audited(self) -> None:
        h = self.harness
        official = self._post_heavy_equipment_invoice("CUST-HEQ-PAY-7")
        paid = h.record_payment(
            h.heavy_equipment_requester, official,
            amount="1500000.00", evidence_ref="EVI-HEQ-REV-1",
            destination_account_alias="ACC-CONTRACTOR",
        )
        self.assertEqual(paid.receivable_status, "PAID")
        # Paid invoices leave the aging surface.
        self.assertEqual(
            h.receivables_open_amount(h.heavy_equipment_ar_reviewer,
                                      UNIT_HEAVY_EQUIPMENT),
            "0",
        )
        reversal = h.reverse_payment(
            h.heavy_equipment_requester, paid.payment_ref,  # type: ignore[arg-type]
            reason="synthetic chargeback",
        )
        self.assertEqual(reversal.outcome, "RECORDED")
        self.assertEqual(reversal.receivable_status, "OPEN")
        # AR reopens to the full amount; reversal is a compensating record
        # (the original payment is never erased).
        self.assertEqual(
            h.receivables_open_amount(h.heavy_equipment_ar_reviewer,
                                      UNIT_HEAVY_EQUIPMENT),
            "1500000.00",
        )
        events = h.payment_workflow.audit_events(official)
        reversed_events = [e for e in events if e["action"] == "payment_reversed"]
        self.assertEqual(len(reversed_events), 1)
        self.assertEqual(reversed_events[0]["receivable_status"], "OPEN")
        self.assertIn("reversal_ref", reversed_events[0])
        # Double reversal is blocked.
        with self.assertRaises(PaymentBlocked):
            h.reverse_payment(
                h.heavy_equipment_requester, paid.payment_ref,  # type: ignore[arg-type]
                reason="second attempt",
            )


if __name__ == "__main__":
    unittest.main()
