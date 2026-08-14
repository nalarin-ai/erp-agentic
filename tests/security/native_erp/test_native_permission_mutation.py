"""ISO-001 probes: permission/scope-escape mutations must be denied server-side.

A unit user must not:
- mutate Company/owner on an accessible document to escape scope,
- create a User Permission for themselves,
- change their own roles.
Every attempt must be denied (403/validation) and admin read-back must
confirm nothing changed.
"""
from __future__ import annotations

import json
import unittest

from tests.security.native_erp import _harness as h


class TestNativePermissionMutation(h.IsolationProbeTestCase):
    SURFACE = "permission_mutation"

    def test_cannot_reassign_company_on_own_lead(self) -> None:
        # BM user edits a BM lead (in scope) and tries to move it to P1.
        status, body, elapsed = self.sess_bm.put(
            f"/api/resource/Lead/{self.lead_bm_name}",
            {"company": h.UNIT_P1})
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       f"PUT Lead/{self.lead_bm_name} company={h.UNIT_P1}",
                       "deny (403/validation)", status, body, elapsed)
        # Admin read-back: company must still be UNIT-BM.
        a_status, a_body = h.admin_get(
            f"/api/resource/Lead/{self.lead_bm_name}",
            params={"fields": json.dumps(["company"])})
        self.assertEqual(a_status, 200)
        company = json.loads(a_body)["data"].get("company")
        self.assertEqual(company, h.UNIT_BM,
                         f"SCOPE ESCAPE: lead moved to {company}")

    def test_cannot_create_user_permission_for_self(self) -> None:
        status, body, elapsed = self.sess_bm.post("/api/resource/User Permission", {
            "user": h.USER_SALES_BM,
            "allow": "Company",
            "for_value": h.UNIT_P1,
            "apply_to_all_doctypes": 1,
        })
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       "POST /api/resource/User Permission (self, P1)",
                       "deny", status, body, elapsed)
        self.assertIn(status, (401, 403, 417),
                      f"user permission self-grant returned {status}")
        # read-back: still only the BM permission exists
        flt = json.dumps([["user", "=", h.USER_SALES_BM],
                          ["allow", "=", "Company"]])
        _, a_body = h.admin_get("/api/resource/User Permission",
                                params={"filters": flt,
                                        "fields": json.dumps(["for_value"])})
        values = {r.get("for_value")
                  for r in json.loads(a_body).get("data", [])}
        self.assertNotIn(h.UNIT_P1, values,
                         "SCOPE ESCAPE: BM user granted themselves P1")

    def test_cannot_change_own_roles(self) -> None:
        status, body, elapsed = self.sess_bm.put(
            f"/api/resource/User/{h.USER_SALES_BM}",
            {"roles": [{"role": "System Manager"}]})
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       "PUT User/self roles=System Manager",
                       "deny", status, body, elapsed)
        _, a_body = h.admin_get(f"/api/resource/User/{h.USER_SALES_BM}",
                                params={"fields": json.dumps(["roles"])})
        roles = {r.get("role")
                 for r in json.loads(a_body)["data"].get("roles", [])}
        self.assertNotIn("System Manager", roles,
                         "SCOPE ESCAPE: BM user self-granted System Manager")

    def test_cannot_disable_own_user_permission(self) -> None:
        # Find the BM user's Company user permission and try to delete it.
        flt = json.dumps([["user", "=", h.USER_SALES_BM],
                          ["allow", "=", "Company"],
                          ["for_value", "=", h.UNIT_BM]])
        _, a_body = h.admin_get("/api/resource/User Permission",
                                params={"filters": flt,
                                        "fields": json.dumps(["name"])})
        rows = json.loads(a_body).get("data") or []
        self.assertTrue(rows, "fixture: BM user permission missing")
        up_name = rows[0]["name"]
        status, body, elapsed = self.sess_bm.request(
            "DELETE", f"/api/resource/User Permission/{up_name}")
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       f"DELETE User Permission/{up_name}",
                       "deny", status, body, elapsed)
        self.assertIn(status, (401, 403, 404, 417))
        self.assertTrue(h.admin_exists("User Permission", up_name),
                        "SCOPE ESCAPE: BM user deleted own scoping permission")

    def test_cannot_create_doc_in_other_unit(self) -> None:
        status, body, elapsed = self.sess_bm.post("/api/resource/Lead", {
            "lead_name": "ISO Escape Attempt",
            "company": h.UNIT_P1,
            "status": "Lead",
            "naming_series": "CRM-LEAD-.YYYY.-",
        })
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       "POST /api/resource/Lead company=UNIT-PR1ME",
                       "deny", status, body, elapsed)
        # If create succeeded, the doc must not be readable as P1-scoped escape:
        # verify admin-side whether a P1 lead appeared owned by BM user's attempt.
        if status in (200, 201):
            name = json.loads(body)["data"]["name"]
            _, a_body = h.admin_get(f"/api/resource/Lead/{name}",
                                    params={"fields": json.dumps(["company"])})
            company = json.loads(a_body)["data"].get("company")
            self.assertNotEqual(company, h.UNIT_P1,
                                "SCOPE ESCAPE: BM user created lead in P1")
        else:
            self.assertIn(status, (401, 403, 417))


if __name__ == "__main__":
    unittest.main()
