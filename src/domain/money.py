from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from src.domain.errors import InvalidDomainValue


_DECIMAL_TEXT = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_MAX_DECIMAL_DIGITS = 64
_MAX_DECIMAL_EXPONENT = 64


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be Decimal")
        if not self.amount.is_finite():
            raise ValueError("amount must be finite")
        decimal_tuple = self.amount.as_tuple()
        exponent = decimal_tuple.exponent
        if not isinstance(exponent, int):
            raise InvalidDomainValue("amount exponent is invalid")
        if len(decimal_tuple.digits) > _MAX_DECIMAL_DIGITS or abs(exponent) > _MAX_DECIMAL_EXPONENT:
            raise InvalidDomainValue("amount exceeds canonical bounds")
        if len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isalpha() or not self.currency.isupper():
            raise ValueError("currency must be a three-letter uppercase ASCII code")

    @classmethod
    def from_decimal(cls, amount: str, currency: str) -> "Money":
        if not isinstance(amount, str):
            raise TypeError("amount must be a decimal string")
        if len(amount) > _MAX_DECIMAL_DIGITS + 2 or _DECIMAL_TEXT.fullmatch(amount) is None:
            raise InvalidDomainValue("amount is not a canonical decimal string")
        try:
            parsed = Decimal(amount)
        except InvalidOperation as exc:
            raise InvalidDomainValue("amount is not a valid decimal string") from exc
        return cls(amount=parsed, currency=currency)

    def to_canonical_payload(self) -> dict[str, str]:
        canonical_amount = self.amount.copy_abs() if self.amount.is_zero() else self.amount
        amount = format(canonical_amount, "f")
        whole, separator, fraction = amount.partition(".")
        if separator:
            fraction = fraction.rstrip("0")
        fraction = fraction.ljust(2, "0")
        return {"amount": f"{whole}.{fraction}", "currency": self.currency}
