"""RED-first tests for FLOW-002: invoice review and posting.

Covers R-004 (review separation), R-005 (fenced post/readback), R-006/R-007
(idempotency, audit), R-008 (outbox), R-016/R-017/R-019 (financial identity
from policy, not branding), R-020 (immutable branding/config snapshot),
R-021 (multi-unit isolation), R-022 (configuration version conflict).

Official number exists only after verified post; delivery is orthogonal.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone


def _t(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _build_workflow():
    """Wire the workflow with fixture dependencies. RED: module absent."""
    from src.adapters.fixture.erp import FixtureErpAdapter
    from src.authz.access import ActorUnitAssignment, IdentityBinding
    from src.contracts.financial_identity import FinancialIdentity
    from src.policy.financial_identity import (
        FinancialIdentityPolicy,
        FinancialPolicyResolver,
        TrustedIssuer,
    )
    from src.units.registry import UnitRegistry
    from src.units.settings import UnitSettingsStore
    from src.workflows.invoice_draft.workflow import InvoiceDraftWorkflow
    from src.workflows.invoice_post.workflow import InvoicePostWorkflow

    registry = UnitRegistry.default()
    settings = UnitSettingsStore(registry)
    # Active settings for two units with distinct branding/template refs.
    draft_b = settings.draft(
        "BANYUMEDIA",
        {"default_currency": "IDR", "invoice_template_ref": "tpl_banyu_v1",
         "logo_asset_ref": "logo_banyu_v1", "payment_terms_days": 14,
         "enabled_modules": ("invoicing",)},
        author="alice", at=_t(),
    )
    settings.activate("BANYUMEDIA", draft_b.configuration_version,
                      expected_version=0, at=_t(1), actor="bos",
                      effective_from=_t(2))
    draft_p = settings.draft(
        "PR1ME",
        {"default_currency": "IDR", "invoice_template_ref": "tpl_pr1me_v1",
         "logo_asset_ref": "logo_pr1me_v1", "payment_terms_days": 7,
         "enabled_modules": ("invoicing",)},
        author="alice", at=_t(),
    )
    settings.activate("PR1ME", draft_p.configuration_version,
                      expected_version=0, at=_t(1), actor="bos",
                      effective_from=_t(2))

    issuer = TrustedIssuer("ISSUER-AUTH-ROOT", b"synthetic-fixture-key-01")
    identity_b = FinancialIdentity(
        "UNIT-BANYUMEDIA", "ISSUER-BANYUMEDIA", "TAX-NONPPN",
        "SERIES-BYM", "LEDGER-BYM", "ACC-BANYUMEDIA",
    )
    identity_p = FinancialIdentity(
        "UNIT-PR1ME", "ISSUER-PR1ME", "TAX-NONPPN",
        "SERIES-PR1", "LEDGER-PR1", "ACC-PR1ME",
    )
    catalog = issuer.issue_catalog("CATALOG-FLOW2", 1, "EVIDENCE-FLOW2",
                                   (identity_b, identity_p))
    policies = (
        FinancialIdentityPolicy(
            policy_ref="POLICY-BYM-1", policy_version=1,
            operating_unit_ref="UNIT-BANYUMEDIA",
            legal_issuer_ref="ISSUER-BANYUMEDIA", tax_profile_ref="TAX-NONPPN",
            invoice_series_ref="SERIES-BYM", receivable_ledger_ref="LEDGER-BYM",
            destination_account_alias="ACC-BANYUMEDIA", currency="IDR",
            effective_from=_t(), effective_until=None, active=True,
        ),
        FinancialIdentityPolicy(
            policy_ref="POLICY-PR1-1", policy_version=1,
            operating_unit_ref="UNIT-PR1ME",
            legal_issuer_ref="ISSUER-PR1ME", tax_profile_ref="TAX-NONPPN",
            invoice_series_ref="SERIES-PR1", receivable_ledger_ref="LEDGER-PR1",
            destination_account_alias="ACC-PR1ME", currency="IDR",
            effective_from=_t(), effective_until=None, active=True,
        ),
    )
    resolver = FinancialPolicyResolver(policies, compatibility_catalog=catalog)
    adapter = FixtureErpAdapter()
    draft_wf = InvoiceDraftWorkflow(
        registry=registry, settings=settings, resolver=resolver, adapter=adapter,
    )
    post_wf = InvoicePostWorkflow(
        registry=registry, settings=settings, resolver=resolver, adapter=adapter,
        draft_workflow=draft_wf,
    )
    return draft_wf, post_wf, adapter, settings


def _requester_assignment(unit_ref: str, revision: int = 1):
    from src.authz.access import ActorUnitAssignment
    return ActorUnitAssignment(
        actor_ref="ACTOR-REQUESTER", unit_ref=unit_ref,
        roles=("FINANCE-REQUESTER",), active=True,
        assignment_ref="ASSIGNMENT-REQ", revision=revision,
    )


def _reviewer_assignment(unit_ref: str, revision: int = 1):
    from src.authz.access import ActorUnitAssignment
    return ActorUnitAssignment(
        actor_ref="ACTOR-REVIEWER", unit_ref=unit_ref,
        roles=("FINANCE-POSTER",), active=True,
        assignment_ref="ASSIGNMENT-REV", revision=revision,
    )


def _requester_binding():
    from src.authz.access import IdentityBinding
    return IdentityBinding(actor_ref="ACTOR-REQUESTER", channel_ref="CHANNEL-WA-1", active=True)


def _reviewer_binding(channel_ref: str = "CHANNEL-WA-1"):
    from src.authz.access import IdentityBinding
    return IdentityBinding(actor_ref="ACTOR-REVIEWER", channel_ref=channel_ref, active=True)


def _lines():
    return ({"service_ref": "SVC-ADS-01", "description": "Ads management",
             "quantity": "1", "unit_price_amount": "1500000", "currency": "IDR"},)


def _open_and_preview(draft_wf):
    handle = draft_wf.open_draft(
        actor_ref="ACTOR-REQUESTER", channel_ref="CHANNEL-WA-1",
        binding=_requester_binding(),
        assignments=(_requester_assignment("UNIT-BANYUMEDIA"),),
        customer_ref="CUST-1", at=_t(3),
    )
    draft_wf.set_lines(handle.draft_id, _lines(),
                       actor_ref="ACTOR-REQUESTER", at=_t(4),
                       binding=_requester_binding(),
                       assignments=(_requester_assignment("UNIT-BANYUMEDIA"),))
    preview = draft_wf.preview(
        handle.draft_id, actor_ref="ACTOR-REQUESTER",
        binding=_requester_binding(),
        assignments=(_requester_assignment("UNIT-BANYUMEDIA"),),
        at=_t(5),
    )
    return handle, preview


class TestReviewSeparation(unittest.TestCase):
    """R-004: post requires a different actor/reviewer role than draft opener."""

    def test_post_requires_invoice_post_action(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        # Requester (FINANCE-REQUESTER) lacks INVOICE_POST permission
        with self.assertRaises(Exception) as ctx:
            post_wf.post(
                preview,
                actor_ref="ACTOR-REQUESTER", at=_t(6),
                binding=_requester_binding(),
                assignments=(_requester_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("not be authorized", str(ctx.exception))

    def test_post_succeeds_with_reviewer_role(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertTrue(result.official_ref.startswith("INV-"))

    def test_reviewer_cannot_post_without_invoice_post_action(self) -> None:
        """Requester role lacks INVOICE_POST; only reviewer can post."""
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        with self.assertRaises(Exception) as ctx:
            post_wf.post(
                preview,
                actor_ref="ACTOR-REQUESTER", at=_t(6),
                binding=_requester_binding(),
                assignments=(_requester_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("not be authorized", str(ctx.exception))


class TestPostOutcomes(unittest.TestCase):
    """R-005/R-006/R-007: fenced post/readback with explicit outcomes."""

    def test_posted_returns_official_reference(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.outcome, "POSTED")
        self.assertTrue(result.official_ref.startswith("INV-"))
        # Verify via adapter read-back
        record = adapter.read_invoice(result.official_ref)
        self.assertEqual(record.status, "POSTED")

    def test_rejected_leaves_no_official_number(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.fail_next_post("REJECTED")
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.outcome, "REJECTED")
        self.assertIsNone(result.official_ref)

    def test_uncertain_triggers_reconcile_not_blind_retry(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.fail_next_post("UNCERTAIN")
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.outcome, "UNCERTAIN")
        self.assertIsNone(result.official_ref)
        # Reconcile classifies without blind retry
        reconciled = post_wf.reconcile_post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(7),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(reconciled.outcome, "POSTED")
        self.assertTrue(reconciled.official_ref.startswith("INV-"))


class TestImmutableBrandingConfigSnapshot(unittest.TestCase):
    """R-020/R-022: posted invoice keeps frozen branding/config snapshot."""

    def test_post_freezes_template_and_logo(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        record = post_wf.get_posted_invoice(result.official_ref)
        self.assertEqual(record.invoice_template_ref, "tpl_banyu_v1")
        self.assertEqual(record.logo_asset_ref, "logo_banyu_v1")
        self.assertEqual(record.configuration_version, 1)

    def test_later_settings_change_does_not_rewrite_posted_pdf(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        # Activate new settings version with different branding
        draft_b2 = settings.draft(
            "BANYUMEDIA",
            {"default_currency": "IDR", "invoice_template_ref": "tpl_banyu_v2",
             "logo_asset_ref": "logo_banyu_v2", "payment_terms_days": 30,
             "enabled_modules": ("invoicing",)},
            author="alice", at=_t(7),
        )
        settings.activate("BANYUMEDIA", draft_b2.configuration_version,
                          expected_version=1, at=_t(8), actor="bos",
                          effective_from=_t(9))
        # Posted record must remain unchanged
        record = post_wf.get_posted_invoice(result.official_ref)
        self.assertEqual(record.invoice_template_ref, "tpl_banyu_v1")
        self.assertEqual(record.logo_asset_ref, "logo_banyu_v1")
        self.assertEqual(record.configuration_version, 1)


class TestTemplatePlaceholderSafety(unittest.TestCase):
    """R-020: template rendering uses safe substitution; no raw injection."""

    def test_pdf_reference_includes_unit_template(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        record = post_wf.get_posted_invoice(result.official_ref)
        self.assertIn("tpl_banyu_v1", record.pdf_reference)

    def test_financial_fields_never_contain_template_placeholders(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        record = post_wf.get_posted_invoice(result.official_ref)
        # Financial identity fields are exact refs, never template strings
        self.assertTrue(record.legal_issuer_ref.startswith("ISSUER-"))
        self.assertTrue(record.receivable_ledger_ref.startswith("LEDGER-"))
        self.assertTrue(record.destination_account_alias.startswith("ACC-"))
        self.assertNotIn("{{", record.legal_issuer_ref)
        self.assertNotIn("{{", record.receivable_ledger_ref)


class TestOrthogonalDelivery(unittest.TestCase):
    """R-008: delivery outbox is separate from post; failure does not un-post."""

    def test_delivery_enqueued_separately(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        delivery = post_wf.enqueue_delivery(
            result.official_ref, channel_ref="CHANNEL-EMAIL-1",
            actor_ref="ACTOR-REVIEWER", at=_t(7),
            binding=_reviewer_binding("CHANNEL-EMAIL-1"),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
        )
        self.assertEqual(delivery.status, "SENT")
        self.assertTrue(delivery.reference.startswith("OUT-"))

    def test_failed_delivery_does_not_unpost(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        adapter.fail_next_delivery()
        delivery = post_wf.enqueue_delivery(
            result.official_ref, channel_ref="CHANNEL-EMAIL-1",
            actor_ref="ACTOR-REVIEWER", at=_t(7),
            binding=_reviewer_binding("CHANNEL-EMAIL-1"),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
        )
        self.assertEqual(delivery.status, "FAILED_RETRYABLE")
        # Invoice remains POSTED
        record = adapter.read_invoice(result.official_ref)
        self.assertEqual(record.status, "POSTED")

    def test_delivery_retry_is_idempotent(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        adapter.fail_next_delivery()
        first = post_wf.enqueue_delivery(
            result.official_ref, channel_ref="CHANNEL-EMAIL-1",
            actor_ref="ACTOR-REVIEWER", at=_t(7),
            binding=_reviewer_binding("CHANNEL-EMAIL-1"),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
        )
        # Retry same logical entry
        second = post_wf.enqueue_delivery(
            result.official_ref, channel_ref="CHANNEL-EMAIL-1",
            actor_ref="ACTOR-REVIEWER", at=_t(8),
            binding=_reviewer_binding("CHANNEL-EMAIL-1"),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
        )
        self.assertEqual(first.reference, second.reference)
        self.assertEqual(second.status, "SENT")


class TestCancellation(unittest.TestCase):
    """Supported cancellation paths: DRAFT direct, POSTED unpaid compensating, POSTED paid rejected."""

    def test_cancel_draft_before_post(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        # Cancel via draft workflow
        draft_wf.cancel(handle.draft_id, actor_ref="ACTOR-REQUESTER", at=_t(6),
                        binding=_requester_binding(),
                        assignments=(_requester_assignment("UNIT-BANYUMEDIA"),))
        # Posting a cancelled draft must fail
        with self.assertRaises(Exception):
            post_wf.post(
                preview,
                actor_ref="ACTOR-REVIEWER", at=_t(7),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )

    def test_cancel_posted_unpaid_uses_compensating_path(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        post_wf.cancel_posted(
            result.official_ref,
            actor_ref="ACTOR-REVIEWER", at=_t(7),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        record = adapter.read_invoice(result.official_ref)
        self.assertEqual(record.status, "CANCELLED")

    def test_cancel_posted_paid_is_rejected(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        # Record full payment
        from src.contracts.erp_port import DraftPaymentCommand
        adapter.record_payment(DraftPaymentCommand(
            invoice_ref=result.official_ref,
            amount="1500000.00", currency="IDR",
            evidence_ref="EVI-PAY-1", destination_account_alias="ACC-BANYUMEDIA",
        ))
        with self.assertRaises(Exception):
            post_wf.cancel_posted(
                result.official_ref,
                actor_ref="ACTOR-REVIEWER", at=_t(7),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )


class TestAuditAndStateTransitions(unittest.TestCase):
    """R-007/R-008: all transitions and denials logged; state machine enforced."""

    def test_audit_trail_for_post(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        events = post_wf.audit_events(result.official_ref)
        actions = [e["action"] for e in events]
        self.assertIn("post", actions)
        self.assertEqual(events[0]["actor_ref"], "ACTOR-REVIEWER")

    def test_denied_events_logged(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        with self.assertRaises(Exception):
            post_wf.post(
                preview,
                actor_ref="ACTOR-REQUESTER", at=_t(6),
                binding=_requester_binding(),
                assignments=(_requester_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        denied = post_wf.denied_events()
        self.assertTrue(any(e["action"] == "post" for e in denied))

    def test_no_transition_from_cancelled_back_to_posted(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        post_wf.cancel_posted(
            result.official_ref,
            actor_ref="ACTOR-REVIEWER", at=_t(7),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        with self.assertRaises(Exception):
            post_wf.post(
                preview,
                actor_ref="ACTOR-REVIEWER", at=_t(8),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )


class TestMultiUnitIsolation(unittest.TestCase):
    """R-021: posting scoped to authorized unit; cross-unit denied."""

    def test_post_scoped_to_authorized_unit(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        # Reviewer assigned to PR1ME tries to post BANYUMEDIA invoice
        with self.assertRaises(Exception) as ctx:
            post_wf.post(
                preview,
                actor_ref="ACTOR-REVIEWER", at=_t(6),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-PR1ME"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("not be authorized", str(ctx.exception))

    def test_cross_unit_denial_discloses_nothing(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        with self.assertRaises(Exception) as ctx:
            post_wf.post(
                preview,
                actor_ref="ACTOR-REVIEWER", at=_t(6),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-PR1ME"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertNotIn("BANYUMEDIA", str(ctx.exception))


class TestConfigurationVersionConflict(unittest.TestCase):
    """R-022: preview rendered against version N refuses when active moved to N+1."""

    def test_stale_preview_config_version_blocks_post(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        # Activate new settings version
        draft_b2 = settings.draft(
            "BANYUMEDIA",
            {"default_currency": "IDR", "invoice_template_ref": "tpl_banyu_v2",
             "logo_asset_ref": "logo_banyu_v2", "payment_terms_days": 30,
             "enabled_modules": ("invoicing",)},
            author="alice", at=_t(6),
        )
        settings.activate("BANYUMEDIA", draft_b2.configuration_version,
                          expected_version=1, at=_t(7), actor="bos",
                          effective_from=_t(8))
        # Post with stale preview must fail
        with self.assertRaises(Exception) as ctx:
            post_wf.post(
                preview,
                actor_ref="ACTOR-REVIEWER", at=_t(9),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("configuration version", str(ctx.exception).lower())

    def test_fresh_preview_after_config_change_succeeds(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        draft_b2 = settings.draft(
            "BANYUMEDIA",
            {"default_currency": "IDR", "invoice_template_ref": "tpl_banyu_v2",
             "logo_asset_ref": "logo_banyu_v2", "payment_terms_days": 30,
             "enabled_modules": ("invoicing",)},
            author="alice", at=_t(6),
        )
        settings.activate("BANYUMEDIA", draft_b2.configuration_version,
                          expected_version=1, at=_t(7), actor="bos",
                          effective_from=_t(8))
        # Re-preview with new config version
        fresh_preview = draft_wf.preview(
            handle.draft_id, actor_ref="ACTOR-REQUESTER",
            binding=_requester_binding(),
            assignments=(_requester_assignment("UNIT-BANYUMEDIA"),),
            at=_t(9),
        )
        result = post_wf.post(
            fresh_preview,
            actor_ref="ACTOR-REVIEWER", at=_t(10),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.outcome, "POSTED")


class TestOfficialNumberOnlyAfterVerifiedPost(unittest.TestCase):
    """No draft/reference assigned before post_invoice returns POSTED."""

    def test_no_official_number_before_post(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        # Adapter has no knowledge of the DFT-* ref (no draft created yet)
        from src.contracts.erp_port import DocumentRejected
        with self.assertRaises(DocumentRejected):
            adapter.read_invoice(handle.draft_id)
        # After post, official ref exists
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertIsNotNone(result.official_ref)
        posted = adapter.read_invoice(result.official_ref)
        self.assertEqual(posted.status, "POSTED")


class TestPostedFinancialSnapshot(unittest.TestCase):
    """R-016/R-017/R-019: financial identity frozen from policy, not branding."""

    def test_posted_snapshot_uses_policy_identity(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        record = post_wf.get_posted_invoice(result.official_ref)
        self.assertEqual(record.legal_issuer_ref, "ISSUER-BANYUMEDIA")
        self.assertEqual(record.tax_profile_ref, "TAX-NONPPN")
        self.assertEqual(record.invoice_series_ref, "SERIES-BYM")
        self.assertEqual(record.receivable_ledger_ref, "LEDGER-BYM")
        self.assertEqual(record.destination_account_alias, "ACC-BANYUMEDIA")

    def test_posted_snapshot_includes_policy_version(self) -> None:
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = post_wf.post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(6),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        record = post_wf.get_posted_invoice(result.official_ref)
        self.assertEqual(record.policy_ref, "POLICY-BYM-1")
        self.assertEqual(record.policy_version, 1)


if __name__ == "__main__":
    unittest.main()
