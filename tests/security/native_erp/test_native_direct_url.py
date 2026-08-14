"""ISO-001 probes: direct document URLs (REST + desk pages) must fail closed.

A unit user must not read another unit's document by guessed ID/direct URL;
error bodies must not disclose protected field values.
"""
from __future__ import annotations

import json
import unittest

from tests.security.native_erp import _harness as h


class TestNativeDirectUrl(h.IsolationProbeTestCase):
    SURFACE = "direct_url"

    def _probe(self, sess: h.UserSession, actor: str, method: str,
               path: str, action: str) -> tuple[int, bytes]:
        status, body, elapsed = sess.request(method, path)
        h.record_probe(self.SURFACE, actor, action, "deny/no-leak",
                       status, body, elapsed)
        return status, body

    def test_cross_unit_lead_rest_get_denied(self) -> None:
        status, body = self._probe(
            self.sess_bm, h.USER_SALES_BM, "GET",
            f"/api/resource/Lead/{self.lead_p1_name}",
            f"GET /api/resource/Lead/{self.lead_p1_name} (cross-unit)")
        self.assertIn(status, (403, 404),
                      f"cross-unit Lead GET returned {status}")
        self.assertNotIn(h.MARKER_P1, body.decode(errors="replace"),
                         "LEAK: error body discloses protected field values")

    def test_cross_unit_lead_rest_get_denied_reverse(self) -> None:
        status, body = self._probe(
            self.sess_p1, h.USER_SALES_P1, "GET",
            f"/api/resource/Lead/{self.lead_bm_name}",
            f"GET /api/resource/Lead/{self.lead_bm_name} (cross-unit)")
        self.assertIn(status, (403, 404))
        self.assertNotIn(h.MARKER_BM, body.decode(errors="replace"))

    def test_cross_unit_quotation_rest_get_denied(self) -> None:
        status, body = self._probe(
            self.sess_bm, h.USER_SALES_BM, "GET",
            f"/api/resource/Quotation/{self.qtn_p1_name}",
            f"GET /api/resource/Quotation/{self.qtn_p1_name} (cross-unit)")
        self.assertIn(status, (403, 404))
        self.assertNotIn(h.MARKER_P1, body.decode(errors="replace"))

    def test_cross_unit_customer_rest_get_denied(self) -> None:
        status, body = self._probe(
            self.sess_bm, h.USER_SALES_BM, "GET",
            f"/api/resource/Customer/{h.CUSTOMER_P1}",
            f"GET /api/resource/Customer/{h.CUSTOMER_P1} (cross-unit)")
        self.assertIn(status, (403, 404))
        self.assertNotIn(h.MARKER_P1, body.decode(errors="replace"))

    def test_desk_form_page_does_not_disclose_doc(self) -> None:
        # Desk page HTML itself is the app shell; the data fetch happens via
        # API. Assert the shell page does not embed the marker or doc name.
        status, body, elapsed = self.sess_bm.get(
            f"/app/lead/{self.lead_p1_name}")
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       f"GET /app/lead/{self.lead_p1_name}",
                       "no field disclosure", status, body, elapsed)
        text = body.decode(errors="replace")
        self.assertNotIn(h.MARKER_P1, text)

    def test_error_indistinguishable_from_nonexistent(self) -> None:
        # Existence oracle: cross-unit existing doc vs random nonexistent doc
        # must return the same status class (no 403-vs-404 split).
        s1, _ = self._probe(self.sess_bm, h.USER_SALES_BM, "GET",
                            f"/api/resource/Lead/{self.lead_p1_name}",
                            "GET existing cross-unit lead")
        s2, _ = self._probe(self.sess_bm, h.USER_SALES_BM, "GET",
                            "/api/resource/Lead/CRM-LEAD-2099-99999",
                            "GET nonexistent lead")
        # Record the oracle pair explicitly: a status split is a leak even
        # though no marker token appears in either body.
        if s1 != s2:
            h.ProbeRecorder.instance().record(h.ProbeResult(
                surface=self.SURFACE, actor=h.USER_SALES_BM,
                action="existence-oracle 403-vs-404 split",
                expected="identical status", status=s1,
                leaked_markers=[f"status-oracle:{s1}vs{s2}"],
                timing_bucket="fast",
                detail="cross-unit existence confirmed via status split"))
        self.assertEqual(
            s1, s2,
            f"existence oracle: cross-unit={s1} vs nonexistent={s2}")


if __name__ == "__main__":
    unittest.main()
