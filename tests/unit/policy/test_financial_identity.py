import unittest
from datetime import datetime, timedelta, timezone

from src.policy.financial_identity import (
    CompatibilityCatalog,
    FinancialIdentityPolicy,
    FinancialPolicyResolver,
    PolicyResolutionError,
    PolicyResolutionRequest,
    RequestedFinancialIdentity,
)


def compatibility_catalog(*identities):
    return CompatibilityCatalog(
        "CATALOG-FINANCIAL-TEST", 1, "EVIDENCE-QUALIFIED-SYNTHETIC", tuple(identities)
    )


class FinancialIdentityPolicyResolverTest(unittest.TestCase):
    def test_exactly_one_effective_policy_resolves_immutable_financial_identity(self) -> None:
        policy = FinancialIdentityPolicy(
            policy_ref="POLICY-BANYUMEDIA-01",
            policy_version=3,
            operating_unit_ref="UNIT-BANYUMEDIA",
            legal_issuer_ref="ISSUER-SYNTHETIC-NONPPN",
            tax_profile_ref="TAX-NONPPN-01",
            invoice_series_ref="SERIES-BANYUMEDIA-01",
            receivable_ledger_ref="LEDGER-BANYUMEDIA-IDR",
            destination_account_alias="ACC-BANYUMEDIA-DEFAULT",
            currency="IDR",
            effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            effective_until=None,
            active=True,
        )
        request = PolicyResolutionRequest(
            operating_unit_ref="UNIT-BANYUMEDIA",
            currency="IDR",
            effective_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )

        resolved = FinancialPolicyResolver((policy,), compatibility_catalog=compatibility_catalog(policy.identity)).resolve(request)

        self.assertEqual(resolved.policy_ref, "POLICY-BANYUMEDIA-01")
        self.assertEqual(resolved.policy_version, 3)
        self.assertEqual(
            resolved.identity.to_canonical_payload(),
            {
                "destination_account_alias": "ACC-BANYUMEDIA-DEFAULT",
                "invoice_series_ref": "SERIES-BANYUMEDIA-01",
                "legal_issuer_ref": "ISSUER-SYNTHETIC-NONPPN",
                "operating_unit_ref": "UNIT-BANYUMEDIA",
                "receivable_ledger_ref": "LEDGER-BANYUMEDIA-IDR",
                "tax_profile_ref": "TAX-NONPPN-01",
            },
        )
        self.assertEqual(resolved.currency, "IDR")
        self.assertEqual(
            resolved.to_redacted_descriptor(),
            {
                "catalog_evidence_ref": "EVIDENCE-QUALIFIED-SYNTHETIC",
                "catalog_ref": "CATALOG-FINANCIAL-TEST",
                "catalog_version": 1,
                "currency": "IDR",
                "identity": {
                    "destination_account_alias": "ACC-[REDACTED]",
                    "invoice_series_ref": "SERIES-BANYUMEDIA-01",
                    "legal_issuer_ref": "ISSUER-SYNTHETIC-NONPPN",
                    "operating_unit_ref": "UNIT-BANYUMEDIA",
                    "receivable_ledger_ref": "LEDGER-BANYUMEDIA-IDR",
                    "tax_profile_ref": "TAX-NONPPN-01",
                },
                "policy_ref": "POLICY-BANYUMEDIA-01",
                "policy_version": 3,
            },
        )
        snapshot = resolved.to_posted_snapshot()
        self.assertEqual(snapshot.identity.destination_account_alias, "ACC-BANYUMEDIA-DEFAULT")
        self.assertEqual(snapshot.policy_ref, "POLICY-BANYUMEDIA-01")
        self.assertEqual(snapshot.policy_version, 3)
        with self.assertRaises(AttributeError):
            resolved.policy_version = 4  # type: ignore[misc]

    def test_missing_ambiguous_inactive_currency_and_effective_boundaries_fail_closed(self) -> None:
        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        end = datetime(2026, 9, 1, tzinfo=timezone.utc)

        def policy(*, active: bool = True, policy_ref: str = "POLICY-UNIT-X-01") -> FinancialIdentityPolicy:
            return FinancialIdentityPolicy(
                policy_ref=policy_ref,
                policy_version=1,
                operating_unit_ref="UNIT-X",
                legal_issuer_ref="ISSUER-X",
                tax_profile_ref="TAX-NONPPN-X",
                invoice_series_ref="SERIES-X",
                receivable_ledger_ref="LEDGER-X-IDR",
                destination_account_alias="ACC-UNIT-X-01",
                currency="IDR",
                effective_from=start,
                effective_until=end,
                active=active,
            )

        def request(at: datetime, currency: str = "IDR") -> PolicyResolutionRequest:
            return PolicyResolutionRequest("UNIT-X", currency, at)

        self.assertEqual(
            FinancialPolicyResolver((policy(),), compatibility_catalog=compatibility_catalog(policy().identity)).resolve(request(start)).policy_ref,
            "POLICY-UNIT-X-01",
        )
        self.assertEqual(
            FinancialPolicyResolver((policy(),), compatibility_catalog=compatibility_catalog(policy().identity)).resolve(request(end - timedelta(microseconds=1))).policy_ref,
            "POLICY-UNIT-X-01",
        )
        for resolver, candidate_request, expected_code in (
            (FinancialPolicyResolver((), compatibility_catalog=compatibility_catalog(policy().identity)), request(start), "POLICY_NOT_FOUND"),
            (FinancialPolicyResolver((policy(active=False),), compatibility_catalog=compatibility_catalog(policy(active=False).identity)), request(start), "POLICY_NOT_FOUND"),
            (FinancialPolicyResolver((policy(),), compatibility_catalog=compatibility_catalog(policy().identity)), request(start, "USD"), "POLICY_NOT_FOUND"),
            (FinancialPolicyResolver((policy(),), compatibility_catalog=compatibility_catalog(policy().identity)), request(end), "POLICY_NOT_FOUND"),
            (
                FinancialPolicyResolver((policy(), policy(policy_ref="POLICY-UNIT-X-02")), compatibility_catalog=compatibility_catalog(policy().identity)),
                request(start),
                "POLICY_AMBIGUOUS",
            ),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(PolicyResolutionError) as caught:
                    resolver.resolve(candidate_request)
                self.assertEqual(caught.exception.code, expected_code)
                self.assertNotIn("UNIT-X", str(caught.exception))
                self.assertNotIn("ACC-", str(caught.exception))

    def test_shared_account_and_ppn_overrides_are_policy_data_not_unit_branches(self) -> None:
        at = datetime(2026, 8, 13, tzinfo=timezone.utc)

        def policy(
            unit: str,
            policy_ref: str,
            issuer: str,
            tax: str,
            series: str,
            ledger: str,
            account: str,
        ) -> FinancialIdentityPolicy:
            return FinancialIdentityPolicy(
                policy_ref=policy_ref,
                policy_version=1,
                operating_unit_ref=unit,
                legal_issuer_ref=issuer,
                tax_profile_ref=tax,
                invoice_series_ref=series,
                receivable_ledger_ref=ledger,
                destination_account_alias=account,
                currency="IDR",
                effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                effective_until=None,
                active=True,
            )

        policies = (
            policy("UNIT-CONTRACTOR", "POLICY-CONTRACTOR-01", "ISSUER-NONPPN-X", "TAX-NONPPN-X", "SERIES-CONTRACTOR-X", "LEDGER-CONTRACTOR-IDR", "ACC-CONTRACTOR-DEFAULT"),
            policy("UNIT-HEAVY-EQUIPMENT", "POLICY-HEAVY-01", "ISSUER-NONPPN-X", "TAX-NONPPN-X", "SERIES-HEAVY-X", "LEDGER-HEAVY-IDR", "ACC-CONTRACTOR-DEFAULT"),
            policy("UNIT-BANYUMEDIA", "POLICY-PT-PPN-01", "ISSUER-PT-TKH", "TAX-PPN-PT-TKH", "SERIES-PT-TKH-PPN", "LEDGER-PT-TKH-IDR", "ACC-PTTKH-DEFAULT"),
        )
        resolver = FinancialPolicyResolver(
            policies, compatibility_catalog=compatibility_catalog(*(policy.identity for policy in policies))
        )

        contractor = resolver.resolve(PolicyResolutionRequest("UNIT-CONTRACTOR", "IDR", at))
        heavy = resolver.resolve(PolicyResolutionRequest("UNIT-HEAVY-EQUIPMENT", "IDR", at))
        self.assertEqual(contractor.identity.destination_account_alias, "ACC-CONTRACTOR-DEFAULT")
        self.assertEqual(heavy.identity.destination_account_alias, "ACC-CONTRACTOR-DEFAULT")

        from src.policy.financial_identity import OverrideAuthorization

        authorization = OverrideAuthorization(True, "REASON-APPROVED", "EVIDENCE-SYNTHETIC", 1)
        pt_request = PolicyResolutionRequest(
            "UNIT-BANYUMEDIA",
            "IDR",
            at,
            requested_identity=RequestedFinancialIdentity(
                legal_issuer_ref="ISSUER-PT-TKH",
                tax_profile_ref="TAX-PPN-PT-TKH",
                invoice_series_ref="SERIES-PT-TKH-PPN",
                receivable_ledger_ref="LEDGER-PT-TKH-IDR",
                destination_account_alias="ACC-PTTKH-DEFAULT",
            ),
            override_authorization=authorization,
        )
        self.assertEqual(resolver.resolve(pt_request).policy_ref, "POLICY-PT-PPN-01")

        wrong_dimensions = (
            {"legal_issuer_ref": "ISSUER-WRONG"},
            {"tax_profile_ref": "TAX-NONPPN-X"},
            {"invoice_series_ref": "SERIES-WRONG"},
            {"receivable_ledger_ref": "LEDGER-WRONG-IDR"},
            {"destination_account_alias": "ACC-BANYUMEDIA-DEFAULT"},
        )
        correct = {
            "legal_issuer_ref": "ISSUER-PT-TKH",
            "tax_profile_ref": "TAX-PPN-PT-TKH",
            "invoice_series_ref": "SERIES-PT-TKH-PPN",
            "receivable_ledger_ref": "LEDGER-PT-TKH-IDR",
            "destination_account_alias": "ACC-PTTKH-DEFAULT",
        }
        for changed in wrong_dimensions:
            with self.subTest(changed=tuple(changed)):
                requested = RequestedFinancialIdentity(**(correct | changed))
                with self.assertRaises(PolicyResolutionError) as caught:
                    resolver.resolve(PolicyResolutionRequest("UNIT-BANYUMEDIA", "IDR", at, requested, authorization))
                self.assertEqual(caught.exception.code, "POLICY_NOT_FOUND")
    def test_invalid_policy_configuration_and_hostile_runtime_types_fail_closed(self) -> None:
        at = datetime(2026, 8, 13, tzinfo=timezone.utc)
        valid = FinancialIdentityPolicy(
            "POLICY-X-01", 1, "UNIT-X", "ISSUER-X", "TAX-X", "SERIES-X",
            "LEDGER-X-IDR", "ACC-X-DEFAULT", "IDR", at, None, True,
        )
        invalid_values = (
            {"policy_version": True},
            {"active": "false"},
            {"currency": 123},
            {"effective_from": datetime(2026, 8, 13)},
            {"effective_until": at - timedelta(seconds=1)},
        )
        for changed in invalid_values:
            with self.subTest(changed=tuple(changed)):
                values = {name: getattr(valid, name) for name in valid.__dataclass_fields__}
                values.update(changed)
                with self.assertRaises(PolicyResolutionError) as caught:
                    FinancialIdentityPolicy(**values)
                self.assertEqual(caught.exception.code, "BLOCKED_CONFIGURATION")

    def test_resolver_requires_versioned_trusted_catalog_capability(self) -> None:
        from src.policy.financial_identity import CompatibilityCatalog

        at = datetime(2026, 8, 13, tzinfo=timezone.utc)
        policy = FinancialIdentityPolicy(
            "POLICY-X-01", 1, "UNIT-X", "ISSUER-X", "TAX-X", "SERIES-X",
            "LEDGER-X-IDR", "ACC-X-DEFAULT", "IDR", at, None, True,
        )
        catalog = CompatibilityCatalog(
            "CATALOG-FINANCIAL-01", 1, "EVIDENCE-QUALIFIED-SYNTHETIC", (policy.identity,)
        )
        resolved = FinancialPolicyResolver((policy,), compatibility_catalog=catalog).resolve(
            PolicyResolutionRequest("UNIT-X", "IDR", at)
        )
        self.assertEqual(resolved.policy_ref, "POLICY-X-01")
        with self.assertRaises(PolicyResolutionError) as caught:
            FinancialPolicyResolver((policy,), compatibility_catalog=(policy.identity,))  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, "BLOCKED_CONFIGURATION")

    def test_compatibility_catalog_rejects_invalid_policy_rows(self) -> None:
        at = datetime(2026, 8, 13, tzinfo=timezone.utc)
        policy = FinancialIdentityPolicy(
            "POLICY-PPN-INVALID", 1, "UNIT-X", "ISSUER-NONPT", "TAX-PPN",
            "SERIES-NONPT", "LEDGER-NONPT-IDR", "ACC-UNIT-DEFAULT", "IDR", at, None, True,
        )
        unrelated = FinancialIdentityPolicy(
            "POLICY-Y-01", 1, "UNIT-Y", "ISSUER-Y", "TAX-Y", "SERIES-Y",
            "LEDGER-Y-IDR", "ACC-Y-DEFAULT", "IDR", at, None, True,
        )
        with self.assertRaises(PolicyResolutionError) as caught:
            FinancialPolicyResolver(
                (policy,), compatibility_catalog=compatibility_catalog(unrelated.identity)
            ).resolve(
                PolicyResolutionRequest("UNIT-X", "IDR", at)
            )
        self.assertEqual(caught.exception.code, "BLOCKED_CONFIGURATION")

    def test_override_requires_authorization_reason_evidence_and_expected_version(self) -> None:
        from src.policy.financial_identity import OverrideAuthorization

        at = datetime(2026, 8, 13, tzinfo=timezone.utc)
        policy = FinancialIdentityPolicy(
            "POLICY-X-01", 2, "UNIT-X", "ISSUER-X", "TAX-X", "SERIES-X",
            "LEDGER-X-IDR", "ACC-X-DEFAULT", "IDR", at, None, True,
        )
        identity = RequestedFinancialIdentity(
            "ISSUER-X", "TAX-X", "SERIES-X", "LEDGER-X-IDR", "ACC-X-DEFAULT"
        )
        resolver = FinancialPolicyResolver((policy,), compatibility_catalog=compatibility_catalog(policy.identity))
        with self.assertRaises(PolicyResolutionError) as caught:
            resolver.resolve(PolicyResolutionRequest("UNIT-X", "IDR", at, identity))
        self.assertEqual(caught.exception.code, "OVERRIDE_AUTHORIZATION_REQUIRED")
        resolved = resolver.resolve(PolicyResolutionRequest(
            "UNIT-X", "IDR", at, identity,
            override_authorization=OverrideAuthorization(True, "REASON-APPROVED", "EVIDENCE-SYNTHETIC", 2),
        ))
        self.assertEqual(resolved.policy_version, 2)

    def test_posted_snapshot_is_an_immutable_typed_value(self) -> None:
        from src.policy.financial_identity import PostedFinancialSnapshot

        at = datetime(2026, 8, 13, tzinfo=timezone.utc)
        policy = FinancialIdentityPolicy(
            "POLICY-X-01", 1, "UNIT-X", "ISSUER-X", "TAX-X", "SERIES-X",
            "LEDGER-X-IDR", "ACC-X-DEFAULT", "IDR", at, None, True,
        )
        resolved = FinancialPolicyResolver((policy,), compatibility_catalog=compatibility_catalog(policy.identity)).resolve(
            PolicyResolutionRequest("UNIT-X", "IDR", at)
        )
        snapshot = resolved.to_posted_snapshot()
        self.assertIsInstance(snapshot, PostedFinancialSnapshot)
        self.assertEqual(snapshot.identity.destination_account_alias, "ACC-X-DEFAULT")
        with self.assertRaises(AttributeError):
            snapshot.policy_version = 2  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
