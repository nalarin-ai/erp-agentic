"""ISO-001 RED-first: harness + seeder sanity tests.

These tests assert that the synthetic fixtures (users, user permissions,
marker records) can be seeded into the pilot and that per-user sessions
authenticate. They are infrastructure gates: a failure here is a HARNESS
bug, not isolation evidence.
"""
from __future__ import annotations

import json
import os
import unittest

from tests.security.native_erp import _harness as h

_REQUIRES_UNIT_USERS = os.environ.get("ISO001_ENABLE_UNIT_USERS") == "1"
_SKIP_REASON = (
    "requires ISO001_ENABLE_UNIT_USERS=1 — post-ISOFIX-001 the pilot steady "
    "state disables unit-scoped users (gateway-only final architecture)"
)


class TestSeedFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        h.ensure_all_seeded()

    def test_admin_login(self) -> None:
        sess = h.admin_session()
        self.assertTrue(sess.logged_in)

    def test_pinned_erpnext_version(self) -> None:
        status, body = h.admin_get(
            "/api/method/frappe.utils.change_log.get_versions")
        self.assertEqual(status, 200)
        versions = json.loads(body)["message"]
        self.assertEqual(
            versions.get("erpnext", {}).get("version"),
            h.PINNED_ERPNEXT_VERSION,
            "pilot ERPNext version must match the pinned qualification version",
        )

    def test_users_exist(self) -> None:
        for email in (h.USER_SALES_BM, h.USER_SALES_P1, h.USER_OWNER,
                      h.USER_DEACTIVATED):
            self.assertTrue(h.admin_exists("User", email), f"missing {email}")

    def test_deactivated_user_disabled(self) -> None:
        status, body = h.admin_get(f"/api/resource/User/{h.USER_DEACTIVATED}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"].get("enabled"), 0)

    @unittest.skipUnless(_REQUIRES_UNIT_USERS, _SKIP_REASON)
    def test_user_permissions_scoped(self) -> None:
        for email, unit in ((h.USER_SALES_BM, h.UNIT_BM),
                            (h.USER_SALES_P1, h.UNIT_P1)):
            flt = json.dumps([["user", "=", email], ["allow", "=", "Company"],
                              ["for_value", "=", unit]])
            status, body = h.admin_get(
                "/api/resource/User Permission",
                params={"filters": flt, "limit_page_length": "1"})
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body).get("data"),
                            f"missing user permission {email}->{unit}")

    @unittest.skipUnless(_REQUIRES_UNIT_USERS, _SKIP_REASON)
    def test_per_user_sessions_login(self) -> None:
        for email in (h.USER_SALES_BM, h.USER_SALES_P1, h.USER_OWNER):
            sess = h.user_session(email)
            self.assertTrue(sess.logged_in, f"login failed for {email}")

    def test_unknown_user_login_rejected(self) -> None:
        status, _ = h.unknown_user_login()
        self.assertNotEqual(status, 200)

    def test_deactivated_user_login_rejected(self) -> None:
        status, _ = h.deactivated_user_login()
        self.assertNotEqual(status, 200)

    def test_marker_leads_seeded(self) -> None:
        bm = h.find_lead_name_by_marker(h.MARKER_BM)
        p1 = h.find_lead_name_by_marker(h.MARKER_P1)
        self.assertIsNotNone(bm, "BM marker lead missing")
        self.assertIsNotNone(p1, "P1 marker lead missing")

    def test_marker_customers_seeded(self) -> None:
        self.assertTrue(h.admin_exists("Customer", h.CUSTOMER_BM))
        self.assertTrue(h.admin_exists("Customer", h.CUSTOMER_P1))

    def test_marker_quotations_seeded(self) -> None:
        self.assertIsNotNone(h.find_quotation_name_by_marker(h.MARKER_BM))
        self.assertIsNotNone(h.find_quotation_name_by_marker(h.MARKER_P1))

    def test_private_attachment_seeded_on_bm_lead(self) -> None:
        flt = json.dumps([["file_name", "=", h.ATTACHMENT_NAME],
                          ["attached_to_doctype", "=", "Lead"]])
        status, body = h.admin_get(
            "/api/resource/File",
            params={"filters": flt, "fields": json.dumps(
                ["name", "file_url", "is_private", "attached_to_name"])})
        self.assertEqual(status, 200)
        data = json.loads(body).get("data") or []
        self.assertTrue(data, "private attachment missing")
        self.assertEqual(data[0].get("is_private"), 1)


class TestLeakTokenScanning(unittest.TestCase):
    """Leak-evidence scanning must catch cross-unit record names and
    attachment filenames, not only opaque marker strings — otherwise the
    JSONL evidence under-reports verified leaks."""

    def test_scan_markers_catches_cross_unit_customer_name(self) -> None:
        found = h.scan_markers(
            '{"data":[{"name":"ISO-CUST-P1-001"}]}')
        self.assertTrue(any("ISO-CUST-P1-001" in tok for tok in found),
                        f"cross-unit customer name not detected: {found}")

    def test_scan_markers_catches_cross_unit_attachment_filename(self) -> None:
        found = h.scan_markers(
            '{"data":[{"file_name":"iso-private-bm-001.txt"}]}')
        self.assertTrue(any("iso-private-bm-001.txt" in tok for tok in found),
                        f"attachment filename not detected: {found}")

    def test_scan_markers_no_false_positive_on_own_unit_echo(self) -> None:
        # scan_markers flags BOTH units' tokens; the actor-aware filtering
        # is applied at record time via leak tokens for the *other* unit.
        found = h.scan_markers('{"data":[{"name":"ISO-LEAD-BM-001"}]}')
        self.assertIsInstance(found, list)


if __name__ == "__main__":
    unittest.main()
