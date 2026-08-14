import unittest
from datetime import datetime, timedelta, timezone

from src.policy.financial_identity import (
    CompatibilityCatalog,
    FinancialIdentityPolicy,
    FinancialPolicyResolver,
    OverrideAuthorization,
    PolicyResolutionError,
    PolicyResolutionRequest,
    RequestedFinancialIdentity,
    TrustedIssuer,
    TrustedIssuerRegistry,
)

AT = datetime(2026, 8, 14, tzinfo=timezone.utc)


def make_policy(**overrides) -> FinancialIdentityPolicy:
    values = {
        "policy_ref": "POLICY-X-01",
        "policy_version": 1,
        "operating_unit_ref": "UNIT-X",
        "legal_issuer_ref": "ISSUER-X",
        "tax_profile_ref": "TAX-X",
        "invoice_series_ref": "SERIES-X",
        "receivable_ledger_ref": "LEDGER-X-IDR",
        "destination_account_alias": "ACC-X-DEFAULT",
        "currency": "IDR",
        "effective_from": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "effective_until": None,
        "active": True,
    }
    values.update(overrides)
    return FinancialIdentityPolicy(**values)


def make_issuer_registry() -> tuple[TrustedIssuer, TrustedIssuerRegistry]:
    issuer = TrustedIssuer("ISSUER-AUTH-POLICY", b"synthetic-test-key-0001")
    return issuer, TrustedIssuerRegistry((issuer,))


class TrustedIssuanceTest(unittest.TestCase):
    def test_catalog_requires_trusted_issuance_signature(self) -> None:
        """Catalog minted by caller without trusted issuer signature must be rejected."""
        policy = make_policy()
        issuer, registry = make_issuer_registry()
        signed = issuer.issue_catalog(
            "CATALOG-X-01", 1, "EVIDENCE-QUALIFIED-X", (policy.identity,)
        )
        resolver = FinancialPolicyResolver(
            (policy,), compatibility_catalog=signed, trusted_issuers=registry
        )
        self.assertEqual(resolver.resolve(PolicyResolutionRequest("UNIT-X", "IDR", AT)).policy_ref, "POLICY-X-01")

    def test_caller_minted_catalog_without_valid_signature_fails_closed(self) -> None:
        policy = make_policy()
        _, registry = make_issuer_registry()
        forged = CompatibilityCatalog(
            "CATALOG-X-01",
            1,
            "EVIDENCE-QUALIFIED-X",
            (policy.identity,),
            issuer_ref="ISSUER-AUTH-POLICY",
            signature="0" * 64,
        )
        with self.assertRaises(PolicyResolutionError) as caught:
            FinancialPolicyResolver(
                (policy,), compatibility_catalog=forged, trusted_issuers=registry
            )
        self.assertEqual(caught.exception.code, "UNTRUSTED_CATALOG")

    def test_catalog_signed_by_unregistered_issuer_fails_closed(self) -> None:
        policy = make_policy()
        rogue = TrustedIssuer("ISSUER-AUTH-ROGUE", b"synthetic-test-key-9999")
        signed = rogue.issue_catalog(
            "CATALOG-X-01", 1, "EVIDENCE-QUALIFIED-X", (policy.identity,)
        )
        _, registry = make_issuer_registry()
        with self.assertRaises(PolicyResolutionError) as caught:
            FinancialPolicyResolver(
                (policy,), compatibility_catalog=signed, trusted_issuers=registry
            )
        self.assertEqual(caught.exception.code, "UNTRUSTED_CATALOG")

    def test_override_authorization_requires_trusted_issuance(self) -> None:
        policy = make_policy()
        issuer, registry = make_issuer_registry()
        catalog = issuer.issue_catalog(
            "CATALOG-X-01", 1, "EVIDENCE-QUALIFIED-X", (policy.identity,)
        )
        resolver = FinancialPolicyResolver(
            (policy,), compatibility_catalog=catalog, trusted_issuers=registry
        )
        requested = RequestedFinancialIdentity(
            "ISSUER-X", "TAX-X", "SERIES-X", "LEDGER-X-IDR", "ACC-X-DEFAULT"
        )
        forged_override = OverrideAuthorization(
            True,
            "REASON-APPROVED",
            "EVIDENCE-SYNTHETIC",
            1,
            issuer_ref="ISSUER-AUTH-POLICY",
            signature="0" * 64,
        )
        with self.assertRaises(PolicyResolutionError) as caught:
            resolver.resolve(
                PolicyResolutionRequest("UNIT-X", "IDR", AT, requested, forged_override)
            )
        self.assertEqual(caught.exception.code, "UNTRUSTED_OVERRIDE")
        signed_override = issuer.issue_override(
            "REASON-APPROVED", "EVIDENCE-SYNTHETIC", 1
        )
        resolved = resolver.resolve(
            PolicyResolutionRequest("UNIT-X", "IDR", AT, requested, signed_override)
        )
        self.assertEqual(resolved.policy_ref, "POLICY-X-01")


class HostileIterableTest(unittest.TestCase):
    def test_hostile_policy_iterable_raises_stable_blocked_error(self) -> None:
        def hostile():
            yield make_policy()
            raise RuntimeError("hostile iterable explosion")

        _, registry = make_issuer_registry()
        policy = make_policy()
        issuer = TrustedIssuer("ISSUER-AUTH-POLICY", b"synthetic-test-key-0001")
        catalog = issuer.issue_catalog(
            "CATALOG-X-01", 1, "EVIDENCE-QUALIFIED-X", (policy.identity,)
        )
        with self.assertRaises(PolicyResolutionError) as caught:
            FinancialPolicyResolver(
                hostile(), compatibility_catalog=catalog, trusted_issuers=registry
            )
        self.assertEqual(caught.exception.code, "BLOCKED_CONFIGURATION")
        self.assertNotIn("hostile iterable explosion", str(caught.exception))

    def test_non_policy_items_in_iterable_fail_closed(self) -> None:
        policy = make_policy()
        issuer, registry = make_issuer_registry()
        catalog = issuer.issue_catalog(
            "CATALOG-X-01", 1, "EVIDENCE-QUALIFIED-X", (policy.identity,)
        )
        with self.assertRaises(PolicyResolutionError) as caught:
            FinancialPolicyResolver(
                (policy, "not-a-policy", None),
                compatibility_catalog=catalog,
                trusted_issuers=registry,
            )
        self.assertEqual(caught.exception.code, "BLOCKED_CONFIGURATION")


class ProvenanceTest(unittest.TestCase):
    def test_descriptor_and_snapshot_carry_catalog_provenance(self) -> None:
        policy = make_policy()
        issuer, registry = make_issuer_registry()
        catalog = issuer.issue_catalog(
            "CATALOG-X-07", 7, "EVIDENCE-QUALIFIED-X", (policy.identity,)
        )
        resolver = FinancialPolicyResolver(
            (policy,), compatibility_catalog=catalog, trusted_issuers=registry
        )
        resolved = resolver.resolve(PolicyResolutionRequest("UNIT-X", "IDR", AT))
        descriptor = resolved.to_redacted_descriptor()
        self.assertEqual(descriptor["catalog_ref"], "CATALOG-X-07")
        self.assertEqual(descriptor["catalog_version"], 7)
        self.assertEqual(descriptor["catalog_evidence_ref"], "EVIDENCE-QUALIFIED-X")
        snapshot = resolved.to_posted_snapshot()
        self.assertEqual(snapshot.catalog_ref, "CATALOG-X-07")
        self.assertEqual(snapshot.catalog_version, 7)
        self.assertEqual(snapshot.catalog_evidence_ref, "EVIDENCE-QUALIFIED-X")
        payload = snapshot.to_canonical_payload()
        self.assertEqual(payload["catalog_ref"], "CATALOG-X-07")
        self.assertEqual(payload["catalog_version"], 7)
        self.assertEqual(payload["catalog_evidence_ref"], "EVIDENCE-QUALIFIED-X")


class ExhaustiveCrossMatrixTest(unittest.TestCase):
    def test_every_single_dimension_substitution_is_denied(self) -> None:
        base_kwargs = {
            "legal_issuer_ref": "ISSUER-PT-TKH",
            "tax_profile_ref": "TAX-PPN-PT-TKH",
            "invoice_series_ref": "SERIES-PT-TKH-PPN",
            "receivable_ledger_ref": "LEDGER-PT-TKH-IDR",
            "destination_account_alias": "ACC-PTTKH-DEFAULT",
        }
        policy = make_policy(
            policy_ref="POLICY-PT-PPN-01",
            operating_unit_ref="UNIT-BANYUMEDIA",
            **base_kwargs,
        )
        issuer, registry = make_issuer_registry()
        catalog = issuer.issue_catalog(
            "CATALOG-PT-01", 1, "EVIDENCE-QUALIFIED-PT", (policy.identity,)
        )
        resolver = FinancialPolicyResolver(
            (policy,), compatibility_catalog=catalog, trusted_issuers=registry
        )
        signed_override = issuer.issue_override("REASON-APPROVED", "EVIDENCE-PT", 1)
        wrong_values = {
            "legal_issuer_ref": ["ISSUER-WRONG", "ISSUER-NONPPN-X"],
            "tax_profile_ref": ["TAX-WRONG", "TAX-NONPPN-X"],
            "invoice_series_ref": ["SERIES-WRONG", "SERIES-BANYUMEDIA-01"],
            "receivable_ledger_ref": ["LEDGER-WRONG-IDR", "LEDGER-BANYUMEDIA-IDR"],
            "destination_account_alias": ["ACC-WRONG", "ACC-BANYUMEDIA-DEFAULT"],
        }
        total_denials = 0
        for dimension, bad_values in wrong_values.items():
            for bad in bad_values:
                with self.subTest(dimension=dimension, bad=bad):
                    requested = RequestedFinancialIdentity(
                        **(base_kwargs | {dimension: bad})
                    )
                    with self.assertRaises(PolicyResolutionError) as caught:
                        resolver.resolve(
                            PolicyResolutionRequest(
                                "UNIT-BANYUMEDIA", "IDR", AT, requested, signed_override
                            )
                        )
                    self.assertEqual(caught.exception.code, "POLICY_NOT_FOUND")
                    total_denials += 1
        self.assertEqual(total_denials, 10)


if __name__ == "__main__":
    unittest.main()
