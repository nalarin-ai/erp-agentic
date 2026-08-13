from dataclasses import FrozenInstanceError
import unittest

from src.contracts.financial_identity import FinancialIdentity


class FinancialIdentityContractTest(unittest.TestCase):
    def test_all_dimensions_are_explicit_immutable_and_canonical(self) -> None:
        identity = FinancialIdentity(
            operating_unit_ref="UNIT-BANYUMEDIA",
            legal_issuer_ref="ISSUER-SYNTHETIC-01",
            tax_profile_ref="TAX-NON-PPN-V1",
            invoice_series_ref="SERIES-SYNTHETIC-01",
            receivable_ledger_ref="LEDGER-SYNTHETIC-IDR-01",
            destination_account_alias="ACC-BANYUMEDIA-DEFAULT",
        )

        self.assertEqual(
            identity.to_canonical_payload(),
            {
                "destination_account_alias": "ACC-BANYUMEDIA-DEFAULT",
                "invoice_series_ref": "SERIES-SYNTHETIC-01",
                "legal_issuer_ref": "ISSUER-SYNTHETIC-01",
                "operating_unit_ref": "UNIT-BANYUMEDIA",
                "receivable_ledger_ref": "LEDGER-SYNTHETIC-IDR-01",
                "tax_profile_ref": "TAX-NON-PPN-V1",
            },
        )
        with self.assertRaises(FrozenInstanceError):
            identity.legal_issuer_ref = "ISSUER-OTHER"  # type: ignore[misc]

    def test_missing_or_nonopaque_dimension_is_rejected(self) -> None:
        valid = {
            "operating_unit_ref": "UNIT-BANYUMEDIA",
            "legal_issuer_ref": "ISSUER-SYNTHETIC-01",
            "tax_profile_ref": "TAX-NON-PPN-V1",
            "invoice_series_ref": "SERIES-SYNTHETIC-01",
            "receivable_ledger_ref": "LEDGER-SYNTHETIC-IDR-01",
            "destination_account_alias": "ACC-BANYUMEDIA-DEFAULT",
        }

        for field, invalid in (("operating_unit_ref", ""), ("tax_profile_ref", " "), ("destination_account_alias", "1234567890")):
            with self.subTest(field=field):
                values = {**valid, field: invalid}
                with self.assertRaises(ValueError):
                    FinancialIdentity(**values)

    def test_each_dimension_requires_its_own_prefix_and_account_alias_is_not_digits(self) -> None:
        valid = {
            "operating_unit_ref": "UNIT-BANYUMEDIA",
            "legal_issuer_ref": "ISSUER-SYNTHETIC-01",
            "tax_profile_ref": "TAX-NON-PPN-V1",
            "invoice_series_ref": "SERIES-SYNTHETIC-01",
            "receivable_ledger_ref": "LEDGER-SYNTHETIC-IDR-01",
            "destination_account_alias": "ACC-BANYUMEDIA-DEFAULT",
        }
        invalid_values = {
            "operating_unit_ref": "ACC-X",
            "legal_issuer_ref": "UNIT-X",
            "tax_profile_ref": "ISSUER-X",
            "invoice_series_ref": "TAX-X",
            "receivable_ledger_ref": "SERIES-X",
            "destination_account_alias": "ACC-1234567890",
        }

        for field, invalid in invalid_values.items():
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    FinancialIdentity(**{**valid, field: invalid})

    def test_account_alias_rejects_long_account_number_shaped_segments(self) -> None:
        valid = {
            "operating_unit_ref": "UNIT-BANYUMEDIA",
            "legal_issuer_ref": "ISSUER-SYNTHETIC-01",
            "tax_profile_ref": "TAX-NON-PPN-V1",
            "invoice_series_ref": "SERIES-SYNTHETIC-01",
            "receivable_ledger_ref": "LEDGER-SYNTHETIC-IDR-01",
        }
        aliases = (
            "ACC-BANK-1234567890123456",
            "ACC-1234567890123456-DEFAULT",
            "ACC-IBAN-GB82-WEST-1234-5698-7654-32",
        )

        for alias in aliases:
            with self.subTest(alias=alias):
                with self.assertRaises(ValueError):
                    FinancialIdentity(**valid, destination_account_alias=alias)

    def test_redacted_descriptor_never_emits_account_alias_value(self) -> None:
        identity = FinancialIdentity(
            operating_unit_ref="UNIT-BANYUMEDIA",
            legal_issuer_ref="ISSUER-SYNTHETIC-01",
            tax_profile_ref="TAX-NON-PPN-V1",
            invoice_series_ref="SERIES-SYNTHETIC-01",
            receivable_ledger_ref="LEDGER-SYNTHETIC-IDR-01",
            destination_account_alias="ACC-BANYUMEDIA-DEFAULT",
        )

        descriptor = identity.to_redacted_descriptor()

        self.assertEqual(descriptor["destination_account_alias"], "ACC-[REDACTED]")
        self.assertNotIn("ACC-BANYUMEDIA-DEFAULT", repr(descriptor))


if __name__ == "__main__":
    unittest.main()
