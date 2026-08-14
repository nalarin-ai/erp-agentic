# UX Evidence Matrix — UX-001

This matrix maps every contract point in `project-control/UX_SPEC.md` (§1–§12) and every acceptance item (§9) to the concrete test(s) in `tests/ui/` that prove it. The repo UI layer is a pure-function view-model/renderer stack (no browser), so component, keyboard, focus, responsive, and copy contracts are asserted as data.

## §1 Chat draft-invoice flow / unit switching

| Contract | Test(s) |
|---|---|
| Selector contains only assigned active units; exactly one selection required | `tests/ui/test_unit_selector.py::test_multi_unit_selector_contains_only_assigned_active`, `test_exactly_one_selection_required` |
| Active unit always visible | `test_single_unit_selector_shows_active_unit`, `test_multi_unit_selector_contains_only_assigned_active` |
| Switch requires confirmation when draft exists; clears scoped results; invalidates preview/action hash; reloads options | `test_switch_confirmation_when_draft_exists`, `test_switch_no_confirmation_when_no_draft` |
| Empty assignment safe, no other-unit disclosure | `test_empty_assignment_safe_state`, `test_render_text_denied_no_unit_names` |
| Revoked assignment safe escalation | `test_revoked_assignment_safe_state` |
| Stale-context safe state with recovery | `test_stale_context_safe_state`, `test_foreign_current_unit_ref_stale_no_disclosure` |
| Switch target must be an assigned unit (generic denial otherwise) | `test_switch_confirmation_rejects_non_member_target` |
| Keyboard: reachable/operable/dismissable; focus returns to unit control | `test_keyboard_a11y_contract` |
| Post result: `posted and verified` only after read-back; else `processing` / `failed without mutation` / `reconciliation required` | `tests/ui/test_invoice_review.py::test_post_result_truthful_states`, `test_no_false_posted_and_verified` |
| §8 copy: verified success, uncertain state | `test_copy_matches_ux_spec_examples` |

## §2 Finance review screen

| Contract | Test(s) |
|---|---|
| Header: document state, unit, issuer, invoice type, reference | `test_build_view_header_fields` |
| Branding preview visually separated from legal-issuer/tax/account policy card | `test_build_view_branding_separate_from_policy` |
| Main: customer, line items, totals, due date | `test_build_view_main_and_audit` |
| Policy card: PPN state, issuer, series, account alias, validation results | `test_build_view_branding_separate_from_policy` |
| Audit section: requester, source, timestamps, changes | `test_build_view_main_and_audit` |
|| Role-based footer actions (Return for correction / Post invoice / Cancel) | `test_role_based_footer_actions` |
|| Self-post separation (opener cannot post); fail-closed via required `opener_ref` from authorized service result, never mutable audit_events | `test_self_post_denied_action_visibility`, `test_self_post_denied_even_with_empty_audit_events`, `test_distinct_poster_still_sees_post_action` |
|| Post REJECTED message sanitized — raw exception/traceback/unit/customer detail never rendered | `test_rejected_reason_never_leaks_raw_detail` |
|| Confirmation summarizes irreversible effects; focus enters heading, contained, returns to trigger | `test_post_confirmation_view_model` |
|| Error states preserve context and identify recoverable next action | `test_error_state_preserves_context` |
|| A11y contract action controls mirror footer_actions exactly (no orphan tab stops) | `test_a11y_contract_matches_available_footer_actions` |
|| Renderer covers all sections | `test_render_text_includes_sections` |

## §3 Receivables screen

| Contract | Test(s) |
|---|---|
| Filters: unit, issuer, sales owner, customer, status, aging bucket, due date | `test_build_view_filters_with_role_scoped_defaults` |
| Default filters honor role scope | `test_build_view_filters_with_role_scoped_defaults` |
| Row/card fields: safe customer identity, unit, issuer, invoice ref, due date, open amount, status, allowed actions | `test_build_view_rows_fields_and_status_tone` |
| Status communicated by text/icon plus color-never-alone (status_label + status_tone) | `test_status_never_color_alone`, `test_build_view_rows_fields_and_status_tone` |
|| Owner roll-up explicitly labeled aggregation, never merged ledger | `test_owner_rollup_labeled_as_aggregation` |
|| Mixed-currency rollup never presents a summed total (owner_total/currency None pass-through, fail-closed on partial null) | `test_owner_rollup_mixed_currency_no_total`, `test_owner_rollup_partial_null_never_shows_total` |
| Empty state with explanation | `test_empty_state` |
| Loading skeleton | `test_loading_state` |
| Offline/recovery state | `test_offline_recovery_state` |

## §4 Payment evidence flow

| Contract | Test(s) |
|---|---|
| Fields: invoice, amount, currency, payment date, account alias, reference alias, evidence upload, note | `test_payment_evidence_form_fields` |
|| Remaining-balance + account-policy validation messaging | `test_payment_evidence_validation_errors`, `test_payment_evidence_substring_alias_rejected`, `test_payment_evidence_exact_allowed_alias_accepted`, `test_payment_evidence_missing_account_alias_required_copy` |
|| Non-numeric amount gets distinct message; unparseable remaining_balance never raises; evidence_upload required | `test_payment_evidence_non_numeric_amount_distinct_message`, `test_payment_evidence_invalid_remaining_balance_never_raises`, `test_payment_evidence_upload_required` |

## §5 Permission-denied behavior

| Contract | Test(s) |
|---|---|
| Generic Indonesian copy, no existence confirmation, safe escalation path | `test_denied_state_generic_no_disclosure` (invoice review), `test_denied_state_generic_copy` (receivables), `test_denied_state` (unit settings) |

## §6 Responsive contract

| Contract | Test(s) |
|---|---|
| Compact 360–430px: no horizontal overflow; tables become labeled cards | `test_responsive_compact_variant` (review), `test_responsive_compact_labeled_cards` (receivables), `test_compact_variant` (selector), `test_responsive_variants` (settings) |
| Wide 1280+: columns/sidebar variants | same tests, `wide` assertions |
| Touch target metadata; key actions reachable without hover | `test_keyboard_and_a11y_contract_as_data`, `test_accessibility_contract` (receivables/settings/selector) |

## §7 Keyboard and accessibility

| Contract | Test(s) |
|---|---|
| Logical tab order | `test_keyboard_and_a11y_contract_as_data`, `test_accessibility_contract`, `test_keyboard_a11y_contract` |
| Visible focus on all interactive elements | same (`focus_visible`) |
| Semantic control roles + accessible names | same (`control_roles`, `accessible_names`) |
| Errors summarized at top and linked to fields | same (`error_summary_position`, `error_links_to_fields`); `test_payment_evidence_validation_errors` |
| Live regions only for real async outcomes | `test_keyboard_and_a11y_contract_as_data` (`live_region_polite=False` default) |
| Reduced motion disables non-essential transitions | `test_keyboard_and_a11y_contract_as_data` (`reduced_motion_disables_transitions`) |
| Indonesian copy, no jargon | `test_copy_matches_ux_spec_examples`, denied/empty/offline copy assertions |

## §8 Content examples

| Contract | Test(s) |
|---|---|
| Preview warning copy | `test_post_confirmation_view_model` (`Periksa penerbit dan rekening…`) |
| Verified success copy | `test_copy_matches_ux_spec_examples` |
| Uncertain state copy | `test_post_result_truthful_states` (`Jangan ulangi…`), `test_uncertain_state_includes_reconciliation_ref` |

## §9 UX acceptance evidence

| Item | Evidence |
|---|---|
| Component assertions for all state inventory items (loading/empty/error/denied/offline/success) | `test_loading_state`, `test_empty_state`, `test_offline_recovery_state`, `test_denied_state_generic_copy`, `test_post_result_truthful_states`, settings `test_denied_state`/`test_unsaved_changes_state`/`test_concurrent_version_conflict_state` |
| Draft → preview → post → receivable states | `test_build_view_*` + `test_post_result_truthful_states` + `test_build_view_rows_fields_and_status_tone` |
| Unauthorized cross-unit action denied without disclosure | `test_denied_state_generic_no_disclosure`, `test_render_text_denied_no_unit_names`, `test_duplicate_evidence_cross_scope_no_disclosure` |
| Timeout-after-mutation reconciles without duplicate (truthful states) | `test_post_result_truthful_states`, `test_no_false_posted_and_verified` |
| Multi-unit: select exactly one scoped unit; cannot reuse preview across units | `test_exactly_one_selection_required`, `test_switch_confirmation_when_draft_exists` (invalidates preview hash) |
| Branding separated from legal/tax/account; historical snapshot immutable | `test_build_view_branding_separate_from_policy`, `test_branding_preview_separated_from_legal_identity` |
| Compact/wide evidence for review and receivable pages | `test_responsive_compact_variant`, `test_responsive_compact_labeled_cards`, `test_render_text_compact_uses_labeled_cards`, `test_render_text_compact_labeled_cards` |
| Keyboard/focus audit for post confirmation and payment evidence | `test_post_confirmation_view_model`, `test_payment_evidence_validation_errors`, `test_keyboard_and_a11y_contract_as_data` |
| Independent UX/a11y review | This matrix + test suite constitutes the reviewable evidence; external reviewer sign-off recorded by parent orchestrator |

## §10 Journey/state contracts

| Journey | Test(s) |
|---|---|
| Overdue/reminder: empty state copy "tidak ada piutang jatuh tempo" | `test_empty_state` |
| Offline/retry: no false success; retry recovery | `test_offline_recovery_state`, `test_no_false_posted_and_verified` |
| Empty report: skeleton then empty explanation | `test_loading_state`, `test_empty_state` |
| Evidence rejection: privacy-safe, no payment write on conflict | `test_duplicate_evidence_same_scope_shows_alias`, `test_duplicate_evidence_cross_scope_no_disclosure` |

## §11 Duplicate payment/evidence UX

| Contract | Test(s) |
|---|---|
|| Same-scope replay shows only existing alias/status | `test_duplicate_evidence_same_scope_shows_alias` |
|| Same-scope with None/empty alias/status falls back to generic copy (no "None" rendered) | `test_duplicate_evidence_same_scope_none_alias_safe_copy` |
| Cross-scope: no matched invoice/customer/amount/account/unit disclosure; controller conflict path | `test_duplicate_evidence_cross_scope_no_disclosure` |

## §12 Unit settings UX

| Contract | Test(s) |
|---|---|
| Grouped settings: Branding, Documents, Sales, Approval, Finance mappings, Modules | `test_build_view_grouped_sections` |
| Current version + effective date | `test_version_and_effective_date_displayed` |
| Edit draft/Validate/Preview/Activate/Rollback per role; read-only state | `test_role_based_actions`, `test_denied_state` |
|| Typed-schema-driven controls; no arbitrary JSON editor; unknown keys excluded from controls and rejected by validation | `test_typed_schema_controls_not_arbitrary_json`, `test_unknown_settings_keys_excluded_and_rejected` |
| Branding preview separated from legal issuer/tax/account | `test_branding_preview_separated_from_legal_identity` |
| Validation errors identify exact setting | `test_validation_errors_identify_exact_setting` |
| Activation confirmation lists unit/changed keys/effective time/preview invalidation/rollback target | `test_activation_confirmation_lists_effects` |
| Concurrent version conflict | `test_concurrent_version_conflict_state` |
| Unsaved changes state | `test_unsaved_changes_state` |
|| Activation success/failure; FAILED message sanitized (no raw reason leak) | `test_activation_success_state`, `test_activation_failure_state`, `test_activation_failure_reason_never_leaks_raw_detail` |
| Rollback state | `test_rollback_state` |
| Compact/wide layouts, keyboard/focus order | `test_responsive_variants`, `test_accessibility_contract` |

No row without a test. Total: 81 tests in `tests/ui/`, all passing.
