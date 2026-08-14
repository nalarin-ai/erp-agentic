"""ISO-001 probes: REST list endpoints must not leak cross-unit rows/counts.

Required isolation (NATIVE_ERP_ISOLATION.md): a unit-sales user cannot
enumerate protected cross-unit records or counts. A leak is a FAIL and is
qualification evidence — assertions are never weakened to force green.
"""
from __future__ import annotations

import json
import unittest

from tests.security.native_erp import _harness as h


class TestNativeRestList(h.IsolationProbeTestCase):
    SURFACE = "rest_list"

    def _list(self, sess: h.UserSession, actor: str, doctype: str,
              fields: list[str] | None = None) -> tuple[int, bytes, float]:
        status, body, elapsed = sess.get(
            f"/api/resource/{doctype}",
            params={"limit_page_length": "500",
                    "fields": json.dumps(fields or ["name"])},
        )
        result = h.record_probe(
            self.SURFACE, actor, f"GET /api/resource/{doctype}",
            "deny/no-leak", status, body, elapsed)
        return status, body, elapsed

    def _assert_scoped(self, sess: h.UserSession, actor: str,
                       doctype: str, own: str, other_marker: str) -> None:
        status, body, _ = self._list(sess, actor, doctype,
                                     fields=["name", "company"])
        # 200 with scoped rows, or 403 — both acceptable fail-closed outcomes.
        self.assertIn(status, (200, 403), f"unexpected status {status}")
        if status == 200:
            rows = json.loads(body).get("data") or []
            for row in rows:
                company = row.get("company")
                if company is not None:
                    self.assertEqual(
                        company, own,
                        f"{actor} sees {doctype} row of company {company}")
        self.assertFalse(
            h.scan_markers(body, tokens=h.cross_unit_tokens(actor)),
            f"LEAK: {actor} list {doctype} exposes other-unit marker")

    def test_lead_list_scoped_for_bm_user(self) -> None:
        self._assert_scoped(self.sess_bm, h.USER_SALES_BM, "Lead",
                            h.UNIT_BM, h.MARKER_P1)

    def test_lead_list_scoped_for_p1_user(self) -> None:
        self._assert_scoped(self.sess_p1, h.USER_SALES_P1, "Lead",
                            h.UNIT_P1, h.MARKER_BM)

    def test_customer_list_scoped_for_bm_user(self) -> None:
        # Customer has no company field; scoping must come via linked docs or
        # be denied. Any P1 marker in the body is a leak.
        status, body, _ = self._list(self.sess_bm, h.USER_SALES_BM, "Customer")
        self.assertIn(status, (200, 403))
        self.assertNotIn(h.CUSTOMER_P1, body.decode(errors="replace"),
                         "LEAK: BM user enumerates P1 customer by name")
        self.assertNotIn(h.MARKER_P1, body.decode(errors="replace"))

    def test_customer_list_scoped_for_p1_user(self) -> None:
        status, body, _ = self._list(self.sess_p1, h.USER_SALES_P1, "Customer")
        self.assertIn(status, (200, 403))
        self.assertNotIn(h.CUSTOMER_BM, body.decode(errors="replace"),
                         "LEAK: P1 user enumerates BM customer by name")
        self.assertNotIn(h.MARKER_BM, body.decode(errors="replace"))

    def test_quotation_list_scoped_for_bm_user(self) -> None:
        self._assert_scoped(self.sess_bm, h.USER_SALES_BM, "Quotation",
                            h.UNIT_BM, h.MARKER_P1)

    def test_quotation_list_scoped_for_p1_user(self) -> None:
        self._assert_scoped(self.sess_p1, h.USER_SALES_P1, "Quotation",
                            h.UNIT_P1, h.MARKER_BM)

    def test_list_count_does_not_leak_cross_unit(self) -> None:
        # Desk list count endpoint. A fail-closed count must not exceed the
        # authoritative own-unit count (admin-side ground truth).
        for sess, actor, own in ((self.sess_bm, h.USER_SALES_BM, h.UNIT_BM),
                                 (self.sess_p1, h.USER_SALES_P1, h.UNIT_P1)):
            status, body, elapsed = sess.post(
                "/api/method/frappe.desk.reportview.get_count",
                form={"doctype": "Lead", "filters": "[]"})
            h.record_probe(self.SURFACE, actor,
                           "POST reportview.get_count Lead",
                           "no cross-unit count leak", status, body, elapsed)
            if status == 200:
                try:
                    count = json.loads(body).get("message")
                except json.JSONDecodeError:
                    continue
                # admin-side authoritative own-unit count (same endpoint)
                _, a_body, _ = h.admin_session().post(
                    "/api/method/frappe.desk.reportview.get_count",
                    form={"doctype": "Lead",
                          "filters": json.dumps([["company", "=", own]])})
                own_count = int(json.loads(a_body).get("message"))
                self.assertLessEqual(
                    int(count), own_count,
                    f"LEAK: {actor} sees Lead count {count} > own-unit "
                    f"count {own_count}")

    def test_customer_count_does_not_inflate_cross_unit(self) -> None:
        # F-6 closure: Customer count must not leak cross-unit existence via
        # count inflation. Customer is unscopeable (no company field), so a
        # unit user observing the admin ground-truth total is a LEAK — this
        # test FAILS on pinned v16.32.1 and the failure is the evidence.
        _, a_body, _ = h.admin_session().post(
            "/api/method/frappe.desk.reportview.get_count",
            form={"doctype": "Customer", "filters": "[]"})
        admin_total = int(json.loads(a_body).get("message"))
        inflated: list[str] = []
        for sess, actor in ((self.sess_bm, h.USER_SALES_BM),
                            (self.sess_p1, h.USER_SALES_P1)):
            status, body, elapsed = sess.post(
                "/api/method/frappe.desk.reportview.get_count",
                form={"doctype": "Customer", "filters": "[]"})
            h.record_probe(self.SURFACE, actor,
                           "POST reportview.get_count Customer",
                           "no cross-unit count leak", status, body, elapsed)
            if status != 200:
                continue
            observed = int(json.loads(body).get("message"))
            if observed == admin_total and admin_total > 0:
                # Record explicit leak row for BOTH actors (NF-2 closure:
                # collect failures, assert after the loop so the P1 probe
                # is not skipped when the BM assertion fires).
                h.ProbeRecorder.instance().record(h.ProbeResult(
                    surface=self.SURFACE, actor=actor,
                    action="Customer count inflation vs admin total",
                    expected="scoped count < admin total",
                    status=status,
                    leaked_markers=[
                        f"count-inflation:{observed}==admin:{admin_total}"],
                    timing_bucket="fast",
                    detail="unit user observes unscoped Customer count"))
                inflated.append(f"{actor} sees {observed} == admin "
                                f"{admin_total}")
        self.assertFalse(
            inflated,
            "LEAK: cross-unit Customer count inflation: "
            + "; ".join(inflated))

    def test_owner_rollup_is_explicit_and_auditable(self) -> None:
        # Owner has cross-unit visibility BY DESIGN (Sales Manager +
        # no Company user permission). Assert the owner CAN see both units
        # (explicit roll-up) — this documents the accepted scope.
        status, body, elapsed = self.sess_owner.get(
            "/api/resource/Lead",
            params={"limit_page_length": "500",
                    "fields": json.dumps(["name", "company"])})
        h.record_probe(self.SURFACE, h.USER_OWNER, "GET /api/resource/Lead",
                       "explicit cross-unit roll-up", status, body, elapsed)
        self.assertEqual(status, 200)
        companies = {r.get("company") for r in json.loads(body).get("data", [])}
        self.assertIn(h.UNIT_BM, companies)
        self.assertIn(h.UNIT_P1, companies)


if __name__ == "__main__":
    unittest.main()
