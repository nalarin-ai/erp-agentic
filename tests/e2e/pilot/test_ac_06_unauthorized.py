"""MVP-AC-06: unauthorized sensitive actions denied — zero disclosure/mutation.

Criteria (TRACEABILITY_MATRIX.md section D; TEST_STRATEGY.md section 3 RBAC
negative matrix):
- Unit sales may NOT post invoices (INVOICE_POST requires FINANCE-POSTER).
- A requester may NOT post their own draft (review separation, F-02).
- Cross-unit posting is denied.
- Direct adapter invocation without an authorization context is fail-closed
  at the workflow layer (authorization precedes idempotency/provider call).
- Every denial discloses nothing protected (generic message; no unit refs).
"""
from __future__ import annotations

import unittest

from src.workflows.invoice_draft.workflow import WorkflowDenied
from src.workflows.invoice_post.workflow import (
    WorkflowBlocked as PostBlocked,
    WorkflowDenied as PostDenied,
)

from tests.e2e.pilot._harness import (
    PilotHarness,
    UNIT_BANYUMEDIA,
    UNIT_CONTRACTOR,
)


def _posted_count(h: PilotHarness) -> int:
    return len(h.post_workflow._posted)  # noqa: SLF001 - test inspection


class TestAc06UnauthorizedSensitiveActions(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PilotHarness.build()

    def _preview_for(self, requester, unit_ref, customer_ref):
        h = self.harness
        handle = h.open_draft(requester, unit_ref, customer_ref=customer_ref)
        h.set_lines(requester, handle.draft_id, h.standard_lines())
        return h.preview(requester, handle.draft_id)

    def test_sales_role_cannot_post_invoice(self) -> None:
        """UNIT-SALES holds no INVOICE_POST action; posting as sales is denied
        with zero provider mutation."""
        h = self.harness
        preview = self._preview_for(h.banyumedia_requester, UNIT_BANYUMEDIA,
                                    "CUST-SEC-1")
        before = _posted_count(h)
        with self.assertRaises(PostDenied) as ctx:
            h.post(h.banyumedia_sales, preview)  # sales actor, no POSTER role
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        self.assertEqual(str(ctx.exception), "Request cannot be authorized.")
        self.assertEqual(_posted_count(h), before)

    def test_requester_cannot_self_post(self) -> None:
        """F-02: the draft opener may never post their own draft, even when
        they would otherwise hold a poster role (here they don't even hold
        it — the self-post guard fires on the role check path first)."""
        h = self.harness
        preview = self._preview_for(h.banyumedia_requester, UNIT_BANYUMEDIA,
                                    "CUST-SEC-2")
        before = _posted_count(h)
        with self.assertRaises(PostDenied):
            h.post(h.banyumedia_requester, preview)
        self.assertEqual(_posted_count(h), before)

    def test_cross_unit_posting_denied(self) -> None:
        """Contractor poster cannot post a Banyumedia preview."""
        h = self.harness
        preview = self._preview_for(h.banyumedia_requester, UNIT_BANYUMEDIA,
                                    "CUST-SEC-3")
        before = _posted_count(h)
        with self.assertRaises(PostDenied) as ctx:
            h.post(h.contractor_poster, preview)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        self.assertEqual(_posted_count(h), before)

    def test_denial_message_discloses_nothing(self) -> None:
        """Every denial carries the static generic message — no unit refs,
        actor refs, amounts, or existence hints leak."""
        h = self.harness
        preview = self._preview_for(h.banyumedia_requester, UNIT_BANYUMEDIA,
                                    "CUST-SEC-4")
        try:
            h.post(h.contractor_poster, preview)
        except PostDenied as exc:
            message = str(exc)
            self.assertNotIn("BANYUMEDIA", message)
            self.assertNotIn("CONTRACTOR", message)
            self.assertNotIn("CUST-SEC-4", message)
            self.assertNotIn("1500000", message)
        else:  # pragma: no cover - assertion guard
            self.fail("cross-unit post must be denied")

    def test_unassigned_actor_denied_everywhere(self) -> None:
        """An actor with zero assignments cannot open drafts at all."""
        h = self.harness
        from tests.e2e.pilot._harness import _actor, at
        stranger = _actor("ACTOR-STRANGER", "CHANNEL-WA-STRANGER")
        with self.assertRaises(WorkflowDenied) as ctx:
            h.draft_workflow.open_draft(
                actor_ref=stranger.actor_ref,
                channel_ref=stranger.channel_ref,
                binding=stranger.binding,
                assignments=stranger.all_assignments(),
                customer_ref="CUST-SEC-5",
                at=at(10),
                selected_unit_ref=UNIT_BANYUMEDIA,
            )
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    def test_post_with_unverified_identity_denied(self) -> None:
        h = self.harness
        preview = self._preview_for(h.banyumedia_requester, UNIT_BANYUMEDIA,
                                    "CUST-SEC-6")
        poster = h.banyumedia_poster
        before = _posted_count(h)
        with self.assertRaises(PostDenied) as ctx:
            h.post_workflow.post(
                preview,
                actor_ref=poster.actor_ref,
                at=__import__("tests.e2e.pilot._harness", fromlist=["at"]).at(20),
                binding=None,  # identity not verified
                assignments=poster.all_assignments(),
                channel_ref=poster.channel_ref,
            )
        self.assertEqual(ctx.exception.code, "IDENTITY_UNVERIFIED")
        self.assertEqual(_posted_count(h), before)

    def test_denied_attempts_are_audited(self) -> None:
        """QA-08/FLOW security audit: denied attempts land in the workflow's
        denied-event log with safe codes (no payload disclosure)."""
        h = self.harness
        preview = self._preview_for(h.banyumedia_requester, UNIT_BANYUMEDIA,
                                    "CUST-SEC-7")
        with self.assertRaises(PostDenied):
            h.post(h.contractor_poster, preview)
        denied = h.post_workflow.denied_events()
        self.assertTrue(any(e["action"] == "post" for e in denied))
        for event in denied:
            self.assertIn("code", event)
            serialized = str(event)
            self.assertNotIn("CUST-SEC-7", serialized)
            self.assertNotIn("1500000", serialized)


if __name__ == "__main__":
    unittest.main()
