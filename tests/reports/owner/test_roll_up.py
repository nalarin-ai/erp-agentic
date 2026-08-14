"""RED-first tests for RPT-001: Owner financial roll-up.

Covers R-001 (owner role-scoped multi-unit oversight without ledger merge),
R-011 (separate commercial entities; no cross-unit leakage), R-021
(effective-dated multi-unit assignments; deny unassigned/inactive/stale).

Design (recorded per task):
- Authorization action: QUERY_RECEIVABLE (existing, OWNER role holds it).
  No new registered actions (src/authz/access.py is outside owned paths).
- Aggregation: per-unit authorized reads via ErpPort.query_invoices +
  read_invoice; each unit's contribution is individually authorized.
  No cross-unit merge of ledger records; per-unit subtotals + owner total.
- Caching: NONE. Assignment changes take effect on next call.
- Multi-currency: per-currency subtotals within each unit; never mixed.
- As-of: per-unit as_of timestamp (ISO-8601 UTC) recorded at read time.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.adapters.fixture.erp import FixtureErpAdapter
from src.authz.access import (
    ActorUnitAssignment,
    IdentityBinding,
)
from src.contracts.erp_port import (
    DraftInvoiceCommand,
    InvoiceLine,
)
from src.contracts.financial_identity import FinancialIdentity


def _t(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


# --------------------------------------------------------------------------
# Helpers: seed invoices directly into the fixture (no full workflow needed)
# --------------------------------------------------------------------------


def _seed_invoice(
    adapter: FixtureErpAdapter,
    *,
    unit_ref: str,
    customer_ref: str,
    amount: str,
    currency: str,
) -> str:
    """Create + post an invoice in the fixture; returns official INV- ref."""
    identity = FinancialIdentity(
        operating_unit_ref=unit_ref,
        legal_issuer_ref=f"ISSUER-{unit_ref.removeprefix('UNIT-')}",
        tax_profile_ref="TAX-NONPPN",
        invoice_series_ref=f"SERIES-{unit_ref.removeprefix('UNIT-')[:3]}",
        receivable_ledger_ref=f"LEDGER-{unit_ref.removeprefix('UNIT-')[:3]}",
        destination_account_alias=f"ACC-{unit_ref.removeprefix('UNIT-')}",
    )
    cmd = DraftInvoiceCommand(
        customer_ref=customer_ref,
        identity=identity,
        lines=(
            InvoiceLine(
                service_ref="SVC-ADS-01",
                description="Ads mgmt",
                quantity="1",
                unit_price_amount=amount,
                currency=currency,
            ),
        ),
        issued_on="2026-08-01",
        due_on="2026-08-15",
    )
    draft_ref = adapter.create_draft_invoice(cmd)
    result = adapter.post_invoice(draft_ref)
    assert result.outcome.value == "POSTED"
    assert result.reference is not None
    return result.reference


def _seed_payment(
    adapter: FixtureErpAdapter,
    *,
    invoice_ref: str,
    amount: str,
    currency: str,
    evidence_ref: str,
) -> str:
    from src.contracts.erp_port import DraftPaymentCommand

    return adapter.record_payment(
        DraftPaymentCommand(
            invoice_ref=invoice_ref,
            amount=amount,
            currency=currency,
            evidence_ref=evidence_ref,
            destination_account_alias="ACC-BANYUMEDIA",
        )
    )


def _owner_assignment(
    unit_ref: str,
    *,
    active: bool = True,
    revision: int = 1,
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
    assignment_ref: str | None = None,
) -> ActorUnitAssignment:
    return ActorUnitAssignment(
        actor_ref="ACTOR-OWNER",
        unit_ref=unit_ref,
        roles=("OWNER",),
        active=active,
        assignment_ref=assignment_ref or f"ASSIGNMENT-OWN-{unit_ref.removeprefix('UNIT-')}",
        revision=revision,
        effective_from=effective_from,
        effective_until=effective_until,
    )


def _owner_binding() -> IdentityBinding:
    return IdentityBinding(
        actor_ref="ACTOR-OWNER", channel_ref="CHANNEL-WA-1", active=True
    )


def _non_owner_assignment(unit_ref: str, role: str = "FINANCE-REVIEWER") -> ActorUnitAssignment:
    return ActorUnitAssignment(
        actor_ref="ACTOR-FIN",
        unit_ref=unit_ref,
        roles=(role,),
        active=True,
        assignment_ref=f"ASSIGNMENT-FIN-{unit_ref.removeprefix('UNIT-')}",
        revision=1,
    )


def _non_owner_binding() -> IdentityBinding:
    return IdentityBinding(actor_ref="ACTOR-FIN", channel_ref="CHANNEL-WA-1", active=True)


def _build_report(adapter: FixtureErpAdapter):
    """RED: the module does not exist yet."""
    from src.reports.owner.roll_up import OwnerRollupReport

    return OwnerRollupReport(adapter=adapter)


# ===========================================================================
# Happy paths
# ===========================================================================


class TestOwnerRollupHappyPaths(unittest.TestCase):
    """R-001: owner sees authorized per-unit subtotals + reconciled total."""

    def test_owner_with_two_units_sees_both_subtotals_and_total(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="CUST-1",
                      amount="1500000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="CUST-2",
                      amount="500000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="CUST-3",
                      amount="750000", currency="IDR")

        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment("UNIT-PR1ME"),
            ),
            channel_ref="CHANNEL-WA-1",
        )

        unit_refs = {u.unit_ref for u in result.per_unit}
        self.assertEqual(unit_refs, {"UNIT-BANYUMEDIA", "UNIT-PR1ME"})
        by_unit = {u.unit_ref: u for u in result.per_unit}
        self.assertEqual(by_unit["UNIT-BANYUMEDIA"].open_amount_total, "2000000")
        self.assertEqual(by_unit["UNIT-PR1ME"].open_amount_total, "750000")
        # Owner-level total reconciles
        self.assertEqual(result.owner_open_amount_total, "2750000")
        self.assertEqual(result.currency, "IDR")
        # As-of timestamp present
        self.assertIsNotNone(result.as_of)
        for u in result.per_unit:
            self.assertIsNotNone(u.as_of)

    def test_owner_single_assignment_gets_single_unit_rollup(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="CUST-1",
                      amount="100000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="CUST-2",
                      amount="999999", currency="IDR")

        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(len(result.per_unit), 1)
        self.assertEqual(result.per_unit[0].unit_ref, "UNIT-BANYUMEDIA")
        self.assertEqual(result.owner_open_amount_total, "100000")

    def test_owner_rollup_excludes_paid_invoices(self) -> None:
        adapter = FixtureErpAdapter()
        ref = _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="CUST-1",
                            amount="100000", currency="IDR")
        _seed_payment(adapter, invoice_ref=ref, amount="100000", currency="IDR",
                      evidence_ref="EVI-FULL-1")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.owner_open_amount_total, "0")

    def test_partial_payment_reflected_in_open_amount(self) -> None:
        adapter = FixtureErpAdapter()
        ref = _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="CUST-1",
                            amount="100000", currency="IDR")
        _seed_payment(adapter, invoice_ref=ref, amount="40000", currency="IDR",
                      evidence_ref="EVI-PART-1")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.owner_open_amount_total, "60000")

    def test_per_unit_invoice_count_matches_open_invoices(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="CUST-1",
                      amount="100", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="CUST-2",
                      amount="200", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="CUST-3",
                      amount="300", currency="IDR")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.per_unit[0].open_invoice_count, 3)


# ===========================================================================
# Reconciliation
# ===========================================================================


class TestOwnerRollupReconciliation(unittest.TestCase):
    """Owner roll-up totals reconcile against independent direct computation."""

    def test_total_reconciles_with_synthetic_ledger(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C2",
                      amount="2000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="C3",
                      amount="3000", currency="IDR")

        # Independent direct computation
        from decimal import Decimal
        expected_by_unit: dict[str, Decimal] = {"UNIT-BANYUMEDIA": Decimal(0), "UNIT-PR1ME": Decimal(0)}
        for unit in expected_by_unit:
            qr = adapter.query_invoices(status="POSTED", operating_unit_ref=unit)
            for ref in qr.references:
                rec = adapter.read_invoice(ref)
                expected_by_unit[unit] += Decimal(rec.open_amount)

        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment("UNIT-PR1ME"),
            ),
            channel_ref="CHANNEL-WA-1",
        )

        from decimal import Decimal as D
        by_unit_actual = {u.unit_ref: D(u.open_amount_total) for u in result.per_unit}
        self.assertEqual(by_unit_actual, expected_by_unit)
        self.assertEqual(
            D(result.owner_open_amount_total),
            sum(expected_by_unit.values(), D(0)),
        )


# ===========================================================================
# Negative authorization — R-021 deny paths
# ===========================================================================


class TestOwnerRollupNegativeAuthorization(unittest.TestCase):
    """R-021: deny unassigned/inactive/stale; R-011: no cross-unit leakage."""

    def test_zero_assignments_denied(self) -> None:
        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        with self.assertRaises(Exception) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=_owner_binding(),
                assignments=(),
                channel_ref="CHANNEL-WA-1",
            )
        # Safe denial — message must not leak
        self.assertIn("cannot be authorized", str(ctx.exception).lower())

    def test_inactive_assignment_excluded(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="C2",
                      amount="2000", currency="IDR")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment("UNIT-PR1ME", active=False),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        unit_refs = {u.unit_ref for u in result.per_unit}
        self.assertEqual(unit_refs, {"UNIT-BANYUMEDIA"})
        self.assertEqual(result.owner_open_amount_total, "1000")

    def test_expired_assignment_excluded(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="C2",
                      amount="2000", currency="IDR")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),  # after expiry
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment(
                    "UNIT-PR1ME",
                    effective_from=_t(0),
                    effective_until=_t(5),
                ),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        unit_refs = {u.unit_ref for u in result.per_unit}
        self.assertEqual(unit_refs, {"UNIT-BANYUMEDIA"})

    def test_not_yet_effective_assignment_excluded(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="C2",
                      amount="2000", currency="IDR")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),  # before effective_from
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment(
                    "UNIT-PR1ME",
                    effective_from=_t(20),
                    effective_until=None,
                ),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        unit_refs = {u.unit_ref for u in result.per_unit}
        self.assertEqual(unit_refs, {"UNIT-BANYUMEDIA"})

    def test_non_owner_role_denied_rollup(self) -> None:
        """A FINANCE-REVIEWER must not get cross-unit owner aggregation."""
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        report = _build_report(adapter)
        with self.assertRaises(Exception) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-FIN",
                at=_t(10),
                binding=_non_owner_binding(),
                assignments=(_non_owner_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertIn("cannot be authorized", str(ctx.exception).lower())

    def test_unverified_identity_denied(self) -> None:
        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        with self.assertRaises(Exception):
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=None,  # no binding
                assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )

    def test_inactive_binding_denied(self) -> None:
        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        with self.assertRaises(Exception):
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=IdentityBinding(
                    actor_ref="ACTOR-OWNER", channel_ref="CHANNEL-WA-1", active=False
                ),
                assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )

    def test_denial_is_logged_for_audit(self) -> None:
        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        with self.assertRaises(Exception):
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=_owner_binding(),
                assignments=(),  # zero assignments
                channel_ref="CHANNEL-WA-1",
            )
        events = report.denied_events()
        self.assertTrue(any(e.get("action") == "query_rollup" for e in events))

    def test_denial_message_is_generic_and_does_not_disclose(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        report = _build_report(adapter)
        with self.assertRaises(Exception) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=_owner_binding(),
                assignments=(),
                channel_ref="CHANNEL-WA-1",
            )
        msg = str(ctx.exception)
        # Must not reveal which units exist or why in a disclosive way
        self.assertNotIn("BANYUMEDIA", msg)
        self.assertNotIn("PR1ME", msg)

    def test_denial_message_is_exactly_generic(self) -> None:
        """Pin: the denial message is EXACTLY the generic string.

        No denial code, unit ref, or reason may be embedded in the
        human-facing message (kills mutant M6).
        """
        from src.reports.owner.roll_up import WorkflowDenied

        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        with self.assertRaises(WorkflowDenied) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=_owner_binding(),
                assignments=(),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(str(ctx.exception), "Request cannot be authorized.")

    def test_unverified_identity_denial_code_is_identity_unverified(self) -> None:
        """Pin: binding=None yields WorkflowDenied(IDENTITY_UNVERIFIED).

        The service-level identity pre-check must fire with the precise
        denial code (kills mutant M8).
        """
        from src.reports.owner.roll_up import WorkflowDenied

        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        with self.assertRaises(WorkflowDenied) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=None,
                assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(ctx.exception.code, "IDENTITY_UNVERIFIED")
        events = report.denied_events()
        self.assertTrue(
            any(e.get("code") == "IDENTITY_UNVERIFIED" for e in events),
            f"expected IDENTITY_UNVERIFIED in denial audit log: {events}",
        )

    def test_unverified_identity_denied_before_any_unit_authorization(self) -> None:
        """Pin: the service-level identity pre-check fires FIRST.

        With multiple units, removing the pre-check would let the first
        per-unit ``authorize()`` raise IDENTITY_UNVERIFIED — the code would
        match, so this test instead proves fail-fast behavior: identity is
        verified before ANY unit authorization runs, even when zero units
        are in scope (an unassigned actor still gets IDENTITY_UNVERIFIED,
        not PERMISSION_DENIED). This kills mutant M8 (pre-check removal),
        which would yield PERMISSION_DENIED here.
        """
        from src.reports.owner.roll_up import WorkflowDenied

        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        with self.assertRaises(WorkflowDenied) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=None,  # no binding AND no assignments
                assignments=(),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(ctx.exception.code, "IDENTITY_UNVERIFIED")
        events = report.denied_events()
        self.assertTrue(
            any(e.get("code") == "IDENTITY_UNVERIFIED" for e in events),
            f"expected IDENTITY_UNVERIFIED in denial audit log: {events}",
        )

    def test_duplicate_active_assignment_for_same_unit_denied(self) -> None:
        """Pin: duplicate ACTIVE assignments for the same unit must DENY.

        Scope derivation dedupes unit refs via a set, but the per-unit
        ``authorize()`` call requires exactly-one effective assignment;
        two active assignments for one unit is ambiguous and fail-closed.
        This pins ``_authorize_unit`` as the sole guard (kills mutant M2).
        """
        from src.reports.owner.roll_up import WorkflowDenied

        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        report = _build_report(adapter)
        with self.assertRaises(WorkflowDenied) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=_owner_binding(),
                assignments=(
                    _owner_assignment("UNIT-BANYUMEDIA", revision=1),
                    _owner_assignment("UNIT-BANYUMEDIA", revision=2),
                ),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        events = report.denied_events()
        self.assertTrue(
            any(e.get("code") == "PERMISSION_DENIED" for e in events),
            f"expected PERMISSION_DENIED in denial audit log: {events}",
        )


# ===========================================================================
# Input validation — fail-closed on invalid ``at`` (F-01)
# ===========================================================================


class TestOwnerRollupInputValidation(unittest.TestCase):
    """F-01: timezone-naive / invalid ``at`` must be denied + audited.

    A naive datetime combined with effective-dated (aware) assignments
    would raise a raw TypeError deep in scope derivation. The public entry
    point must fail closed instead: WorkflowDenied("INVALID_INPUT") plus a
    denial audit event — never an unwrapped, unaudited TypeError.
    """

    def test_naive_datetime_denied_invalid_input_and_audited(self) -> None:
        from src.reports.owner.roll_up import WorkflowDenied

        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        naive_at = datetime(2026, 8, 14, 0, 0, 0)  # no tzinfo
        with self.assertRaises(WorkflowDenied) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=naive_at,
                binding=_owner_binding(),
                assignments=(
                    _owner_assignment("UNIT-BANYUMEDIA", effective_from=_t(0)),
                ),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(ctx.exception.code, "INVALID_INPUT")
        self.assertEqual(str(ctx.exception), "Request cannot be authorized.")
        events = report.denied_events()
        self.assertTrue(
            any(
                e.get("action") == "query_rollup" and e.get("code") == "INVALID_INPUT"
                for e in events
            ),
            f"expected audited INVALID_INPUT denial: {events}",
        )

    def test_naive_datetime_denied_even_without_effective_dates(self) -> None:
        from src.reports.owner.roll_up import WorkflowDenied

        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        naive_at = datetime(2026, 8, 14, 0, 0, 0)
        with self.assertRaises(WorkflowDenied) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=naive_at,
                binding=_owner_binding(),
                assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(ctx.exception.code, "INVALID_INPUT")

    def test_wrong_type_at_denied_invalid_input(self) -> None:
        from src.reports.owner.roll_up import WorkflowDenied

        adapter = FixtureErpAdapter()
        report = _build_report(adapter)
        with self.assertRaises(WorkflowDenied) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at="2026-08-14",  # type: ignore[arg-type]
                binding=_owner_binding(),
                assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        self.assertEqual(ctx.exception.code, "INVALID_INPUT")

    def test_aware_datetime_still_accepted(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA", effective_from=_t(0)),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.owner_open_amount_total, "1000")

    def test_aware_non_utc_datetime_accepted(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        report = _build_report(adapter)
        wib = timezone(timedelta(hours=7))
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=datetime(2026, 8, 14, 7, 10, 0, tzinfo=wib),  # == _t(10) UTC
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA", effective_from=_t(0)),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.owner_open_amount_total, "1000")


# ===========================================================================
# Blocked (provider failure) paths — F-05
# ===========================================================================


class _RejectingAdapter:
    """Provider double that always rejects — for WorkflowBlocked paths."""

    def query_invoices(self, **kwargs: object) -> object:
        from src.contracts.erp_port import ProviderContractError

        raise ProviderContractError("sensitive provider detail: UNIT-BANYUMEDIA")


class TestOwnerRollupBlockedPaths(unittest.TestCase):
    """F-05: WorkflowBlocked message is generic; detail only in __cause__."""

    def test_blocked_message_is_generic_and_chained(self) -> None:
        from src.reports.owner.roll_up import WorkflowBlocked

        report = _build_report(_RejectingAdapter())
        with self.assertRaises(WorkflowBlocked) as ctx:
            report.query_rollup(
                actor_ref="ACTOR-OWNER",
                at=_t(10),
                binding=_owner_binding(),
                assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
                channel_ref="CHANNEL-WA-1",
            )
        # Top-level message is generic — no provider internals leak
        self.assertEqual(str(ctx.exception), "provider rejected receivables query")
        self.assertNotIn("BANYUMEDIA", str(ctx.exception))
        self.assertNotIn("sensitive", str(ctx.exception))
        # Chaining is acceptable: provider detail stays in __cause__ only
        self.assertIsNotNone(ctx.exception.__cause__)


# ===========================================================================
# Cross-unit leakage probes (R-011)
# ===========================================================================


class TestOwnerRollupCrossUnitLeakage(unittest.TestCase):
    """R-011: no route — filters, counts, export, error — leaks cross-unit data."""

    def test_owner_cannot_see_unassigned_unit_via_filter(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="C2",
                      amount="9999", currency="IDR")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        # Result must contain no reference to PR1ME at all
        self.assertEqual({u.unit_ref for u in result.per_unit}, {"UNIT-BANYUMEDIA"})
        blob = str(result)
        self.assertNotIn("PR1ME", blob)

    def test_unassigned_unit_contributes_nothing(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="C2",
                      amount="9999", currency="IDR")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        # Total must not include the unassigned unit's 9999
        self.assertEqual(result.owner_open_amount_total, "1000")

    def test_no_invoice_refs_leak_across_units(self) -> None:
        adapter = FixtureErpAdapter()
        ref_b = _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                              amount="1000", currency="IDR")
        ref_p = _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="C2",
                              amount="2000", currency="IDR")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment("UNIT-PR1ME"),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        by_unit = {u.unit_ref: u for u in result.per_unit}
        # Per-unit invoice refs are scoped to their own unit
        self.assertIn(ref_b, by_unit["UNIT-BANYUMEDIA"].invoice_refs)
        self.assertNotIn(ref_p, by_unit["UNIT-BANYUMEDIA"].invoice_refs)
        self.assertIn(ref_p, by_unit["UNIT-PR1ME"].invoice_refs)
        self.assertNotIn(ref_b, by_unit["UNIT-PR1ME"].invoice_refs)


# ===========================================================================
# Multi-currency
# ===========================================================================


class TestOwnerRollupMultiCurrency(unittest.TestCase):
    """Per-currency subtotals; never silently mixed."""

    def test_per_currency_subtotals_within_unit(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C2",
                      amount="50", currency="USD")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        unit = result.per_unit[0]
        # per-currency breakdown must be present
        currencies = {c.currency for c in unit.per_currency}
        self.assertEqual(currencies, {"IDR", "USD"})
        by_curr = {c.currency: c for c in unit.per_currency}
        self.assertEqual(by_curr["IDR"].open_amount_total, "1000")
        self.assertEqual(by_curr["USD"].open_amount_total, "50")
        # When multiple currencies present, the headline total is None
        # (cannot sum across currencies without an FX rate)
        self.assertIsNone(result.owner_open_amount_total)
        self.assertIsNone(result.currency)

    def test_single_currency_still_produces_total(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        report = _build_report(adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual(result.owner_open_amount_total, "1000")
        self.assertEqual(result.currency, "IDR")


# ===========================================================================
# Cache behavior
# ===========================================================================


class TestOwnerRollupCacheBehavior(unittest.TestCase):
    """No caching: assignment revocation/expiry reflects on the next call."""

    def test_revocation_reflected_immediately(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="C2",
                      amount="2000", currency="IDR")
        report = _build_report(adapter)

        # First call: owner sees both
        result1 = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment("UNIT-PR1ME"),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual({u.unit_ref for u in result1.per_unit},
                         {"UNIT-BANYUMEDIA", "UNIT-PR1ME"})

        # Revoke PR1ME (active=False); next call must NOT see it
        result2 = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(20),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment("UNIT-PR1ME", active=False),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        self.assertEqual({u.unit_ref for u in result2.per_unit}, {"UNIT-BANYUMEDIA"})


if __name__ == "__main__":
    unittest.main()
