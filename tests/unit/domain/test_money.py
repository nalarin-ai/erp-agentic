from dataclasses import FrozenInstanceError
import unittest

from src.domain.errors import InvalidDomainValue
from src.domain.money import Money


class MoneyCanonicalPayloadTest(unittest.TestCase):
    def test_decimal_string_and_currency_produce_stable_immutable_payload(self) -> None:
        money = Money.from_decimal("1250.50", "IDR")

        self.assertEqual(
            money.to_canonical_payload(),
            {"amount": "1250.50", "currency": "IDR"},
        )
        with self.assertRaises(FrozenInstanceError):
            money.currency = "USD"  # type: ignore[misc]

    def test_binary_float_amount_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            Money.from_decimal(0.1, "IDR")  # type: ignore[arg-type]

    def test_non_finite_amount_or_noncanonical_currency_is_rejected(self) -> None:
        invalid_inputs = (("NaN", "IDR"), ("Infinity", "IDR"), ("1.00", "idr"), ("1.00", ""))

        for amount, currency in invalid_inputs:
            with self.subTest(amount=amount, currency=currency):
                with self.assertRaises(ValueError):
                    Money.from_decimal(amount, currency)

    def test_direct_constructor_cannot_bypass_invariants(self) -> None:
        from decimal import Decimal

        with self.assertRaises(ValueError):
            Money(amount=Decimal("NaN"), currency="IDR")

    def test_malformed_decimal_raises_redacted_domain_error(self) -> None:
        secret_like_input = "not-a-number-1234567890"

        with self.assertRaises(InvalidDomainValue) as raised:
            Money.from_decimal(secret_like_input, "IDR")

        self.assertNotIn(secret_like_input, str(raised.exception))

    def test_equivalent_decimal_inputs_share_one_canonical_payload(self) -> None:
        first = Money.from_decimal("1250.50", "IDR")
        second = Money.from_decimal("1250.500", "IDR")

        self.assertEqual(first.to_canonical_payload(), second.to_canonical_payload())

    def test_decimal_grammar_zero_and_size_are_canonical_and_bounded(self) -> None:
        from decimal import Decimal

        for invalid in (" 1.00 ", "1_000.00", "+1.00", ".5", "1.", "1E+1000000"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(InvalidDomainValue):
                    Money.from_decimal(invalid, "IDR")

        for invalid_decimal in (Decimal("1E+65"), Decimal("1" * 65)):
            with self.subTest(invalid_decimal=invalid_decimal):
                with self.assertRaises(InvalidDomainValue):
                    Money(amount=invalid_decimal, currency="IDR")

        self.assertEqual(
            Money.from_decimal("-0", "IDR").to_canonical_payload(),
            Money.from_decimal("0", "IDR").to_canonical_payload(),
        )


if __name__ == "__main__":
    unittest.main()
