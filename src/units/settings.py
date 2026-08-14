"""Versioned unit settings with CAS lifecycle (R-022, R-020 hooks).

UNIT-001 slice 2. Typed allowlisted settings; draft -> activate (CAS
expected_version, atomic retire+activate) -> rollback (new version from a
verified prior snapshot). Unknown keys, wrong types, and script-like values
fail closed. Every transition is audited. This is the in-memory fixture;
durable persistence plugs into the same contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any

from src.domain.errors import InvalidDomainValue
from src.units.registry import UnitRegistry


class SettingsStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


# Allowlisted typed settings schema. Financial-identity fields (issuer, tax,
# series, ledger, account) are deliberately NOT here — R-020 forbids
# branding/settings from overriding them; they come from FND-003 policy.
_ALLOWED: dict[str, type | tuple[type, ...]] = {
    "default_currency": str,
    "invoice_template_ref": str,
    "quotation_template_ref": str,
    "logo_asset_ref": str,
    "numbering_series_ref": str,
    "branding_tagline": str,  # free text: only the forbidden-content scan protects it
    "payment_terms_days": int,
    "enabled_modules": tuple,
    "approval_threshold_amount": int,
}
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_REF = re.compile(r"^[a-z0-9_]{2,60}$")
_FORBIDDEN_TEXT = re.compile(r"(?i)<\s*script|javascript:|;|\x00")
_MAX_TEXT = 200


def _validate_setting(key: str, value: Any) -> None:
    if key not in _ALLOWED:
        raise InvalidDomainValue(f"unknown setting key: {key!r}")
    expected = _ALLOWED[key]
    if expected is int and isinstance(value, bool):
        raise InvalidDomainValue(f"setting {key} must be int")
    if not isinstance(value, expected):
        raise InvalidDomainValue(f"setting {key} has wrong type")
    if isinstance(value, str):
        if _FORBIDDEN_TEXT.search(value):
            raise InvalidDomainValue(f"setting {key} contains forbidden content")
        if len(value) > _MAX_TEXT:
            raise InvalidDomainValue(f"setting {key} exceeds max length")
        if key == "default_currency" and not _CURRENCY.fullmatch(value):
            raise InvalidDomainValue("default_currency must be ISO-4217 alpha-3")
        if key.endswith("_ref") and not _REF.fullmatch(value):
            raise InvalidDomainValue(f"setting {key} must be an opaque reference")
    if isinstance(value, tuple):
        for element in value:
            if not isinstance(element, str) or _FORBIDDEN_TEXT.search(element):
                raise InvalidDomainValue(f"setting {key} contains forbidden content")
    if key == "payment_terms_days":
        assert isinstance(value, int)
        if not (0 <= value <= 365):
            raise InvalidDomainValue("payment_terms_days out of range")
    if key == "approval_threshold_amount":
        assert isinstance(value, int)
        if value < 0:
            raise InvalidDomainValue("approval_threshold_amount must be non-negative")
        if value > 10**15:
            raise InvalidDomainValue("approval_threshold_amount exceeds ceiling")
    if key == "enabled_modules":
        if not isinstance(value, tuple):
            raise InvalidDomainValue("enabled_modules must be a tuple")
        allowed = {"invoicing", "crm", "payments", "reports", "reminders"}
        unknown = set(value) - allowed
        if unknown:
            raise InvalidDomainValue(f"unknown modules: {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class SettingsVersion:
    unit_code: str
    configuration_version: int
    status: SettingsStatus
    settings: dict[str, Any]
    author: str
    created_at: datetime
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    previous_version: int | None = None
    rollback_of: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        # L1: the settings mapping must be immutable post-creation even though
        # the field type is dict; MappingProxyType blocks item assignment.
        if not isinstance(self.settings, MappingProxyType):
            object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))


class UnitSettingsStore:
    """In-memory versioned settings store with CAS + audit."""

    def __init__(self, registry: UnitRegistry) -> None:
        self._registry = registry
        self._versions: dict[str, list[SettingsVersion]] = {}
        self._audit: dict[str, list[dict[str, Any]]] = {}

    # -- helpers -----------------------------------------------------------

    def _validate_unit(self, unit_code: str) -> None:
        self._registry.get(unit_code)  # fails closed on unknown unit

    def _log(self, unit_code: str, action: str, actor: str, at: datetime, detail: dict[str, Any]) -> None:
        self._audit.setdefault(unit_code, []).append(
            {"action": action, "actor": actor, "at": at.isoformat(), **detail}
        )

    def _next_version(self, unit_code: str) -> int:
        return len(self._versions.get(unit_code, [])) + 1

    # -- commands ----------------------------------------------------------

    def draft(self, unit_code: str, settings: dict[str, Any], *, author: str, at: datetime) -> SettingsVersion:
        self._validate_unit(unit_code)
        if not isinstance(settings, dict) or not settings:
            raise InvalidDomainValue("settings must be a non-empty mapping")
        for key, value in settings.items():
            _validate_setting(key, value)
        normalized = {
            k: (tuple(v) if isinstance(v, list) else v) for k, v in settings.items()
        }
        version = SettingsVersion(
            unit_code=unit_code,
            configuration_version=self._next_version(unit_code),
            status=SettingsStatus.DRAFT,
            settings=normalized,
            author=author,
            created_at=at,
        )
        self._versions.setdefault(unit_code, []).append(version)
        self._log(unit_code, "draft", author, at, {"version": version.configuration_version})
        return version

    def preview(self, unit_code: str, configuration_version: int) -> dict[str, Any]:
        """Read-only projection of a draft/active version. No side effects."""
        self._validate_unit(unit_code)
        version = self.get_version(unit_code, configuration_version)
        return dict(version.settings)

    def activate(
        self,
        unit_code: str,
        configuration_version: int,
        *,
        expected_version: int,
        at: datetime,
        actor: str,
        effective_from: datetime,
    ) -> SettingsVersion:
        """CAS activate: exactly one winner; atomically retires prior active."""
        self._validate_unit(unit_code)
        versions = self._versions.get(unit_code, [])
        current_active = self._current_active_version_number(unit_code)
        if expected_version != current_active:
            self._log(unit_code, "activate_denied", actor, at, {
                "version": configuration_version, "expected_version": expected_version,
                "actual_version": current_active,
            })
            raise InvalidDomainValue(
                f"version conflict: expected {expected_version}, active is {current_active}"
            )
        # H1: reject effective_from regression (new version starts before the
        # current active one), which would leave an unservable gap.
        if current_active:
            current_row = self.get_version(unit_code, current_active)
            if current_row.effective_from is not None and effective_from < current_row.effective_from:
                raise InvalidDomainValue(
                    "effective_from must not precede the current active version"
                )
        target = self.get_version(unit_code, configuration_version)
        if target.status is not SettingsStatus.DRAFT:
            raise InvalidDomainValue("only a DRAFT version can be activated")
        new_rows: list[SettingsVersion] = []
        for row in versions:
            if row.status is SettingsStatus.ACTIVE:
                # Atomic retire: the prior active version ends at effective_from
                row = replace(row, status=SettingsStatus.RETIRED, effective_to=effective_from)
            new_rows.append(row)
        activated = replace(
            target,
            status=SettingsStatus.ACTIVE,
            effective_from=effective_from,
            previous_version=current_active or None,
        )
        new_rows = [activated if r.configuration_version == configuration_version else r for r in new_rows]
        self._versions[unit_code] = new_rows
        self._log(unit_code, "activate", actor, at, {
            "version": configuration_version, "expected_version": expected_version,
        })
        return activated

    def rollback(
        self,
        unit_code: str,
        *,
        to_version: int,
        expected_version: int,
        at: datetime,
        actor: str,
        effective_from: datetime,
        reason: str,
    ) -> SettingsVersion:
        """Rollback creates a NEW version from a verified prior snapshot.

        C1 fix: the CAS gate is evaluated BEFORE any mutation; the new version
        is appended only after the CAS check passes, and activate() is called
        with the fresh expected_version so a racing loser leaves zero rows.
        """
        self._validate_unit(unit_code)
        target = self.get_version(unit_code, to_version)
        current_active = self._current_active_version_number(unit_code)
        if expected_version != current_active:
            self._log(unit_code, "activate_denied", actor, at, {
                "version": "rollback", "expected_version": expected_version,
                "actual_version": current_active,
            })
            raise InvalidDomainValue(
                f"version conflict: expected {expected_version}, active is {current_active}"
            )
        # Re-validate the snapshot against the current schema (never trust history)
        for key, value in target.settings.items():
            _validate_setting(key, value)
        new_version = SettingsVersion(
            unit_code=unit_code,
            configuration_version=self._next_version(unit_code),
            status=SettingsStatus.DRAFT,
            settings=dict(target.settings),
            author=actor,
            created_at=at,
            rollback_of=to_version,
            reason=reason,
        )
        self._versions[unit_code].append(new_version)
        self._log(unit_code, "rollback_draft", actor, at, {
            "version": new_version.configuration_version, "rollback_of": to_version, "reason": reason,
        })
        return self.activate(
            unit_code, new_version.configuration_version,
            expected_version=expected_version, at=at, actor=actor,
            effective_from=effective_from,
        )

    # -- queries -----------------------------------------------------------

    def get_version(self, unit_code: str, configuration_version: int) -> SettingsVersion:
        for row in self._versions.get(unit_code, []):
            if row.configuration_version == configuration_version:
                return row
        raise InvalidDomainValue(f"unknown version {configuration_version} for {unit_code}")

    def get_active(self, unit_code: str, *, at: datetime) -> SettingsVersion:
        self._validate_unit(unit_code)
        for row in self._versions.get(unit_code, []):
            if (
                row.status is SettingsStatus.ACTIVE
                and row.effective_from is not None
                and row.effective_from <= at
                and (row.effective_to is None or at < row.effective_to)
            ):
                return row
        raise InvalidDomainValue(f"no active settings for {unit_code}")

    def audit_events(self, unit_code: str) -> list[dict[str, Any]]:
        self._validate_unit(unit_code)
        return list(self._audit.get(unit_code, []))

    def _current_active_version_number(self, unit_code: str) -> int:
        for row in self._versions.get(unit_code, []):
            if row.status is SettingsStatus.ACTIVE:
                return row.configuration_version
        return 0
