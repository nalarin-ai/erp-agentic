"""ISOFIX-001 QA-r1 remediation tests (TDD RED-first).

QA-01 (MEDIUM): ISO001_ENABLE_UNIT_USERS=1 escape hatch must actually
re-enable disabled unit users — seed_users() currently skips existing
users without restoring enabled=1, so the historical suites cannot run.

QA-02 (LOW): the final migration must purge User Permissions even when
seed-side helpers just re-created them; ensure_final_architecture_seeded
must converge the pilot to (disabled AND purged) in one call.

QA-03 (LOW): the ISOLATION_FINAL verdict JSON must carry run_id +
generated_at so a stale verdict cannot survive newer raw runs.

QA-04 (INFO, accepted-documented): role identity is whitespace-normalized
by design (defensive UX); identity matching itself remains exact/case-
sensitive. Locked by an explicit test.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.isolation_architecture import RoleClass, classify_role, write_verdict
from src.isolation_architecture.config import final_config
from tests.security.isolation_final import _harness as fh
from tests.security.isolation_final.seed_final import (
    ensure_final_architecture_seeded,
    migrate_unit_user_to_gateway_only,
)
from tests.security.native_erp import _harness as h


class TestQA01RollbackPathReEnables(unittest.TestCase):
    """The documented rollback must work: env-gated seeding re-enables users."""

    def test_seed_users_reenables_disabled_unit_user(self) -> None:
        # Arrange: disable BM user (final-architecture steady state).
        h.admin_put("User", h.USER_SALES_BM, {"enabled": 0})
        status, body = h.admin_get(f"/api/resource/User/{h.USER_SALES_BM}")
        self.assertEqual(json.loads(body)["data"]["enabled"], 0)
        # Act: rollback path (what the ISO-001 suites invoke when env-gated).
        h.seed_users()
        # Assert: user is enabled again.
        status, body = h.admin_get(f"/api/resource/User/{h.USER_SALES_BM}")
        self.assertEqual(
            json.loads(body)["data"]["enabled"], 1,
            "rollback path must re-enable disabled unit users",
        )
        # Restore final steady state for other suites.
        migrate_unit_user_to_gateway_only(h.USER_SALES_BM)

    def test_seed_users_keeps_deactivated_fixture_disabled(self) -> None:
        h.seed_users()
        status, body = h.admin_get(f"/api/resource/User/{h.USER_DEACTIVATED}")
        self.assertEqual(json.loads(body)["data"]["enabled"], 0)


class TestQA02MigrationConverges(unittest.TestCase):
    """ensure_final_architecture_seeded must leave users disabled AND purged
    even if a seed-side helper re-created User Permissions first."""

    def test_purge_after_permission_recreation(self) -> None:
        # Arrange: simulate seed-side residue — re-create a permission row.
        h.admin_create("User Permission", {
            "user": h.USER_SALES_P1, "allow": "Company",
            "for_value": h.UNIT_P1, "apply_to_all_doctypes": 1,
        })
        # Act
        outcome = migrate_unit_user_to_gateway_only(h.USER_SALES_P1)
        # Assert
        self.assertEqual(
            outcome, {"disabled": True, "permissions_purged": True},
            f"migration must converge to disabled+purged: {outcome}",
        )
        status, body = h.admin_get(f"/api/resource/User/{h.USER_SALES_P1}")
        self.assertEqual(json.loads(body)["data"]["enabled"], 0)
        from tests.security.isolation_final.seed_final import _admin_list_user_permissions
        self.assertEqual(_admin_list_user_permissions(h.USER_SALES_P1), [])

    def test_ensure_final_architecture_seeded_is_convergent(self) -> None:
        h.ensure_all_seeded()  # recreates permissions for enabled users
        ensure_final_architecture_seeded()
        from tests.security.isolation_final.seed_final import _admin_list_user_permissions
        for username in (h.USER_SALES_BM, h.USER_SALES_P1):
            with self.subTest(user=username):
                status, body = h.admin_get(f"/api/resource/User/{username}")
                self.assertEqual(json.loads(body)["data"]["enabled"], 0)
                self.assertEqual(_admin_list_user_permissions(username), [])


class TestQA03VerdictFreshnessFields(unittest.TestCase):
    def test_verdict_carries_run_id_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_verdict(
                Path(tmp),
                verdict="PASS",
                config=final_config(),
                matrix_summary={"total_probes": 1, "leak_positive_probes": 0},
                findings=[],
                run_id="20260815T000000-deadbeef",
            )
            payload = json.loads(target.read_text())
            self.assertEqual(payload["run_id"], "20260815T000000-deadbeef")
            self.assertIn("generated_at", payload)

    def test_verdict_rejects_blank_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_verdict(
                    Path(tmp),
                    verdict="PASS",
                    config=final_config(),
                    matrix_summary={},
                    findings=[],
                    run_id="  ",
                )


class TestQA04RoleWhitespaceNormalizationDocumented(unittest.TestCase):
    def test_whitespace_wrapped_role_classifies_but_case_does_not(self) -> None:
        self.assertIs(classify_role("\tSales User\n"), RoleClass.UNIT_SCOPED)
        with self.assertRaises(Exception):
            classify_role("sales user")  # case-fold confusion still denied


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
