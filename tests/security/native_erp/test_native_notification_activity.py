"""ISO-001 probes: comments, activity feeds, assignments, notifications.

Cross-unit content must not reach a unit user through Comment/Communication
lists, assignment (ToDo) surfaces, or notification logs.
"""
from __future__ import annotations

import json
import unittest

from tests.security.native_erp import _harness as h


class TestNativeNotificationActivity(h.IsolationProbeTestCase):
    SURFACE = "notification_activity"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # Seed a comment containing the BM marker on the BM lead (admin side).
        flt = json.dumps([["reference_doctype", "=", "Lead"],
                          ["reference_name", "=", cls.lead_bm_name],
                          ["content", "like", f"%{h.MARKER_BM}%"]])
        status, body = h.admin_get("/api/resource/Comment",
                                   params={"filters": flt,
                                           "limit_page_length": "1"})
        if not (status == 200 and json.loads(body).get("data")):
            s, b = h.admin_create("Comment", {
                "comment_type": "Comment",
                "reference_doctype": "Lead",
                "reference_name": cls.lead_bm_name,
                "content": f"ISO note {h.MARKER_BM}",
            })
            if s not in (200, 201):
                raise RuntimeError(f"comment seed failed: {s} {b[:200]}")

    def _list(self, sess: h.UserSession, actor: str, doctype: str,
              extra: dict | None = None) -> tuple[int, bytes]:
        params = {"limit_page_length": "500",
                  "fields": json.dumps(["name", "reference_name"])}
        if extra:
            params.update(extra)
        status, body, elapsed = sess.get(f"/api/resource/{doctype}",
                                         params=params)
        h.record_probe(self.SURFACE, actor, f"GET /api/resource/{doctype}",
                       "no cross-unit content", status, body, elapsed)
        return status, body

    def test_comment_list_no_cross_unit(self) -> None:
        status, body = self._list(self.sess_p1, h.USER_SALES_P1, "Comment")
        if status == 200:
            text = body.decode(errors="replace")
            self.assertNotIn(h.MARKER_BM, text)
            self.assertNotIn(self.lead_bm_name or "", text)

    def test_comment_on_cross_unit_lead_denied(self) -> None:
        flt = json.dumps([["reference_doctype", "=", "Lead"],
                          ["reference_name", "=", self.lead_bm_name]])
        status, body = self._list(self.sess_p1, h.USER_SALES_P1, "Comment",
                                  {"filters": flt})
        if status == 200:
            rows = json.loads(body).get("data") or []
            self.assertEqual(rows, [],
                             "LEAK: P1 user lists comments on BM lead")

    def test_todo_assignment_list_scoped(self) -> None:
        status, body = self._list(self.sess_p1, h.USER_SALES_P1, "ToDo")
        if status == 200:
            self.assertNotIn(self.lead_bm_name or "",
                             body.decode(errors="replace"))

    def test_notification_log_scoped(self) -> None:
        status, body = self._list(self.sess_p1, h.USER_SALES_P1,
                                  "Notification Log")
        # Denied (403) is a PASS; 200 must contain no cross-unit markers.
        if status == 200:
            text = body.decode(errors="replace")
            self.assertNotIn(h.MARKER_BM, text)
            self.assertNotIn(self.lead_bm_name or "", text)

    def test_communication_list_no_cross_unit(self) -> None:
        status, body = self._list(self.sess_bm, h.USER_SALES_BM,
                                  "Communication")
        if status == 200:
            text = body.decode(errors="replace")
            self.assertNotIn(h.MARKER_P1, text)
            self.assertNotIn(self.lead_p1_name or "", text)


if __name__ == "__main__":
    unittest.main()
