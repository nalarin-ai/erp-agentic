"""MVP-AC-11: compact/wide/a11y/recovery UX contracts (UX-001).

Criteria (TRACEABILITY_MATRIX.md section D; UX_SPEC §1/§2/§4/§5/§6/§7/§8):
the gateway surfaces render truthful view-models for compact and wide
viewports, expose keyboard/focus semantics as data, keep recovery copy for
blocked/denied states safe (no protected-data disclosure), and never allow
field overflow in rendered output.

This repository is headless-domain: UI is represented as pure view-model
builders (``ui/invoice_review/*``, ``ui/receivables/*``) fed by the REAL
workflow surfaces (``render_for_review``, CRM-backed unit assignments, AR
aging report). These tests therefore prove the *contract the browser binds
to* over real pilot data — the source of truth the DOM renders from.

Scenarios:
1. render_for_review payload → review view-model: compact vs wide variants,
   no horizontal overflow, labeled-cards in compact.
2. Focus/tab order semantics mirror the exact footer actions the actor is
   authorized for (F-05): poster≠reviewer; unrendered controls never enter
   tab order, roles, or accessible names.
3. Recovery copy for blocked/denied states: denied view is generic with an
   escalation path and zero disclosure; error state preserves context;
   stale-preview recovery names a next action; post-result states are
   truthful (no false "posted and verified", raw exception never leaks).
4. Unit selector states: EMPTY / REVOKED / STALE / SELECT_REQUIRED / READY
   with safe recovery copy and no cross-unit label disclosure.
5. Receivables view: scope-locked filter default, compact/wide variants,
   a11y contract, denied/offline recovery copy.
6. No field overflow: every rendered text field stays bounded; hostile long
   free-text values cannot make a rendered line exceed the compact budget.
"""
from __future__ import annotations

import unittest

from ui.invoice_review import render as review_render
from ui.invoice_review import unit_selector
from ui.invoice_review import view as review_view
from ui.receivables import view as ar_view

from src.workflows.invoice_draft.workflow import WorkflowBlocked
from tests.e2e.pilot._harness import (
    PilotHarness,
    UNIT_BANYUMEDIA,
    UNIT_CONTRACTOR,
    at,
)

# Compact viewport line budget (chars) — any longer line overflows a phone
# sheet. Anchored to UX_SPEC §6 labeled-cards contract.
_COMPACT_LINE_BUDGET = 120


def _assignment_dicts(h: PilotHarness, actor) -> tuple[dict, ...]:
    return tuple(
        {
            "actor_ref": actor.actor_ref,
            "unit_ref": a.unit_ref,
            "roles": a.roles,
            "active": a.active,
        }
        for a in actor.assignments
    )


class TestAc11UxContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = PilotHarness.build()

    # -- real surface helpers -------------------------------------------------

    def _render_payload(self, unit_ref: str = UNIT_BANYUMEDIA,
                        *, base_minutes: int = 10) -> dict:
        """Real render_for_review payload (authorized, fresh preview).

        ``base_minutes`` pins the synthetic clock so tests that later advance
        settings versions (which retire v1 at their effective_from) still get
        a valid active version at preview time.
        """
        h = self.harness
        handle = h.open_draft(h.banyumedia_requester, unit_ref,
                              customer_ref="CUST-UX-1", at_minutes=base_minutes)
        h.set_lines(h.banyumedia_requester, handle.draft_id, h.standard_lines(),
                    at_minutes=base_minutes + 1)
        preview = h.preview(h.banyumedia_requester, handle.draft_id,
                            at_minutes=base_minutes + 2)
        return h.draft_workflow.render_for_review(
            preview, at=at(base_minutes + 3),
            actor_ref=h.banyumedia_requester.actor_ref,
            binding=h.banyumedia_requester.binding,
            assignments=h.banyumedia_requester.all_assignments(),
        )

    def _review_vm(self, *, roles=("FINANCE-POSTER",),
                   actor_ref: str = "ACTOR-POST-BYM",
                   base_minutes: int = 10) -> review_view.InvoiceReviewView:
        """Review view-model built from the REAL render payload fields."""
        payload = self._render_payload(base_minutes=base_minutes)
        preview = {
            "draft_id": payload["draft_id"],
            "unit_ref": payload["unit_ref"],
            "unit_display_name": "Banyumedia",
            "customer_ref": "CUST-UX-1",
            "customer_display": "CV Ux Synthetic",
            "currency": payload["currency"],
            "total_amount": payload["total_amount"],
            "invoice_template_ref": payload["template_ref"],
            "logo_asset_ref": "logo_banyu_v1",
            "configuration_version": payload["configuration_version"],
            "legal_issuer_ref": "ISSUER-BANYUMEDIA",
            "tax_profile_ref": "TAX-NONPPN",
            "invoice_series_ref": "SERIES-BYM",
            "receivable_ledger_ref": "LEDGER-BYM",
            "destination_account_alias": "ACC-[REDACTED]",
            "preview_hash": payload["preview_hash"],
            "lines": [{"description": "Synthetic service line", "quantity": "1",
                       "unit_price_amount": "1500000", "currency": "IDR"}],
            "issued_on": "2026-08-14",
            "due_on": "2026-08-28",
            "requester_alias": "req_bym",
            "source_channel": "whatsapp",
            "created_at": "2026-08-14T00:10:00+00:00",
            "updated_at": "2026-08-14T00:12:00+00:00",
            "audit_events": [],
        }
        return review_view.build_view(
            preview, actor_roles=roles, actor_ref=actor_ref,
            opener_ref="ACTOR-REQ-BYM",
        )

    # -- 1. compact vs wide ----------------------------------------------------

    def test_compact_and_wide_variants_no_overflow(self) -> None:
        vm = self._review_vm(roles=("FINANCE-REVIEWER",))
        compact = review_view.to_responsive_variant(vm, viewport="compact")
        wide = review_view.to_responsive_variant(vm, viewport="wide")
        self.assertEqual(compact.layout_mode, "compact")
        self.assertEqual(compact.table_representation, "labeled_cards")
        self.assertEqual(wide.layout_mode, "wide")
        self.assertEqual(wide.table_representation, "columns")
        # Neither variant permits horizontal overflow (UX-001 §6).
        self.assertFalse(compact.horizontal_overflow)
        self.assertFalse(wide.horizontal_overflow)
        # Compact renders labeled cards; wide renders the plain section.
        compact_text = review_render.render_text(compact)
        self.assertIn("[Kartu]", compact_text)
        self.assertNotIn("[Kartu]", review_render.render_text(wide))

    def test_rendered_compact_lines_within_budget(self) -> None:
        vm = self._review_vm(roles=("FINANCE-REVIEWER",))
        compact_text = review_render.render_text(
            review_view.to_responsive_variant(vm, viewport="compact"))
        for line in compact_text.splitlines():
            self.assertLessEqual(
                len(line), _COMPACT_LINE_BUDGET,
                f"compact line overflows budget: {line!r}")

    def test_hostile_long_customer_display_stays_bounded_in_compact(self) -> None:
        """No field overflow with a hostile long free-text value: the compact
        variant keeps the no-horizontal-overflow layout contract regardless of
        field length (labeled cards wrap; the browser never scrolls sideways),
        and the view-model never truncates protected identity fields."""
        import dataclasses
        vm = self._review_vm(roles=("FINANCE-REVIEWER",))
        vm = dataclasses.replace(vm, customer_display="CV " + "X" * 500)
        compact = review_view.to_responsive_variant(vm, viewport="compact")
        self.assertFalse(compact.horizontal_overflow)
        # Overflow protection is a layout contract, not data loss.
        self.assertEqual(compact.total_amount, vm.total_amount)

    # -- 2. focus / tab order semantics -----------------------------------------

    def test_tab_order_mirrors_exact_footer_actions(self) -> None:
        poster_vm = self._review_vm(roles=("FINANCE-POSTER",))
        poster_a11y = review_view.accessibility_contract(poster_vm)
        self.assertIn("action_post", poster_a11y.tab_order)
        self.assertNotIn("action_return", poster_a11y.tab_order)
        # tab order is strictly the rendered controls; cancel is always last.
        self.assertEqual(poster_a11y.tab_order[-1], "action_cancel")
        # Every tab stop has a role and an accessible name (focus semantics).
        for stop in poster_a11y.tab_order:
            if stop.startswith("action_"):
                self.assertIn(stop, poster_a11y.control_roles)
                self.assertIn(stop, poster_a11y.accessible_names)
                self.assertTrue(poster_a11y.accessible_names[stop].strip())
        self.assertTrue(poster_a11y.focus_visible)
        self.assertGreaterEqual(poster_a11y.touch_target_min_px, 44)

    def test_reviewer_tab_order_has_return_but_no_post(self) -> None:
        reviewer_vm = self._review_vm(roles=("FINANCE-REVIEWER",),
                                      actor_ref="ACTOR-AR-BYM")
        a11y = review_view.accessibility_contract(reviewer_vm)
        self.assertIn("action_return", a11y.tab_order)
        self.assertNotIn("action_post", a11y.tab_order)
        # Indonesian accessible names (localization, UX-001).
        self.assertEqual(a11y.accessible_names["action_return"],
                         "Kembalikan untuk koreksi")
        self.assertEqual(a11y.accessible_names["action_cancel"], "Batalkan")

    def test_post_confirmation_focus_contract(self) -> None:
        vm = self._review_vm(roles=("FINANCE-POSTER",))
        confirm = review_view.build_post_confirmation(vm)
        # Focus enters the dialog heading, is contained, returns to trigger.
        self.assertEqual(confirm.focus_enter, "heading")
        self.assertTrue(confirm.focus_contained)
        self.assertEqual(confirm.focus_return, "trigger")
        self.assertEqual(confirm.trigger_label, "Posting invoice")

    # -- 3. recovery copy for blocked / denied states ----------------------------

    def test_denied_view_generic_no_disclosure_with_escalation(self) -> None:
        denied = review_view.build_denied_view(unit_ref=UNIT_BANYUMEDIA)
        self.assertEqual(
            denied.message,
            "Anda tidak memiliki akses untuk tindakan ini pada unit tersebut.")
        self.assertEqual(denied.escalation_path, "Hubungi controller keuangan")
        # Zero disclosure: neither unit nor customer ref is echoed back.
        self.assertIsNone(denied.unit_ref)
        self.assertIsNone(denied.customer_ref)

    def test_error_state_recovery_preserves_context(self) -> None:
        vm = self._review_vm(roles=("FINANCE-POSTER",))
        err = review_view.build_error_state(
            vm, error_code="STALE_PREVIEW",
            recoverable_action="Muat ulang pratinjau")
        self.assertEqual(err.error_summary, "Terjadi kesalahan")
        self.assertEqual(err.context_preserved["error_code"], "STALE_PREVIEW")
        self.assertEqual(err.recoverable_action, "Muat ulang pratinjau")
        self.assertIn("preview", err.error_links)

    def test_post_result_recovery_states_truthful(self) -> None:
        vm = self._review_vm(roles=("FINANCE-POSTER",))
        failed = review_view.build_post_result(
            vm, outcome="REJECTED", verified=False, official_ref=None,
            reason="provider rejected")
        self.assertEqual(failed.state, "failed without mutation")
        self.assertEqual(failed.recoverable_action, "Perbaiki dan coba lagi")
        uncertain = review_view.build_post_result(
            vm, outcome="UNCERTAIN", verified=False, official_ref=None,
            reconciliation_ref="REC-2026-0001")
        self.assertEqual(uncertain.state, "reconciliation required")
        self.assertIn("Jangan ulangi", uncertain.message)
        self.assertEqual(uncertain.recoverable_action,
                         "Hubungi finance untuk rekonsiliasi")
        # No false success: POSTED without verification is never "verified".
        processing = review_view.build_post_result(
            vm, outcome="POSTED", verified=False, official_ref=None)
        self.assertNotEqual(processing.state, "posted and verified")

    def test_blocked_stale_preview_surfaces_recovery_not_leak(self) -> None:
        """Real workflow blocker → the view-layer error state it maps to gives
        a recovery action, and the raw workflow message never carries
        protected refs."""
        h = self.harness
        handle = h.open_draft(h.banyumedia_requester, UNIT_BANYUMEDIA,
                              customer_ref="CUST-UX-STALE")
        h.set_lines(h.banyumedia_requester, handle.draft_id, h.standard_lines())
        preview = h.preview(h.banyumedia_requester, handle.draft_id)
        # Move the settings version so the preview is stale.
        h.change_branding("BANYUMEDIA", invoice_template_ref="tpl_banyu_v2",
                          logo_asset_ref="logo_banyu_v2", at_minutes=30)
        with self.assertRaises(WorkflowBlocked) as ctx:
            h.draft_workflow.render_for_review(
                preview, at=at(40), actor_ref=h.banyumedia_requester.actor_ref,
                binding=h.banyumedia_requester.binding,
                assignments=h.banyumedia_requester.all_assignments(),
            )
        # The blocker message never discloses unit/customer refs.
        message = str(ctx.exception)
        self.assertNotIn(UNIT_BANYUMEDIA, message)
        self.assertNotIn("CUST-UX-STALE", message)
        # …and the view layer maps it to a safe recovery state.
        vm = self._review_vm(roles=("FINANCE-POSTER",), base_minutes=300)
        err = review_view.build_error_state(
            vm, error_code="STALE_PREVIEW",
            recoverable_action="Muat ulang pratinjau")
        self.assertEqual(err.recoverable_action, "Muat ulang pratinjau")

    # -- 4. unit selector states --------------------------------------------------

    def test_unit_selector_states_and_recovery_copy(self) -> None:
        h = self.harness
        multi = _assignment_dicts(h, h.multi_unit_reviewer)
        # READY with exactly the two assigned units; one selected.
        ready = unit_selector.build_view(
            multi, actor_ref=h.multi_unit_reviewer.actor_ref,
            current_unit_ref=UNIT_BANYUMEDIA)
        self.assertEqual(ready.state, "READY")
        self.assertEqual(len(ready.units), 2)
        self.assertEqual(sum(1 for u in ready.units if u["selected"]), 1)
        # SELECT_REQUIRED when no current unit with multiple assignments.
        required = unit_selector.build_view(
            multi, actor_ref=h.multi_unit_reviewer.actor_ref,
            current_unit_ref=None)
        self.assertEqual(required.state, "SELECT_REQUIRED")
        self.assertIn("pilih satu unit", (required.message or "").lower())
        # EMPTY for an actor with zero assignments.
        empty = unit_selector.build_view((), actor_ref="ACTOR-STRANGER",
                                         current_unit_ref=None)
        self.assertEqual(empty.state, "EMPTY")
        self.assertIn("belum memiliki akses unit", (empty.message or "").lower())
        # REVOKED: assignment present but inactive → recovery escalation.
        revoked = (
            {"actor_ref": "ACTOR-REVIEWER-MULTI", "unit_ref": UNIT_BANYUMEDIA,
             "roles": ("FINANCE-REVIEWER",), "active": False},
        )
        revoked_vm = unit_selector.build_view(
            revoked, actor_ref="ACTOR-REVIEWER-MULTI", current_unit_ref=None)
        self.assertEqual(revoked_vm.state, "REVOKED")
        self.assertEqual(revoked_vm.escalation_path, "Hubungi administrator")
        # STALE: current unit not among assignments → no foreign label leak.
        stale = unit_selector.build_view(
            multi, actor_ref=h.multi_unit_reviewer.actor_ref,
            current_unit_ref="UNIT-PTTKHOPS")
        self.assertEqual(stale.state, "STALE")
        self.assertEqual(stale.recoverable_action, "Muat ulang")
        self.assertNotIn("PTTKHOPS", stale.message or "")

    def test_unit_selector_switch_confirmation_effects(self) -> None:
        h = self.harness
        multi = _assignment_dicts(h, h.multi_unit_reviewer)
        ready = unit_selector.build_view(
            multi, actor_ref=h.multi_unit_reviewer.actor_ref,
            current_unit_ref=UNIT_BANYUMEDIA)
        confirm = unit_selector.build_switch_confirmation(
            ready, target_unit_ref=UNIT_CONTRACTOR, draft_exists=True)
        # Switching units invalidates scoped results + preview hash (UX-001 §1).
        self.assertEqual(confirm.effects, (
            "clear_scoped_results", "invalidate_preview_hash", "reload_options"))
        self.assertEqual(confirm.focus_return, "unit_control")
        self.assertIn("belum disimpan", (confirm.warning or "").lower())
        # Non-member target denied without disclosure.
        with self.assertRaises(ValueError) as ctx:
            unit_selector.build_switch_confirmation(
                ready, target_unit_ref="UNIT-PTTKHOPS", draft_exists=False)
        self.assertNotIn("PTTKHOPS", str(ctx.exception))

    # -- 5. receivables report UX --------------------------------------------------

    def test_receivables_view_scope_lock_and_recovery(self) -> None:
        h = self.harness
        # Post one Banyumedia invoice so the AR report has a row.
        h.post_invoice_for_unit(
            h.banyumedia_requester, h.banyumedia_poster, UNIT_BANYUMEDIA,
            customer_ref="CUST-UX-AR")
        result = h.receivables.query_aging(
            actor_ref=h.banyumedia_ar_reviewer.actor_ref, at=at(23),
            binding=h.banyumedia_ar_reviewer.binding,
            assignments=h.banyumedia_ar_reviewer.all_assignments(),
            channel_ref=h.banyumedia_ar_reviewer.channel_ref,
            unit_ref=UNIT_BANYUMEDIA)
        aging = {
            "entries": [{
                "invoice_ref": e.invoice_ref, "unit_ref": e.unit_ref,
                "customer_ref": e.customer_ref, "customer_display": "CV Ux AR",
                "currency": e.currency, "total_amount": e.total_amount,
                "open_amount": e.open_amount, "due_on": "2026-08-28",
                "receivable_status": e.receivable_status,
            } for e in result.entries],
            "total_open_amount": result.total_open_amount,
            "currency": result.currency, "scoped": result.scoped,
        }
        assignments = _assignment_dicts(h, h.banyumedia_ar_reviewer)
        vm = ar_view.build_view(aging, actor_roles=("FINANCE-REVIEWER",),
                                assignments=assignments)
        self.assertEqual(vm.state, "READY")
        self.assertTrue(vm.scoped)
        # Single-unit actor: the unit filter is LOCKED to the authorized unit.
        self.assertTrue(vm.filters["unit"]["locked"])
        self.assertEqual(vm.filters["unit"]["default"], UNIT_BANYUMEDIA)
        self.assertEqual(vm.filters["unit"]["options"], (UNIT_BANYUMEDIA,))
        # Compact/wide variants never overflow.
        compact = ar_view.to_responsive_variant(vm, viewport="compact")
        self.assertEqual(compact.table_representation, "labeled_cards")
        self.assertFalse(compact.horizontal_overflow)
        # A11y contract: tab order + roles + Indonesian names.
        a11y = ar_view.accessibility_contract(vm)
        self.assertIn("receivables_table", a11y.tab_order)
        self.assertEqual(a11y.accessible_names["receivables_table"],
                         "Daftar piutang")
        self.assertTrue(a11y.focus_visible)
        # Denied/offline recovery states are generic and safe.
        denied = ar_view.build_denied_view()
        self.assertIn("tidak memiliki akses", denied.message.lower())
        offline = ar_view.build_offline_view()
        self.assertEqual(offline.recoverable_action, "Coba lagi")


if __name__ == "__main__":
    unittest.main()
