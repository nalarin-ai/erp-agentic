"""Unit registry: typed, immutable catalog of operating units (R-001/R-002).

UNIT-001 slice 1. The default catalog is loaded from
`config/fixtures/units/catalog.yaml`; onboarding a new unit is a fixture
change, never a source branch. All identifiers are opaque synthetic aliases.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from src.domain.errors import InvalidDomainValue

_CATALOG = (
    Path(__file__).resolve().parent.parent.parent
    / "config" / "fixtures" / "units" / "catalog.yaml"
)
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
_ALIAS = re.compile(r"^acct_[a-z0-9_]{2,40}$")


@dataclass(frozen=True, slots=True)
class UnitSpec:
    """One operating unit. Immutable; identity derived from code."""

    code: str
    display_name: str
    account_alias: str
    issues_ppn: bool
    service_categories: tuple[str, ...]
    shared_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _CODE.fullmatch(self.code):
            raise InvalidDomainValue(f"invalid unit code: {self.code!r}")
        if not self.display_name or not self.display_name.strip():
            raise InvalidDomainValue("display_name required")
        if not _ALIAS.fullmatch(self.account_alias):
            raise InvalidDomainValue(f"invalid account alias: {self.account_alias!r}")
        if not isinstance(self.issues_ppn, bool):
            raise InvalidDomainValue("issues_ppn must be bool")
        if not self.service_categories:
            raise InvalidDomainValue("service_categories must be non-empty")
        object.__setattr__(self, "service_categories", tuple(self.service_categories))
        object.__setattr__(self, "shared_with", tuple(self.shared_with))

    @property
    def unit_id(self) -> str:
        """Opaque stable ID derived from the immutable code."""
        digest = hashlib.sha256(f"unit:{self.code}".encode("utf-8")).hexdigest()[:16]
        return f"unit_{digest}"


class UnitRegistry:
    """Immutable registry of unit specs keyed by code."""

    def __init__(self, specs: tuple[UnitSpec, ...]) -> None:
        codes = [s.code for s in specs]
        if len(codes) != len(set(codes)):
            raise InvalidDomainValue("duplicate unit code")
        # R-013: at most one PPN-issuing entity.
        ppn_issuers = [s.code for s in specs if s.issues_ppn]
        if len(ppn_issuers) > 1:
            raise InvalidDomainValue(f"multiple PPN issuers: {ppn_issuers}")
        # R-015: alias sharing must be explicitly declared via shared_with.
        alias_to_codes: dict[str, list[str]] = {}
        for s in specs:
            alias_to_codes.setdefault(s.account_alias, []).append(s.code)
        for alias, owners in alias_to_codes.items():
            if len(owners) > 1:
                for code in owners:
                    spec = next(s for s in specs if s.code == code)
                    if not set(owners) - {code} <= set(spec.shared_with):
                        raise InvalidDomainValue(
                            f"shared alias {alias!r} not declared by {code!r}"
                        )
        self._by_code = {s.code: s for s in specs}

    @classmethod
    def default(cls) -> "UnitRegistry":
        return cls(_load_catalog(_CATALOG))

    def all(self) -> tuple[UnitSpec, ...]:
        return tuple(self._by_code.values())

    def get(self, code: str) -> UnitSpec:
        try:
            return self._by_code[code]
        except KeyError:
            raise InvalidDomainValue(f"unknown unit: {code!r}") from None

    def with_unit(self, spec: UnitSpec) -> "UnitRegistry":
        """Return a new registry with the additional unit (immutability)."""
        if spec.code in self._by_code:
            raise InvalidDomainValue(f"duplicate unit code: {spec.code}")
        return UnitRegistry(tuple(self._by_code.values()) + (spec,))


def _load_catalog(path: Path) -> tuple[UnitSpec, ...]:
    return _load_catalog_from_text(path.read_text(encoding="utf-8"))


_KNOWN_KEYS = {"code", "display_name", "account_alias", "issues_ppn", "service_categories", "shared_with"}


def _load_catalog_from_text(text: str) -> tuple[UnitSpec, ...]:
    """Parse the fixture catalog with a strict minimal YAML subset parser.

    The fixture is data, not code: only the documented list-of-maps shape is
    accepted; anything else fails closed. (No external YAML dependency.)
    Unknown keys, non-bool issues_ppn scalars, and scalar service_categories
    are rejected (QA H2/H3/H4).
    """
    specs: list[UnitSpec] = []
    current: dict[str, object] | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or line.strip() == "units:":
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if current is not None:
                specs.append(_to_spec(current))
            current = {}
            stripped = stripped[2:].strip()
            if stripped:
                key, _, value = stripped.partition(":")
                current[key.strip()] = _parse_value(key.strip(), value.strip())
        elif current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            current[key.strip()] = _parse_value(key.strip(), value.strip())
        else:
            raise InvalidDomainValue(f"malformed catalog line: {raw!r}")
    if current is not None:
        specs.append(_to_spec(current))
    return tuple(specs)


def _parse_value(key: str, raw: str) -> object:
    if key not in _KNOWN_KEYS:
        raise InvalidDomainValue(f"unknown catalog key: {key!r}")
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return tuple(part.strip() for part in inner.split(",") if part.strip())
    if key == "issues_ppn":
        # Fail closed: only exact lowercase true/false are valid booleans.
        if raw == "true":
            return True
        if raw == "false":
            return False
        raise InvalidDomainValue(f"issues_ppn must be true/false, got {raw!r}")
    if raw in ("true", "false"):
        return raw == "true"
    return raw


def _to_spec(data: dict[str, object]) -> UnitSpec:
    try:
        categories = data["service_categories"]
        if not isinstance(categories, tuple):
            raise InvalidDomainValue("service_categories must be a list")
        shared_raw = data.get("shared_with") or ()
        if not isinstance(shared_raw, tuple):
            raise InvalidDomainValue("shared_with must be a list")
        return UnitSpec(
            code=str(data["code"]),
            display_name=str(data["display_name"]),
            account_alias=str(data["account_alias"]),
            issues_ppn=data["issues_ppn"],  # type: ignore[arg-type]
            service_categories=categories,
            shared_with=shared_raw,
        )
    except KeyError as exc:
        raise InvalidDomainValue(f"catalog row missing key: {exc}") from None
