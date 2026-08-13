from __future__ import annotations

from dataclasses import asdict, dataclass
import re


_OPAQUE_REF = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
_FIELD_PREFIXES = {
    "operating_unit_ref": "UNIT-",
    "legal_issuer_ref": "ISSUER-",
    "tax_profile_ref": "TAX-",
    "invoice_series_ref": "SERIES-",
    "receivable_ledger_ref": "LEDGER-",
    "destination_account_alias": "ACC-",
}


@dataclass(frozen=True, slots=True)
class FinancialIdentity:
    operating_unit_ref: str
    legal_issuer_ref: str
    tax_profile_ref: str
    invoice_series_ref: str
    receivable_ledger_ref: str
    destination_account_alias: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, str) or _OPAQUE_REF.fullmatch(value) is None:
                raise ValueError(f"{name} must be a canonical opaque reference")
            if not value.startswith(_FIELD_PREFIXES[name]):
                raise ValueError(f"{name} has the wrong reference namespace")
        account_suffix = self.destination_account_alias.removeprefix("ACC-")
        if not any(character.isalpha() for character in account_suffix):
            raise ValueError("destination_account_alias cannot be a raw numeric identifier")
        if sum(character.isdigit() for character in account_suffix) >= 10:
            raise ValueError("destination_account_alias resembles a raw account identifier")

    def to_canonical_payload(self) -> dict[str, str]:
        return dict(sorted(asdict(self).items()))

    def to_redacted_descriptor(self) -> dict[str, str]:
        descriptor = self.to_canonical_payload()
        descriptor["destination_account_alias"] = "ACC-[REDACTED]"
        return descriptor
