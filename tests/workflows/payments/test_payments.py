"""RED-first tests for FLOW-003: payment evidence and receivables.

Covers R-006/R-007 (evidence-bound, idempotent, audited payment recording),
R-008 (reversal via compensating records only), R-013/R-017/R-019 (account
validation from policy; receivable state computed from records, never from
chat text).

Chat text alone can NEVER confirm a payment: an opaque EVI-* evidence
reference is mandatory on every record attempt.
"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone


def _t(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _build():
    """Wire workflows with fixture dependencies. RED: payments module absent."""
    from src.adapters.fixture.erp import FixtureErpAdapter
    from src.contracts.financial_identity import FinancialIdentity
    from src.policy.financial_identity import (
        FinancialIdentityPolicy,
        FinancialPolicyResolver,
        TrustedIssuer,
    )
    from src.reconciliation.engine import ReconciliationEngine
    from src.reconciliation.queue import OperatorQueue
    from src.units.registry import UnitRegistry
    from src.units.settings import UnitSettingsStore
    from src.workflows.invoice_draft.workflow import InvoiceDraftWorkflow
    from src.workflows.invoice_post.workflow import InvoicePostWorkflow
    from src.workflows.payments.workflow import PaymentWorkflow
    from src.reports.receivables.aging import ReceivablesAgingReport

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
    catalog = issuer.issue_catalog("CATALOG-FLOW3", 1, "EVIDENCE-FLOW3",
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
    queue = OperatorQueue()
    engine = ReconciliationEngine(adapter, queue)
    pay_wf = PaymentWorkflow(
        registry=registry, resolver=resolver, adapter=adapter,
        reconciliation=engine,
    )
    aging = ReceivablesAgingReport(adapter=adapter)
    return draft_wf, post_wf, pay_wf, aging, adapter, queue


def _assignment(actor_ref: str, unit_ref: str, roles: tuple[str, ...],
                assignment_ref: str):
    from src.authz.access import ActorUnitAssignment
    return ActorUnitAssignment(
        actor_ref=actor_ref, unit_ref=unit_ref, roles=roles, active=True,
        assignment_ref=assignment_ref, revision=1,
    )


def _finance_assignment(unit_ref: str):
    return _assignment("ACTOR-FIN", unit_ref, ("FINANCE-REQUESTER",), "ASSIGNMENT-FIN")


def _viewer_assignment(unit_ref: str):
    return _assignment("ACTOR-VIEWER", unit_ref, ("FINANCE-REVIEWER",), "ASSIGNMENT-VIEW")


def _fin_binding():
    from src.authz.access import IdentityBinding
    return IdentityBinding(actor_ref="ACTOR-FIN", channel_ref="CHANNEL-WA-1", active=True)


def _viewer_binding():
    from src.authz.access import IdentityBinding
    return IdentityBinding(actor_ref="ACTOR-VIEWER", channel_ref="CHANNEL-WA-1", active=True)


def _post_invoice(draft_wf, post_wf, unit_ref: str = "UNIT-BANYUMEDIA",
                  amount: str = "1500000") -> str:
    """Helper: open, set lines, preview, and post; returns official INV- ref."""
    from src.authz.access import IdentityBinding, ActorUnitAssignment
    req_binding = IdentityBinding(actor_ref="ACTOR-REQ", channel_ref="CHANNEL-WA-1", active=True)
    req_assign = ActorUnitAssignment(
        actor_ref="ACTOR-REQ", unit_ref=unit_ref,
        roles=("FINANCE-REQUESTER",), active=True,
        assignment_ref=f"ASSIGNMENT-REQ-{unit_ref}", revision=1,
    )
    rev_binding = IdentityBinding(actor_ref="ACTOR-REV", channel_ref="CHANNEL-WA-1", active=True)
    rev_assign = ActorUnitAssignment(
        actor_ref="ACTOR-REV", unit_ref=unit_ref,
        roles=("FINANCE-POSTER",), active=True,
        assignment_ref=f"ASSIGNMENT-REV-{unit_ref}", revision=1,
    )
    handle = draft_wf.open_draft(
        actor_ref="ACTOR-REQ", channel_ref="CHANNEL-WA-1",
        binding=req_binding, assignments=(req_assign,),
        customer_ref="CUST-1", at=_t(3),
    )
    draft_wf.set_lines(
        handle.draft_id,
        ({"service_ref": "SVC-ADS-01", "description": "Ads management",
          "quantity": "1", "unit_price_amount": amount, "currency": "IDR"},),
        actor_ref="ACTOR-REQ", at=_t(4), binding=req_binding,
        assignments=(req_assign,),
    )
    preview = draft_wf.preview(
        handle.draft_id, actor_ref="ACTOR-REQ", binding=req_binding,
        assignments=(req_assign,), at=_t(5),
    )
    result = post_wf.post(
        preview, actor_ref="ACTOR-REV", at=_t(6), binding=rev_binding,
        assignments=(rev_assign,), channel_ref="CHANNEL-WA-1",
    )
    assert result.outcome == "POSTED"
    return result.official_ref


class TestPaymentRecordingHappyPaths(unittest.TestCase):
    """R-006/R-017: partial and full payments against a POSTED invoice."""

    def test_full_payment_marks_invoice_paid(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        result = pay_wf.record_payment(
            invoice_ref=invoice_ref,
            amount="1500000.00", currency="IDR",
            evidence_ref="EVI-PAY-1",
            destination_account_alias="ACC-BANYUMEDIA",
            actor_ref="ACTOR-FIN", at=_t(10),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.outcome, "RECORDED")
        self.assertTrue(result.payment_ref.startswith("PAY-"))
        record = adapter.read_invoice(invoice_ref)
        self.assertEqual(float(record.open_amount), 0.0)

    def test_partial_payment_leaves_open_amount(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        result = pay_wf.record_payment(
            invoice_ref=invoice_ref,
            amount="500000.00", currency="IDR",
            evidence_ref="EVI-PAY-2",
            destination_account_alias="ACC-BANYUMEDIA",
            actor_ref="ACTOR-FIN", at=_t(10),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.outcome, "RECORDED")
        self.assertEqual(result.receivable_status, "PARTIALLY_PAID")
        record = adapter.read_invoice(invoice_ref)
        self.assertEqual(float(record.open_amount), 1000000.0)


def _record(pay_wf, invoice_ref: str, **overrides):
    """Helper with sane defaults for a BANYUMEDIA payment attempt."""
    params = dict(
        invoice_ref=invoice_ref,
        amount="500000.00", currency="IDR",
        evidence_ref="EVI-GENERIC-1",
        destination_account_alias="ACC-BANYUMEDIA",
        actor_ref="ACTOR-FIN", at=_t(10),
        binding=_fin_binding(),
        assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
        channel_ref="CHANNEL-WA-1",
    )
    params.update(overrides)
    return pay_wf.record_payment(**params)


class TestEvidenceMandate(unittest.TestCase):
    """R-006: chat text alone can NEVER confirm a payment; EVI-* is mandatory."""

    def test_missing_evidence_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        with self.assertRaises(Exception) as ctx:
            _record(pay_wf, invoice_ref, evidence_ref="")
        self.assertIn("evidence", str(ctx.exception).lower())

    def test_non_evi_reference_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        # Raw chat-ish confirmation text must never pass as evidence.
        with self.assertRaises(Exception) as ctx:
            _record(pay_wf, invoice_ref,
                    evidence_ref="sudah transfer ya pak 500rb")
        self.assertIn("evidence", str(ctx.exception).lower())

    def test_denied_attempts_are_audited(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        with self.assertRaises(Exception):
            _record(pay_wf, invoice_ref, evidence_ref="")
        denied = pay_wf.denied_events()
        self.assertTrue(any(e["action"] == "record_payment" for e in denied))


class TestAuthorization(unittest.TestCase):
    """R-006/R-013: PAYMENT_RECORD action + unit scope enforced per attempt."""

    def test_unauthorized_role_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        # FINANCE-POSTER role does not hold PAYMENT_RECORD.
        from src.authz.access import IdentityBinding
        poster_binding = IdentityBinding(
            actor_ref="ACTOR-REV", channel_ref="CHANNEL-WA-1", active=True)
        with self.assertRaises(Exception) as ctx:
            _record(
                pay_wf, invoice_ref,
                actor_ref="ACTOR-REV", binding=poster_binding,
                assignments=(_assignment("ACTOR-REV", "UNIT-BANYUMEDIA",
                                         ("FINANCE-POSTER",), "ASSIGNMENT-P"),),
            )
        self.assertIn("not be authorized", str(ctx.exception))

    def test_cross_unit_payment_denied_without_disclosure(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        # Actor only assigned to PR1ME tries to pay a BANYUMEDIA invoice.
        with self.assertRaises(Exception) as ctx:
            _record(
                pay_wf, invoice_ref,
                assignments=(_finance_assignment("UNIT-PR1ME"),),
            )
        self.assertNotIn("BANYUMEDIA", str(ctx.exception))
        denied = pay_wf.denied_events()
        self.assertTrue(any(e["action"] == "record_payment" for e in denied))


class TestAccountValidation(unittest.TestCase):
    """R-013/R-019: destination account alias must match unit policy."""

    def test_wrong_account_alias_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        with self.assertRaises(Exception):
            _record(pay_wf, invoice_ref,
                    destination_account_alias="ACC-PR1ME")
        # No provider mutation may have happened.
        self.assertEqual(adapter.payment_evidence_index(), ())

    def test_malformed_account_alias_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        with self.assertRaises(Exception):
            _record(pay_wf, invoice_ref,
                    destination_account_alias="bank bca 1234567890")


class TestOverpayAndStateGuards(unittest.TestCase):
    """R-006/R-017: overpay and non-OPEN receivables are denied pre-mutation."""

    def test_overpay_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        with self.assertRaises(Exception) as ctx:
            _record(pay_wf, invoice_ref, amount="2000000.00")
        self.assertIn("open amount", str(ctx.exception))
        self.assertEqual(adapter.payment_evidence_index(), ())

    def test_payment_on_paid_invoice_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        _record(pay_wf, invoice_ref, amount="1500000.00",
                evidence_ref="EVI-FULL-1")
        with self.assertRaises(Exception):
            _record(pay_wf, invoice_ref, amount="100.00",
                    evidence_ref="EVI-EXTRA-1")
        # Exactly one payment recorded.
        self.assertEqual(len(adapter.payment_evidence_index()), 1)

    def test_payment_on_unknown_invoice_blocked(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        _post_invoice(draft_wf, post_wf)
        with self.assertRaises(Exception):
            _record(pay_wf, "INV-999999")

    def test_currency_mismatch_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        with self.assertRaises(Exception):
            _record(pay_wf, invoice_ref, currency="USD")
        self.assertEqual(adapter.payment_evidence_index(), ())


class TestIdempotency(unittest.TestCase):
    """R-007: per-actor idempotency with payload conflict detection."""

    def test_replay_same_key_and_payload_returns_same_payment(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        first = _record(pay_wf, invoice_ref, evidence_ref="EVI-IDEM-1",
                        idempotency_key="pay-attempt-1")
        second = _record(pay_wf, invoice_ref, evidence_ref="EVI-IDEM-1",
                         idempotency_key="pay-attempt-1")
        self.assertEqual(first.payment_ref, second.payment_ref)
        self.assertEqual(len(adapter.payment_evidence_index()), 1)

    def test_same_key_different_payload_conflicts(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        _record(pay_wf, invoice_ref, amount="100000.00",
                evidence_ref="EVI-IDEM-2", idempotency_key="pay-attempt-2")
        with self.assertRaises(Exception) as ctx:
            _record(pay_wf, invoice_ref, amount="200000.00",
                    evidence_ref="EVI-IDEM-3", idempotency_key="pay-attempt-2")
        self.assertIn("conflict", str(ctx.exception).lower())
        # The conflicting attempt must not reach the provider.
        self.assertEqual(len(adapter.payment_evidence_index()), 1)

    def test_duplicate_evidence_ref_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        _record(pay_wf, invoice_ref, evidence_ref="EVI-DUP-1",
                idempotency_key="k-1")
        with self.assertRaises(Exception):
            _record(pay_wf, invoice_ref, evidence_ref="EVI-DUP-1",
                    idempotency_key="k-2")
        self.assertEqual(len(adapter.payment_evidence_index()), 1)

    def test_concurrent_duplicate_race_mutates_provider_exactly_once(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        outcomes: list[str] = []
        errors: list[Exception] = []

        def attempt() -> None:
            try:
                result = _record(
                    pay_wf, invoice_ref, evidence_ref="EVI-RACE-1",
                    idempotency_key="race-key",
                )
                outcomes.append(result.payment_ref or "")
            except Exception as exc:  # losing racer must fail safely
                errors.append(exc)

        threads = [threading.Thread(target=attempt) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # Exactly one provider mutation; every racer observed success or a
        # safe denial — never two payments.
        self.assertEqual(len(adapter.payment_evidence_index()), 1)
        self.assertTrue(outcomes)
        self.assertEqual(len(set(outcomes)), 1)


class TestClaimReplayOrdering(unittest.TestCase):
    """F-02: idempotency replay must win over the overpay guard, and a
    replayed RECORDED result must report the FRESH receivable status."""

    def test_full_pay_then_replay_returns_recorded_with_fresh_paid_status(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        first = _record(pay_wf, invoice_ref, amount="1500000.00",
                        evidence_ref="EVI-REPLAY-1", idempotency_key="replay-1")
        self.assertEqual(first.outcome, "RECORDED")
        self.assertEqual(first.receivable_status, "PAID")
        # Invoice is now PAID (open_amount == 0). Replaying the original key
        # must return the recorded result, not an overpay denial.
        replay = _record(pay_wf, invoice_ref, amount="1500000.00",
                         evidence_ref="EVI-REPLAY-1", idempotency_key="replay-1")
        self.assertEqual(replay.outcome, "RECORDED")
        self.assertEqual(replay.payment_ref, first.payment_ref)
        self.assertEqual(replay.receivable_status, "PAID")
        # Exactly one provider mutation.
        self.assertEqual(len(adapter.payment_evidence_index()), 1)

    def test_partial_pay_replay_returns_recorded_result(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        first = _record(pay_wf, invoice_ref, amount="500000.00",
                        evidence_ref="EVI-REPLAY-2", idempotency_key="replay-2")
        self.assertEqual(first.outcome, "RECORDED")
        self.assertEqual(first.receivable_status, "PARTIALLY_PAID")
        replay = _record(pay_wf, invoice_ref, amount="500000.00",
                         evidence_ref="EVI-REPLAY-2", idempotency_key="replay-2")
        self.assertEqual(replay.outcome, "RECORDED")
        self.assertEqual(replay.payment_ref, first.payment_ref)
        self.assertEqual(replay.receivable_status, "PARTIALLY_PAID")
        self.assertEqual(len(adapter.payment_evidence_index()), 1)

    def test_replay_after_invoice_paid_by_another_payment_still_replays(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        first = _record(pay_wf, invoice_ref, amount="500000.00",
                        evidence_ref="EVI-REPLAY-3", idempotency_key="replay-3")
        # A second, distinct payment closes the invoice.
        _record(pay_wf, invoice_ref, amount="1000000.00",
                evidence_ref="EVI-REPLAY-4", idempotency_key="replay-4")
        replay = _record(pay_wf, invoice_ref, amount="500000.00",
                         evidence_ref="EVI-REPLAY-3", idempotency_key="replay-3")
        self.assertEqual(replay.outcome, "RECORDED")
        self.assertEqual(replay.payment_ref, first.payment_ref)
        # Fresh status reflects the PAID invoice, not a stale snapshot.
        self.assertEqual(replay.receivable_status, "PAID")
        self.assertEqual(len(adapter.payment_evidence_index()), 2)

    def test_replay_with_different_payload_still_conflicts(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        _record(pay_wf, invoice_ref, amount="1500000.00",
                evidence_ref="EVI-REPLAY-5", idempotency_key="replay-5")
        with self.assertRaises(Exception) as ctx:
            _record(pay_wf, invoice_ref, amount="999999.00",
                    evidence_ref="EVI-REPLAY-5", idempotency_key="replay-5")
        self.assertIn("conflict", str(ctx.exception).lower())
        self.assertEqual(len(adapter.payment_evidence_index()), 1)


class TestReversal(unittest.TestCase):
    """R-008/R-017: reversal is compensating only; state recomputed."""

    def test_reverse_full_payment_reopens_receivable(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        paid = _record(pay_wf, invoice_ref, amount="1500000.00",
                       evidence_ref="EVI-RVSBL-1")
        self.assertEqual(paid.receivable_status, "PAID")
        reversed_result = pay_wf.reverse_payment(
            payment_ref=paid.payment_ref, reason="duplicate transfer",
            actor_ref="ACTOR-FIN", at=_t(11),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(reversed_result.outcome, "RECORDED")
        # Receivable state recomputed from compensating records -> OPEN again.
        self.assertEqual(reversed_result.receivable_status, "OPEN")
        record = adapter.read_invoice(invoice_ref)
        self.assertEqual(float(record.open_amount), 1500000.0)
        # The original payment is never mutated or deleted.
        original = adapter.read_payment(paid.payment_ref)
        self.assertIsNone(original.reversal_of)
        reversal = adapter.read_payment(reversed_result.payment_ref)
        self.assertEqual(reversal.reversal_of, paid.payment_ref)

    def test_reverse_partial_payment_recomputes_open(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        paid = _record(pay_wf, invoice_ref, amount="500000.00",
                       evidence_ref="EVI-RVSBL-2")
        self.assertEqual(paid.receivable_status, "PARTIALLY_PAID")
        reversed_result = pay_wf.reverse_payment(
            payment_ref=paid.payment_ref, reason="wrong invoice",
            actor_ref="ACTOR-FIN", at=_t(11),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(reversed_result.receivable_status, "OPEN")

    def test_reverse_unknown_payment_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        _post_invoice(draft_wf, post_wf)
        with self.assertRaises(Exception):
            pay_wf.reverse_payment(
                payment_ref="PAY-999999", reason="mistake",
                actor_ref="ACTOR-FIN", at=_t(11),
                binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )

    def test_double_reversal_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        paid = _record(pay_wf, invoice_ref, amount="500000.00",
                       evidence_ref="EVI-RVSBL-3")
        pay_wf.reverse_payment(
            payment_ref=paid.payment_ref, reason="first reversal",
            actor_ref="ACTOR-FIN", at=_t(11),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        with self.assertRaises(Exception):
            pay_wf.reverse_payment(
                payment_ref=paid.payment_ref, reason="second reversal",
                actor_ref="ACTOR-FIN", at=_t(12),
                binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )

    def test_reversal_requires_reason(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        paid = _record(pay_wf, invoice_ref, amount="500000.00",
                       evidence_ref="EVI-RVSBL-4")
        with self.assertRaises(Exception):
            pay_wf.reverse_payment(
                payment_ref=paid.payment_ref, reason="",
                actor_ref="ACTOR-FIN", at=_t(11),
                binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )

    def test_reversal_unauthorized_role_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        paid = _record(pay_wf, invoice_ref, amount="500000.00",
                       evidence_ref="EVI-RVSBL-5")
        from src.authz.access import IdentityBinding
        poster_binding = IdentityBinding(
            actor_ref="ACTOR-REV", channel_ref="CHANNEL-WA-1", active=True)
        with self.assertRaises(Exception) as ctx:
            pay_wf.reverse_payment(
                payment_ref=paid.payment_ref, reason="unauthorized attempt",
                actor_ref="ACTOR-REV", at=_t(11),
                binding=poster_binding,
                assignments=(_assignment("ACTOR-REV", "UNIT-BANYUMEDIA",
                                         ("FINANCE-POSTER",), "ASSIGNMENT-P2"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("not be authorized", str(ctx.exception))
        denied = pay_wf.denied_events()
        self.assertTrue(any(e["action"] == "reverse_payment" for e in denied))


class TestUncertainReconciliation(unittest.TestCase):
    """R-006/REC-001: UNCERTAIN enqueues reconciliation; blind retry blocked."""

    def test_uncertain_enqueues_reconciliation_and_blocks_retry(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        adapter.fail_next_payment("UNCERTAIN")
        result = _record(pay_wf, invoice_ref, evidence_ref="EVI-UNC-1")
        self.assertEqual(result.outcome, "UNCERTAIN")
        self.assertIsNone(result.payment_ref)
        # Enqueued for fenced classification.
        self.assertEqual(queue.depth(), 1)
        # Blind retry of the same evidence ref is blocked.
        with self.assertRaises(Exception) as ctx:
            _record(pay_wf, invoice_ref, evidence_ref="EVI-UNC-1")
        self.assertIn("reconciliation", str(ctx.exception))

    def test_reconcile_present_resolves_payment(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        adapter.fail_next_payment("UNCERTAIN")
        _record(pay_wf, invoice_ref, amount="1500000.00",
                evidence_ref="EVI-UNC-2")
        resolved = pay_wf.reconcile_payment(
            evidence_ref="EVI-UNC-2",
            actor_ref="ACTOR-FIN", at=_t(11),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(resolved.outcome, "RECORDED")
        self.assertEqual(resolved.receivable_status, "PAID")
        # The reserved evidence ref now maps to a real payment.
        payment = adapter.reconcile_payment("EVI-UNC-2")
        self.assertTrue(payment.reference.startswith("PAY-"))

    def test_uncertain_same_key_replay_blocked_until_reconciled(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        adapter.fail_next_payment("UNCERTAIN")
        _record(pay_wf, invoice_ref, evidence_ref="EVI-UNC-3",
                idempotency_key="unc-key")
        with self.assertRaises(Exception):
            _record(pay_wf, invoice_ref, evidence_ref="EVI-UNC-3",
                    idempotency_key="unc-key")

    def test_provider_rejection_translated_to_blocked(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        adapter.fail_next_payment("REJECTED")
        from src.contracts.erp_port import DocumentRejected
        with self.assertRaises(Exception) as ctx:
            _record(pay_wf, invoice_ref, evidence_ref="EVI-REJ-1")
        # Raw provider exceptions never escape the workflow boundary.
        self.assertNotIsInstance(ctx.exception, DocumentRejected)
        self.assertIn("rejected", str(ctx.exception).lower())


class TestReconcileAuthorization(unittest.TestCase):
    """F-01: reconcile_payment requires PAYMENT_RECORD authz within scope."""

    def _make_uncertain(self, pay_wf, adapter, invoice_ref,
                        evidence_ref="EVI-RA-1"):
        adapter.fail_next_payment("UNCERTAIN")
        result = _record(pay_wf, invoice_ref, amount="1500000.00",
                         evidence_ref=evidence_ref)
        self.assertEqual(result.outcome, "UNCERTAIN")
        return evidence_ref

    def test_unauthenticated_reconcile_denied_and_audited(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        evidence_ref = self._make_uncertain(pay_wf, adapter, invoice_ref)
        with self.assertRaises(Exception) as ctx:
            pay_wf.reconcile_payment(
                evidence_ref=evidence_ref,
                actor_ref="ACTOR-FIN", at=_t(11),
                binding=None, assignments=(),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("not be authorized", str(ctx.exception))
        # No classification leaked: still pending, no payment_ref disclosed.
        denied = pay_wf.denied_events()
        self.assertTrue(any(e["action"] == "reconcile_payment" for e in denied))

    def test_cross_unit_actor_reconcile_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)  # BANYUMEDIA invoice
        evidence_ref = self._make_uncertain(pay_wf, adapter, invoice_ref)
        # ACTOR-FIN reassigned to PR1ME only — must not resolve a
        # BANYUMEDIA-scope UNCERTAIN claim.
        from src.authz.access import IdentityBinding
        foreign_binding = IdentityBinding(
            actor_ref="ACTOR-FIN", channel_ref="CHANNEL-WA-1", active=True)
        with self.assertRaises(Exception) as ctx:
            pay_wf.reconcile_payment(
                evidence_ref=evidence_ref,
                actor_ref="ACTOR-FIN", at=_t(11),
                binding=foreign_binding,
                assignments=(_finance_assignment("UNIT-PR1ME"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("not be authorized", str(ctx.exception))
        self.assertNotIn("BANYUMEDIA", str(ctx.exception))
        denied = pay_wf.denied_events()
        self.assertTrue(any(e["action"] == "reconcile_payment" for e in denied))

    def test_wrong_role_reconcile_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        evidence_ref = self._make_uncertain(pay_wf, adapter, invoice_ref)
        # FINANCE-POSTER does not hold PAYMENT_RECORD.
        from src.authz.access import IdentityBinding
        poster_binding = IdentityBinding(
            actor_ref="ACTOR-REV", channel_ref="CHANNEL-WA-1", active=True)
        with self.assertRaises(Exception) as ctx:
            pay_wf.reconcile_payment(
                evidence_ref=evidence_ref,
                actor_ref="ACTOR-REV", at=_t(11),
                binding=poster_binding,
                assignments=(_assignment("ACTOR-REV", "UNIT-BANYUMEDIA",
                                         ("FINANCE-POSTER",), "ASSIGNMENT-P3"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("not be authorized", str(ctx.exception))
        denied = pay_wf.denied_events()
        self.assertTrue(any(e["action"] == "reconcile_payment" for e in denied))

    def test_authorized_reconcile_still_resolves(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        evidence_ref = self._make_uncertain(pay_wf, adapter, invoice_ref)
        resolved = pay_wf.reconcile_payment(
            evidence_ref=evidence_ref,
            actor_ref="ACTOR-FIN", at=_t(11),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(resolved.outcome, "RECORDED")
        self.assertTrue(resolved.payment_ref.startswith("PAY-"))
        self.assertEqual(resolved.receivable_status, "PAID")
        # Audit of the resolution carries the actor's assignment ref.
        events = pay_wf.audit_events(invoice_ref)
        entry = next(e for e in events if e["action"] == "reconcile_payment")
        self.assertEqual(entry["actor_ref"], "ACTOR-FIN")


class TestWorkflowLevelGuards(unittest.TestCase):
    """F-03: mutant killers — the WORKFLOW layer (not the provider) must
    enforce the double-reversal guard (M6) and the pending-uncertain
    blind-retry guard (M7), and aging must deny an explicit foreign unit
    BEFORE any disclosure-producing call (M9). Stub adapters are used so
    the provider cannot mask a missing workflow-level guard."""

    def _build_with_adapter(self, adapter):
        from src.contracts.financial_identity import FinancialIdentity
        from src.policy.financial_identity import (
            FinancialIdentityPolicy,
            FinancialPolicyResolver,
            TrustedIssuer,
        )
        from src.reconciliation.engine import ReconciliationEngine
        from src.reconciliation.queue import OperatorQueue
        from src.units.registry import UnitRegistry
        from src.workflows.payments.workflow import PaymentWorkflow

        registry = UnitRegistry.default()
        issuer = TrustedIssuer("ISSUER-AUTH-ROOT", b"synthetic-fixture-key-01")
        identity_b = FinancialIdentity(
            "UNIT-BANYUMEDIA", "ISSUER-BANYUMEDIA", "TAX-NONPPN",
            "SERIES-BYM", "LEDGER-BYM", "ACC-BANYUMEDIA",
        )
        catalog = issuer.issue_catalog("CATALOG-FLOW3", 1, "EVIDENCE-FLOW3",
                                       (identity_b,))
        policies = (
            FinancialIdentityPolicy(
                policy_ref="POLICY-BYM-1", policy_version=1,
                operating_unit_ref="UNIT-BANYUMEDIA",
                legal_issuer_ref="ISSUER-BANYUMEDIA", tax_profile_ref="TAX-NONPPN",
                invoice_series_ref="SERIES-BYM", receivable_ledger_ref="LEDGER-BYM",
                destination_account_alias="ACC-BANYUMEDIA", currency="IDR",
                effective_from=_t(), effective_until=None, active=True,
            ),
        )
        resolver = FinancialPolicyResolver(policies, compatibility_catalog=catalog)
        queue = OperatorQueue()
        engine = ReconciliationEngine(adapter, queue)
        pay_wf = PaymentWorkflow(
            registry=registry, resolver=resolver, adapter=adapter,
            reconciliation=engine,
        )
        return pay_wf

    class _Invoice:
        def __init__(self, open_amount="1500000.00"):
            self.reference = "INV-000001"
            self.status = "POSTED"
            self.total_amount = "1500000.00"
            self.currency = "IDR"
            self.open_amount = open_amount
            self.issued_on = "2026-08-01"
            self.due_on = "2026-08-15"
            self.payload = {"identity": {"operating_unit_ref": "UNIT-BANYUMEDIA"}}

    class _Payment:
        def __init__(self, reference, invoice_ref, evidence_ref, reversal_of=None):
            self.reference = reference
            self.invoice_ref = invoice_ref
            self.amount = "500000.00"
            self.currency = "IDR"
            self.evidence_ref = evidence_ref
            self.destination_account_alias = "ACC-BANYUMEDIA"
            self.reversal_of = reversal_of

    def test_m6_workflow_denies_second_reversal_even_if_provider_allows(self) -> None:
        """M6 killer: stub provider does NOT reject double reversal; the
        workflow-level _reversed guard must deny the second attempt before
        any second provider mutation."""

        class PermissiveReversalAdapter:
            """Provider that happily reverses the same payment twice."""

            def __init__(self):
                self.invoice = TestWorkflowLevelGuards._Invoice()
                self.payments = {}
                self.reverse_calls = 0
                self._seq = 0

            def read_invoice(self, reference):
                return self.invoice

            def read_payment(self, reference):
                return self.payments[reference]

            def record_payment(self, command):
                self._seq += 1
                ref = f"PAY-{self._seq:06d}"
                self.payments[ref] = TestWorkflowLevelGuards._Payment(
                    ref, command.invoice_ref, command.evidence_ref)
                from decimal import Decimal
                self.invoice.open_amount = str(
                    Decimal(self.invoice.open_amount) - Decimal(command.amount))
                return ref

            def reverse_payment(self, command):
                # NO double-reversal rejection here — unlike the fixture.
                self.reverse_calls += 1
                self._seq += 1
                ref = f"PAY-{self._seq:06d}"
                original = self.payments[command.payment_ref]
                self.payments[ref] = TestWorkflowLevelGuards._Payment(
                    ref, original.invoice_ref, f"EVI-REV-{original.reference}",
                    reversal_of=original.reference)
                from decimal import Decimal
                self.invoice.open_amount = str(
                    Decimal(self.invoice.open_amount) + Decimal(original.amount))
                return ref

        adapter = PermissiveReversalAdapter()
        pay_wf = self._build_with_adapter(adapter)
        paid = pay_wf.record_payment(
            invoice_ref="INV-000001", amount="500000.00", currency="IDR",
            evidence_ref="EVI-M6-1", destination_account_alias="ACC-BANYUMEDIA",
            actor_ref="ACTOR-FIN", at=_t(10), binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(paid.outcome, "RECORDED")
        first = pay_wf.reverse_payment(
            payment_ref=paid.payment_ref, reason="first reversal",
            actor_ref="ACTOR-FIN", at=_t(11), binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(first.outcome, "RECORDED")
        self.assertEqual(adapter.reverse_calls, 1)
        # Second reversal: the provider WOULD allow it — the workflow must not.
        from src.workflows.payments.workflow import WorkflowBlocked
        with self.assertRaises(WorkflowBlocked) as ctx:
            pay_wf.reverse_payment(
                payment_ref=paid.payment_ref, reason="second reversal",
                actor_ref="ACTOR-FIN", at=_t(12), binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("already reversed", str(ctx.exception))
        # Denial origin is the workflow: the provider was never called again,
        # and the denial was audited at the workflow layer.
        self.assertEqual(adapter.reverse_calls, 1)
        denied = pay_wf.denied_events()
        self.assertTrue(any(
            e["action"] == "reverse_payment" and e["code"] == "INVALID_STATE"
            for e in denied
        ))

    def test_m7_workflow_blocks_blind_retry_when_provider_does_not_reserve(self) -> None:
        """M7 killer: stub provider raises UNCERTAIN WITHOUT reserving the
        evidence ref; the workflow-level _pending_uncertain guard must block
        the blind retry (new key, same evidence) before the provider runs."""
        from src.contracts.erp_port import UncertainOutcome

        class NonReservingUncertainAdapter:
            """UNCERTAIN outcome that does NOT reserve the evidence ref —
            a blind retry would reach (and mutate) the provider again."""

            def __init__(self):
                self.invoice = TestWorkflowLevelGuards._Invoice()
                self.payments = {}
                self.record_calls = 0
                self._seq = 0
                self._fail_next = None

            def fail_next_payment(self, mode):
                self._fail_next = mode

            def read_invoice(self, reference):
                return self.invoice

            def read_payment(self, reference):
                return self.payments[reference]

            def reconcile_payment(self, evidence_ref):
                for payment in self.payments.values():
                    if payment.evidence_ref == evidence_ref:
                        return payment
                from src.contracts.erp_port import DocumentRejected
                raise DocumentRejected("unknown evidence reference")

            def record_payment(self, command):
                self.record_calls += 1
                if self._fail_next == "UNCERTAIN":
                    self._fail_next = None
                    # Apply nothing, reserve nothing — outcome simply unknown.
                    raise UncertainOutcome("payment outcome unknown")
                self._seq += 1
                ref = f"PAY-{self._seq:06d}"
                self.payments[ref] = TestWorkflowLevelGuards._Payment(
                    ref, command.invoice_ref, command.evidence_ref)
                return ref

        adapter = NonReservingUncertainAdapter()
        pay_wf = self._build_with_adapter(adapter)
        adapter.fail_next_payment("UNCERTAIN")
        result = pay_wf.record_payment(
            invoice_ref="INV-000001", amount="500000.00", currency="IDR",
            evidence_ref="EVI-M7-1", destination_account_alias="ACC-BANYUMEDIA",
            actor_ref="ACTOR-FIN", at=_t(10), binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1", idempotency_key="m7-key-1",
        )
        self.assertEqual(result.outcome, "UNCERTAIN")
        self.assertEqual(adapter.record_calls, 1)
        # Blind retry with a NEW idempotency key, same evidence ref: the
        # provider would accept it (nothing reserved) — the workflow must not.
        from src.workflows.payments.workflow import WorkflowBlocked
        with self.assertRaises(WorkflowBlocked) as ctx:
            pay_wf.record_payment(
                invoice_ref="INV-000001", amount="500000.00", currency="IDR",
                evidence_ref="EVI-M7-1",
                destination_account_alias="ACC-BANYUMEDIA",
                actor_ref="ACTOR-FIN", at=_t(11), binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1", idempotency_key="m7-key-2",
            )
        self.assertIn("pending reconciliation", str(ctx.exception))
        # Denial origin is the workflow: no second provider mutation.
        self.assertEqual(adapter.record_calls, 1)
        denied = pay_wf.denied_events()
        self.assertTrue(any(
            e["action"] == "record_payment" and e["code"] == "INVALID_STATE"
            for e in denied
        ))

    def test_m9_foreign_unit_denied_before_any_disclosure_producing_call(self) -> None:
        """M9 killer: an explicitly named foreign unit must be denied by the
        EARLY guard — before authorize() (scope enumeration) or any provider
        query runs. Counting spies prove zero disclosure-producing calls."""
        import src.reports.receivables.aging as aging_module

        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        _post_invoice(draft_wf, post_wf, unit_ref="UNIT-PR1ME")

        authorize_calls = []
        real_authorize = aging_module.authorize

        def counting_authorize(**kwargs):
            authorize_calls.append(kwargs)
            return real_authorize(**kwargs)

        provider_queries = []
        real_query_invoices = adapter.query_invoices

        def counting_query_invoices(**kwargs):
            provider_queries.append(kwargs)
            return real_query_invoices(**kwargs)

        try:
            aging_module.authorize = counting_authorize
            adapter.query_invoices = counting_query_invoices
            from src.reports.receivables.aging import WorkflowDenied
            with self.assertRaises(WorkflowDenied) as ctx:
                aging.query_aging(
                    actor_ref="ACTOR-VIEWER", at=_t(20),
                    binding=_viewer_binding(),
                    assignments=(_viewer_assignment("UNIT-BANYUMEDIA"),),
                    channel_ref="CHANNEL-WA-1",
                    unit_ref="UNIT-PR1ME",  # explicitly named foreign unit
                )
            self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
            # EARLY deny: neither the authz enumeration nor any provider
            # query was reached — zero disclosure-producing calls happened.
            self.assertEqual(authorize_calls, [])
            self.assertEqual(provider_queries, [])
            denied = aging.denied_events()
            self.assertTrue(any(
                e["action"] == "query_aging" and e["code"] == "PERMISSION_DENIED"
                for e in denied
            ))
        finally:
            aging_module.authorize = real_authorize
            adapter.query_invoices = real_query_invoices


class TestAuditTrail(unittest.TestCase):
    """R-007: every transition and denial is audited with opaque refs only."""

    def test_payment_audit_entries(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        _record(pay_wf, invoice_ref, evidence_ref="EVI-AUD-1")
        events = pay_wf.audit_events(invoice_ref)
        actions = [e["action"] for e in events]
        self.assertIn("payment_recorded", actions)
        entry = next(e for e in events if e["action"] == "payment_recorded")
        self.assertEqual(entry["actor_ref"], "ACTOR-FIN")
        self.assertEqual(entry["evidence_ref"], "EVI-AUD-1")

    def test_reversal_audit_entries(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        paid = _record(pay_wf, invoice_ref, evidence_ref="EVI-AUD-2")
        pay_wf.reverse_payment(
            payment_ref=paid.payment_ref, reason="audit check",
            actor_ref="ACTOR-FIN", at=_t(11),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        events = pay_wf.audit_events(invoice_ref)
        actions = [e["action"] for e in events]
        self.assertIn("payment_reversed", actions)

    def test_audit_never_contains_raw_chat_or_account_numbers(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        _record(pay_wf, invoice_ref, evidence_ref="EVI-AUD-3")
        import json
        blob = json.dumps(pay_wf.audit_events(invoice_ref)) + json.dumps(
            pay_wf.denied_events())
        self.assertNotIn("sudah transfer", blob)
        self.assertNotIn("1234567890", blob)  # no raw account numbers


class TestReadBackOrphanClaim(unittest.TestCase):
    """QA-R2-F-01: a successful provider record_payment whose read-back
    fails or mismatches must follow the same recovery path as
    UncertainOutcome — claim persisted with full linkage, pending-uncertain
    set, reconciliation enqueued, audit emitted, blind retry blocked."""

    class _OrphanAdapterBase:
        """record_payment succeeds; read-back behaviour is overridden."""

        def __init__(self):
            self.invoice = TestWorkflowLevelGuards._Invoice()
            self.payments = {}
            self.record_calls = 0
            self._seq = 0

        def read_invoice(self, reference):
            return self.invoice

        def record_payment(self, command):
            self.record_calls += 1
            self._seq += 1
            ref = f"PAY-{self._seq:06d}"
            self.payments[ref] = TestWorkflowLevelGuards._Payment(
                ref, command.invoice_ref, command.evidence_ref)
            return ref

        def reconcile_payment(self, evidence_ref):
            for payment in self.payments.values():
                if payment.evidence_ref == evidence_ref:
                    return payment
            from src.contracts.erp_port import DocumentRejected
            raise DocumentRejected("unknown evidence reference")

    def _record_orphan(self, adapter, evidence_ref):
        from src.workflows.payments.workflow import PaymentWorkflow
        from src.reconciliation.engine import ReconciliationEngine
        from src.reconciliation.queue import OperatorQueue
        from src.units.registry import UnitRegistry
        from src.contracts.financial_identity import FinancialIdentity
        from src.policy.financial_identity import (
            FinancialIdentityPolicy,
            FinancialPolicyResolver,
            TrustedIssuer,
        )

        registry = UnitRegistry.default()
        issuer = TrustedIssuer("ISSUER-AUTH-ROOT", b"synthetic-fixture-key-01")
        identity_b = FinancialIdentity(
            "UNIT-BANYUMEDIA", "ISSUER-BANYUMEDIA", "TAX-NONPPN",
            "SERIES-BYM", "LEDGER-BYM", "ACC-BANYUMEDIA",
        )
        catalog = issuer.issue_catalog("CATALOG-FLOW3", 1, "EVIDENCE-FLOW3",
                                       (identity_b,))
        policies = (
            FinancialIdentityPolicy(
                policy_ref="POLICY-BYM-1", policy_version=1,
                operating_unit_ref="UNIT-BANYUMEDIA",
                legal_issuer_ref="ISSUER-BANYUMEDIA",
                tax_profile_ref="TAX-NONPPN",
                invoice_series_ref="SERIES-BYM",
                receivable_ledger_ref="LEDGER-BYM",
                destination_account_alias="ACC-BANYUMEDIA", currency="IDR",
                effective_from=_t(), effective_until=None, active=True,
            ),
        )
        resolver = FinancialPolicyResolver(policies, compatibility_catalog=catalog)
        queue = OperatorQueue()
        engine = ReconciliationEngine(adapter, queue)
        pay_wf = PaymentWorkflow(
            registry=registry, resolver=resolver, adapter=adapter,
            reconciliation=engine,
        )
        from src.workflows.payments.workflow import WorkflowBlocked
        with self.assertRaises(WorkflowBlocked):
            pay_wf.record_payment(
                invoice_ref="INV-000001", amount="500000.00", currency="IDR",
                evidence_ref=evidence_ref,
                destination_account_alias="ACC-BANYUMEDIA",
                actor_ref="ACTOR-FIN", at=_t(10), binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1", idempotency_key="orphan-key-1",
            )
        return pay_wf, queue

    def test_read_back_failure_enqueues_reconciliation(self) -> None:
        """read_payment raises ProviderContractError after a successful
        record: the claim must NOT be orphaned — it is enqueued, pending,
        audited, and a blind retry is blocked."""
        from src.contracts.erp_port import ProviderContractError

        class ReadBackFailsAdapter(self._OrphanAdapterBase):
            def read_payment(self, reference):
                raise ProviderContractError("read-back unavailable")

        adapter = ReadBackFailsAdapter()
        pay_wf, queue = self._record_orphan(adapter, "EVI-ORB-1")
        # Enqueued for fenced classification.
        self.assertEqual(queue.depth(), 1)
        # Blind retry (new key, same evidence) blocked by pending-uncertain.
        from src.workflows.payments.workflow import WorkflowBlocked
        with self.assertRaises(WorkflowBlocked) as ctx:
            pay_wf.record_payment(
                invoice_ref="INV-000001", amount="500000.00", currency="IDR",
                evidence_ref="EVI-ORB-1",
                destination_account_alias="ACC-BANYUMEDIA",
                actor_ref="ACTOR-FIN", at=_t(11), binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1", idempotency_key="orphan-key-2",
            )
        self.assertIn("pending reconciliation", str(ctx.exception))
        # Recovery path audited with full linkage.
        events = pay_wf.audit_events("INV-000001")
        entry = next(e for e in events if e["action"] == "payment_uncertain")
        self.assertEqual(entry["evidence_ref"], "EVI-ORB-1")
        # Provider actually executed the payment; reconcile PRESENT resolves.
        resolved = pay_wf.reconcile_payment(
            evidence_ref="EVI-ORB-1", actor_ref="ACTOR-FIN", at=_t(12),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(resolved.outcome, "RECORDED")
        self.assertTrue(resolved.payment_ref.startswith("PAY-"))

    def test_read_back_mismatch_enqueues_reconciliation(self) -> None:
        """read-back returns mismatched evidence after a successful record:
        same recovery path — enqueued, pending, audited, retry blocked."""

        class MismatchAdapter(self._OrphanAdapterBase):
            def read_payment(self, reference):
                payment = self.payments[reference]
                return TestWorkflowLevelGuards._Payment(
                    payment.reference, payment.invoice_ref,
                    "EVI-TAMPERED")  # mismatched evidence ref

        adapter = MismatchAdapter()
        pay_wf, queue = self._record_orphan(adapter, "EVI-ORB-2")
        self.assertEqual(queue.depth(), 1)
        from src.workflows.payments.workflow import WorkflowBlocked
        with self.assertRaises(WorkflowBlocked) as ctx:
            pay_wf.record_payment(
                invoice_ref="INV-000001", amount="500000.00", currency="IDR",
                evidence_ref="EVI-ORB-2",
                destination_account_alias="ACC-BANYUMEDIA",
                actor_ref="ACTOR-FIN", at=_t(11), binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1", idempotency_key="orphan-key-3",
            )
        self.assertIn("pending reconciliation", str(ctx.exception))
        events = pay_wf.audit_events("INV-000001")
        entry = next(e for e in events if e["action"] == "payment_uncertain")
        self.assertEqual(entry["evidence_ref"], "EVI-ORB-2")


class TestReconcileAbsentScope(unittest.TestCase):
    """QA-R2-F-02: the ABSENT classification path must apply the same
    caller-scope intersection as the PRESENT path — a cross-unit actor's
    reconcile must never resolve (reject) another unit's pending claim,
    and must not disclose its existence."""

    class _AbsentAdapter:
        """record_payment raises UNCERTAIN without reserving the evidence
        ref, so reconcile_payment raises DocumentRejected (ABSENT path)."""

        def __init__(self):
            self.invoices = {}
            self.payments = {}
            self._fail_next = None
            self._seq = 0

        def fail_uncertain_for(self, invoice_ref):
            self._fail_next = invoice_ref

        def read_invoice(self, reference):
            return self.invoices[reference]

        def read_payment(self, reference):
            return self.payments[reference]

        def record_payment(self, command):
            from src.contracts.erp_port import UncertainOutcome
            if self._fail_next == command.invoice_ref:
                self._fail_next = None
                # Apply nothing, reserve nothing — outcome unknown.
                raise UncertainOutcome("payment outcome unknown")
            self._seq += 1
            ref = f"PAY-{self._seq:06d}"
            self.payments[ref] = TestWorkflowLevelGuards._Payment(
                ref, command.invoice_ref, command.evidence_ref)
            return ref

        def reconcile_payment(self, evidence_ref):
            for payment in self.payments.values():
                if payment.evidence_ref == evidence_ref:
                    return payment
            from src.contracts.erp_port import DocumentRejected
            raise DocumentRejected("unknown evidence reference")

    def _build_two_units(self):
        from src.reconciliation.engine import ReconciliationEngine
        from src.reconciliation.queue import OperatorQueue
        from src.units.registry import UnitRegistry
        from src.contracts.financial_identity import FinancialIdentity
        from src.policy.financial_identity import (
            FinancialIdentityPolicy,
            FinancialPolicyResolver,
            TrustedIssuer,
        )
        from src.workflows.payments.workflow import PaymentWorkflow

        registry = UnitRegistry.default()
        issuer = TrustedIssuer("ISSUER-AUTH-ROOT", b"synthetic-fixture-key-01")
        identity_b = FinancialIdentity(
            "UNIT-BANYUMEDIA", "ISSUER-BANYUMEDIA", "TAX-NONPPN",
            "SERIES-BYM", "LEDGER-BYM", "ACC-BANYUMEDIA",
        )
        identity_p = FinancialIdentity(
            "UNIT-PR1ME", "ISSUER-PR1ME", "TAX-NONPPN",
            "SERIES-PR1", "LEDGER-PR1", "ACC-PR1ME",
        )
        catalog = issuer.issue_catalog("CATALOG-FLOW3", 1, "EVIDENCE-FLOW3",
                                       (identity_b, identity_p))
        policies = (
            FinancialIdentityPolicy(
                policy_ref="POLICY-BYM-1", policy_version=1,
                operating_unit_ref="UNIT-BANYUMEDIA",
                legal_issuer_ref="ISSUER-BANYUMEDIA",
                tax_profile_ref="TAX-NONPPN",
                invoice_series_ref="SERIES-BYM",
                receivable_ledger_ref="LEDGER-BYM",
                destination_account_alias="ACC-BANYUMEDIA", currency="IDR",
                effective_from=_t(), effective_until=None, active=True,
            ),
            FinancialIdentityPolicy(
                policy_ref="POLICY-PR1-1", policy_version=1,
                operating_unit_ref="UNIT-PR1ME",
                legal_issuer_ref="ISSUER-PR1ME",
                tax_profile_ref="TAX-NONPPN",
                invoice_series_ref="SERIES-PR1",
                receivable_ledger_ref="LEDGER-PR1",
                destination_account_alias="ACC-PR1ME", currency="IDR",
                effective_from=_t(), effective_until=None, active=True,
            ),
        )
        resolver = FinancialPolicyResolver(policies, compatibility_catalog=catalog)
        adapter = self._AbsentAdapter()
        # One POSTED invoice per unit.
        adapter.invoices["INV-BYM-1"] = TestWorkflowLevelGuards._Invoice()
        adapter.invoices["INV-BYM-1"].reference = "INV-BYM-1"
        invoice_p = TestWorkflowLevelGuards._Invoice()
        invoice_p.reference = "INV-PRI-1"
        invoice_p.payload = {"identity": {"operating_unit_ref": "UNIT-PR1ME"}}
        adapter.invoices["INV-PRI-1"] = invoice_p

        queue = OperatorQueue()
        engine = ReconciliationEngine(adapter, queue)
        pay_wf = PaymentWorkflow(
            registry=registry, resolver=resolver, adapter=adapter,
            reconciliation=engine,
        )
        return pay_wf, adapter, queue

    def _record_uncertain(self, pay_wf, adapter, invoice_ref, evidence_ref,
                          unit_ref, account_alias):
        adapter.fail_uncertain_for(invoice_ref)
        result = pay_wf.record_payment(
            invoice_ref=invoice_ref, amount="500000.00", currency="IDR",
            evidence_ref=evidence_ref,
            destination_account_alias=account_alias,
            actor_ref="ACTOR-FIN", at=_t(10), binding=_fin_binding(),
            assignments=(_finance_assignment(unit_ref),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.outcome, "UNCERTAIN")
        return evidence_ref

    def test_cross_unit_absent_reconcile_leaves_foreign_claim_uncertain(self) -> None:
        """A multi-unit actor reconciles a unit-B evidence ref (ABSENT at
        the provider); the ABSENT path must NOT reject unit-A's pending
        claim — it stays UNCERTAIN and undisclosed."""
        pay_wf, adapter, queue = self._build_two_units()
        # Unit-A (BANYUMEDIA) payment goes UNCERTAIN (evidence NOT reserved).
        self._record_uncertain(pay_wf, adapter, "INV-BYM-1", "EVI-ABS-A1",
                               "UNIT-BANYUMEDIA", "ACC-BANYUMEDIA")
        # Unit-B (PR1ME) payment also goes UNCERTAIN so the reconcile anchor
        # resolves to a unit the actor IS authorized for.
        self._record_uncertain(pay_wf, adapter, "INV-PRI-1", "EVI-ABS-B1",
                               "UNIT-PR1ME", "ACC-PR1ME")
        from src.authz.access import ActorUnitAssignment
        both = (
            _assignment("ACTOR-FIN", "UNIT-BANYUMEDIA",
                        ("FINANCE-REQUESTER",), "ASSIGNMENT-FIN-B"),
            _assignment("ACTOR-FIN", "UNIT-PR1ME",
                        ("FINANCE-REQUESTER",), "ASSIGNMENT-FIN-P"),
        )
        # Reconcile the unit-B evidence ref; provider reports ABSENT.
        result = pay_wf.reconcile_payment(
            evidence_ref="EVI-ABS-B1",
            actor_ref="ACTOR-FIN", at=_t(11),
            binding=_fin_binding(), assignments=both,
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.outcome, "REJECTED")
        # The unit-B claim is resolved; the unit-A claim must remain
        # UNCERTAIN and still pending — never rejected by another unit's
        # reconcile.
        self.assertIn("EVI-ABS-A1", pay_wf._pending_uncertain)
        self.assertNotIn("EVI-ABS-B1", pay_wf._pending_uncertain)
        claims = {s: c for s, c in pay_wf._claims.items()}
        a_claim = next(c for s, c in claims.items()
                       if c.invoice_ref == "INV-BYM-1")
        b_claim = next(c for s, c in claims.items()
                       if c.invoice_ref == "INV-PRI-1")
        self.assertEqual(a_claim.outcome, "UNCERTAIN")
        self.assertEqual(b_claim.outcome, "REJECTED")

    def test_reconcile_scope_anchor_tracks_evidence_not_assignment_order(self) -> None:
        """Regression (flaky cross-unit test): the reconcile authorization
        scope must anchor on the unit owning the reconciled evidence_ref's
        claim — never on assignment order or on which pending claim the
        workflow happens to iterate first. Both assignment permutations must
        resolve the unit-B claim and leave the unit-A claim UNCERTAIN."""
        from src.authz.access import ActorUnitAssignment  # noqa: F401
        for order in (0, 1):
            with self.subTest(order=order):
                pay_wf, adapter, queue = self._build_two_units()
                self._record_uncertain(pay_wf, adapter, "INV-BYM-1", "EVI-ABS-A1",
                                       "UNIT-BANYUMEDIA", "ACC-BANYUMEDIA")
                self._record_uncertain(pay_wf, adapter, "INV-PRI-1", "EVI-ABS-B1",
                                       "UNIT-PR1ME", "ACC-PR1ME")
                pair = (
                    _assignment("ACTOR-FIN", "UNIT-BANYUMEDIA",
                                ("FINANCE-REQUESTER",), "ASSIGNMENT-FIN-B"),
                    _assignment("ACTOR-FIN", "UNIT-PR1ME",
                                ("FINANCE-REQUESTER",), "ASSIGNMENT-FIN-P"),
                )
                both = pair if order == 0 else (pair[1], pair[0])
                result = pay_wf.reconcile_payment(
                    evidence_ref="EVI-ABS-B1",
                    actor_ref="ACTOR-FIN", at=_t(11),
                    binding=_fin_binding(), assignments=both,
                    channel_ref="CHANNEL-WA-1",
                )
                self.assertEqual(result.outcome, "REJECTED")
                self.assertIn("EVI-ABS-A1", pay_wf._pending_uncertain)
                self.assertNotIn("EVI-ABS-B1", pay_wf._pending_uncertain)
                claims = list(pay_wf._claims.values())
                a_claim = next(c for c in claims if c.invoice_ref == "INV-BYM-1")
                b_claim = next(c for c in claims if c.invoice_ref == "INV-PRI-1")
                self.assertEqual(a_claim.outcome, "UNCERTAIN")
                self.assertEqual(b_claim.outcome, "REJECTED")

    def test_in_scope_absent_reconcile_rejects_claim(self) -> None:
        """Authorized path still works: a unit-A actor reconcile ABSENT
        rejects the unit-A claim with audit."""
        pay_wf, adapter, queue = self._build_two_units()
        self._record_uncertain(pay_wf, adapter, "INV-BYM-1", "EVI-ABS-A2",
                               "UNIT-BANYUMEDIA", "ACC-BANYUMEDIA")
        result = pay_wf.reconcile_payment(
            evidence_ref="EVI-ABS-A2",
            actor_ref="ACTOR-FIN", at=_t(11),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.outcome, "REJECTED")
        self.assertNotIn("EVI-ABS-A2", pay_wf._pending_uncertain)
        claims = [c for c in pay_wf._claims.values()]
        self.assertTrue(any(c.outcome == "REJECTED" for c in claims))
        # ABSENT resolution is audited.
        events = pay_wf.audit_events("EVI-ABS-A2")
        self.assertTrue(any(e["action"] == "reconcile_absent" for e in events))


class TestReconcileDenialAudit(unittest.TestCase):
    """QA-R2-F-03: every reconcile denial path — including the early-deny
    guards — must emit a denial audit record, matching the invoice_post
    bar (audit on ALL denial/transition paths)."""

    def test_reconcile_no_pending_denial_is_audited(self) -> None:
        """Reconciling an evidence ref with no pending UNCERTAIN payment
        is denied AND audited (action + INVALID_STATE code)."""
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        from src.workflows.payments.workflow import WorkflowBlocked
        with self.assertRaises(WorkflowBlocked) as ctx:
            pay_wf.reconcile_payment(
                evidence_ref="EVI-NOPE-1",
                actor_ref="ACTOR-FIN", at=_t(11),
                binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("no pending uncertain", str(ctx.exception))
        denied = pay_wf.denied_events()
        matches = [e for e in denied if e["action"] == "reconcile_payment"]
        self.assertTrue(matches)
        self.assertEqual(matches[0]["code"], "INVALID_STATE")
        self.assertEqual(matches[0]["actor_ref"], "ACTOR-FIN")


class TestReceivablesAging(unittest.TestCase):
    """R-013/R-017/R-019: authorized aging read model over provider records."""

    def _query(self, aging, **overrides):
        params = dict(
            actor_ref="ACTOR-VIEWER", at=_t(20),
            binding=_viewer_binding(),
            assignments=(_viewer_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        params.update(overrides)
        return aging.query_aging(**params)

    def test_open_invoice_appears_in_aging(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        result = self._query(aging)
        self.assertTrue(result.scoped)
        self.assertEqual(len(result.entries), 1)
        entry = result.entries[0]
        self.assertEqual(entry.invoice_ref, invoice_ref)
        self.assertEqual(entry.receivable_status, "OPEN")
        self.assertEqual(float(entry.open_amount), 1500000.0)
        self.assertEqual(float(result.total_open_amount), 1500000.0)

    def test_partial_payment_appears_as_partially_paid(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        _record(pay_wf, invoice_ref, amount="500000.00",
                evidence_ref="EVI-AGE-1")
        result = self._query(aging)
        self.assertEqual(len(result.entries), 1)
        entry = result.entries[0]
        self.assertEqual(entry.receivable_status, "PARTIALLY_PAID")
        self.assertEqual(float(entry.open_amount), 1000000.0)
        # Balances reconcile: total_open == sum of entries.
        from decimal import Decimal
        summed = sum(Decimal(e.open_amount) for e in result.entries)
        self.assertEqual(Decimal(result.total_open_amount), summed)

    def test_fully_paid_invoice_leaves_aging(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        _record(pay_wf, invoice_ref, amount="1500000.00",
                evidence_ref="EVI-AGE-2")
        result = self._query(aging)
        self.assertEqual(result.entries, ())
        self.assertEqual(float(result.total_open_amount), 0.0)

    def test_reversal_returns_invoice_to_aging(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        invoice_ref = _post_invoice(draft_wf, post_wf)
        paid = _record(pay_wf, invoice_ref, amount="1500000.00",
                       evidence_ref="EVI-AGE-3")
        self.assertEqual(self._query(aging).entries, ())
        pay_wf.reverse_payment(
            payment_ref=paid.payment_ref, reason="aging recompute",
            actor_ref="ACTOR-FIN", at=_t(11),
            binding=_fin_binding(),
            assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        result = self._query(aging)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].receivable_status, "OPEN")

    def test_cross_unit_scope_never_leaks(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        # Post one invoice in EACH unit.
        _post_invoice(draft_wf, post_wf, unit_ref="UNIT-BANYUMEDIA")
        _post_invoice(draft_wf, post_wf, unit_ref="UNIT-PR1ME")
        # Viewer is only authorized for BANYUMEDIA.
        result = self._query(aging)
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].unit_ref, "UNIT-BANYUMEDIA")
        import json
        from dataclasses import asdict
        self.assertNotIn("PR1ME", json.dumps([asdict(e) for e in result.entries]))

    def test_explicit_foreign_unit_filter_denied(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        _post_invoice(draft_wf, post_wf, unit_ref="UNIT-PR1ME")
        with self.assertRaises(Exception) as ctx:
            # Viewer (BANYUMEDIA-only) asks for PR1ME explicitly.
            self._query(aging, unit_ref="UNIT-PR1ME")
        self.assertNotIn("PR1ME", str(ctx.exception))
        denied = aging.denied_events()
        self.assertTrue(any(e["action"] == "query_aging" for e in denied))

    def test_multi_unit_actor_sees_all_own_units(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        _post_invoice(draft_wf, post_wf, unit_ref="UNIT-BANYUMEDIA")
        _post_invoice(draft_wf, post_wf, unit_ref="UNIT-PR1ME")
        from src.authz.access import IdentityBinding
        from src.authz.access import ActorUnitAssignment
        both = (
            ActorUnitAssignment(
                actor_ref="ACTOR-VIEWER", unit_ref="UNIT-BANYUMEDIA",
                roles=("FINANCE-REVIEWER",), active=True,
                assignment_ref="ASSIGNMENT-VIEW-B", revision=1,
            ),
            ActorUnitAssignment(
                actor_ref="ACTOR-VIEWER", unit_ref="UNIT-PR1ME",
                roles=("FINANCE-REVIEWER",), active=True,
                assignment_ref="ASSIGNMENT-VIEW-P", revision=1,
            ),
        )
        result = aging.query_aging(
            actor_ref="ACTOR-VIEWER", at=_t(20),
            binding=_viewer_binding(), assignments=both,
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(len(result.entries), 2)
        self.assertEqual(
            {e.unit_ref for e in result.entries},
            {"UNIT-BANYUMEDIA", "UNIT-PR1ME"},
        )
        self.assertEqual(float(result.total_open_amount), 3000000.0)

    def test_query_requires_query_receivable_action(self) -> None:
        draft_wf, post_wf, pay_wf, aging, adapter, queue = _build()
        _post_invoice(draft_wf, post_wf)
        # FINANCE-REQUESTER lacks QUERY_RECEIVABLE.
        with self.assertRaises(Exception) as ctx:
            aging.query_aging(
                actor_ref="ACTOR-FIN", at=_t(20),
                binding=_fin_binding(),
                assignments=(_finance_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("not be authorized", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
