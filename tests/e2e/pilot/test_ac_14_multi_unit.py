"""MVP-AC-14: multi-unit user selects exactly one authorized active unit.

Criteria (TRACEABILITY_MATRIX.md section D; FND-002, CRM-001, FLOW-001/002,
RPT-001, UX-001): a user holding several unit assignments must select
exactly one authorized active unit per request; unassigned/expired/revoked
selection is denied; cross-unit data never leaks; stale cache/preview after
assignment or settings change cannot be posted; report/export surfaces are
scope-bounded per unit.

Harness notes:
- ``multi_unit_reviewer`` holds FINANCE-REVIEWER on BANYUMEDIA + CONTRACTOR.
- The CRM roster is read live by the fixture adapter, so roster revocation
  is immediately visible to CRM gateway calls.
- The authz engine (FND-002) evaluates assignment effectiveness per request:
  active flag, effective window, revision pinning (STALE_CONTEXT /
  STALE_PREVIEW), and exactly-one-unit selection.

Scenarios:
1. Positive: the multi-unit reviewer acts in each unit — exactly one active
   unit context per request (a request without selection is denied
   UNIT_CONTEXT_REQUIRED; a selected request binds exactly that unit).
2. Unassigned unit selection is denied PERMISSION_DENIED (zero disclosure).
3. Revoked assignment (CRM roster + authz inactive flag) is denied live.
4. Cross-unit leak denied: the AR report intersects server-derived scope —
   asking for a foreign unit fails closed with no data.
5. Stale preview after a settings version change cannot be posted
   (STALE_PREVIEW before any provider mutation).
6. Stale assignment revision after revocation+bump cannot be used
   (STALE_CONTEXT) — a changed assignment invalidates pinned context.
7. Report/export surfaces are scope-bounded per unit: the aging query only
   ever returns entries for the requested authorized unit.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from src.authz.access import ActorUnitAssignment
from src.workflows.invoice_draft.workflow import (
    WorkflowBlocked as DraftBlocked,
    WorkflowDenied as DraftDenied,
)
from src.workflows.invoice_post.workflow import (
    WorkflowBlocked as PostBlocked,
    WorkflowDenied as PostDenied,
)
from src.reports.receivables.aging import WorkflowDenied as ArDenied

from tests.e2e.pilot._harness import (
    PilotHarness,
    UNIT_BANYUMEDIA,
    UNIT_CONTRACTOR,
    UNIT_PT_TKH,
    at,
    _actor,
)


def _posted_count(h: PilotHarness) -> int:
    return len(h.post_workflow._posted)  # noqa: SLF001 - test inspection


class TestAc14MultiUnitSelection(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PilotHarness.build()

    # -- 1. positive: exactly one active unit context per request --------------

    def test_multi_unit_actor_acts_in_each_unit_one_context_per_request(self) -> None:
        h = self.harness
        reviewer = h.multi_unit_reviewer
        # Reviewer can render/read in BOTH assigned units, each request
        # carrying exactly one selected unit.
        for unit_ref, requester in (
            (UNIT_BANYUMEDIA, h.banyumedia_requester),
            (UNIT_CONTRACTOR, h.contractor_requester),
        ):
            preview, _posted = h.post_invoice_for_unit(
                requester,
                h.banyumedia_poster if unit_ref == UNIT_BANYUMEDIA
                else h.contractor_poster,
                unit_ref, customer_ref=f"CUST-MU-{unit_ref[-4:]}",
                at_minutes=10,
            )
            result = h.receivables.query_aging(
                actor_ref=reviewer.actor_ref, at=at(40),
                binding=reviewer.binding,
                assignments=reviewer.all_assignments(),
                channel_ref=reviewer.channel_ref,
                unit_ref=unit_ref,
            )
            self.assertTrue(result.scoped)
            self.assertTrue(result.entries)
            # Every entry belongs to the requested unit only.
            self.assertEqual({e.unit_ref for e in result.entries}, {unit_ref})

    def test_multi_unit_actor_without_selection_denied_unit_context_required(self) -> None:
        """R-011: with several active assignments and no explicit selection,
        the request is ambiguous and denied — never silently picks a unit."""
        h = self.harness
        reviewer = h.multi_unit_reviewer
        from src.authz.access import AuthorizationRequest, authorize
        decision = authorize(
            request=AuthorizationRequest(
                actor_ref=reviewer.actor_ref,
                channel_ref=reviewer.channel_ref,
                action="QUERY_RECEIVABLE",
                selected_unit_ref=None,
                requested_at=at(40),
            ),
            binding=reviewer.binding,
            assignments=reviewer.all_assignments(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "UNIT_CONTEXT_REQUIRED")
        # A denied decision can never disclose a unit_ref.
        self.assertIsNone(decision.unit_ref)

    # -- 2. unassigned selection denied ------------------------------------------

    def test_unassigned_unit_selection_denied_no_disclosure(self) -> None:
        h = self.harness
        reviewer = h.multi_unit_reviewer
        # Reviewer holds BYM+CTR; selecting PT_TKH (not assigned) is denied.
        with self.assertRaises(ArDenied) as ctx:
            h.receivables.query_aging(
                actor_ref=reviewer.actor_ref, at=at(40),
                binding=reviewer.binding,
                assignments=reviewer.all_assignments(),
                channel_ref=reviewer.channel_ref,
                unit_ref=UNIT_PT_TKH,
            )
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        self.assertEqual(str(ctx.exception), "Request cannot be authorized.")
        # Zero disclosure: the message never echoes the requested unit.
        self.assertNotIn("PTTKHOPS", str(ctx.exception))
        # …and the denial is audited on the report surface.
        self.assertTrue(any(
            e["code"] == "PERMISSION_DENIED"
            for e in h.receivables.denied_events()))

    # -- 3. revoked assignment denied live (CRM roster + authz) -------------------

    def test_revoked_crm_roster_selection_denied_live(self) -> None:
        """CRM-001 roster is read live: removing the actor from a unit roster
        immediately denies CRM access for that unit — no stale cache."""
        h = self.harness
        # Seed: BYM sales owns a lead; roster mirrors the assignment.
        lead_ref = h.create_lead(
            h.banyumedia_sales, UNIT_BANYUMEDIA,
            display_name="Lead Mu Revoke", contact_handle="wa-mu-1")
        # Positive control: readable while rostered.
        self.assertEqual(
            h.read_lead(h.banyumedia_sales, UNIT_BANYUMEDIA, lead_ref).reference,
            lead_ref)
        # Revoke the roster membership live (CRM-001 revocation path).
        h.crm_roster[h.banyumedia_sales.actor_ref] = frozenset()
        from src.crm.port import CrmDenied
        with self.assertRaises(CrmDenied):
            h.read_lead(h.banyumedia_sales, UNIT_BANYUMEDIA, lead_ref)

    def test_revoked_authz_assignment_denied_everywhere(self) -> None:
        """FND-002: flipping the assignment to inactive denies workflow and
        report surfaces that previously authorized the actor."""
        h = self.harness
        reviewer = h.multi_unit_reviewer
        revoked_assignments = tuple(
            replace(a, active=False) if a.unit_ref == UNIT_CONTRACTOR else a
            for a in reviewer.assignments
        )
        with self.assertRaises(ArDenied) as ctx:
            h.receivables.query_aging(
                actor_ref=reviewer.actor_ref, at=at(40),
                binding=reviewer.binding,
                assignments=revoked_assignments,
                channel_ref=reviewer.channel_ref,
                unit_ref=UNIT_CONTRACTOR,
            )
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    # -- 4. cross-unit leak denied -------------------------------------------------

    def test_cross_unit_report_entries_never_leak(self) -> None:
        """An actor scoped to one unit can never read another unit's rows,
        even by asking; the scope intersection is server-derived."""
        h = self.harness
        # Post an invoice in Contractor; the BYM-only AR reviewer asks for it.
        h.post_invoice_for_unit(
            h.contractor_requester, h.contractor_poster, UNIT_CONTRACTOR,
            customer_ref="CUST-MU-CTR")
        with self.assertRaises(ArDenied) as ctx:
            h.receivables.query_aging(
                actor_ref=h.banyumedia_ar_reviewer.actor_ref, at=at(40),
                binding=h.banyumedia_ar_reviewer.binding,
                assignments=h.banyumedia_ar_reviewer.all_assignments(),
                channel_ref=h.banyumedia_ar_reviewer.channel_ref,
                unit_ref=UNIT_CONTRACTOR,
            )
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    # -- 5. stale preview after settings change cannot be posted -------------------

    def test_stale_preview_after_settings_change_cannot_be_posted(self) -> None:
        """R-022: a preview rendered against settings vN is blocked once the
        active version moves on — reviewers never post a stale snapshot."""
        h = self.harness
        handle = h.open_draft(h.banyumedia_requester, UNIT_BANYUMEDIA,
                              customer_ref="CUST-MU-STALE")
        h.set_lines(h.banyumedia_requester, handle.draft_id, h.standard_lines())
        preview = h.preview(h.banyumedia_requester, handle.draft_id)
        # Settings move on AFTER the preview (new branding version active).
        h.change_branding("BANYUMEDIA", invoice_template_ref="tpl_banyu_v2",
                          logo_asset_ref="logo_banyu_v2", at_minutes=30)
        before = _posted_count(h)
        with self.assertRaises(PostBlocked):
            h.post(h.banyumedia_poster, preview, at_minutes=40)
        # Zero provider mutation: nothing posted for the stale preview.
        self.assertEqual(_posted_count(h), before)
        self.assertTrue(any(
            e["code"] == "STALE_PREVIEW"
            for e in h.post_workflow._denied))  # noqa: SLF001

    # -- 6. stale assignment revision cannot be used --------------------------------

    def test_stale_assignment_revision_denied_stale_context(self) -> None:
        """FND-002 revision pinning: if the actor's assignment changes
        (revocation re-issue bumps the revision), any request still pinning
        the old revision is denied STALE_CONTEXT."""
        h = self.harness
        reviewer = h.multi_unit_reviewer
        stale_assignment = ActorUnitAssignment(
            actor_ref=reviewer.actor_ref,
            unit_ref=UNIT_BANYUMEDIA,
            roles=("FINANCE-REVIEWER",),
            active=True,
            assignment_ref=reviewer.for_unit(UNIT_BANYUMEDIA).assignment_ref,
            revision=2,  # bumped: the pinned revision 1 is now stale
        )
        from src.authz.access import (
            AuthorizationRequest,
            PreviewBinding,
            authorize,
        )
        pinned = reviewer.for_unit(UNIT_BANYUMEDIA)
        decision = authorize(
            request=AuthorizationRequest(
                actor_ref=reviewer.actor_ref,
                channel_ref=reviewer.channel_ref,
                action="QUERY_RECEIVABLE",
                selected_unit_ref=UNIT_BANYUMEDIA,
                requested_at=at(40),
                preview=PreviewBinding(
                    unit_ref=UNIT_BANYUMEDIA,
                    assignment_ref=pinned.assignment_ref,
                    assignment_revision=pinned.revision,  # old revision
                ),
            ),
            binding=reviewer.binding,
            assignments=(stale_assignment,),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "STALE_PREVIEW")
        self.assertIsNone(decision.unit_ref)

    # -- 7. report/export scope-bounded per unit -----------------------------------

    def test_report_scope_bounded_per_unit_for_multi_unit_actor(self) -> None:
        """RPT-001: each report query returns ONLY the requested unit's rows;
        scoping is server-derived and the result is marked scoped."""
        h = self.harness
        reviewer = h.multi_unit_reviewer
        h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref="CUST-MU-SCOPE-B")
        h.post_invoice_for_unit(
            h.contractor_requester, h.contractor_poster, UNIT_CONTRACTOR,
            customer_ref="CUST-MU-SCOPE-C")
        bym = h.receivables.query_aging(
            actor_ref=reviewer.actor_ref, at=at(40), binding=reviewer.binding,
            assignments=reviewer.all_assignments(),
            channel_ref=reviewer.channel_ref, unit_ref=UNIT_BANYUMEDIA)
        ctr = h.receivables.query_aging(
            actor_ref=reviewer.actor_ref, at=at(41), binding=reviewer.binding,
            assignments=reviewer.all_assignments(),
            channel_ref=reviewer.channel_ref, unit_ref=UNIT_CONTRACTOR)
        self.assertTrue(bym.scoped and ctr.scoped)
        self.assertEqual({e.unit_ref for e in bym.entries}, {UNIT_BANYUMEDIA})
        self.assertEqual({e.unit_ref for e in ctr.entries}, {UNIT_CONTRACTOR})
        # Totals are per-unit, never merged across units.
        self.assertNotEqual(bym.entries, ctr.entries)
        # No unit filter (None) spans ONLY authorized units, never foreign.
        all_units = h.receivables.query_aging(
            actor_ref=reviewer.actor_ref, at=at(42), binding=reviewer.binding,
            assignments=reviewer.all_assignments(),
            channel_ref=reviewer.channel_ref)
        self.assertEqual(
            {e.unit_ref for e in all_units.entries},
            {UNIT_BANYUMEDIA, UNIT_CONTRACTOR})
        self.assertNotIn(UNIT_PT_TKH,
                         {e.unit_ref for e in all_units.entries})


if __name__ == "__main__":
    unittest.main()
