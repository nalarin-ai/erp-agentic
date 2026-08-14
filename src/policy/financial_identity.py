from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import re
from typing import Iterable

from src.contracts.financial_identity import FinancialIdentity


_REF = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_ISSUER_REF = re.compile(r"^ISSUER-AUTH-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
_SIG = re.compile(r"^[0-9a-f]{64}$")


class PolicyResolutionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("Financial identity cannot be resolved.")


def _blocked(condition: bool) -> None:
    if condition:
        raise PolicyResolutionError("BLOCKED_CONFIGURATION")


def _aware(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _canonical_identity(identity: FinancialIdentity) -> tuple[object, ...]:
    payload = identity.to_canonical_payload()
    return tuple(payload[key] for key in sorted(payload))


def _catalog_signing_payload(
    catalog_ref: str,
    catalog_version: int,
    approval_evidence_ref: str,
    identities: tuple[FinancialIdentity, ...],
) -> bytes:
    parts: list[str] = [catalog_ref, str(catalog_version), approval_evidence_ref]
    for identity in identities:
        parts.append(repr(_canonical_identity(identity)))
    return "|".join(parts).encode("utf-8")


def _override_signing_payload(reason_ref: str, evidence_ref: str, expected_policy_version: int) -> bytes:
    return f"{reason_ref}|{evidence_ref}|{expected_policy_version}".encode("utf-8")


@dataclass(frozen=True, slots=True)
class TrustedIssuer:
    """Synthetic trusted issuer: signs catalogs and overrides with an HMAC key.

    Keys are opaque synthetic bytes for test fixtures only; never real credentials.
    """

    issuer_ref: str
    signing_key: bytes

    def __post_init__(self) -> None:
        _blocked(type(self.issuer_ref) is not str or _ISSUER_REF.fullmatch(self.issuer_ref) is None)
        _blocked(type(self.signing_key) is not bytes or len(self.signing_key) < 16)

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self.signing_key, payload, hashlib.sha256).hexdigest()

    def issue_catalog(
        self,
        catalog_ref: str,
        catalog_version: int,
        approval_evidence_ref: str,
        identities: tuple[FinancialIdentity, ...],
    ) -> CompatibilityCatalog:
        identities_tuple = tuple(identities)
        signature = self._sign(
            _catalog_signing_payload(catalog_ref, catalog_version, approval_evidence_ref, identities_tuple)
        )
        return CompatibilityCatalog(
            catalog_ref,
            catalog_version,
            approval_evidence_ref,
            identities_tuple,
            issuer_ref=self.issuer_ref,
            signature=signature,
        )

    def issue_override(
        self, reason_ref: str, evidence_ref: str, expected_policy_version: int
    ) -> OverrideAuthorization:
        signature = self._sign(_override_signing_payload(reason_ref, evidence_ref, expected_policy_version))
        return OverrideAuthorization(
            True,
            reason_ref,
            evidence_ref,
            expected_policy_version,
            issuer_ref=self.issuer_ref,
            signature=signature,
        )


class TrustedIssuerRegistry:
    def __init__(self, issuers: Iterable[TrustedIssuer]) -> None:
        try:
            issuer_tuple = tuple(issuers)
        except Exception as exc:
            raise PolicyResolutionError("BLOCKED_CONFIGURATION") from exc
        _blocked(not issuer_tuple)
        _blocked(any(type(issuer) is not TrustedIssuer for issuer in issuer_tuple))
        refs = [issuer.issuer_ref for issuer in issuer_tuple]
        _blocked(len(set(refs)) != len(refs))
        self._by_ref = {issuer.issuer_ref: issuer for issuer in issuer_tuple}

    def verify_catalog(self, catalog: CompatibilityCatalog) -> bool:
        issuer = self._by_ref.get(catalog.issuer_ref)
        if issuer is None:
            return False
        expected = issuer._sign(
            _catalog_signing_payload(
                catalog.catalog_ref,
                catalog.catalog_version,
                catalog.approval_evidence_ref,
                catalog.identities,
            )
        )
        return hmac.compare_digest(expected, catalog.signature)

    def verify_override(self, override: OverrideAuthorization) -> bool:
        issuer = self._by_ref.get(override.issuer_ref)
        if issuer is None:
            return False
        expected = issuer._sign(
            _override_signing_payload(
                override.reason_ref, override.evidence_ref, override.expected_policy_version
            )
        )
        return hmac.compare_digest(expected, override.signature)



@dataclass(frozen=True, slots=True)
class RequestedFinancialIdentity:
    legal_issuer_ref: str
    tax_profile_ref: str
    invoice_series_ref: str
    receivable_ledger_ref: str
    destination_account_alias: str

    def for_unit(self, operating_unit_ref: str) -> FinancialIdentity:
        try:
            return FinancialIdentity(operating_unit_ref, self.legal_issuer_ref, self.tax_profile_ref,
                                     self.invoice_series_ref, self.receivable_ledger_ref,
                                     self.destination_account_alias)
        except (TypeError, ValueError) as exc:
            raise PolicyResolutionError("BLOCKED_CONFIGURATION") from exc


@dataclass(frozen=True, slots=True)
class OverrideAuthorization:
    authorized: bool
    reason_ref: str
    evidence_ref: str
    expected_policy_version: int
    issuer_ref: str = ""
    signature: str = ""

    def __post_init__(self) -> None:
        _blocked(type(self.authorized) is not bool or not self.authorized)
        _blocked(type(self.expected_policy_version) is not int or self.expected_policy_version < 1)
        _blocked(type(self.reason_ref) is not str or not self.reason_ref.startswith("REASON-") or _REF.fullmatch(self.reason_ref) is None)
        _blocked(type(self.evidence_ref) is not str or not self.evidence_ref.startswith("EVIDENCE-") or _REF.fullmatch(self.evidence_ref) is None)
        _blocked(type(self.issuer_ref) is not str)
        _blocked(type(self.signature) is not str)
        _blocked(bool(self.issuer_ref) != bool(self.signature))
        _blocked(bool(self.signature) and _SIG.fullmatch(self.signature) is None)


@dataclass(frozen=True, slots=True)
class PolicyResolutionRequest:
    operating_unit_ref: str
    currency: str
    effective_at: datetime
    requested_identity: RequestedFinancialIdentity | None = None
    override_authorization: OverrideAuthorization | None = None

    def __post_init__(self) -> None:
        _blocked(type(self.operating_unit_ref) is not str or not self.operating_unit_ref.startswith("UNIT-") or _REF.fullmatch(self.operating_unit_ref) is None)
        _blocked(type(self.currency) is not str or _CURRENCY.fullmatch(self.currency) is None)
        _blocked(not _aware(self.effective_at))
        _blocked(self.requested_identity is not None and type(self.requested_identity) is not RequestedFinancialIdentity)
        _blocked(self.override_authorization is not None and type(self.override_authorization) is not OverrideAuthorization)
        _blocked(self.requested_identity is None and self.override_authorization is not None)


@dataclass(frozen=True, slots=True)
class FinancialIdentityPolicy:
    policy_ref: str
    policy_version: int
    operating_unit_ref: str
    legal_issuer_ref: str
    tax_profile_ref: str
    invoice_series_ref: str
    receivable_ledger_ref: str
    destination_account_alias: str
    currency: str
    effective_from: datetime
    effective_until: datetime | None
    active: bool

    def __post_init__(self) -> None:
        _blocked(type(self.policy_ref) is not str or not self.policy_ref.startswith("POLICY-") or _REF.fullmatch(self.policy_ref) is None)
        _blocked(type(self.policy_version) is not int or self.policy_version < 1)
        _blocked(type(self.active) is not bool)
        _blocked(type(self.currency) is not str or _CURRENCY.fullmatch(self.currency) is None)
        _blocked(not _aware(self.effective_from))
        _blocked(self.effective_until is not None and not _aware(self.effective_until))
        _blocked(self.effective_until is not None and self.effective_from >= self.effective_until)
        self.identity

    @property
    def identity(self) -> FinancialIdentity:
        try:
            return FinancialIdentity(self.operating_unit_ref, self.legal_issuer_ref, self.tax_profile_ref,
                                     self.invoice_series_ref, self.receivable_ledger_ref,
                                     self.destination_account_alias)
        except (TypeError, ValueError) as exc:
            raise PolicyResolutionError("BLOCKED_CONFIGURATION") from exc


@dataclass(frozen=True, slots=True)
class PostedFinancialSnapshot:
    policy_ref: str
    policy_version: int
    identity: FinancialIdentity
    currency: str
    catalog_ref: str = ""
    catalog_version: int = 0
    catalog_evidence_ref: str = ""

    def __post_init__(self) -> None:
        _blocked(type(self.policy_ref) is not str or not self.policy_ref.startswith("POLICY-") or _REF.fullmatch(self.policy_ref) is None)
        _blocked(type(self.policy_version) is not int or self.policy_version < 1)
        _blocked(type(self.identity) is not FinancialIdentity)
        _blocked(type(self.currency) is not str or _CURRENCY.fullmatch(self.currency) is None)
        _blocked(type(self.catalog_ref) is not str)
        _blocked(type(self.catalog_version) is not int or self.catalog_version < 0)
        _blocked(type(self.catalog_evidence_ref) is not str)
        has_catalog = bool(self.catalog_ref)
        _blocked(has_catalog != bool(self.catalog_version))
        _blocked(has_catalog != bool(self.catalog_evidence_ref))
        _blocked(has_catalog and _REF.fullmatch(self.catalog_ref) is None)

    def to_canonical_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"currency": self.currency, "identity": self.identity.to_canonical_payload(),
                "policy_ref": self.policy_ref, "policy_version": self.policy_version}
        if self.catalog_ref:
            payload["catalog_ref"] = self.catalog_ref
            payload["catalog_version"] = self.catalog_version
            payload["catalog_evidence_ref"] = self.catalog_evidence_ref
        return payload


@dataclass(frozen=True, slots=True)
class ResolvedFinancialPolicy:
    policy_ref: str
    policy_version: int
    identity: FinancialIdentity
    currency: str
    override_authorization: OverrideAuthorization | None = None
    catalog: CompatibilityCatalog | None = None

    def to_redacted_descriptor(self) -> dict[str, object]:
        descriptor: dict[str, object] = {"currency": self.currency, "identity": self.identity.to_redacted_descriptor(),
                "policy_ref": self.policy_ref, "policy_version": self.policy_version}
        if self.catalog is not None:
            descriptor["catalog_ref"] = self.catalog.catalog_ref
            descriptor["catalog_version"] = self.catalog.catalog_version
            descriptor["catalog_evidence_ref"] = self.catalog.approval_evidence_ref
        if self.override_authorization is not None:
            descriptor["override"] = {
                "evidence_ref": self.override_authorization.evidence_ref,
                "reason_ref": self.override_authorization.reason_ref,
            }
        return descriptor

    def to_posted_snapshot(self) -> PostedFinancialSnapshot:
        if self.catalog is None:
            return PostedFinancialSnapshot(self.policy_ref, self.policy_version, self.identity, self.currency)
        return PostedFinancialSnapshot(
            self.policy_ref,
            self.policy_version,
            self.identity,
            self.currency,
            catalog_ref=self.catalog.catalog_ref,
            catalog_version=self.catalog.catalog_version,
            catalog_evidence_ref=self.catalog.approval_evidence_ref,
        )


@dataclass(frozen=True, slots=True)
class CompatibilityCatalog:
    catalog_ref: str
    catalog_version: int
    approval_evidence_ref: str
    identities: tuple[FinancialIdentity, ...]
    issuer_ref: str = ""
    signature: str = ""

    def __post_init__(self) -> None:
        _blocked(type(self.catalog_ref) is not str or not self.catalog_ref.startswith("CATALOG-") or _REF.fullmatch(self.catalog_ref) is None)
        _blocked(type(self.catalog_version) is not int or self.catalog_version < 1)
        _blocked(type(self.approval_evidence_ref) is not str or not self.approval_evidence_ref.startswith("EVIDENCE-") or _REF.fullmatch(self.approval_evidence_ref) is None)
        _blocked(type(self.identities) is not tuple or not self.identities)
        _blocked(any(type(identity) is not FinancialIdentity for identity in self.identities))
        _blocked(len(set(self.identities)) != len(self.identities))
        _blocked(type(self.issuer_ref) is not str)
        _blocked(type(self.signature) is not str)
        _blocked(bool(self.issuer_ref) != bool(self.signature))
        _blocked(bool(self.signature) and _SIG.fullmatch(self.signature) is None)


class FinancialPolicyResolver:
    def __init__(
        self,
        policies: Iterable[FinancialIdentityPolicy],
        *,
        compatibility_catalog: CompatibilityCatalog,
        trusted_issuers: TrustedIssuerRegistry | None = None,
    ) -> None:
        try:
            policy_tuple = tuple(policies)
        except Exception as exc:
            raise PolicyResolutionError("BLOCKED_CONFIGURATION") from exc
        _blocked(any(type(policy) is not FinancialIdentityPolicy for policy in policy_tuple))
        self._policies = policy_tuple
        _blocked(type(compatibility_catalog) is not CompatibilityCatalog)
        if trusted_issuers is not None:
            _blocked(type(trusted_issuers) is not TrustedIssuerRegistry)
            if not trusted_issuers.verify_catalog(compatibility_catalog):
                raise PolicyResolutionError("UNTRUSTED_CATALOG")
        self._trusted_issuers = trusted_issuers
        self._catalog = compatibility_catalog
        self._compatible = frozenset(compatibility_catalog.identities)

    def resolve(self, request: PolicyResolutionRequest) -> ResolvedFinancialPolicy:
        if type(request) is not PolicyResolutionRequest:
            raise PolicyResolutionError("BLOCKED_CONFIGURATION")
        requested = request.requested_identity
        requested_value = requested.for_unit(request.operating_unit_ref) if requested is not None else None
        if requested is not None and request.override_authorization is None:
            raise PolicyResolutionError("OVERRIDE_AUTHORIZATION_REQUIRED")
        if (
            request.override_authorization is not None
            and self._trusted_issuers is not None
            and not self._trusted_issuers.verify_override(request.override_authorization)
        ):
            raise PolicyResolutionError("UNTRUSTED_OVERRIDE")
        matches = tuple(policy for policy in self._policies if policy.active
                        and policy.operating_unit_ref == request.operating_unit_ref
                        and policy.currency == request.currency
                        and policy.effective_from <= request.effective_at
                        and (policy.effective_until is None or request.effective_at < policy.effective_until)
                        and (requested_value is None or policy.identity == requested_value))
        if len(matches) == 0:
            raise PolicyResolutionError("POLICY_NOT_FOUND")
        if len(matches) != 1:
            raise PolicyResolutionError("POLICY_AMBIGUOUS")
        policy = matches[0]
        if policy.identity not in self._compatible:
            raise PolicyResolutionError("BLOCKED_CONFIGURATION")
        if request.override_authorization is not None and request.override_authorization.expected_policy_version != policy.policy_version:
            raise PolicyResolutionError("OVERRIDE_POLICY_VERSION_MISMATCH")
        return ResolvedFinancialPolicy(policy.policy_ref, policy.policy_version, policy.identity, policy.currency,
                                       request.override_authorization, self._catalog)
