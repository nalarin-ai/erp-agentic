"""Tests for ui.unit_selector (UX_SPEC §1, §7)."""
from __future__ import annotations

import unittest

from ui.invoice_review import unit_selector


def _assignments() -> tuple:
    return (
        {"actor_ref": "ACTOR-001", "unit_ref": "UNIT-BANYUMEDIA", "roles": ("FINANCE-REVIEWER",), "active": True},
        {"actor_ref": "ACTOR-001", "unit_ref": "UNIT-CONTRACTOR", "roles": ("FINANCE-REVIEWER",), "active": True},
    )


def _single_assignment() -> tuple:
    return (
        {"actor_ref": "ACTOR-001", "unit_ref": "UNIT-BANYUMEDIA", "roles": ("FINANCE-REVIEWER",), "active": True},
    )


class UnitSelectorTests(unittest.TestCase):
    def test_multi_unit_selector_contains_only_assigned_active(self):
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BANYUMEDIA")
        self.assertEqual(vm.state, "READY")
        self.assertEqual(len(vm.units), 2)
        self.assertEqual(vm.units[0]["unit_ref"], "UNIT-BANYUMEDIA")
        self.assertEqual(vm.units[0]["selected"], True)
        self.assertEqual(vm.units[1]["unit_ref"], "UNIT-CONTRACTOR")
        self.assertEqual(vm.units[1]["selected"], False)
        self.assertEqual(vm.active_unit_label, "Banyumedia")

    def test_single_unit_selector_shows_active_unit(self):
        vm = unit_selector.build_view(_single_assignment(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BANYUMEDIA")
        self.assertEqual(vm.state, "SINGLE_UNIT")
        self.assertEqual(vm.active_unit_label, "Banyumedia")
        self.assertEqual(len(vm.units), 1)

    def test_empty_assignment_safe_state(self):
        vm = unit_selector.build_view((), actor_ref="ACTOR-001", current_unit_ref=None)
        self.assertEqual(vm.state, "EMPTY")
        self.assertIn("belum memiliki akses unit", vm.message.lower())
        self.assertIsNone(vm.active_unit_label)

    def test_revoked_assignment_safe_state(self):
        revoked = (
            {"actor_ref": "ACTOR-001", "unit_ref": "UNIT-BANYUMEDIA", "roles": ("FINANCE-REVIEWER",), "active": False},
        )
        vm = unit_selector.build_view(revoked, actor_ref="ACTOR-001", current_unit_ref=None)
        self.assertEqual(vm.state, "REVOKED")
        self.assertIn("akses unit telah dinonaktifkan", vm.message.lower())
        self.assertEqual(vm.escalation_path, "Hubungi administrator")

    def test_stale_context_safe_state(self):
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BANYUMEDIA", stale=True)
        self.assertEqual(vm.state, "STALE")
        self.assertIn("konteks unit tidak valid", vm.message.lower())
        self.assertEqual(vm.recoverable_action, "Muat ulang")

    def test_exactly_one_selection_required(self):
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref=None)
        self.assertEqual(vm.state, "SELECT_REQUIRED")
        self.assertIn("pilih satu unit", vm.message.lower())

    def test_switch_confirmation_when_draft_exists(self):
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BANYUMEDIA")
        confirm = unit_selector.build_switch_confirmation(vm, target_unit_ref="UNIT-CONTRACTOR", draft_exists=True)
        self.assertEqual(confirm.heading, "Konfirmasi ganti unit")
        self.assertTrue(confirm.draft_exists)
        self.assertIn("perubahan yang belum disimpan", confirm.warning.lower())
        self.assertEqual(confirm.effects, ("clear_scoped_results", "invalidate_preview_hash", "reload_options"))
        self.assertEqual(confirm.focus_return, "unit_control")

    def test_switch_no_confirmation_when_no_draft(self):
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BANYUMEDIA")
        confirm = unit_selector.build_switch_confirmation(vm, target_unit_ref="UNIT-CONTRACTOR", draft_exists=False)
        self.assertFalse(confirm.draft_exists)
        self.assertEqual(confirm.heading, "Konfirmasi ganti unit")

    def test_keyboard_a11y_contract(self):
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BANYUMEDIA")
        a11y = unit_selector.accessibility_contract(vm)
        self.assertEqual(a11y.tab_order, ("unit_selector_button", "unit_list", "unit_option_0", "unit_option_1"))
        self.assertTrue(a11y.focus_visible)
        self.assertEqual(a11y.control_roles["unit_selector_button"], "button")
        self.assertEqual(a11y.control_roles["unit_list"], "listbox")
        self.assertEqual(a11y.accessible_names["unit_selector_button"], "Pilih unit aktif")
        self.assertTrue(a11y.dismissable)
        self.assertEqual(a11y.focus_return, "unit_control")

    def test_compact_variant(self):
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BANYUMEDIA")
        compact = unit_selector.to_responsive_variant(vm, viewport="compact")
        self.assertEqual(compact.layout_mode, "compact")
        self.assertEqual(compact.list_representation, "dropdown_sheet")
        wide = unit_selector.to_responsive_variant(vm, viewport="wide")
        self.assertEqual(wide.layout_mode, "wide")
        self.assertEqual(wide.list_representation, "dropdown_menu")

    def test_render_text(self):
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BANYUMEDIA")
        text = unit_selector.render_text(vm)
        self.assertIn("Unit aktif: Banyumedia", text)
        self.assertIn("Banyumedia", text)
        self.assertIn("Contractor", text)

    def test_render_text_denied_no_unit_names(self):
        vm = unit_selector.build_view((), actor_ref="ACTOR-001", current_unit_ref=None)
        text = unit_selector.render_text(vm)
        self.assertNotIn("Banyumedia", text)
        self.assertNotIn("Contractor", text)

    def test_build_view_rejects_wrong_type(self):
        with self.assertRaises(TypeError):
            unit_selector.build_view("not assignments", actor_ref="ACTOR-001", current_unit_ref=None)

    def test_foreign_current_unit_ref_stale_no_disclosure(self):
        """F-04: a current_unit_ref not among assigned units must yield STALE, no foreign unit label."""
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BALONESIA")
        self.assertEqual(vm.state, "STALE")
        self.assertEqual(vm.units, ())
        self.assertIsNone(vm.active_unit_label)
        self.assertNotIn("Balonesia", vm.message or "")
        self.assertNotIn("UNIT-BALONESIA", vm.message or "")
        self.assertEqual(vm.recoverable_action, "Muat ulang")

    def test_switch_confirmation_rejects_non_member_target(self):
        """F-04: build_switch_confirmation must reject a target not in assigned units."""
        vm = unit_selector.build_view(_assignments(), actor_ref="ACTOR-001", current_unit_ref="UNIT-BANYUMEDIA")
        with self.assertRaises(ValueError) as ctx:
            unit_selector.build_switch_confirmation(vm, target_unit_ref="UNIT-BALONESIA", draft_exists=False)
        self.assertNotIn("Balonesia", str(ctx.exception))
        # member target still works
        confirm = unit_selector.build_switch_confirmation(vm, target_unit_ref="UNIT-CONTRACTOR", draft_exists=False)
        self.assertEqual(confirm.heading, "Konfirmasi ganti unit")


if __name__ == "__main__":
    unittest.main()
