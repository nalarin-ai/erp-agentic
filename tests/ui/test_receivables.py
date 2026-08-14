"""Tests for ui.receivables (UX_SPEC §3, §4, §5, §6, §7, §11)."""
from __future__ import annotations

import unittest

from ui.receivables import view as recv_view
from ui.receivables import render as recv_render


def _aging_result() -> dict:
    return {
        "entries": [
            {
                "invoice_ref": "INV-2026-0001",
                "unit_ref": "UNIT-BANYUMEDIA",
                "customer_ref": "CUST-0001",
                "customer_display": "CV Contoh",
                "currency": "IDR",
                "total_amount": "1000000",
                "open_amount": "1000000",
                "receivable_status": "OPEN",
                "due_on": "2026-09-14",
            },
            {
                "invoice_ref": "INV-2026-0002",
                "unit_ref": "UNIT-BANYUMEDIA",
                "customer_ref": "CUST-0002",
                "customer_display": "PT Sampel",
                "currency": "IDR",
                "total_amount": "2000000",
                "open_amount": "500000",
                "receivable_status": "PARTIALLY_PAID",
                "due_on": "2026-08-20",
            },
        ],
        "total_open_amount": "1500000",
        "currency": "IDR",
        "scoped": True,
    }


def _assignments() -> tuple:
    return (
        {"actor_ref": "ACTOR-001", "unit_ref": "UNIT-BANYUMEDIA", "roles": ("FINANCE-REVIEWER",), "active": True},
    )


class ReceivablesViewTests(unittest.TestCase):
    def test_build_view_filters_with_role_scoped_defaults(self):
        vm = recv_view.build_view(_aging_result(), actor_roles=("FINANCE-REVIEWER",), assignments=_assignments())
        self.assertIn("unit", vm.filters)
        self.assertIn("issuer", vm.filters)
        self.assertIn("sales_owner", vm.filters)
        self.assertIn("customer", vm.filters)
        self.assertIn("status", vm.filters)
        self.assertIn("aging_bucket", vm.filters)
        self.assertIn("due_date", vm.filters)
        self.assertEqual(vm.filters["unit"]["default"], "UNIT-BANYUMEDIA")
        self.assertTrue(vm.filters["unit"]["locked"])

    def test_build_view_rows_fields_and_status_tone(self):
        vm = recv_view.build_view(_aging_result(), actor_roles=("FINANCE-REVIEWER",), assignments=_assignments())
        self.assertEqual(len(vm.rows), 2)
        row = vm.rows[0]
        self.assertEqual(row["customer_display"], "CV Contoh")
        self.assertEqual(row["unit_ref"], "UNIT-BANYUMEDIA")
        self.assertEqual(row["invoice_ref"], "INV-2026-0001")
        self.assertEqual(row["due_on"], "2026-09-14")
        self.assertEqual(row["open_amount"], "1000000")
        self.assertEqual(row["status_label"], "Terbuka")
        self.assertEqual(row["status_tone"], "warning")
        self.assertEqual(row["allowed_actions"], ("record_payment", "view_detail"))
        partial = vm.rows[1]
        self.assertEqual(partial["status_label"], "Sebagian dibayar")
        self.assertEqual(partial["status_tone"], "info")

    def test_status_never_color_alone(self):
        vm = recv_view.build_view(_aging_result(), actor_roles=("FINANCE-REVIEWER",), assignments=_assignments())
        for row in vm.rows:
            self.assertIn("status_label", row)
            self.assertIn("status_tone", row)
            self.assertIsInstance(row["status_label"], str)
            self.assertIsInstance(row["status_tone"], str)

    def test_owner_rollup_labeled_as_aggregation(self):
        rollup = {
            "per_unit": [
                {"unit_ref": "UNIT-BANYUMEDIA", "open_amount_total": "1500000", "currency": "IDR", "open_invoice_count": 2},
                {"unit_ref": "UNIT-CONTRACTOR", "open_amount_total": "3000000", "currency": "IDR", "open_invoice_count": 1},
            ],
            "owner_open_amount_total": "4500000",
            "currency": "IDR",
            "as_of": "2026-08-15T10:00:00+00:00",
            "scoped": True,
        }
        vm = recv_view.build_owner_rollup_view(rollup)
        self.assertTrue(vm.is_aggregation)
        self.assertEqual(vm.aggregation_label, "Agregasi lintas unit (bukan ledger gabungan)")
        self.assertEqual(len(vm.unit_rows), 2)
        self.assertEqual(vm.owner_total, "4500000")

    def test_owner_rollup_mixed_currency_no_total(self):
        """F-09 (R1): mixed-currency rollup must NOT present a summed total.
        The service contract (src/reports/owner/roll_up.py) sets
        owner_open_amount_total=None and currency=None when currencies mix;
        the view-model surfaces that faithfully."""
        rollup = {
            "per_unit": [
                {"unit_ref": "UNIT-BANYUMEDIA", "open_amount_total": "1500000", "currency": "IDR", "open_invoice_count": 2},
                {"unit_ref": "UNIT-CONTRACTOR", "open_amount_total": "1200", "currency": "USD", "open_invoice_count": 1},
            ],
            "owner_open_amount_total": None,
            "currency": None,
            "as_of": "2026-08-15T10:00:00+00:00",
            "scoped": True,
        }
        vm = recv_view.build_owner_rollup_view(rollup)
        self.assertTrue(vm.is_aggregation)
        self.assertEqual(vm.aggregation_label, "Agregasi lintas unit (bukan ledger gabungan)")
        self.assertIsNone(vm.owner_total)
        self.assertIsNone(vm.currency)
        self.assertEqual(len(vm.unit_rows), 2)

    def test_owner_rollup_partial_null_never_shows_total(self):
        """F-09 (R1): fail-closed — a total with currency=None (or vice versa)
        is never presented, even if the service payload is inconsistent."""
        for total, currency in (("999", None), (None, "IDR")):
            rollup = {
                "per_unit": [],
                "owner_open_amount_total": total,
                "currency": currency,
                "as_of": "2026-08-15T10:00:00+00:00",
                "scoped": True,
            }
            vm = recv_view.build_owner_rollup_view(rollup)
            self.assertIsNone(vm.owner_total)
            self.assertIsNone(vm.currency)
            self.assertTrue(vm.is_aggregation)

    def test_denied_state_generic_copy(self):
        vm = recv_view.build_denied_view()
        self.assertEqual(vm.message, "Anda tidak memiliki akses untuk tindakan ini pada unit tersebut.")
        self.assertEqual(vm.escalation_path, "Hubungi controller keuangan")

    def test_payment_evidence_form_fields(self):
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-[REDACTED]",), "max_amount": "1000000"},
        )
        self.assertEqual(vm.fields, (
            "invoice", "amount", "currency", "payment_date", "account_alias",
            "reference_alias", "evidence_upload", "note",
        ))
        self.assertEqual(vm.remaining_balance, "1000000")
        self.assertEqual(vm.currency, "IDR")
        self.assertIn("ACC-[REDACTED]", vm.account_policy_message)

    def test_payment_evidence_validation_errors(self):
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-[REDACTED]",), "max_amount": "1000000"},
        )
        err = recv_view.validate_payment_evidence(vm, {
            "invoice": "INV-2026-0001",
            "amount": "1500000",
            "currency": "IDR",
            "payment_date": "2026-08-15",
            "account_alias": "ACC-WRONG",
            "reference_alias": "REF-001",
            "evidence_upload": "evidence.pdf",
            "note": "",
        })
        self.assertEqual(err.error_summary, "Periksa kembali isian Anda")
        self.assertIn("amount", err.field_errors)
        self.assertIn("account_alias", err.field_errors)
        self.assertIn("Maksimum", err.field_errors["amount"])
        self.assertIn("tidak diizinkan", err.field_errors["account_alias"])

    def test_payment_evidence_substring_alias_rejected(self):
        """F-01: 'ACC-A' must NOT be accepted when only 'ACC-AB' is allowed."""
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-AB",), "max_amount": "1000000"},
        )
        self.assertEqual(vm.allowed_accounts, ("ACC-AB",))
        err = recv_view.validate_payment_evidence(vm, {
            "invoice": "INV-2026-0001",
            "amount": "1000000",
            "currency": "IDR",
            "payment_date": "2026-08-15",
            "account_alias": "ACC-A",
            "reference_alias": "REF-001",
            "evidence_upload": "evidence.pdf",
            "note": "",
        })
        self.assertIn("account_alias", err.field_errors)

    def test_payment_evidence_exact_allowed_alias_accepted(self):
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-AB",), "max_amount": "1000000"},
        )
        err = recv_view.validate_payment_evidence(vm, {
            "invoice": "INV-2026-0001",
            "amount": "1000000",
            "currency": "IDR",
            "payment_date": "2026-08-15",
            "account_alias": "ACC-AB",
            "reference_alias": "REF-001",
            "evidence_upload": "evidence.pdf",
            "note": "",
        })
        self.assertNotIn("account_alias", err.field_errors)

    def test_payment_evidence_missing_account_alias_required_copy(self):
        """F-02: missing account_alias must get a required-field message, not 'not allowed'."""
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-[REDACTED]",), "max_amount": "1000000"},
        )
        values = {
            "invoice": "INV-2026-0001",
            "amount": "1000000",
            "currency": "IDR",
            "payment_date": "2026-08-15",
            "reference_alias": "REF-001",
            "evidence_upload": "evidence.pdf",
            "note": "",
        }
        err = recv_view.validate_payment_evidence(vm, values)
        self.assertIn("account_alias", err.field_errors)
        self.assertIn("wajib diisi", err.field_errors["account_alias"])
        self.assertNotIn("tidak diizinkan", err.field_errors["account_alias"])

        values_with_alias = dict(values, account_alias="ACC-WRONG")
        err2 = recv_view.validate_payment_evidence(vm, values_with_alias)
        self.assertIn("tidak diizinkan", err2.field_errors["account_alias"])

    def test_payment_evidence_non_numeric_amount_distinct_message(self):
        """F-07 (R1): non-numeric amount gets its own message, never raises."""
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-[REDACTED]",), "max_amount": "1000000"},
        )
        err = recv_view.validate_payment_evidence(vm, {
            "invoice": "INV-2026-0001",
            "amount": "seratus",
            "currency": "IDR",
            "payment_date": "2026-08-15",
            "account_alias": "ACC-[REDACTED]",
            "evidence_upload": "evidence.pdf",
        })
        self.assertEqual(err.field_errors["amount"], "Jumlah harus berupa angka")
        self.assertNotIn("Maksimum", err.field_errors["amount"])

    def test_payment_evidence_invalid_remaining_balance_never_raises(self):
        """F-07 (R1): unparseable remaining_balance yields a field error, not an exception."""
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="bukan-angka",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-[REDACTED]",), "max_amount": "1000000"},
        )
        err = recv_view.validate_payment_evidence(vm, {
            "invoice": "INV-2026-0001",
            "amount": "100",
            "currency": "IDR",
            "payment_date": "2026-08-15",
            "account_alias": "ACC-[REDACTED]",
            "evidence_upload": "evidence.pdf",
        })
        self.assertEqual(err.field_errors["amount"], "Sisa tagihan tidak valid")

    def test_payment_evidence_upload_required(self):
        """F-07 (R1): evidence_upload is required — missing/empty gets a field error."""
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-[REDACTED]",), "max_amount": "1000000"},
        )
        base = {
            "invoice": "INV-2026-0001",
            "amount": "1000000",
            "currency": "IDR",
            "payment_date": "2026-08-15",
            "account_alias": "ACC-[REDACTED]",
        }
        err_missing = recv_view.validate_payment_evidence(vm, dict(base))
        self.assertEqual(err_missing.field_errors["evidence_upload"], "Bukti pembayaran wajib diunggah")
        err_empty = recv_view.validate_payment_evidence(vm, dict(base, evidence_upload=""))
        self.assertEqual(err_empty.field_errors["evidence_upload"], "Bukti pembayaran wajib diunggah")
        ok = recv_view.validate_payment_evidence(vm, dict(base, evidence_upload="evidence.pdf"))
        self.assertNotIn("evidence_upload", ok.field_errors)

    def test_duplicate_evidence_same_scope_shows_alias(self):
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-[REDACTED]",), "max_amount": "1000000"},
        )
        dup = recv_view.build_duplicate_evidence_state(vm, scope="same", existing_alias="PAY-2026-0001", existing_status="PENDING")
        self.assertEqual(dup.state, "duplicate_same_scope")
        self.assertEqual(dup.existing_record_alias, "PAY-2026-0001")
        self.assertEqual(dup.existing_record_status, "PENDING")
        self.assertIn("sudah ada", dup.message)

    def test_duplicate_evidence_same_scope_none_alias_safe_copy(self):
        """F-04 (R1): None/empty alias or status falls back to generic copy."""
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-[REDACTED]",), "max_amount": "1000000"},
        )
        for alias, status in ((None, "PENDING"), ("PAY-2026-0001", None), (None, None), ("", "")):
            dup = recv_view.build_duplicate_evidence_state(
                vm, scope="same", existing_alias=alias, existing_status=status,
            )
            self.assertEqual(dup.state, "duplicate_same_scope")
            self.assertNotIn("None", dup.message)
            self.assertIn("sudah ada", dup.message)

    def test_duplicate_evidence_cross_scope_no_disclosure(self):
        vm = recv_view.build_payment_evidence_form(
            invoice_ref="INV-2026-0001",
            remaining_balance="1000000",
            currency="IDR",
            account_policy={"allowed_accounts": ("ACC-[REDACTED]",), "max_amount": "1000000"},
        )
        dup = recv_view.build_duplicate_evidence_state(vm, scope="cross", existing_alias=None, existing_status=None)
        self.assertEqual(dup.state, "duplicate_cross_scope")
        self.assertIsNone(dup.existing_record_alias)
        self.assertIsNone(dup.existing_record_status)
        self.assertIn("konflik", dup.message.lower())
        self.assertNotIn("UNIT-", dup.message)
        self.assertNotIn("CUST-", dup.message)

    def test_responsive_compact_labeled_cards(self):
        vm = recv_view.build_view(_aging_result(), actor_roles=("FINANCE-REVIEWER",), assignments=_assignments())
        compact = recv_view.to_responsive_variant(vm, viewport="compact")
        self.assertEqual(compact.layout_mode, "compact")
        self.assertEqual(compact.table_representation, "labeled_cards")
        self.assertFalse(compact.horizontal_overflow)

    def test_accessibility_contract(self):
        vm = recv_view.build_view(_aging_result(), actor_roles=("FINANCE-REVIEWER",), assignments=_assignments())
        a11y = recv_view.accessibility_contract(vm)
        self.assertEqual(a11y.tab_order, (
            "unit_selector", "filter_bar", "receivables_table", "pagination", "summary",
        ))
        self.assertTrue(a11y.focus_visible)
        self.assertEqual(a11y.control_roles["receivables_table"], "table")
        self.assertEqual(a11y.accessible_names["filter_unit"], "Filter unit")
        self.assertEqual(a11y.error_summary_position, "top")
        self.assertTrue(a11y.error_links_to_fields)

    def test_render_text_rows(self):
        vm = recv_view.build_view(_aging_result(), actor_roles=("FINANCE-REVIEWER",), assignments=_assignments())
        text = recv_render.render_text(vm)
        self.assertIn("Piutang", text)
        self.assertIn("INV-2026-0001", text)
        self.assertIn("Terbuka", text)
        self.assertIn("Sebagian dibayar", text)

    def test_render_text_compact_labeled_cards(self):
        vm = recv_view.build_view(_aging_result(), actor_roles=("FINANCE-REVIEWER",), assignments=_assignments())
        compact = recv_view.to_responsive_variant(vm, viewport="compact")
        text = recv_render.render_text(compact)
        self.assertIn("[Kartu]", text)

    def test_empty_state(self):
        empty = recv_view.build_view({"entries": [], "total_open_amount": "0", "currency": None, "scoped": True},
                                     actor_roles=("FINANCE-REVIEWER",), assignments=_assignments())
        self.assertEqual(empty.state, "EMPTY")
        self.assertEqual(empty.empty_message, "Tidak ada piutang jatuh tempo")

    def test_loading_state(self):
        vm = recv_view.build_loading_view()
        self.assertEqual(vm.state, "LOADING")
        self.assertEqual(vm.skeleton_rows, 3)

    def test_offline_recovery_state(self):
        vm = recv_view.build_offline_view()
        self.assertEqual(vm.state, "OFFLINE")
        self.assertIn("tidak dapat terhubung", vm.message.lower())
        self.assertEqual(vm.recoverable_action, "Coba lagi")

    def test_build_view_rejects_wrong_type(self):
        with self.assertRaises(TypeError):
            recv_view.build_view("not a result", actor_roles=("FINANCE-REVIEWER",), assignments=_assignments())


if __name__ == "__main__":
    unittest.main()
