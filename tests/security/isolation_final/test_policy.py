"""ISOFIX-001 policy unit tests (TDD RED→GREEN).

Fail-closed admission policy for the final gateway-only architecture.
No network, no credentials — pure decision matrix tests plus hostile-input
denial coverage.
"""
from __future__ import annotations

import unittest

from src.isolation_architecture import (
    Decision,
    IsolationDenied,
    RoleClass,
    Surface,
    admit,
    classify_role,
    issue_native_credential,
    require_gateway_only,
)


class TestRoleClassification(unittest.TestCase):
    def test_unit_scoped_roles(self) -> None:
        for role in ("Sales User", "Sales Manager", "Support User"):
            with self.subTest(role=role):
                self.assertIs(classify_role(role), RoleClass.UNIT_SCOPED)

    def test_operator_roles(self) -> None:
        for role in ("Operator", "System Manager"):
            with self.subTest(role=role):
                self.assertIs(classify_role(role), RoleClass.OPERATOR)

    def test_owner_controller_roles(self) -> None:
        for role in ("Owner", "Controller"):
            with self.subTest(role=role):
                self.assertIs(classify_role(role), RoleClass.OWNER_CONTROLLER)

    def test_unknown_role_denied(self) -> None:
        with self.assertRaises(IsolationDenied):
            classify_role("Administrator")

    def test_empty_role_denied(self) -> None:
        with self.assertRaises(IsolationDenied):
            classify_role("")

    def test_whitespace_only_role_denied(self) -> None:
        with self.assertRaises(IsolationDenied):
            classify_role("   ")

    def test_non_string_role_denied(self) -> None:
        with self.assertRaises(IsolationDenied):
            classify_role(None)  # type: ignore[arg-type]

    def test_hostile_role_denied(self) -> None:
        for hostile in (
            "Sales User\x00",
            "Sales User<script>alert(1)</script>",
            "Sales User\nAdministrator",
            "' OR '1'='1",
        ):
            with self.subTest(hostile=hostile):
                with self.assertRaises(IsolationDenied):
                    classify_role(hostile)

    def test_case_sensitive_no_casefold_confusion(self) -> None:
        # Identity comparison is exact; lowercase variant is NOT the role.
        with self.assertRaises(IsolationDenied):
            classify_role("sales user")

    def test_surrounding_whitespace_normalized(self) -> None:
        self.assertIs(classify_role("  Sales User  "), RoleClass.UNIT_SCOPED)

    def test_denial_message_is_generic(self) -> None:
        try:
            classify_role("Administrator")
        except IsolationDenied as exc:
            msg = str(exc)
            self.assertNotIn("Administrator", msg)
            self.assertEqual(msg, "Access denied by final isolation architecture.")
        else:  # pragma: no cover
            self.fail("expected IsolationDenied")


class TestAdmissionMatrix(unittest.TestCase):
    def test_unit_scoped_denied_all_native_surfaces(self) -> None:
        for surface in (
            Surface.NATIVE_DESK,
            Surface.NATIVE_API,
            Surface.NATIVE_FILES,
            Surface.NATIVE_REPORTS,
        ):
            with self.subTest(surface=surface):
                self.assertIs(admit("Sales User", surface), Decision.DENY)

    def test_unit_scoped_allowed_gateway_ports(self) -> None:
        for surface in (Surface.GATEWAY_ERP_PORT, Surface.GATEWAY_CRM_PORT):
            with self.subTest(surface=surface):
                self.assertIs(admit("Sales User", surface), Decision.ALLOW)

    def test_unit_scoped_denied_owner_rollup(self) -> None:
        self.assertIs(admit("Sales User", Surface.GATEWAY_REPORTS), Decision.DENY)

    def test_operator_allowed_native_surfaces(self) -> None:
        for surface in (
            Surface.NATIVE_DESK,
            Surface.NATIVE_API,
            Surface.NATIVE_FILES,
            Surface.NATIVE_REPORTS,
        ):
            with self.subTest(surface=surface):
                self.assertIs(admit("Operator", surface), Decision.ALLOW)

    def test_operator_denied_owner_rollup(self) -> None:
        self.assertIs(admit("Operator", Surface.GATEWAY_REPORTS), Decision.DENY)

    def test_owner_denied_native_surfaces(self) -> None:
        # Owner roll-up is explicit, server-side, auditable — via gateway only.
        for surface in (
            Surface.NATIVE_DESK,
            Surface.NATIVE_API,
            Surface.NATIVE_FILES,
            Surface.NATIVE_REPORTS,
        ):
            with self.subTest(surface=surface):
                self.assertIs(admit("Owner", surface), Decision.DENY)

    def test_owner_allowed_gateway_including_rollup(self) -> None:
        for surface in (
            Surface.GATEWAY_ERP_PORT,
            Surface.GATEWAY_CRM_PORT,
            Surface.GATEWAY_REPORTS,
        ):
            with self.subTest(surface=surface):
                self.assertIs(admit("Owner", surface), Decision.ALLOW)

    def test_matrix_is_total(self) -> None:
        # Every (role class, surface) pair has an explicit decision.
        for role in ("Sales User", "Operator", "Owner"):
            for surface in Surface:
                with self.subTest(role=role, surface=surface):
                    self.assertIn(admit(role, surface), (Decision.ALLOW, Decision.DENY))

    def test_invalid_surface_denied_fail_closed(self) -> None:
        with self.assertRaises(IsolationDenied):
            admit("Sales User", "NATIVE_API")  # type: ignore[arg-type]

    def test_unknown_role_admit_denied(self) -> None:
        with self.assertRaises(IsolationDenied):
            admit("Administrator", Surface.GATEWAY_ERP_PORT)

    def test_require_gateway_only_allows_gateway(self) -> None:
        require_gateway_only("Sales User", Surface.GATEWAY_ERP_PORT)  # no raise

    def test_require_gateway_only_denies_native(self) -> None:
        with self.assertRaises(IsolationDenied):
            require_gateway_only("Sales User", Surface.NATIVE_API)

    def test_require_gateway_only_denies_owner_native(self) -> None:
        with self.assertRaises(IsolationDenied):
            require_gateway_only("Owner", Surface.NATIVE_DESK)


class TestNativeCredentialIssuance(unittest.TestCase):
    def test_unit_scoped_native_credential_denied(self) -> None:
        for role in ("Sales User", "Sales Manager", "Support User"):
            with self.subTest(role=role):
                with self.assertRaises(IsolationDenied):
                    issue_native_credential(role, "iso-sales-bm@example.test")

    def test_unit_scoped_denial_does_not_echo_username(self) -> None:
        try:
            issue_native_credential("Sales User", "victim@example.test")
        except IsolationDenied as exc:
            self.assertNotIn("victim@example.test", str(exc))
        else:  # pragma: no cover
            self.fail("expected IsolationDenied")

    def test_operator_native_credential_allowed(self) -> None:
        issue_native_credential("Operator", "ops@example.test")  # no raise

    def test_owner_native_credential_allowed(self) -> None:
        # Owner/Controller is not unit-scoped; issuance allowed at this layer
        # but remains governed by a separate ops control.
        issue_native_credential("Owner", "owner@example.test")  # no raise

    def test_unknown_role_issuance_denied(self) -> None:
        with self.assertRaises(IsolationDenied):
            issue_native_credential("Administrator", "x@example.test")

    def test_blank_username_denied(self) -> None:
        with self.assertRaises(IsolationDenied):
            issue_native_credential("Operator", "   ")

    def test_non_string_username_denied(self) -> None:
        with self.assertRaises(IsolationDenied):
            issue_native_credential("Operator", None)  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
