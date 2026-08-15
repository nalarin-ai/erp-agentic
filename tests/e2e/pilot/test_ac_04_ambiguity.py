"""MVP-AC-04: required ambiguity blocks posting — zero official number/provider write.

Criteria (TRACEABILITY_MATRIX.md section D):
- Missing required data (no lines) blocks preview/post with a precise safe
  blocker; no official number is ever issued.
- Actor-scope ambiguity (multi-unit actor without an explicit unit
  selection) denies draft opening — no provider write occurs.
- Unknown/unverified identity denies before any provider interaction.

Provider-write proof: the fixture ERP adapter's draft/post surfaces are
instrumented via call counting; every blocked path asserts zero calls.
"""
from __future__ import annotations

import unittest

from src.workflows.invoice_draft.workflow import WorkflowBlocked, WorkflowDenied

from tests.e2e.pilot._harness import (
    ActorFixture,
    PilotHarness,
    UNIT_BANYUMEDIA,
    UNIT_CONTRACTOR,
)


def _provider_write_count(h: PilotHarness) -> int:
    return len(h.erp_adapter._invoices)  # noqa: SLF001 - test inspection


class TestAc04AmbiguityBlocksPosting(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PilotHarness.build()

    def test_preview_without_lines_blocked_zero_provider_write(self) -> None:
        h = self.harness
        before = _provider_write_count(h)
        handle = h.open_draft(h.banyumedia_requester, UNIT_BANYUMEDIA,
                              customer_ref="CUST-BYM-AMB-1")
        with self.assertRaises(WorkflowBlocked) as ctx:
            h.preview(h.banyumedia_requester, handle.draft_id)
        self.assertIn("no lines", str(ctx.exception))
        self.assertEqual(_provider_write_count(h), before)

    def test_multi_unit_actor_without_selection_denied_zero_provider_write(self) -> None:
        """R-021: an actor with several active assignments MUST select exactly
        one unit; an unselected open is denied (UNIT_CONTEXT_REQUIRED)."""
        h = self.harness
        before = _provider_write_count(h)
        multi = h.multi_unit_reviewer  # BANYUMEDIA + CONTRACTOR assignments
        with self.assertRaises(WorkflowDenied) as ctx:
            h.draft_workflow.open_draft(
                actor_ref=multi.actor_ref,
                channel_ref=multi.channel_ref,
                binding=multi.binding,
                assignments=multi.all_assignments(),
                customer_ref="CUST-MULTI-1",
                at=__import__("tests.e2e.pilot._harness", fromlist=["at"]).at(10),
                selected_unit_ref=None,  # ambiguous
            )
        self.assertEqual(ctx.exception.code, "UNIT_CONTEXT_REQUIRED")
        self.assertEqual(_provider_write_count(h), before)

    def test_unverified_identity_denied_zero_provider_write(self) -> None:
        h = self.harness
        before = _provider_write_count(h)
        actor = h.banyumedia_requester
        with self.assertRaises(WorkflowDenied) as ctx:
            h.draft_workflow.open_draft(
                actor_ref=actor.actor_ref,
                channel_ref=actor.channel_ref,
                binding=None,  # unverified identity
                assignments=actor.all_assignments(),
                customer_ref="CUST-BYM-AMB-2",
                at=__import__("tests.e2e.pilot._harness", fromlist=["at"]).at(10),
                selected_unit_ref=UNIT_BANYUMEDIA,
            )
        self.assertEqual(ctx.exception.code, "IDENTITY_UNVERIFIED")
        self.assertEqual(_provider_write_count(h), before)

    def test_cross_unit_selection_denied_zero_provider_write(self) -> None:
        """Requester assigned only to Banyumedia selecting Contractor: denied,
        zero provider writes, and the denial message discloses nothing."""
        h = self.harness
        before = _provider_write_count(h)
        actor = h.banyumedia_requester
        with self.assertRaises(WorkflowDenied) as ctx:
            h.draft_workflow.open_draft(
                actor_ref=actor.actor_ref,
                channel_ref=actor.channel_ref,
                binding=actor.binding,
                assignments=actor.all_assignments(),
                customer_ref="CUST-BYM-AMB-3",
                at=__import__("tests.e2e.pilot._harness", fromlist=["at"]).at(10),
                selected_unit_ref=UNIT_CONTRACTOR,
            )
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        self.assertNotIn("CONTRACTOR", str(ctx.exception))
        self.assertEqual(_provider_write_count(h), before)

    def test_no_official_number_exists_for_blocked_draft(self) -> None:
        """Blocked drafts never reach the provider: no posted invoice record
        is addressable and the draft stays OPEN without lines."""
        h = self.harness
        handle = h.open_draft(h.banyumedia_requester, UNIT_BANYUMEDIA,
                              customer_ref="CUST-BYM-AMB-4")
        with self.assertRaises(WorkflowBlocked):
            h.preview(h.banyumedia_requester, handle.draft_id)
        snapshot = h.draft_workflow.get_draft(handle.draft_id)
        self.assertEqual(snapshot.status, "OPEN")
        self.assertEqual(len(snapshot.lines), 0)
        # Nothing posted under this draft id anywhere in the workflow.
        self.assertEqual(h.post_workflow._by_draft_id.get(handle.draft_id), None)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
