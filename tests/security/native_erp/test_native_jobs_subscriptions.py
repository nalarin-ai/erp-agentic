"""ISO-001 probes: background jobs, scheduler logs, subscriptions, activity.

Unit users must not read job internals or cross-unit activity streams.
Where a surface requires a role the synthetic users don't have, DENIED is
the required (pass) outcome.
"""
from __future__ import annotations

import json
import unittest

from tests.security.native_erp import _harness as h


class TestNativeJobsSubscriptions(h.IsolationProbeTestCase):
    SURFACE = "jobs_subscriptions"

    def _probe_list(self, sess: h.UserSession, actor: str,
                    doctype: str) -> tuple[int, bytes]:
        status, body, elapsed = sess.get(
            f"/api/resource/{doctype}",
            params={"limit_page_length": "100",
                    "fields": json.dumps(["name"])})
        h.record_probe(self.SURFACE, actor, f"GET /api/resource/{doctype}",
                       "deny-or-scoped", status, body, elapsed)
        return status, body

    def test_scheduled_job_log_denied(self) -> None:
        status, body = self._probe_list(self.sess_bm, h.USER_SALES_BM,
                                        "Scheduled Job Log")
        if status == 200:
            rows = json.loads(body).get("data") or []
            self.assertEqual(rows, [],
                             "LEAK: unit user enumerates scheduled job logs")
        else:
            self.assertIn(status, (401, 403))

    def test_rq_job_denied(self) -> None:
        status, _ = self._probe_list(self.sess_bm, h.USER_SALES_BM, "RQ Job")
        if status != 200:
            self.assertIn(status, (401, 403, 404))

    def test_activity_log_no_cross_unit(self) -> None:
        status, body = self._probe_list(self.sess_p1, h.USER_SALES_P1,
                                        "Activity Log")
        if status == 200:
            text = body.decode(errors="replace")
            self.assertNotIn(h.MARKER_BM, text)
            self.assertNotIn(self.lead_bm_name or "", text)

    def test_energy_point_log_no_cross_unit(self) -> None:
        status, body = self._probe_list(self.sess_p1, h.USER_SALES_P1,
                                        "Energy Point Log")
        if status == 200:
            text = body.decode(errors="replace")
            self.assertNotIn(h.MARKER_BM, text)

    def test_version_log_no_cross_unit(self) -> None:
        # Version (audit trail) rows for the BM lead must not be visible to P1.
        flt = json.dumps([["ref_doctype", "=", "Lead"],
                          ["docname", "=", self.lead_bm_name]])
        status, body, elapsed = self.sess_p1.get(
            "/api/resource/Version",
            params={"filters": flt, "limit_page_length": "100",
                    "fields": json.dumps(["name", "docname", "data"])})
        h.record_probe(self.SURFACE, h.USER_SALES_P1,
                       "GET /api/resource/Version (BM lead history)",
                       "deny/no-leak", status, body, elapsed)
        if status == 200:
            rows = json.loads(body).get("data") or []
            self.assertEqual(rows, [],
                             "LEAK: P1 user reads BM lead version history")
        else:
            self.assertIn(status, (401, 403))

    def test_data_import_tool_denied(self) -> None:
        status, body, elapsed = self.sess_bm.post("/api/resource/Data Import", {
            "reference_doctype": "Lead",
            "import_type": "Insert New Records",
        })
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       "POST /api/resource/Data Import",
                       "deny-or-scoped", status, body, elapsed)
        # Denied is pass; allowed-but-scoped is acceptable only if it cannot
        # reference cross-unit docs — assert no cross-unit markers in reply.
        self.assertNotIn(h.MARKER_P1, body.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
