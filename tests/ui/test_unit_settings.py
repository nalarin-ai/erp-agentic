"""Tests for ui.unit_settings (UX_SPEC §12, §6, §7)."""
from __future__ import annotations

import unittest

from ui.invoice_review import unit_settings


def _settings_version() -> dict:
    return {
        "unit_code": "BANYUMEDIA",
        "configuration_version": 3,
        "status": "ACTIVE",
        "settings": {
            "default_currency": "IDR",
            "invoice_template_ref": "tpl_banyu_v1",
            "quotation_template_ref": "qtpl_banyu_v1",
            "logo_asset_ref": "logo_banyu_v1",
            "numbering_series_ref": "ser_inv_2026",
            "branding_tagline": "Kreasi Hebat",
            "payment_terms_days": 30,
            "enabled_modules": ("invoicing", "crm"),
            "approval_threshold_amount": 5000000,
        },
        "author": "ACTOR-ADMIN",
        "created_at": "2026-08-01T00:00:00+00:00",
        "effective_from": "2026-08-01T00:00:00+00:00",
        "previous_version": 2,
    }


def _draft_version() -> dict:
    return {
        "unit_code": "BANYUMEDIA",
        "configuration_version": 4,
        "status": "DRAFT",
        "settings": {
            "default_currency": "IDR",
            "invoice_template_ref": "tpl_banyu_v2",
            "quotation_template_ref": "qtpl_banyu_v1",
            "logo_asset_ref": "logo_banyu_v2",
            "numbering_series_ref": "ser_inv_2026",
            "branding_tagline": "Kreasi Hebat Baru",
            "payment_terms_days": 14,
            "enabled_modules": ("invoicing", "crm", "reports"),
            "approval_threshold_amount": 5000000,
        },
        "author": "ACTOR-ADMIN",
        "created_at": "2026-08-15T00:00:00+00:00",
        "previous_version": None,
    }


class UnitSettingsTests(unittest.TestCase):
    def test_build_view_grouped_sections(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        self.assertEqual(vm.state, "READY")
        self.assertIn("branding", vm.sections)
        self.assertIn("documents", vm.sections)
        self.assertIn("sales", vm.sections)
        self.assertIn("approval", vm.sections)
        self.assertIn("finance_mappings", vm.sections)
        self.assertIn("modules", vm.sections)
        self.assertEqual(vm.sections["branding"]["logo_asset_ref"], "logo_banyu_v1")
        self.assertEqual(vm.sections["branding"]["branding_tagline"], "Kreasi Hebat")
        self.assertEqual(vm.sections["documents"]["invoice_template_ref"], "tpl_banyu_v1")
        self.assertEqual(vm.sections["sales"]["payment_terms_days"], 30)

    def test_version_and_effective_date_displayed(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        self.assertEqual(vm.current_version, 3)
        self.assertEqual(vm.effective_from, "2026-08-01T00:00:00+00:00")

    def test_role_based_actions(self):
        admin = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        self.assertEqual(admin.allowed_actions, ("EDIT_DRAFT", "VALIDATE", "PREVIEW", "ACTIVATE", "ROLLBACK"))
        viewer = unit_settings.build_view(_settings_version(), actor_roles=("FINANCE-REVIEWER",))
        self.assertEqual(viewer.allowed_actions, ("PREVIEW",))
        self.assertTrue(viewer.read_only)

    def test_denied_state(self):
        vm = unit_settings.build_denied_view()
        self.assertEqual(vm.state, "DENIED")
        self.assertEqual(vm.message, "Anda tidak memiliki akses untuk tindakan ini pada unit tersebut.")
        self.assertEqual(vm.escalation_path, "Hubungi administrator")

    def test_typed_schema_controls_not_arbitrary_json(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        self.assertEqual(vm.control_types["default_currency"], "select")
        self.assertEqual(vm.control_types["payment_terms_days"], "number")
        self.assertEqual(vm.control_types["enabled_modules"], "checkbox_group")
        self.assertEqual(vm.control_types["branding_tagline"], "text")
        self.assertNotIn("json_editor", vm.control_types.values())

    def test_unknown_settings_keys_excluded_and_rejected(self):
        """F-06 (R1): arbitrary keys never become orphan controls and are
        rejected by validation with 'Pengaturan tidak dikenal'."""
        version = _settings_version()
        version["settings"]["evil_arbitrary_key"] = "x"
        vm = unit_settings.build_view(version, actor_roles=("UNIT-ADMIN",))
        self.assertNotIn("evil_arbitrary_key", vm.control_types)
        # Known keys still typed
        self.assertEqual(vm.control_types["default_currency"], "select")
        # No section carries the orphan control either
        for section in vm.sections.values():
            self.assertNotIn("evil_arbitrary_key", section)
        errors = unit_settings.validate_settings(vm, {"evil_arbitrary_key": "x"})
        self.assertIn("evil_arbitrary_key", errors.field_errors)
        self.assertEqual(errors.field_errors["evil_arbitrary_key"], "Pengaturan tidak dikenal")

    def test_branding_preview_separated_from_legal_identity(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        preview = unit_settings.build_branding_preview(vm)
        self.assertEqual(preview.template_ref, "tpl_banyu_v1")
        self.assertEqual(preview.logo_asset_ref, "logo_banyu_v1")
        self.assertNotIn("legal_issuer_ref", preview.fields)
        self.assertNotIn("tax_profile_ref", preview.fields)
        self.assertNotIn("destination_account_alias", preview.fields)
        self.assertEqual(preview.disclaimer, "Branding unit terpisah dari identitas legal/pajak/rekening.")

    def test_validation_errors_identify_exact_setting(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        errors = unit_settings.validate_settings(vm, {"payment_terms_days": 400, "default_currency": "IDR"})
        self.assertIn("payment_terms_days", errors.field_errors)
        self.assertIn("0..365", errors.field_errors["payment_terms_days"])
        self.assertNotIn("default_currency", errors.field_errors)

    def test_activation_confirmation_lists_effects(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        draft = _draft_version()
        confirm = unit_settings.build_activation_confirmation(vm, draft)
        self.assertEqual(confirm.heading, "Konfirmasi aktivasi pengaturan")
        self.assertEqual(confirm.affected_unit, "BANYUMEDIA")
        self.assertIn("invoice_template_ref", confirm.changed_keys)
        self.assertIn("payment_terms_days", confirm.changed_keys)
        self.assertEqual(confirm.effective_time, "2026-08-15T00:00:00+00:00")
        self.assertTrue(confirm.preview_invalidated)
        self.assertEqual(confirm.rollback_target, 3)

    def test_concurrent_version_conflict_state(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        conflict = unit_settings.build_version_conflict_state(vm, expected_version=3, actual_version=5)
        self.assertEqual(conflict.state, "VERSION_CONFLICT")
        self.assertIn("versi 3", conflict.message)
        self.assertIn("versi 5", conflict.message)
        self.assertEqual(conflict.recoverable_action, "Muat ulang pengaturan")

    def test_unsaved_changes_state(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        dirty = unit_settings.build_unsaved_changes_state(vm)
        self.assertEqual(dirty.state, "UNSAVED_CHANGES")
        self.assertIn("belum disimpan", dirty.message.lower())
        self.assertEqual(dirty.recoverable_action, "Simpan atau batalkan perubahan")

    def test_activation_success_state(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        success = unit_settings.build_activation_result(vm, outcome="ACTIVATED", new_version=4)
        self.assertEqual(success.state, "ACTIVATED")
        self.assertIn("berhasil diaktifkan", success.message)

    def test_activation_failure_state(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        failure = unit_settings.build_activation_result(vm, outcome="FAILED", reason="validation")
        self.assertEqual(failure.state, "FAILED")
        self.assertEqual(failure.recoverable_action, "Perbaiki dan coba lagi")

    def test_activation_failure_reason_never_leaks_raw_detail(self):
        """F-02 (R1): raw exception/traceback text must never reach the message."""
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        hostile_reason = (
            "Traceback (most recent call last): KeyError 'BANYUMEDIA' "
            "in activate_settings unit BANYUMEDIA"
        )
        failure = unit_settings.build_activation_result(vm, outcome="FAILED", reason=hostile_reason)
        self.assertEqual(failure.state, "FAILED")
        self.assertEqual(failure.recoverable_action, "Perbaiki dan coba lagi")
        self.assertIn("gagal", failure.message.lower())
        for leak in ("Traceback", "KeyError", "BANYUMEDIA", hostile_reason):
            self.assertNotIn(leak, failure.message)

    def test_rollback_state(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        rollback = unit_settings.build_rollback_state(vm, to_version=2)
        self.assertEqual(rollback.state, "ROLLBACK")
        self.assertIn("versi 2", rollback.message)
        self.assertEqual(rollback.recoverable_action, "Konfirmasi rollback")

    def test_responsive_variants(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        compact = unit_settings.to_responsive_variant(vm, viewport="compact")
        self.assertEqual(compact.layout_mode, "compact")
        self.assertEqual(compact.form_representation, "stacked_cards")
        wide = unit_settings.to_responsive_variant(vm, viewport="wide")
        self.assertEqual(wide.layout_mode, "wide")
        self.assertEqual(wide.form_representation, "two_column")

    def test_accessibility_contract(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        a11y = unit_settings.accessibility_contract(vm)
        self.assertEqual(a11y.tab_order, (
            "unit_selector", "section_tabs", "form_fields", "action_validate", "action_preview",
            "action_activate", "action_rollback",
        ))
        self.assertTrue(a11y.focus_visible)
        self.assertEqual(a11y.control_roles["action_activate"], "button")
        self.assertEqual(a11y.accessible_names["action_activate"], "Aktifkan pengaturan")
        self.assertEqual(a11y.error_summary_position, "top")
        self.assertTrue(a11y.error_links_to_fields)

    def test_render_text(self):
        vm = unit_settings.build_view(_settings_version(), actor_roles=("UNIT-ADMIN",))
        text = unit_settings.render_text(vm)
        self.assertIn("Pengaturan Unit: BANYUMEDIA", text)
        self.assertIn("Versi: 3", text)
        self.assertIn("Branding", text)
        self.assertIn("Dokumen", text)
        self.assertIn("Penjualan", text)

    def test_build_view_rejects_wrong_type(self):
        with self.assertRaises(TypeError):
            unit_settings.build_view("not a version", actor_roles=("UNIT-ADMIN",))


if __name__ == "__main__":
    unittest.main()
