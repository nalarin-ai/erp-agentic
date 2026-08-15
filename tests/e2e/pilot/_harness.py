"""PILOT-001 synthetic acceptance harness (seeder/facade).

Wires the REAL production components — UNIT-001 registry/settings, FND-002
authz, FND-003 financial policy, FLOW-001/002 workflows, CRM-001 port,
ISOFIX-001 final isolation policy — over the network-disabled fixture
adapters with synthetic opaque references only.

Safety invariants:
- No network: FixtureErpAdapter / FixtureCrmAdapter only; the live ERPNext
  pilot is never touched (no migration/destructive/credential actions).
- Synthetic opaque refs only (ACTOR-*, UNIT-*, CUST-*, SVC-*, ACC-*, ...).
- Idempotent build(): repeated PilotHarness.build() calls produce fresh,
  equivalent state; seeding is deterministic.
- ISO001_ENABLE_UNIT_USERS stays unset: unit-scoped roles exist ONLY on the
  gateway surface; native credential issuance is denied (ISOFIX-001).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from src.adapters.fixture.erp import FixtureErpAdapter
from src.adapters.fixture_crm import FixtureCrmAdapter
from src.authz.access import (
    ActorUnitAssignment,
    IdentityBinding,
)
from src.contracts.financial_identity import FinancialIdentity
from src.crm.port import (
    CrmIdentity,
    CrmQuery,
    CrmQueryPage,
    LeadCommand,
    LeadRecord,
)
from src.isolation_architecture import policy as isolation_policy
from src.policy.financial_identity import (
    FinancialIdentityPolicy,
    FinancialPolicyResolver,
    TrustedIssuer,
    TrustedIssuerRegistry,
)
from src.units.registry import UnitRegistry
from src.units.settings import UnitSettingsStore
from src.workflows.invoice_draft.workflow import (
    InvoiceDraftWorkflow,
    Preview,
)
from src.workflows.invoice_post.workflow import (
    InvoicePostWorkflow,
    PostedInvoiceRecord,
    PostResult,
)

T0 = datetime(2026, 8, 14, 0, 0, 0, tzinfo=timezone.utc)


class _PilotDraftWorkflow(InvoiceDraftWorkflow):
    """Harness glue: explicit unit-code map.

    The production `_unit_code_for_ref` derives refs as UNIT-{code}, which
    cannot represent underscore catalog codes (HEAVY_EQUIPMENT, PT_TKH_OPS)
    through the authz canonical-ref grammar. The harness binds an explicit
    code↔ref map instead. NOTE: this is a harness-side workaround for a
    latent source limitation; see docs/evidence/pilot/ac-02.md findings.
    """

    _CODE_BY_REF = {
        "UNIT-BANYUMEDIA": "BANYUMEDIA",
        "UNIT-PR1ME": "PR1ME",
        "UNIT-CONTRACTOR": "CONTRACTOR",
        "UNIT-HEAVYEQUIPMENT": "HEAVY_EQUIPMENT",
        "UNIT-PTTKHOPS": "PT_TKH_OPS",
    }

    def _unit_code_for_ref(self, unit_ref: str) -> str:
        try:
            return self._CODE_BY_REF[unit_ref]
        except KeyError:
            return super()._unit_code_for_ref(unit_ref)


class _PilotPostWorkflow(InvoicePostWorkflow):
    _CODE_BY_REF = _PilotDraftWorkflow._CODE_BY_REF

    def _unit_code_for_ref(self, unit_ref: str) -> str:
        try:
            return self._CODE_BY_REF[unit_ref]
        except KeyError:
            return super()._unit_code_for_ref(unit_ref)


def at(minutes: int = 0) -> datetime:
    """Deterministic synthetic clock anchored at T0."""
    return T0 + timedelta(minutes=minutes)


# Unit refs used across the pilot scenarios (catalog codes from
# config/fixtures/units/catalog.yaml — the normative synthetic source).
UNIT_BANYUMEDIA = "UNIT-BANYUMEDIA"
UNIT_PR1ME = "UNIT-PR1ME"
UNIT_CONTRACTOR = "UNIT-CONTRACTOR"
# NOTE: opaque refs use canonical [A-Z0-9-] form (src/contracts) — catalog
# codes with underscores map to dash-free ref suffixes.
UNIT_HEAVY_EQUIPMENT = "UNIT-HEAVYEQUIPMENT"
UNIT_PT_TKH = "UNIT-PTTKHOPS"

# catalog code -> unit ref
_UNIT_REF_BY_CODE = {
    "BANYUMEDIA": UNIT_BANYUMEDIA,
    "PR1ME": UNIT_PR1ME,
    "CONTRACTOR": UNIT_CONTRACTOR,
    "HEAVY_EQUIPMENT": UNIT_HEAVY_EQUIPMENT,
    "PT_TKH_OPS": UNIT_PT_TKH,
}

# Financial identity aliases per unit (FND-003). The Heavy Equipment policy
# deliberately binds the Contractor destination account alias (R-015 shared
# mapping); PT TKH is the sole PPN-issuing entity (R-016).
_IDENTITY_MATRIX: dict[str, dict[str, str]] = {
    UNIT_BANYUMEDIA: {
        "legal_issuer_ref": "ISSUER-BANYUMEDIA",
        "tax_profile_ref": "TAX-NONPPN",
        "invoice_series_ref": "SERIES-BYM",
        "receivable_ledger_ref": "LEDGER-BYM",
        "destination_account_alias": "ACC-BANYUMEDIA",
    },
    UNIT_PR1ME: {
        "legal_issuer_ref": "ISSUER-PR1ME",
        "tax_profile_ref": "TAX-NONPPN",
        "invoice_series_ref": "SERIES-PR1",
        "receivable_ledger_ref": "LEDGER-PR1",
        "destination_account_alias": "ACC-PR1ME",
    },
    UNIT_CONTRACTOR: {
        "legal_issuer_ref": "ISSUER-CONTRACTOR",
        "tax_profile_ref": "TAX-NONPPN",
        "invoice_series_ref": "SERIES-CTR",
        "receivable_ledger_ref": "LEDGER-CTR",
        "destination_account_alias": "ACC-CONTRACTOR",
    },
    UNIT_HEAVY_EQUIPMENT: {
        "legal_issuer_ref": "ISSUER-HEAVY-EQUIPMENT",
        "tax_profile_ref": "TAX-NONPPN",
        "invoice_series_ref": "SERIES-HEQ",
        "receivable_ledger_ref": "LEDGER-HEQ",
        # R-015: shared Contractor destination account (approved mapping).
        "destination_account_alias": "ACC-CONTRACTOR",
    },
    UNIT_PT_TKH: {
        "legal_issuer_ref": "ISSUER-PT-TKH",
        "tax_profile_ref": "TAX-PPN-11",
        "invoice_series_ref": "SERIES-TKH",
        "receivable_ledger_ref": "LEDGER-TKH",
        "destination_account_alias": "ACC-PT-TKH",
    },
}

# Per-unit ACTIVE branding/settings profile (UNIT-001 settings schema only;
# financial-identity fields are NOT settable — R-020).
_SETTINGS_MATRIX: dict[str, dict[str, Any]] = {
    "BANYUMEDIA": {
        "default_currency": "IDR",
        "invoice_template_ref": "tpl_banyu_v1",
        "logo_asset_ref": "logo_banyu_v1",
        "payment_terms_days": 14,
        "enabled_modules": ("invoicing", "crm"),
    },
    "PR1ME": {
        "default_currency": "IDR",
        "invoice_template_ref": "tpl_pr1me_v1",
        "logo_asset_ref": "logo_pr1me_v1",
        "payment_terms_days": 7,
        "enabled_modules": ("invoicing", "crm"),
    },
    "CONTRACTOR": {
        "default_currency": "IDR",
        "invoice_template_ref": "tpl_contractor_v1",
        "logo_asset_ref": "logo_contractor_v1",
        "payment_terms_days": 30,
        "enabled_modules": ("invoicing", "crm"),
    },
    "HEAVY_EQUIPMENT": {
        "default_currency": "IDR",
        "invoice_template_ref": "tpl_heavyeq_v1",
        "logo_asset_ref": "logo_heavyeq_v1",
        "payment_terms_days": 30,
        "enabled_modules": ("invoicing", "crm"),
    },
    "PT_TKH_OPS": {
        "default_currency": "IDR",
        "invoice_template_ref": "tpl_pttkh_v1",
        "logo_asset_ref": "logo_pttkh_v1",
        "payment_terms_days": 30,
        "enabled_modules": ("invoicing", "crm"),
    },
}


@dataclass(frozen=True, slots=True)
class ActorFixture:
    """One synthetic actor: identity binding + unit assignments."""

    actor_ref: str
    channel_ref: str
    assignments: tuple[ActorUnitAssignment, ...]

    @property
    def binding(self) -> IdentityBinding:
        return IdentityBinding(
            actor_ref=self.actor_ref, channel_ref=self.channel_ref, active=True
        )

    def for_unit(self, unit_ref: str) -> ActorUnitAssignment:
        for assignment in self.assignments:
            if assignment.unit_ref == unit_ref:
                return assignment
        raise KeyError(f"{self.actor_ref} has no assignment for {unit_ref}")

    def all_assignments(self) -> tuple[ActorUnitAssignment, ...]:
        return self.assignments

    def assignment_for(self, unit_ref: str) -> tuple[ActorUnitAssignment, ...]:
        return (self.for_unit(unit_ref),)


def _actor(
    actor_ref: str,
    channel_ref: str,
    *unit_roles: tuple[str, tuple[str, ...]],
) -> ActorFixture:
    assignments = tuple(
        ActorUnitAssignment(
            actor_ref=actor_ref,
            unit_ref=unit_ref,
            roles=roles,
            active=True,
            assignment_ref=f"ASSIGNMENT-{actor_ref.removeprefix('ACTOR-')}-{index + 1}",
            revision=1,
        )
        for index, (unit_ref, roles) in enumerate(unit_roles)
    )
    return ActorFixture(actor_ref=actor_ref, channel_ref=channel_ref,
                        assignments=assignments)


class PilotHarness:
    """Facade over the wired production components with synthetic fixtures."""

    def __init__(self) -> None:
        self.registry = UnitRegistry.default()
        self.settings = UnitSettingsStore(self.registry)
        self._seed_settings()

        self.erp_adapter = FixtureErpAdapter()
        # CRM roster: actor_ref -> set of unit refs (read live by the
        # adapter, so revocation/expiry is immediately visible).
        self.crm_roster: dict[str, frozenset[str]] = {}
        self.crm = FixtureCrmAdapter(self.crm_roster)

        self._trusted_issuer = TrustedIssuer(
            "ISSUER-AUTH-ROOT", b"pilot-synthetic-key-v1"
        )
        self.resolver = self._build_resolver()

        self.draft_workflow = _PilotDraftWorkflow(
            registry=self.registry,
            settings=self.settings,
            resolver=self.resolver,
            adapter=self.erp_adapter,
        )
        self.post_workflow = _PilotPostWorkflow(
            registry=self.registry,
            settings=self.settings,
            resolver=self.resolver,
            adapter=self.erp_adapter,
            draft_workflow=self.draft_workflow,
        )
        self._seed_actors()

    # -- construction --------------------------------------------------------

    @classmethod
    def build(cls) -> "PilotHarness":
        """Idempotent seed: every call returns a fresh equivalent harness."""
        return cls()

    def _seed_settings(self) -> None:
        for unit_code, settings_payload in _SETTINGS_MATRIX.items():
            drafted = self.settings.draft(
                unit_code, dict(settings_payload),
                author="pilot-seeder", at=at(0),
            )
            self.settings.activate(
                unit_code, drafted.configuration_version,
                expected_version=0, at=at(0), actor="pilot-seeder",
                effective_from=at(1),
            )

    def _build_resolver(self) -> FinancialPolicyResolver:
        identities = tuple(
            FinancialIdentity(unit_ref, **fields)  # type: ignore[arg-type]
            for unit_ref, fields in _IDENTITY_MATRIX.items()
        )
        catalog = self._trusted_issuer.issue_catalog(
            "CATALOG-PILOT-1", 1, "EVIDENCE-PILOT-CATALOG", identities
        )
        policies = tuple(
            FinancialIdentityPolicy(
                policy_ref=(
                    "POLICY-"
                    + unit_ref.removeprefix("UNIT-").replace("_", "")
                    + "-1"
                ),
                policy_version=1,
                operating_unit_ref=unit_ref,
                currency="IDR",
                effective_from=at(0),
                effective_until=None,
                active=True,
                **fields,  # type: ignore[arg-type]
            )
            for unit_ref, fields in _IDENTITY_MATRIX.items()
        )
        return FinancialPolicyResolver(
            policies,
            compatibility_catalog=catalog,
            trusted_issuers=TrustedIssuerRegistry((self._trusted_issuer,)),
        )

    def _seed_actors(self) -> None:
        # Sales actors (unit-scoped; UNIT-SALES role).
        self.banyumedia_sales = _actor(
            "ACTOR-SALES-BYM", "CHANNEL-WA-SALES-BYM",
            (UNIT_BANYUMEDIA, ("UNIT-SALES",)),
        )
        self.contractor_sales = _actor(
            "ACTOR-SALES-CTR", "CHANNEL-WA-SALES-CTR",
            (UNIT_CONTRACTOR, ("UNIT-SALES",)),
        )
        self.heavy_equipment_sales = _actor(
            "ACTOR-SALES-HEQ", "CHANNEL-WA-SALES-HEQ",
            (UNIT_HEAVY_EQUIPMENT, ("UNIT-SALES",)),
        )
        # Finance requesters (open drafts/previews, record payments).
        self.banyumedia_requester = _actor(
            "ACTOR-REQ-BYM", "CHANNEL-WA-REQ-BYM",
            (UNIT_BANYUMEDIA, ("FINANCE-REQUESTER",)),
        )
        self.contractor_requester = _actor(
            "ACTOR-REQ-CTR", "CHANNEL-WA-REQ-CTR",
            (UNIT_CONTRACTOR, ("FINANCE-REQUESTER",)),
        )
        self.heavy_equipment_requester = _actor(
            "ACTOR-REQ-HEQ", "CHANNEL-WA-REQ-HEQ",
            (UNIT_HEAVY_EQUIPMENT, ("FINANCE-REQUESTER",)),
        )
        self.pt_tkh_requester = _actor(
            "ACTOR-REQ-TKH", "CHANNEL-WA-REQ-TKH",
            (UNIT_PT_TKH, ("FINANCE-REQUESTER",)),
        )
        # Finance posters (review/post; distinct actors from requesters so
        # review separation F-02 is satisfiable).
        self.banyumedia_poster = _actor(
            "ACTOR-POST-BYM", "CHANNEL-WA-POST-BYM",
            (UNIT_BANYUMEDIA, ("FINANCE-POSTER",)),
        )
        self.contractor_poster = _actor(
            "ACTOR-POST-CTR", "CHANNEL-WA-POST-CTR",
            (UNIT_CONTRACTOR, ("FINANCE-POSTER",)),
        )
        self.heavy_equipment_poster = _actor(
            "ACTOR-POST-HEQ", "CHANNEL-WA-POST-HEQ",
            (UNIT_HEAVY_EQUIPMENT, ("FINANCE-POSTER",)),
        )
        self.pt_tkh_poster = _actor(
            "ACTOR-POST-TKH", "CHANNEL-WA-POST-TKH",
            (UNIT_PT_TKH, ("FINANCE-POSTER",)),
        )
        # Multi-unit finance reviewer (positive cross-unit control; still
        # exactly one active unit context per request).
        self.multi_unit_reviewer = _actor(
            "ACTOR-REVIEWER-MULTI", "CHANNEL-WA-REVIEWER-MULTI",
            (UNIT_BANYUMEDIA, ("FINANCE-REVIEWER",)),
            (UNIT_CONTRACTOR, ("FINANCE-REVIEWER",)),
        )

        # CRM roster mirrors the sales assignments (sales actors own leads).
        for actor in (
            self.banyumedia_sales,
            self.contractor_sales,
            self.heavy_equipment_sales,
        ):
            self.crm_roster[actor.actor_ref] = frozenset(
                a.unit_ref for a in actor.assignments
            )

    # -- CRM gateway surface -------------------------------------------------

    def create_lead(
        self,
        actor: ActorFixture,
        unit_ref: str,
        *,
        display_name: str,
        contact_handle: str,
        contact_channel: str = "WHATSAPP",
    ) -> str:
        identity = CrmIdentity(actor_ref=actor.actor_ref, operating_unit_ref=unit_ref)
        return self.crm.create_lead(LeadCommand(
            identity=identity,
            display_name=display_name,
            contact_channel=contact_channel,
            contact_handle=contact_handle,
            source="ORGANIC",
        ))

    def read_lead(
        self, actor: ActorFixture, unit_ref: str, lead_ref: str
    ) -> LeadRecord:
        identity = CrmIdentity(actor_ref=actor.actor_ref, operating_unit_ref=unit_ref)
        return self.crm.read_lead(identity, lead_ref)

    def search_leads(
        self,
        actor: ActorFixture,
        unit_ref: str,
        *,
        text: str | None = None,
    ) -> CrmQueryPage:
        identity = CrmIdentity(actor_ref=actor.actor_ref, operating_unit_ref=unit_ref)
        return self.crm.search_leads(CrmQuery(identity=identity, text=text))

    # -- isolation policy (final gateway-only architecture) ------------------

    @staticmethod
    def native_surfaces() -> tuple[str, ...]:
        return ("NATIVE_DESK", "NATIVE_API", "NATIVE_FILES", "NATIVE_REPORTS")

    @staticmethod
    def native_admission_allows(role: str, surface: str) -> bool:
        decision = isolation_policy.admit(
            role, isolation_policy.Surface(surface)
        )
        return decision is isolation_policy.Decision.ALLOW

    @staticmethod
    def native_credential_issuance_allowed(role: str, username: str) -> bool:
        try:
            isolation_policy.issue_native_credential(role, username)
        except isolation_policy.IsolationDenied:
            return False
        return True

    # -- invoice draft/post flows ---------------------------------------------

    def open_draft(
        self,
        requester: ActorFixture,
        unit_ref: str,
        *,
        customer_ref: str,
        at_minutes: int = 10,
        idempotency_key: str | None = None,
    ):
        return self.draft_workflow.open_draft(
            actor_ref=requester.actor_ref,
            channel_ref=requester.channel_ref,
            binding=requester.binding,
            assignments=requester.all_assignments(),
            customer_ref=customer_ref,
            at=at(at_minutes),
            selected_unit_ref=unit_ref,
            idempotency_key=idempotency_key,
        )

    def set_lines(
        self,
        requester: ActorFixture,
        draft_id: str,
        lines: Iterable[dict[str, str]],
        *,
        at_minutes: int = 11,
    ) -> None:
        self.draft_workflow.set_lines(
            draft_id, tuple(lines),
            actor_ref=requester.actor_ref,
            at=at(at_minutes),
            binding=requester.binding,
            assignments=requester.all_assignments(),
        )

    def preview(
        self,
        requester: ActorFixture,
        draft_id: str,
        *,
        at_minutes: int = 12,
    ) -> Preview:
        return self.draft_workflow.preview(
            draft_id,
            actor_ref=requester.actor_ref,
            binding=requester.binding,
            assignments=requester.all_assignments(),
            at=at(at_minutes),
        )

    def post(
        self,
        poster: ActorFixture,
        preview: Preview,
        *,
        at_minutes: int = 13,
    ) -> PostResult:
        return self.post_workflow.post(
            preview,
            actor_ref=poster.actor_ref,
            at=at(at_minutes),
            binding=poster.binding,
            assignments=poster.all_assignments(),
            channel_ref=poster.channel_ref,
        )

    def get_posted_invoice(self, official_ref: str) -> PostedInvoiceRecord:
        return self.post_workflow.get_posted_invoice(official_ref)

    def change_branding(
        self,
        unit_code: str,
        *,
        invoice_template_ref: str,
        logo_asset_ref: str,
        at_minutes: int,
    ) -> int:
        """Activate a new settings version with different branding.

        Returns the new configuration_version. Used to prove posted branding
        snapshots are immutable (MVP-AC-13).
        """
        active = self.settings.get_active(unit_code, at=at(at_minutes))
        payload = dict(active.settings)
        payload["invoice_template_ref"] = invoice_template_ref
        payload["logo_asset_ref"] = logo_asset_ref
        drafted = self.settings.draft(
            unit_code, payload, author="pilot-seeder", at=at(at_minutes),
        )
        self.settings.activate(
            unit_code, drafted.configuration_version,
            expected_version=active.configuration_version,
            at=at(at_minutes), actor="pilot-seeder",
            effective_from=at(at_minutes + 1),
        )
        return drafted.configuration_version

    # -- canned line fixtures ---------------------------------------------------

    @staticmethod
    def standard_lines(currency: str = "IDR") -> tuple[dict[str, str], ...]:
        return ({
            "service_ref": "SVC-SYN-01",
            "description": "Synthetic service line",
            "quantity": "1",
            "unit_price_amount": "1500000",
            "currency": currency,
        },)

    def post_invoice_for_unit(
        self,
        requester: ActorFixture,
        poster: ActorFixture,
        unit_ref: str,
        *,
        customer_ref: str,
        at_minutes: int = 10,
    ) -> tuple[Preview, PostResult]:
        """Happy-path helper: open → lines → preview → post."""
        handle = self.open_draft(
            requester, unit_ref, customer_ref=customer_ref,
            at_minutes=at_minutes,
        )
        self.set_lines(requester, handle.draft_id, self.standard_lines(),
                       at_minutes=at_minutes + 1)
        preview = self.preview(requester, handle.draft_id,
                               at_minutes=at_minutes + 2)
        result = self.post(poster, preview, at_minutes=at_minutes + 3)
        return preview, result
