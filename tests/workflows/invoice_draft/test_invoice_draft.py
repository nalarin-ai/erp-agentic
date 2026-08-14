"""RED-first tests for FLOW-001: chat invoice draft and preview.

Covers R-003/R-004 (chat channel, actor→unit resolution before data),
R-006/R-007 (draft→preview, idempotency, audit), R-011 (multi-unit isolation),
R-016/R-017/R-019 (separate issuer/tax identity, ledger/account from policy —
never branding), R-020 (unit branding profile on preview), R-021 (one active
unit context; ambiguous/denied/stale fail closed), R-022 (versioned settings
drive template/branding; version conflicts invalidate preview).

Preview must make ZERO provider writes; edits invalidate the preview hash and
scoped caches; users get a complete preview or a precise safe blocker.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone


def _t(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _build_workflow():
    """Wire the workflow with fixture dependencies. RED: module absent."""
    from src.adapters.fixture.erp import FixtureErpAdapter
    from src.policy.financial_identity import (
        FinancialIdentityPolicy,
        FinancialPolicyResolver,
        TrustedIssuer,
    )
    from src.units.registry import UnitRegistry
    from src.units.settings import UnitSettingsStore
    from src.workflows.invoice_draft.workflow import InvoiceDraftWorkflow

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
    from src.contracts.financial_identity import FinancialIdentity
    identity_b = FinancialIdentity(
        "UNIT-BANYUMEDIA", "ISSUER-BANYUMEDIA", "TAX-NONPPN",
        "SERIES-BYM", "LEDGER-BYM", "ACC-BANYUMEDIA",
    )
    identity_p = FinancialIdentity(
        "UNIT-PR1ME", "ISSUER-PR1ME", "TAX-NONPPN",
        "SERIES-PR1", "LEDGER-PR1", "ACC-PR1ME",
    )
    catalog = issuer.issue_catalog("CATALOG-FLOW1", 1, "EVIDENCE-FLOW1",
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
    return InvoiceDraftWorkflow(
        registry=registry, settings=settings, resolver=resolver, adapter=adapter,
    )


def _assignment(unit_ref: str, roles=("FINANCE-REQUESTER",), revision: int = 1,
                assignment_ref: str = "ASSIGNMENT-1", active: bool = True):
    from src.authz.access import ActorUnitAssignment
    return ActorUnitAssignment(
        actor_ref="ACTOR-1", unit_ref=unit_ref, roles=roles, active=active,
        assignment_ref=assignment_ref, revision=revision,
    )


def _binding():
    from src.authz.access import IdentityBinding
    return IdentityBinding(actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1", active=True)


def _lines():
    return ({"service_ref": "SVC-ADS-01", "description": "Ads management",
             "quantity": "1", "unit_price_amount": "1500000", "currency": "IDR"},)


class TestDraftCollection(unittest.TestCase):
    def test_open_draft_requires_verified_identity(self) -> None:
        wf = _build_workflow()
        with self.assertRaises(Exception) as ctx:
            wf.open_draft(
                actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1",
                binding=None, assignments=(_assignment("UNIT-BANYUMEDIA"),),
                customer_ref="CUST-1", at=_t(3),
            )
        self.assertIn("not be authorized", str(ctx.exception))

    def test_open_draft_denied_without_assignment(self) -> None:
        wf = _build_workflow()
        with self.assertRaises(Exception):
            wf.open_draft(
                actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1",
                binding=_binding(), assignments=(),
                customer_ref="CUST-1", at=_t(3),
            )

    def test_open_draft_ambiguous_multi_unit_requires_selection(self) -> None:
        wf = _build_workflow()
        with self.assertRaises(Exception) as ctx:
            wf.open_draft(
                actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1",
                binding=_binding(),
                assignments=(_assignment("UNIT-BANYUMEDIA"),
                             _assignment("UNIT-PR1ME", assignment_ref="ASSIGNMENT-2")),
                customer_ref="CUST-1", at=_t(3),
            )
        # safe denial: no unit leaked in message
        self.assertNotIn("BANYUMEDIA", str(ctx.exception))

    def test_open_draft_with_explicit_unit_succeeds(self) -> None:
        wf = _build_workflow()
        handle = wf.open_draft(
            actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1",
            binding=_binding(), assignments=(_assignment("UNIT-BANYUMEDIA"),),
            customer_ref="CUST-1", at=_t(3),
        )
        self.assertTrue(handle.draft_id.startswith("DFT-"))
        self.assertEqual(handle.unit_ref, "UNIT-BANYUMEDIA")

    def test_open_draft_idempotent_on_client_key(self) -> None:
        wf = _build_workflow()
        kwargs = dict(
            actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1",
            binding=_binding(), assignments=(_assignment("UNIT-BANYUMEDIA"),),
            customer_ref="CUST-1", at=_t(3),
        )
        first = wf.open_draft(idempotency_key="CHATMSG-1", **kwargs)
        second = wf.open_draft(idempotency_key="CHATMSG-1", **kwargs)
        self.assertEqual(first.draft_id, second.draft_id)


class TestLineCollectionAndEdit(unittest.TestCase):
    def _open(self):
        wf = _build_workflow()
        handle = wf.open_draft(
            actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1",
            binding=_binding(), assignments=(_assignment("UNIT-BANYUMEDIA"),),
            customer_ref="CUST-1", at=_t(3),
        )
        return wf, handle

    def test_set_lines_normalizes_and_stores(self) -> None:
        wf, handle = self._open()
        wf.set_lines(handle.draft_id, _lines(),
                     actor_ref="ACTOR-1", at=_t(4),
                     binding=_binding(),
                     assignments=(_assignment("UNIT-BANYUMEDIA"),))
        draft = wf.get_draft(handle.draft_id)
        self.assertEqual(len(draft.lines), 1)
        self.assertEqual(draft.lines[0]["service_ref"], "SVC-ADS-01")

    def test_set_lines_rejects_non_positive_quantity(self) -> None:
        wf, handle = self._open()
        bad = ({"service_ref": "SVC-ADS-01", "description": "x",
                "quantity": "0", "unit_price_amount": "100", "currency": "IDR"},)
        with self.assertRaises(Exception):
            wf.set_lines(handle.draft_id, bad, actor_ref="ACTOR-1", at=_t(4),
                         binding=_binding(),
                         assignments=(_assignment("UNIT-BANYUMEDIA"),))

    def test_set_lines_rejects_unknown_actor(self) -> None:
        wf, handle = self._open()
        with self.assertRaises(Exception):
            wf.set_lines(handle.draft_id, _lines(),
                         actor_ref="ACTOR-INTRUDER", at=_t(4),
                         binding=_binding(),
                         assignments=(_assignment("UNIT-BANYUMEDIA"),))

    def test_edit_after_preview_invalidates_preview_hash(self) -> None:
        wf, handle = self._open()
        wf.set_lines(handle.draft_id, _lines(),
                     actor_ref="ACTOR-1", at=_t(4),
                     binding=_binding(),
                     assignments=(_assignment("UNIT-BANYUMEDIA"),))
        preview1 = wf.preview(handle.draft_id, actor_ref="ACTOR-1",
                              binding=_binding(),
                              assignments=(_assignment("UNIT-BANYUMEDIA"),),
                              at=_t(5))
        wf.set_lines(
            handle.draft_id,
            ({"service_ref": "SVC-ADS-02", "description": "SEO",
              "quantity": "2", "unit_price_amount": "750000", "currency": "IDR"},),
            actor_ref="ACTOR-1", at=_t(6),
            binding=_binding(),
            assignments=(_assignment("UNIT-BANYUMEDIA"),),
        )
        preview2 = wf.preview(handle.draft_id, actor_ref="ACTOR-1",
                              binding=_binding(),
                              assignments=(_assignment("UNIT-BANYUMEDIA"),),
                              at=_t(7))
        self.assertNotEqual(preview1.preview_hash, preview2.preview_hash)

    def test_cancel_draft_blocks_further_edits(self) -> None:
        wf, handle = self._open()
        wf.cancel(handle.draft_id, actor_ref="ACTOR-1", at=_t(4),
                  binding=_binding(),
                  assignments=(_assignment("UNIT-BANYUMEDIA"),))
        with self.assertRaises(Exception):
            wf.set_lines(handle.draft_id, _lines(),
                         actor_ref="ACTOR-1", at=_t(5),
                         binding=_binding(),
                         assignments=(_assignment("UNIT-BANYUMEDIA"),))


class TestPreview(unittest.TestCase):
    def _ready(self):
        wf = _build_workflow()
        handle = wf.open_draft(
            actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1",
            binding=_binding(), assignments=(_assignment("UNIT-BANYUMEDIA"),),
            customer_ref="CUST-1", at=_t(3),
        )
        wf.set_lines(handle.draft_id, _lines(), actor_ref="ACTOR-1", at=_t(4),
                     binding=_binding(),
                     assignments=(_assignment("UNIT-BANYUMEDIA"),))
        return wf, handle

    def test_preview_makes_zero_provider_writes(self) -> None:
        wf, handle = self._ready()
        adapter = wf._adapter  # fixture; inspecting write counters
        before = len(adapter._invoices)
        wf.preview(handle.draft_id, actor_ref="ACTOR-1", binding=_binding(),
                   assignments=(_assignment("UNIT-BANYUMEDIA"),), at=_t(5))
        self.assertEqual(len(adapter._invoices), before)

    def test_preview_resolves_branding_from_active_unit_settings(self) -> None:
        wf, handle = self._ready()
        preview = wf.preview(handle.draft_id, actor_ref="ACTOR-1",
                             binding=_binding(),
                             assignments=(_assignment("UNIT-BANYUMEDIA"),),
                             at=_t(5))
        self.assertEqual(preview.invoice_template_ref, "tpl_banyu_v1")
        self.assertEqual(preview.logo_asset_ref, "logo_banyu_v1")
        self.assertEqual(preview.configuration_version, 1)

    def test_preview_carries_policy_identity_separate_from_branding(self) -> None:
        wf, handle = self._ready()
        preview = wf.preview(handle.draft_id, actor_ref="ACTOR-1",
                             binding=_binding(),
                             assignments=(_assignment("UNIT-BANYUMEDIA"),),
                             at=_t(5))
        # Financial identity from FND-003 policy — NOT from branding/settings.
        self.assertEqual(preview.legal_issuer_ref, "ISSUER-BANYUMEDIA")
        self.assertEqual(preview.invoice_series_ref, "SERIES-BYM")
        self.assertEqual(preview.receivable_ledger_ref, "LEDGER-BYM")
        # Destination account stays redacted on the preview descriptor.
        self.assertEqual(preview.destination_account_alias, "ACC-[REDACTED]")

    def test_preview_denied_when_assignment_revoked(self) -> None:
        wf, handle = self._ready()
        revoked = _assignment("UNIT-BANYUMEDIA", active=False)
        with self.assertRaises(Exception):
            wf.preview(handle.draft_id, actor_ref="ACTOR-1", binding=_binding(),
                       assignments=(revoked,), at=_t(5))

    def test_preview_denied_stale_assignment_revision(self) -> None:
        wf, handle = self._ready()
        preview = wf.preview(handle.draft_id, actor_ref="ACTOR-1",
                             binding=_binding(),
                             assignments=(_assignment("UNIT-BANYUMEDIA"),),
                             at=_t(5))
        # Caller replays with an older expected revision.
        with self.assertRaises(Exception):
            wf.preview(handle.draft_id, actor_ref="ACTOR-1", binding=_binding(),
                       assignments=(_assignment("UNIT-BANYUMEDIA", revision=2),),
                       expected_assignment_revision=1, at=_t(6))

    def test_preview_blocked_without_lines(self) -> None:
        wf = _build_workflow()
        handle = wf.open_draft(
            actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1",
            binding=_binding(), assignments=(_assignment("UNIT-BANYUMEDIA"),),
            customer_ref="CUST-1", at=_t(3),
        )
        with self.assertRaises(Exception) as ctx:
            wf.preview(handle.draft_id, actor_ref="ACTOR-1", binding=_binding(),
                       assignments=(_assignment("UNIT-BANYUMEDIA"),), at=_t(4))
        self.assertIn("line", str(ctx.exception).lower())

    def test_preview_total_uses_money_semantics(self) -> None:
        wf, handle = self._ready()
        preview = wf.preview(handle.draft_id, actor_ref="ACTOR-1",
                             binding=_binding(),
                             assignments=(_assignment("UNIT-BANYUMEDIA"),),
                             at=_t(5))
        self.assertEqual(preview.total_amount, "1500000.00")
        self.assertEqual(preview.currency, "IDR")

    def test_preview_denied_on_configuration_version_conflict(self) -> None:
        """R-022: a preview bound to settings version N must refuse when the
        active version has moved on (stale config)."""
        wf, handle = self._ready()
        preview = wf.preview(handle.draft_id, actor_ref="ACTOR-1",
                             binding=_binding(),
                             assignments=(_assignment("UNIT-BANYUMEDIA"),),
                             at=_t(5))
        self.assertEqual(preview.configuration_version, 1)
        # Rotate settings to version 2.
        store = wf._settings
        draft2 = store.draft("BANYUMEDIA",
                             {"default_currency": "IDR",
                              "invoice_template_ref": "tpl_banyu_v2"},
                             author="alice", at=_t(6))
        store.activate("BANYUMEDIA", draft2.configuration_version,
                       expected_version=1, at=_t(7), actor="bos",
                       effective_from=_t(8))
        with self.assertRaises(Exception) as ctx:
            wf.render_for_review(preview, at=_t(9), actor_ref="ACTOR-1",
                                 binding=_binding(),
                                 assignments=(_assignment("UNIT-BANYUMEDIA"),))
        self.assertIn("configuration", str(ctx.exception).lower())


class TestAudit(unittest.TestCase):
    def test_material_transitions_are_audited(self) -> None:
        wf = _build_workflow()
        handle = wf.open_draft(
            actor_ref="ACTOR-1", channel_ref="CHANNEL-WA-1",
            binding=_binding(), assignments=(_assignment("UNIT-BANYUMEDIA"),),
            customer_ref="CUST-1", at=_t(3),
        )
        wf.set_lines(handle.draft_id, _lines(), actor_ref="ACTOR-1", at=_t(4),
                     binding=_binding(),
                     assignments=(_assignment("UNIT-BANYUMEDIA"),))
        wf.preview(handle.draft_id, actor_ref="ACTOR-1", binding=_binding(),
                   assignments=(_assignment("UNIT-BANYUMEDIA"),), at=_t(5))
        events = wf.audit_events(handle.draft_id)
        actions = [e["action"] for e in events]
        self.assertIn("open", actions)
        self.assertIn("set_lines", actions)
        self.assertIn("preview", actions)
        for event in events:
            self.assertEqual(event["actor_ref"], "ACTOR-1")


if __name__ == "__main__":
    unittest.main()
