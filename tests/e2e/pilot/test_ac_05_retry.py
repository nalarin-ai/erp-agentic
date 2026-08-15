"""MVP-AC-05: retry never duplicates (FND-004, REC-001).

Criteria (TRACEABILITY_MATRIX.md section D): a stale worker or lost response
may re-issue the exact same request; the system must never duplicate state:

1. open_draft replayed with the same idempotency_key returns the SAME draft —
   no duplicate draft, no extra audit "open" entry.
2. Re-posting the same draft (lost response retry) never issues a second
   official number — the state guard blocks the duplicate.
3. Re-recording a payment with the same evidence_ref returns the recorded
   result without a second provider write (no double-apply to AR).
4. A blind retry while the first attempt is UNCERTAIN is BLOCKED until
   reconciliation classifies it — for both post and payment paths.

Verification is via production audit_events / denied_events / provider state
counts — no mocks anywhere.
"""
from __future__ import annotations

import unittest

from src.workflows.invoice_draft.workflow import (
    WorkflowBlocked as DraftBlocked,
)
from src.workflows.invoice_post.workflow import (
    WorkflowBlocked as PostBlocked,
)
from src.workflows.payments.workflow import (
    WorkflowBlocked as PaymentBlocked,
)

from tests.e2e.pilot._harness import (
    PilotHarness,
    UNIT_BANYUMEDIA,
    UNIT_HEAVY_EQUIPMENT,
)


def _draft_count(h: PilotHarness) -> int:
    return len(h.draft_workflow._drafts)  # noqa: SLF001 - test inspection


def _posted_count(h: PilotHarness) -> int:
    return len(h.post_workflow._posted)  # noqa: SLF001


def _provider_payment_count(h: PilotHarness) -> int:
    return len(h.erp_adapter._payments)  # noqa: SLF001


class TestAc05RetryNeverDuplicates(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PilotHarness.build()

    # -- 1. draft open idempotency ---------------------------------------------

    def test_open_draft_replay_same_idempotency_key_returns_same_draft(self) -> None:
        h = self.harness
        actor = h.banyumedia_requester
        first = h.open_draft(actor, UNIT_BANYUMEDIA,
                             customer_ref="CUST-BYM-RETRY-1",
                             idempotency_key="IDK-OPEN-1")
        before = _draft_count(h)
        # Stale worker / lost response: identical request re-issued twice.
        second = h.open_draft(actor, UNIT_BANYUMEDIA,
                              customer_ref="CUST-BYM-RETRY-1",
                              idempotency_key="IDK-OPEN-1")
        third = h.open_draft(actor, UNIT_BANYUMEDIA,
                             customer_ref="CUST-BYM-RETRY-1",
                             idempotency_key="IDK-OPEN-1")
        self.assertEqual(first.draft_id, second.draft_id)
        self.assertEqual(first.draft_id, third.draft_id)
        # Exactly one draft exists; exactly one "open" audit entry.
        self.assertEqual(_draft_count(h), before)
        opens = [e for e in h.draft_workflow.audit_events(first.draft_id)
                 if e["action"] == "open"]
        self.assertEqual(len(opens), 1)

    def test_open_draft_idempotency_conflict_on_different_payload(self) -> None:
        h = self.harness
        actor = h.banyumedia_requester
        h.open_draft(actor, UNIT_BANYUMEDIA, customer_ref="CUST-BYM-RETRY-2",
                     idempotency_key="IDK-OPEN-2")
        with self.assertRaises(DraftBlocked) as ctx:
            h.open_draft(actor, UNIT_BANYUMEDIA,
                         customer_ref="CUST-BYM-RETRY-OTHER",
                         idempotency_key="IDK-OPEN-2")
        self.assertIn("idempotency", str(ctx.exception).lower())
        denied_codes = [e["code"] for e in h.draft_workflow.denied_events()]
        self.assertIn("IDEMPOTENCY_CONFLICT", denied_codes)

    # -- 2. post idempotency -----------------------------------------------------

    def test_post_retry_after_success_never_issues_second_official_number(self) -> None:
        h = self.harness
        preview, result = h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref="CUST-BYM-RETRY-3",
        )
        self.assertEqual(result.outcome, "POSTED")
        official = result.official_ref
        self.assertIsNotNone(official)
        before = _posted_count(h)
        # Lost-response retry: the poster re-submits the same preview.
        with self.assertRaises(PostBlocked) as ctx:
            h.post(h.banyumedia_poster, preview)
        self.assertIn("already posted", str(ctx.exception))
        # Still exactly one posted record; no second official number.
        self.assertEqual(_posted_count(h), before)
        self.assertEqual(
            h.post_workflow._by_draft_id[preview.draft_id], official)  # noqa: SLF001
        denied_codes = [e["code"] for e in h.post_workflow.denied_events()]
        self.assertIn("INVALID_STATE", denied_codes)

    def test_blind_repost_blocked_until_reconcile_classifies_uncertain(self) -> None:
        """REC-001: an UNCERTAIN post outcome forbids blind retry; only the
        fenced reconcile path may classify it."""
        h = self.harness
        handle = h.open_draft(h.banyumedia_requester, UNIT_BANYUMEDIA,
                              customer_ref="CUST-BYM-RETRY-4")
        h.set_lines(h.banyumedia_requester, handle.draft_id,
                    h.standard_lines())
        preview = h.preview(h.banyumedia_requester, handle.draft_id)
        # Provider applies the mutation but reports the outcome as unknown.
        h.erp_adapter.fail_next_post("UNCERTAIN")
        result = h.post(h.banyumedia_poster, preview)
        self.assertEqual(result.outcome, "UNCERTAIN")
        self.assertIsNone(result.official_ref)
        # Blind retry while pending reconciliation is BLOCKED, and the block
        # is audited as INVALID_STATE.
        with self.assertRaises(PostBlocked) as ctx:
            h.post(h.banyumedia_poster, preview)
        self.assertIn("pending reconciliation", str(ctx.exception))
        codes = [e["code"] for e in h.post_workflow.denied_events()
                 if e["action"] == "post"]
        self.assertIn("INVALID_STATE", codes)
        # Fenced classification (reconcile_post) resolves to POSTED — exactly
        # one official number is ever issued for this draft.
        reconciled = h.post_workflow.reconcile_post(
            preview,
            actor_ref=h.banyumedia_poster.actor_ref,
            at=__import__("tests.e2e.pilot._harness", fromlist=["at"]).at(30),
            binding=h.banyumedia_poster.binding,
            assignments=h.banyumedia_poster.all_assignments(),
            channel_ref=h.banyumedia_poster.channel_ref,
        )
        self.assertEqual(reconciled.outcome, "POSTED")
        self.assertEqual(_posted_count(h), 1)
        # After classification the draft is posted; any further retry is the
        # ordinary already-posted guard, never a second provider mutation.
        with self.assertRaises(PostBlocked):
            h.post(h.banyumedia_poster, preview)

    # -- 3. payment idempotency ---------------------------------------------------

    def test_payment_retry_same_evidence_never_double_applies(self) -> None:
        h = self.harness
        _, posted = h.post_invoice_for_unit(
            h.heavy_equipment_requester, h.heavy_equipment_poster,
            UNIT_HEAVY_EQUIPMENT, customer_ref="CUST-HEQ-RETRY-1",
        )
        official = posted.official_ref
        assert official is not None
        first = h.record_payment(
            h.heavy_equipment_requester, official,
            amount="1500000.00", evidence_ref="EVI-HEQ-RETRY-1",
            destination_account_alias="ACC-CONTRACTOR",  # R-015 shared alias
        )
        self.assertEqual(first.outcome, "RECORDED")
        self.assertEqual(first.receivable_status, "PAID")
        before = _provider_payment_count(h)
        # Retry (lost response): same evidence_ref, same payload -> replay,
        # not a second provider mutation.
        replay = h.record_payment(
            h.heavy_equipment_requester, official,
            amount="1500000.00", evidence_ref="EVI-HEQ-RETRY-1",
            destination_account_alias="ACC-CONTRACTOR",
        )
        self.assertEqual(replay.outcome, "RECORDED")
        self.assertEqual(replay.payment_ref, first.payment_ref)
        self.assertEqual(_provider_payment_count(h), before)
        # AR read-back still reflects exactly one payment (fully paid, so the
        # invoice has left the aging surface).
        self.assertEqual(
            h.receivables_open_amount(h.heavy_equipment_ar_reviewer,
                                      UNIT_HEAVY_EQUIPMENT),
            "0",
        )
        # The same evidence ref under a DIFFERENT claim key is denied — the
        # duplicate can never slip in through a fresh idempotency namespace.
        # NOTE: the workflow's overpay guard runs before the evidence-dup
        # check; on a fully-paid invoice the duplicate retry therefore
        # surfaces as the overpay block. Either way: audited denial, zero
        # provider mutation.
        with self.assertRaises(PaymentBlocked) as ctx:
            h.record_payment(
                h.heavy_equipment_requester, official,
                amount="1500000.00", evidence_ref="EVI-HEQ-RETRY-1",
                destination_account_alias="ACC-CONTRACTOR",
                idempotency_key="IDK-PAY-OTHER",
            )
        self.assertIn(str(ctx.exception), (
            "payment exceeds open amount",
            "evidence reference already recorded",
        ))
        dup_codes = [e["code"] for e in h.payment_workflow.denied_events()
                     if e["action"] == "record_payment"]
        self.assertTrue(
            {"OVERPAYMENT", "IDEMPOTENCY_CONFLICT"} & set(dup_codes),
            f"expected an audited denial for the duplicate evidence retry; got {dup_codes}",
        )
        self.assertEqual(_provider_payment_count(h), before)

    def test_blind_payment_retry_blocked_until_reconcile_classifies(self) -> None:
        h = self.harness
        _, posted = h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref="CUST-BYM-RETRY-5",
        )
        official = posted.official_ref
        assert official is not None
        h.erp_adapter.fail_next_payment("UNCERTAIN")
        uncertain = h.record_payment(
            h.banyumedia_requester, official,
            amount="500000.00", evidence_ref="EVI-BYM-UNC-1",
            destination_account_alias="ACC-BANYUMEDIA",
        )
        self.assertEqual(uncertain.outcome, "UNCERTAIN")
        # Blind retry of the same evidence is BLOCKED while classification
        # is pending (REC-001), and the block is audited.
        with self.assertRaises(PaymentBlocked) as ctx:
            h.record_payment(
                h.banyumedia_requester, official,
                amount="500000.00", evidence_ref="EVI-BYM-UNC-1",
                destination_account_alias="ACC-BANYUMEDIA",
            )
        self.assertIn("pending reconciliation", str(ctx.exception))
        codes = [e["code"] for e in h.payment_workflow.denied_events()]
        self.assertIn("INVALID_STATE", codes)
        # The fenced reconcile path classifies it as RECORDED — applied
        # exactly once at the provider.
        reconciled = h.reconcile_payment(h.banyumedia_requester, "EVI-BYM-UNC-1")
        self.assertEqual(reconciled.outcome, "RECORDED")
        self.assertEqual(reconciled.receivable_status, "PARTIALLY_PAID")
        self.assertEqual(_provider_payment_count(h), 1)
        invoice = h.erp_adapter.read_invoice(official)
        self.assertEqual(invoice.open_amount, "1000000.00")


if __name__ == "__main__":
    unittest.main()
