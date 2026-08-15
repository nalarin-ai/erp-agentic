"""ISOFIX-001 live requalification: native surfaces denied for unit roles.

After the gateway-only migration, ISO-001 unit-scoped synthetic users hold
NO native credentials (accounts disabled, User Permissions purged). Every
native surface that leaked in ISO-001 must now be denied for those users.
Assertions never weaken: any leak remains a failing test.
"""
from __future__ import annotations

import unittest

from tests.security.isolation_final import _harness as fh
from tests.security.isolation_final.seed_final import ensure_final_architecture_seeded
from tests.security.native_erp import _harness as h


class TestFinalNativeDenied(unittest.TestCase):
    """Unit-scoped users cannot establish any native session post-migration."""

    @classmethod
    def setUpClass(cls) -> None:
        h.ensure_all_seeded()
        ensure_final_architecture_seeded()

    def _login_attempt(self, username: str) -> tuple[int, bytes]:
        session = h.UserSession(username, h.USER_PASSWORDS[username])
        return session.login()

    def test_unit_sales_bm_login_denied(self) -> None:
        status, body = self._login_attempt(h.USER_SALES_BM)
        fh.record_probe(
            "final-native-login", h.USER_SALES_BM, "POST /api/method/login",
            "denied (disabled account)", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_BM),
        )
        self.assertNotEqual(status, 200, "disabled unit user must not log in")

    def test_unit_sales_p1_login_denied(self) -> None:
        status, body = self._login_attempt(h.USER_SALES_P1)
        fh.record_probe(
            "final-native-login", h.USER_SALES_P1, "POST /api/method/login",
            "denied (disabled account)", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_P1),
        )
        self.assertNotEqual(status, 200, "disabled unit user must not log in")

    def test_unit_sales_bm_rest_list_denied(self) -> None:
        session = h.UserSession(h.USER_SALES_BM, h.USER_PASSWORDS[h.USER_SALES_BM])
        session.login()
        status, body, elapsed = session.get("/api/resource/Lead")
        fh.record_probe(
            "final-native-api", h.USER_SALES_BM, "GET /api/resource/Lead",
            "denied without session", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_BM), elapsed_s=elapsed,
        )
        self.assertIn(status, (401, 403))
        self.assertEqual(h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_BM)), [])

    def test_unit_sales_p1_customer_enumeration_denied(self) -> None:
        # ISO-001 leak class 1 (Customer unscopeable) is CLOSED BY CONSTRUCTION:
        # there is no unit-scoped native credential to enumerate with.
        session = h.UserSession(h.USER_SALES_P1, h.USER_PASSWORDS[h.USER_SALES_P1])
        session.login()
        status, body, elapsed = session.get("/api/resource/Customer")
        fh.record_probe(
            "final-native-api", h.USER_SALES_P1, "GET /api/resource/Customer",
            "denied without session", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_P1), elapsed_s=elapsed,
        )
        self.assertIn(status, (401, 403))
        self.assertEqual(h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_P1)), [])

    def test_unit_sales_bm_direct_get_cross_unit_denied(self) -> None:
        session = h.UserSession(h.USER_SALES_BM, h.USER_PASSWORDS[h.USER_SALES_BM])
        session.login()
        status, body, elapsed = session.get(f"/api/resource/Lead/{h.LEAD_P1}")
        fh.record_probe(
            "final-native-direct", h.USER_SALES_BM,
            f"GET /api/resource/Lead/{h.LEAD_P1} (cross-unit)",
            "denied without session", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_BM), elapsed_s=elapsed,
        )
        self.assertIn(status, (401, 403))
        self.assertEqual(h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_BM)), [])

    def test_unit_sales_p1_file_metadata_denied(self) -> None:
        # ISO-001 leak class 2 (File metadata enumeration) closed by construction.
        session = h.UserSession(h.USER_SALES_P1, h.USER_PASSWORDS[h.USER_SALES_P1])
        session.login()
        status, body, elapsed = session.get(
            "/api/resource/File",
            params={"filters": '[["File","attached_to_doctype","=","Lead"]]'},
        )
        fh.record_probe(
            "final-native-files", h.USER_SALES_P1,
            "GET /api/resource/File (lead attachments)",
            "denied without session", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_P1), elapsed_s=elapsed,
        )
        self.assertIn(status, (401, 403))
        self.assertEqual(h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_P1)), [])

    def test_unit_sales_bm_private_file_bytes_denied(self) -> None:
        session = h.UserSession(h.USER_SALES_BM, h.USER_PASSWORDS[h.USER_SALES_BM])
        session.login()
        status, body, elapsed = session.get(f"/private/files/{h.ATTACHMENT_NAME}")
        fh.record_probe(
            "final-native-files", h.USER_SALES_BM,
            f"GET /private/files/{h.ATTACHMENT_NAME}",
            "denied without session", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_BM), elapsed_s=elapsed,
        )
        self.assertIn(status, (401, 403))
        self.assertEqual(h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_BM)), [])

    def test_unit_sales_p1_search_autocomplete_denied(self) -> None:
        session = h.UserSession(h.USER_SALES_P1, h.USER_PASSWORDS[h.USER_SALES_P1])
        session.login()
        status, body, elapsed = session.post(
            "/api/method/frappe.desk.search.search_link",
            form={"doctype": "Customer", "txt": "ISO-CUST", "page_length": "20"},
        )
        fh.record_probe(
            "final-native-search", h.USER_SALES_P1,
            "search_link Customer txt='ISO-CUST'",
            "denied without session", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_P1), elapsed_s=elapsed,
        )
        self.assertIn(status, (401, 403))
        self.assertEqual(h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_P1)), [])

    def test_unit_sales_bm_query_report_denied(self) -> None:
        session = h.UserSession(h.USER_SALES_BM, h.USER_PASSWORDS[h.USER_SALES_BM])
        session.login()
        status, body, elapsed = session.get(
            "/api/method/frappe.desk.query_report.run",
            params={"report_name": "General Ledger"},
        )
        fh.record_probe(
            "final-native-reports", h.USER_SALES_BM,
            "query_report General Ledger",
            "denied without session", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_BM), elapsed_s=elapsed,
        )
        self.assertIn(status, (401, 403))
        self.assertEqual(h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_BM)), [])

    def test_unit_sales_p1_desk_denied(self) -> None:
        session = h.UserSession(h.USER_SALES_P1, h.USER_PASSWORDS[h.USER_SALES_P1])
        login_status, _ = session.login()
        status, body, elapsed = session.get("/app")
        text = body.decode(errors="replace")
        # Without a session Frappe serves the public Login page (200); it
        # still defines a minimal `frappe.boot` for the login app itself.
        # Denial evidence = login failed AND the Login meta marker present
        # AND no authenticated desk markers (logged-user boot/session info).
        login_page = "<meta name=\"title\" content=\"Login\">" in text
        no_logged_user = (
            "boot.user" not in text
            and '"session_user"' not in text
            and "desk#" not in text
        )
        fh.record_probe(
            "final-native-desk", h.USER_SALES_P1, "GET /app",
            "login denied; unauthenticated login page only", status, body,
            tokens=h.cross_unit_tokens(h.USER_SALES_P1), elapsed_s=elapsed,
            detail=f"login_status={login_status} login_page={login_page} no_logged_user={no_logged_user}",
        )
        self.assertNotEqual(login_status, 200, "disabled unit user must not log in")
        self.assertTrue(login_page, "unauthenticated /app must be the Login page")
        self.assertTrue(no_logged_user, "no authenticated session markers in body")
        self.assertEqual(h.scan_markers(body, tokens=h.cross_unit_tokens(h.USER_SALES_P1)), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
