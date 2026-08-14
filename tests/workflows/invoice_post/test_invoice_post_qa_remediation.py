"""RED-first regression tests for FLOW-002 independent QA findings F-01..F-12.

Every test in this module was RED against the pre-remediation workflow and
turns GREEN only after the corresponding fix lands.
"""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone


def _t(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _build_workflow():
    from src.adapters.fixture.erp import FixtureErpAdapter
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


def _post(post_wf, preview, at=_t(6), actor_ref="ACTOR-REVIEWER"):
    return post_wf.post(
        preview,
        actor_ref=actor_ref, at=at,
        binding=_reviewer_binding(),
        assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
        channel_ref="CHANNEL-WA-1",
    )


class TestF01ForgedPreview(unittest.TestCase):
    """F-01: caller-supplied Preview fields must be recomputed and verified."""

    def _assert_forged_denied(self, draft_wf, post_wf, preview):
        from src.workflows.invoice_post.workflow import WorkflowDenied
        with self.assertRaises(WorkflowDenied) as ctx:
            _post(post_wf, preview)
        self.assertEqual(ctx.exception.code, "PREVIEW_HASH_MISMATCH")
        self.assertTrue(
            any(e["code"] == "PREVIEW_HASH_MISMATCH" and e["action"] == "post"
                for e in post_wf.denied_events())
        )

    def test_forged_hash_denied(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        forged = replace(preview, preview_hash="0" * 64)
        self._assert_forged_denied(draft_wf, post_wf, forged)

    def test_forged_total_denied(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        forged = replace(preview, total_amount="1.00")
        self._assert_forged_denied(draft_wf, post_wf, forged)

    def test_forged_customer_denied(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        forged = replace(preview, customer_ref="CUST-2")
        self._assert_forged_denied(draft_wf, post_wf, forged)

    def test_forged_template_denied(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        forged = replace(preview, invoice_template_ref="tpl_evil")
        self._assert_forged_denied(draft_wf, post_wf, forged)

    def test_forged_unit_denied(self):
        from src.workflows.invoice_post.workflow import WorkflowDenied
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        forged = replace(preview, unit_ref="UNIT-PR1ME")
        # Authorize against the forged unit so the ONLY thing standing between
        # the caller and a provider write is the preview-authenticity check.
        with self.assertRaises(WorkflowDenied) as ctx:
            post_wf.post(
                forged,
                actor_ref="ACTOR-REVIEWER", at=_t(6),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-PR1ME"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(ctx.exception.code, "PREVIEW_HASH_MISMATCH")

    def test_forged_issuer_denied(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        forged = replace(preview, legal_issuer_ref="ISSUER-EVIL")
        self._assert_forged_denied(draft_wf, post_wf, forged)

    def test_forged_reconcile_denied(self):
        from src.workflows.invoice_post.workflow import WorkflowDenied
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.fail_next_post("UNCERTAIN")
        _post(post_wf, preview)
        forged = replace(preview, customer_ref="CUST-2")
        with self.assertRaises(WorkflowDenied) as ctx:
            post_wf.reconcile_post(
                forged,
                actor_ref="ACTOR-REVIEWER", at=_t(7),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(ctx.exception.code, "PREVIEW_HASH_MISMATCH")


class TestF02SelfPostDenied(unittest.TestCase):
    """F-02: draft opener cannot post their own draft."""

    def test_opener_with_poster_role_cannot_self_post(self):
        from src.authz.access import ActorUnitAssignment, IdentityBinding
        from src.workflows.invoice_post.workflow import WorkflowDenied
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        # Same actor opens AND posts — grant them FINANCE-POSTER role so only
        # the self-post guard stands in the way.
        assignment = ActorUnitAssignment(
            actor_ref="ACTOR-REQUESTER", unit_ref="UNIT-BANYUMEDIA",
            roles=("FINANCE-POSTER",), active=True,
            assignment_ref="ASSIGNMENT-SELF", revision=1,
        )
        binding = IdentityBinding(actor_ref="ACTOR-REQUESTER",
                                  channel_ref="CHANNEL-WA-1", active=True)
        with self.assertRaises(WorkflowDenied) as ctx:
            post_wf.post(
                preview,
                actor_ref="ACTOR-REQUESTER", at=_t(6),
                binding=binding, assignments=(assignment,),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(ctx.exception.code, "SELF_POST_DENIED")
        self.assertTrue(
            any(e["code"] == "SELF_POST_DENIED" for e in post_wf.denied_events())
        )


class TestF03UncertainRepostBlocked(unittest.TestCase):
    """F-03: re-post after UNCERTAIN must raise WorkflowBlocked, not duplicate."""

    def test_repost_while_pending_uncertain_blocked(self):
        from src.workflows.invoice_post.workflow import WorkflowBlocked
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.fail_next_post("UNCERTAIN")
        result = _post(post_wf, preview)
        self.assertEqual(result.outcome, "UNCERTAIN")
        with self.assertRaises(WorkflowBlocked):
            _post(post_wf, preview, at=_t(7))
        # Reconcile still works
        reconciled = post_wf.reconcile_post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(8),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(reconciled.outcome, "POSTED")
        self.assertTrue(reconciled.official_ref.startswith("INV-"))


class TestF04ReconcileStaleConfig(unittest.TestCase):
    """F-04: reconcile_post must refuse a stale configuration version."""

    def test_reconcile_with_stale_preview_blocked(self):
        from src.workflows.invoice_post.workflow import WorkflowBlocked
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.fail_next_post("UNCERTAIN")
        _post(post_wf, preview)
        # Move config to v2 while post is pending
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
        with self.assertRaises(WorkflowBlocked) as ctx:
            post_wf.reconcile_post(
                preview,
                actor_ref="ACTOR-REVIEWER", at=_t(10),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("configuration version", str(ctx.exception).lower())

    def test_reconcile_with_fresh_preview_succeeds(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.fail_next_post("UNCERTAIN")
        _post(post_wf, preview)
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
        fresh_preview = draft_wf.preview(
            handle.draft_id, actor_ref="ACTOR-REQUESTER",
            binding=_requester_binding(),
            assignments=(_requester_assignment("UNIT-BANYUMEDIA"),),
            at=_t(10),
        )
        reconciled = post_wf.reconcile_post(
            fresh_preview,
            actor_ref="ACTOR-REVIEWER", at=_t(11),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(reconciled.outcome, "POSTED")


class TestF05PaymentTermsDueOn(unittest.TestCase):
    """F-05: due_on derives from payment_terms_days."""

    def test_due_on_uses_payment_terms_days(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = _post(post_wf, preview, at=_t(6))
        self.assertEqual(result.outcome, "POSTED")
        record = adapter.read_invoice(result.official_ref)
        # BANYUMEDIA has payment_terms_days=14
        expected_due = (_t(6).date() + timedelta(days=14)).isoformat()
        self.assertEqual(record.issued_on, _t(6).date().isoformat())
        self.assertEqual(record.due_on, expected_due)


class TestF06AdapterExceptionTranslation(unittest.TestCase):
    """F-06: adapter contract exceptions never escape raw."""

    def test_post_during_outage_blocked_not_raw_rejected(self):
        from src.workflows.invoice_post.workflow import WorkflowBlocked
        from src.contracts.erp_port import DocumentRejected, ProviderContractError
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.simulate_outage(True)  # create_draft_invoice raises DocumentRejected
        with self.assertRaises(WorkflowBlocked):
            _post(post_wf, preview)

    def test_enqueue_delivery_on_cancelled_blocked(self):
        from src.workflows.invoice_post.workflow import WorkflowBlocked
        from src.contracts.erp_port import DocumentRejected
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = _post(post_wf, preview)
        post_wf.cancel_posted(
            result.official_ref,
            actor_ref="ACTOR-REVIEWER", at=_t(7),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        # The adapter raises DocumentRejected("only POSTED documents...") —
        # the workflow must translate it into a safe WorkflowBlocked.
        with self.assertRaises(WorkflowBlocked):
            post_wf.enqueue_delivery(
                result.official_ref, channel_ref="CHANNEL-EMAIL-1",
                actor_ref="ACTOR-REVIEWER", at=_t(8),
                binding=_reviewer_binding("CHANNEL-EMAIL-1"),
                assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            )


class TestN01StubAdapterExceptionGuards(unittest.TestCase):
    """N-01: raw provider exceptions raised by post_invoice / reconcile_post
    must be translated by the workflow (a stub adapter raises what the fixture
    adapter never raises in those positions). These tests kill the surviving
    mutants from QA round 2: removing any of these except-clauses must fail.
    """

    def _wire_stub(self, stub):
        """Rebuild the post workflow around a stub adapter wrapping the fixture."""
        draft_wf, post_wf, real_adapter, settings = _build_workflow()
        from src.workflows.invoice_post.workflow import InvoicePostWorkflow
        post_wf = InvoicePostWorkflow(
            registry=post_wf._registry, settings=settings,
            resolver=post_wf._resolver, adapter=stub(real_adapter),
            draft_workflow=draft_wf,
        )
        return draft_wf, post_wf

    def test_post_invoice_raw_document_rejected_translated(self):
        from src.contracts.erp_port import DocumentRejected
        from src.workflows.invoice_post.workflow import WorkflowBlocked

        class _Stub:
            def __init__(self, inner):
                self._inner = inner
            def __getattr__(self, name):
                return getattr(self._inner, name)
            def post_invoice(self, reference):
                raise DocumentRejected("provider-internal detail must not leak")

        draft_wf, post_wf = self._wire_stub(_Stub)
        handle, preview = _open_and_preview(draft_wf)
        with self.assertRaises(WorkflowBlocked) as ctx:
            _post(post_wf, preview)
        # safe message; provider-internal phrasing must not leak
        self.assertNotIn("provider-internal detail", str(ctx.exception))

    def test_post_invoice_raw_uncertain_outcome_becomes_uncertain_result(self):
        from src.contracts.erp_port import UncertainOutcome

        class _Stub:
            def __init__(self, inner):
                self._inner = inner
            def __getattr__(self, name):
                return getattr(self._inner, name)
            def post_invoice(self, reference):
                raise UncertainOutcome("timeout mid-commit")

        draft_wf, post_wf = self._wire_stub(_Stub)
        handle, preview = _open_and_preview(draft_wf)
        result = _post(post_wf, preview)
        self.assertEqual(result.outcome, "UNCERTAIN")
        self.assertIsNone(result.official_ref)
        # pending marker recorded: re-post must be blocked
        from src.workflows.invoice_post.workflow import WorkflowBlocked
        with self.assertRaises(WorkflowBlocked):
            _post(post_wf, preview)

    def test_reconcile_post_raw_uncertain_outcome_translated(self):
        from src.contracts.erp_port import UncertainOutcome
        from src.workflows.invoice_post.workflow import WorkflowBlocked

        class _Stub:
            def __init__(self, inner):
                self._inner = inner
            def __getattr__(self, name):
                return getattr(self._inner, name)
            def reconcile_post(self, draft_reference):
                raise UncertainOutcome("read-back timed out")

        draft_wf, post_wf = self._wire_stub(_Stub)
        handle, preview = _open_and_preview(draft_wf)
        # Drive into pending-UNCERTAIN via the REAL fixture adapter, then
        # reconcile through the stub whose reconcile_post raises.
        post_wf._adapter._inner.fail_next_post("UNCERTAIN")
        result = _post(post_wf, preview)
        self.assertEqual(result.outcome, "UNCERTAIN")
        # reconcile via stub must translate UncertainOutcome → UNCERTAIN result
        # (still pending) and never raise the raw provider exception.
        outcome = post_wf.reconcile_post(
            preview,
            actor_ref="ACTOR-REVIEWER", at=_t(7),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertIn(outcome.outcome, ("UNCERTAIN", "REJECTED"))
        self.assertIsNone(outcome.official_ref)


class TestF07RejectedCleansUpOrphanDraft(unittest.TestCase):
    """F-07: REJECTED post must not leave an orphan provider draft."""

    def test_rejected_post_cancels_provider_draft(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.fail_next_post("REJECTED")
        result = _post(post_wf, preview)
        self.assertEqual(result.outcome, "REJECTED")
        # The orphan provider draft ref is disclosed in the audit trail (F-12).
        events = post_wf.audit_events(preview.draft_id)
        rejected = [e for e in events if e["action"] == "post_rejected"]
        self.assertTrue(rejected)
        provider_draft_ref = rejected[0]["provider_draft_ref"]
        # F-07: cleanup ran — the provider-side draft is CANCELLED, never a
        # dangling DRAFT that a later reconcile could pick up.
        orphan = adapter.read_invoice(provider_draft_ref)
        self.assertEqual(orphan.status, "CANCELLED")


class TestF08DoubleCancelAndNoPending(unittest.TestCase):
    """F-08: extra guards — double cancel, reconcile with no pending."""

    def test_double_cancel_posted_blocked(self):
        from src.workflows.invoice_post.workflow import WorkflowBlocked
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = _post(post_wf, preview)
        post_wf.cancel_posted(
            result.official_ref,
            actor_ref="ACTOR-REVIEWER", at=_t(7),
            binding=_reviewer_binding(),
            assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        with self.assertRaises(WorkflowBlocked) as ctx:
            post_wf.cancel_posted(
                result.official_ref,
                actor_ref="ACTOR-REVIEWER", at=_t(8),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("already cancelled", str(ctx.exception).lower())

    def test_reconcile_with_no_pending_blocked(self):
        from src.workflows.invoice_post.workflow import WorkflowBlocked
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        with self.assertRaises(WorkflowBlocked):
            post_wf.reconcile_post(
                preview,
                actor_ref="ACTOR-REVIEWER", at=_t(6),
                binding=_reviewer_binding(),
                assignments=(_reviewer_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )


class TestF10AssignmentInAudit(unittest.TestCase):
    """F-10: selected assignment_ref is included in mutating audit entries."""

    def test_post_audit_includes_assignment_ref(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        result = _post(post_wf, preview)
        events = post_wf.audit_events(result.official_ref)
        post_events = [e for e in events if e["action"] == "post"]
        self.assertTrue(post_events)
        self.assertEqual(post_events[0].get("assignment_ref"), "ASSIGNMENT-REV")


class TestF12AuditKeying(unittest.TestCase):
    """F-12: REJECTED/UNCERTAIN audit entries include provider_draft_ref."""

    def test_rejected_audit_includes_provider_draft_ref(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.fail_next_post("REJECTED")
        _post(post_wf, preview)
        events = post_wf.audit_events(preview.draft_id)
        rejected = [e for e in events if e["action"] == "post_rejected"]
        self.assertTrue(rejected)
        self.assertIn("provider_draft_ref", rejected[0])
        self.assertTrue(rejected[0]["provider_draft_ref"].startswith("DRAFT-"))

    def test_uncertain_audit_includes_provider_draft_ref(self):
        draft_wf, post_wf, adapter, settings = _build_workflow()
        handle, preview = _open_and_preview(draft_wf)
        adapter.fail_next_post("UNCERTAIN")
        _post(post_wf, preview)
        events = post_wf.audit_events(preview.draft_id)
        uncertain = [e for e in events if e["action"] == "post_uncertain"]
        self.assertTrue(uncertain)
        self.assertIn("provider_draft_ref", uncertain[0])
        self.assertTrue(uncertain[0]["provider_draft_ref"].startswith("DRAFT-"))


if __name__ == "__main__":
    unittest.main()
