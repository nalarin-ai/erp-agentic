"""Tests for ui.invoice_review (UX_SPEC §2, §6, §7, §8)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ui.invoice_review import view as review_view
from ui.invoice_review import render as review_render

# Fixture draft opener (mirrors the authorized service result's opener ref).
_OPENER = "ACTOR-001"


def _preview() -> dict:
    return {
        "draft_id": "DFT-000001",
        "unit_ref": "UNIT-BANYUMEDIA",
        "unit_display_name": "Banyumedia",
        "customer_ref": "CUST-0001",
        "customer_display": "CV Contoh",
        "currency": "IDR",
        "total_amount": "1000000",
        "invoice_template_ref": "tpl_banyu_v1",
        "logo_asset_ref": "logo_banyu_v1",
        "configuration_version": 3,
        "legal_issuer_ref": "ISSUER-PT-TKH",
        "tax_profile_ref": "TAX-PPN-11",
        "invoice_series_ref": "SERIES-INV-2026",
        "receivable_ledger_ref": "LEDGER-AR-01",
        "destination_account_alias": "ACC-[REDACTED]",
        "preview_hash": "abc123",
        "lines": [
            {"description": "Jasa desain", "quantity": "2", "unit_price_amount": "500000", "currency": "IDR"},
        ],
        "issued_on": "2026-08-15",
        "due_on": "2026-09-14",
        "requester_alias": "sales_andi",
        "source_channel": "whatsapp",
        "created_at": "2026-08-15T08:00:00+00:00",
        "updated_at": "2026-08-15T08:05:00+00:00",
        "audit_events": [{"action": "open", "actor_ref": "ACTOR-001", "at": "2026-08-15T08:00:00+00:00"}],
    }


class InvoiceReviewViewModelTests(unittest.TestCase):
    def test_build_view_header_fields(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER",), actor_ref="ACTOR-002", opener_ref=_OPENER)
        self.assertEqual(vm.state, "REVIEW")
        self.assertEqual(vm.unit_display_name, "Banyumedia")
        self.assertEqual(vm.issuer_ref, "ISSUER-PT-TKH")
        self.assertEqual(vm.invoice_type, "INVOICE")
        self.assertEqual(vm.reference, "DFT-000001")

    def test_build_view_branding_separate_from_policy(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER",), actor_ref="ACTOR-002", opener_ref=_OPENER)
        self.assertEqual(vm.branding_block["template_ref"], "tpl_banyu_v1")
        self.assertEqual(vm.branding_block["logo_asset_ref"], "logo_banyu_v1")
        self.assertEqual(vm.policy_card["issuer_ref"], "ISSUER-PT-TKH")
        self.assertEqual(vm.policy_card["tax_profile_ref"], "TAX-PPN-11")
        self.assertEqual(vm.policy_card["destination_account_alias"], "ACC-[REDACTED]")
        self.assertNotEqual(vm.branding_block, vm.policy_card)

    def test_build_view_main_and_audit(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER",), actor_ref="ACTOR-002", opener_ref=_OPENER)
        self.assertEqual(vm.customer_display, "CV Contoh")
        self.assertEqual(len(vm.line_items), 1)
        self.assertEqual(vm.total_amount, "1000000")
        self.assertEqual(vm.due_on, "2026-09-14")
        self.assertEqual(vm.audit["requester_alias"], "sales_andi")
        self.assertEqual(vm.audit["source_channel"], "whatsapp")

    def test_role_based_footer_actions(self):
        reviewer = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER",), actor_ref="ACTOR-002", opener_ref=_OPENER)
        self.assertEqual(reviewer.footer_actions, ("RETURN_FOR_CORRECTION", "CANCEL"))
        poster = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003", opener_ref=_OPENER)
        self.assertEqual(poster.footer_actions, ("POST_INVOICE", "CANCEL"))
        both = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER", "FINANCE-POSTER"), actor_ref="ACTOR-004", opener_ref=_OPENER)
        self.assertEqual(both.footer_actions, ("RETURN_FOR_CORRECTION", "POST_INVOICE", "CANCEL"))

    def test_self_post_denied_action_visibility(self):
        # Opener is _OPENER; FINANCE-POSTER who opened the draft cannot post
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref=_OPENER, opener_ref=_OPENER)
        self.assertNotIn("POST_INVOICE", vm.footer_actions)

    def test_self_post_denied_even_with_empty_audit_events(self):
        """F-03 (R1): SoD guard is fail-closed — opener==poster denies POST_INVOICE
        even when audit_events are empty (opener comes from opener_ref param)."""
        preview = _preview()
        preview["audit_events"] = []
        vm = review_view.build_view(
            preview, actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-001",
            opener_ref="ACTOR-001",
        )
        self.assertNotIn("POST_INVOICE", vm.footer_actions)
        self.assertEqual(vm.footer_actions, ("CANCEL",))

    def test_distinct_poster_still_sees_post_action(self):
        """F-03 (R1): a legitimate distinct poster still gets POST_INVOICE."""
        vm = review_view.build_view(
            _preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003",
            opener_ref="ACTOR-001",
        )
        self.assertIn("POST_INVOICE", vm.footer_actions)

    def test_post_confirmation_view_model(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003", opener_ref=_OPENER)
        confirm = review_view.build_post_confirmation(vm)
        self.assertEqual(confirm.heading, "Konfirmasi posting invoice")
        self.assertEqual(confirm.effects, (
            "official_number", "ledger_posting", "tax_issuer", "destination_account",
        ))
        self.assertEqual(confirm.focus_enter, "heading")
        self.assertEqual(confirm.focus_contained, True)
        self.assertEqual(confirm.focus_return, "trigger")
        self.assertEqual(confirm.trigger_label, "Posting invoice")

    def test_post_result_truthful_states(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003", opener_ref=_OPENER)
        posted = review_view.build_post_result(vm, outcome="POSTED", verified=True, official_ref="INV-2026-0001")
        self.assertEqual(posted.state, "posted and verified")
        self.assertIn("INV-2026-0001", posted.message)

        processing = review_view.build_post_result(vm, outcome="POSTED", verified=False, official_ref=None)
        self.assertEqual(processing.state, "processing")
        self.assertIn("Menunggu verifikasi", processing.message)

        failed = review_view.build_post_result(vm, outcome="REJECTED", verified=False, official_ref=None, reason="provider rejected")
        self.assertEqual(failed.state, "failed without mutation")
        self.assertEqual(failed.recoverable_action, "Perbaiki dan coba lagi")

        recon = review_view.build_post_result(vm, outcome="UNCERTAIN", verified=False, official_ref=None)
        self.assertEqual(recon.state, "reconciliation required")
        self.assertIn("Jangan ulangi", recon.message)

    def test_rejected_reason_never_leaks_raw_detail(self):
        """F-01 (R1): raw exception/traceback text must never reach the message."""
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003", opener_ref=_OPENER)
        hostile_reason = (
            "Traceback (most recent call last): File src/erp.py line 42 "
            "in post_invoice: UnitRefError UNIT-BANYUMEDIA customer CUST-0001"
        )
        failed = review_view.build_post_result(
            vm, outcome="REJECTED", verified=False, official_ref=None,
            reason=hostile_reason,
        )
        self.assertEqual(failed.state, "failed without mutation")
        self.assertEqual(failed.recoverable_action, "Perbaiki dan coba lagi")
        self.assertIn("gagal", failed.message.lower())
        for leak in ("Traceback", "UNIT-BANYUMEDIA", "CUST-0001", "src/erp.py", hostile_reason):
            self.assertNotIn(leak, failed.message)

    def test_no_false_posted_and_verified(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003", opener_ref=_OPENER)
        not_verified = review_view.build_post_result(vm, outcome="POSTED", verified=False, official_ref="INV-2026-0001")
        self.assertNotEqual(not_verified.state, "posted and verified")
        self.assertEqual(not_verified.state, "processing")

    def test_uncertain_state_includes_reconciliation_ref(self):
        """F-05: uncertain copy includes opaque reconciliation ref per UX_SPEC §8."""
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003", opener_ref=_OPENER)
        with_ref = review_view.build_post_result(
            vm, outcome="UNCERTAIN", verified=False, official_ref=None,
            reconciliation_ref="REC-2026-0007",
        )
        self.assertEqual(with_ref.state, "reconciliation required")
        self.assertIn("REC-2026-0007", with_ref.message)
        self.assertIn("referensi", with_ref.message.lower())
        self.assertEqual(with_ref.reconciliation_ref, "REC-2026-0007")
        without_ref = review_view.build_post_result(
            vm, outcome="UNCERTAIN", verified=False, official_ref=None,
        )
        self.assertIsNone(without_ref.reconciliation_ref)
        self.assertIn("Jangan ulangi", without_ref.message)
        self.assertNotIn("None", without_ref.message)

    def test_error_state_preserves_context(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003", opener_ref=_OPENER)
        err = review_view.build_error_state(vm, error_code="STALE_PREVIEW", recoverable_action="Muat ulang pratinjau")
        self.assertEqual(err.error_summary, "Terjadi kesalahan")
        self.assertEqual(err.error_links, ("preview",))
        self.assertEqual(err.context_preserved["draft_id"], "DFT-000001")
        self.assertEqual(err.recoverable_action, "Muat ulang pratinjau")

    def test_denied_state_generic_no_disclosure(self):
        vm = review_view.build_denied_view(unit_ref="UNIT-BANYUMEDIA")
        self.assertEqual(vm.message, "Anda tidak memiliki akses untuk tindakan ini pada unit tersebut.")
        self.assertEqual(vm.escalation_path, "Hubungi controller keuangan")
        self.assertIsNone(vm.unit_ref)
        self.assertIsNone(vm.customer_ref)

    def test_responsive_compact_variant(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER",), actor_ref="ACTOR-002", opener_ref=_OPENER)
        compact = review_view.to_responsive_variant(vm, viewport="compact")
        self.assertEqual(compact.layout_mode, "compact")
        self.assertEqual(compact.table_representation, "labeled_cards")
        self.assertFalse(compact.horizontal_overflow)
        wide = review_view.to_responsive_variant(vm, viewport="wide")
        self.assertEqual(wide.layout_mode, "wide")
        self.assertEqual(wide.table_representation, "columns")

    def test_keyboard_and_a11y_contract_as_data(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003", opener_ref=_OPENER)
        a11y = review_view.accessibility_contract(vm)
        # Poster-only actor: RETURN_FOR_CORRECTION not in footer_actions (F-05).
        self.assertEqual(a11y.tab_order, (
            "unit_selector", "header", "branding_preview", "main_content", "policy_card",
            "audit_section", "action_post", "action_cancel",
        ))
        self.assertTrue(a11y.focus_visible)
        self.assertEqual(a11y.control_roles["action_post"], "button")
        self.assertEqual(a11y.accessible_names["action_post"], "Posting invoice")
        self.assertEqual(a11y.error_summary_position, "top")
        self.assertTrue(a11y.error_links_to_fields)
        self.assertFalse(a11y.live_region_polite)  # no async by default
        self.assertTrue(a11y.reduced_motion_disables_transitions)
        self.assertGreaterEqual(a11y.touch_target_min_px, 44)

    def test_a11y_contract_matches_available_footer_actions(self):
        """F-05 (R1): tab_order/control_roles/accessible_names only include
        action_* entries actually present in view.footer_actions."""
        # Reviewer-only: no POST_INVOICE → no action_post in the a11y contract
        reviewer = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER",), actor_ref="ACTOR-002", opener_ref=_OPENER)
        a11y = review_view.accessibility_contract(reviewer)
        self.assertNotIn("action_post", a11y.tab_order)
        self.assertNotIn("action_post", a11y.control_roles)
        self.assertNotIn("action_post", a11y.accessible_names)
        self.assertIn("action_return", a11y.tab_order)
        self.assertIn("action_cancel", a11y.tab_order)

        # Poster denied by SoD: no action_post either
        denied_poster = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref=_OPENER, opener_ref=_OPENER)
        a11y_denied = review_view.accessibility_contract(denied_poster)
        self.assertNotIn("action_post", a11y_denied.tab_order)
        self.assertNotIn("action_post", a11y_denied.control_roles)
        self.assertNotIn("action_post", a11y_denied.accessible_names)
        self.assertNotIn("action_return", a11y_denied.tab_order)

        # Full roles: all three actions present
        both = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER", "FINANCE-POSTER"), actor_ref="ACTOR-004", opener_ref=_OPENER)
        a11y_full = review_view.accessibility_contract(both)
        for action in ("action_return", "action_post", "action_cancel"):
            self.assertIn(action, a11y_full.tab_order)
            self.assertIn(action, a11y_full.control_roles)
            self.assertIn(action, a11y_full.accessible_names)

    def test_render_text_includes_sections(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER",), actor_ref="ACTOR-002", opener_ref=_OPENER)
        text = review_render.render_text(vm)
        self.assertIn("Review Invoice", text)
        self.assertIn("Branding:", text)
        self.assertIn("Kebijakan:", text)
        self.assertIn("Audit:", text)
        self.assertIn("Tindakan:", text)

    def test_render_text_compact_uses_labeled_cards(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-REVIEWER",), actor_ref="ACTOR-002", opener_ref=_OPENER)
        compact = review_view.to_responsive_variant(vm, viewport="compact")
        text = review_render.render_text(compact)
        self.assertIn("[Kartu]", text)

    def test_build_view_rejects_wrong_type(self):
        with self.assertRaises(TypeError):
            review_view.build_view("not a preview", actor_roles=("FINANCE-REVIEWER",), actor_ref="ACTOR-002", opener_ref=_OPENER)

    def test_copy_matches_ux_spec_examples(self):
        vm = review_view.build_view(_preview(), actor_roles=("FINANCE-POSTER",), actor_ref="ACTOR-003", opener_ref=_OPENER)
        confirm = review_view.build_post_confirmation(vm)
        self.assertIn("Periksa penerbit dan rekening", confirm.warning)
        posted = review_view.build_post_result(vm, outcome="POSTED", verified=True, official_ref="INV-2026-0001")
        self.assertIn("Invoice berhasil diposting dan diverifikasi di ERP", posted.message)


if __name__ == "__main__":
    unittest.main()
