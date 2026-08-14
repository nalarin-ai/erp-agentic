"""ISO-001 probes: global search / autocomplete / link fields.

A unit user must not infer cross-unit customer existence via autocomplete
results, error text, or response-shape differences beyond the accepted
threat model. We compare the result SET for an existing cross-unit marker
query vs a random nonexistent query: they must be indistinguishable.
"""
from __future__ import annotations

import json
import unittest

from tests.security.native_erp import _harness as h

SEARCH_ENDPOINT = "/api/method/frappe.desk.search.search_link"
NONEXISTENT = "ISO-NOPE-9z8y7x6w"


class TestNativeSearchAutocomplete(h.IsolationProbeTestCase):
    SURFACE = "search_autocomplete"

    def _search(self, sess: h.UserSession, actor: str, doctype: str,
                txt: str) -> tuple[int, list, float]:
        status, body, elapsed = sess.post(SEARCH_ENDPOINT, form={
            "doctype": doctype, "txt": txt, "page_length": "20"})
        h.record_probe(self.SURFACE, actor,
                       f"search_link {doctype} txt={txt!r}",
                       "no cross-unit results", status, body, elapsed)
        results = []
        if status == 200:
            try:
                results = json.loads(body).get("results") or []
            except json.JSONDecodeError:
                results = []
        return status, results, elapsed

    def _names(self, results: list) -> set:
        return {r.get("value") for r in results if isinstance(r, dict)}

    def test_lead_link_field_no_cross_unit(self) -> None:
        _, results, _ = self._search(self.sess_bm, h.USER_SALES_BM,
                                     "Lead", "ISO Synth")
        self.assertNotIn(self.lead_p1_name, self._names(results),
                         "LEAK: BM user autocompletes P1 lead")

    def test_customer_link_field_no_cross_unit(self) -> None:
        _, results, _ = self._search(self.sess_bm, h.USER_SALES_BM,
                                     "Customer", "ISO-CUST")
        names = self._names(results)
        self.assertNotIn(h.CUSTOMER_P1, names,
                         "LEAK: BM user autocompletes P1 customer")

    def test_customer_link_field_no_cross_unit_reverse(self) -> None:
        _, results, _ = self._search(self.sess_p1, h.USER_SALES_P1,
                                     "Customer", "ISO-CUST")
        names = self._names(results)
        self.assertNotIn(h.CUSTOMER_BM, names,
                         "LEAK: P1 user autocompletes BM customer")

    def test_existence_oracle_existing_vs_nonexistent(self) -> None:
        # Querying the exact cross-unit customer name must return the same
        # empty result set as a random nonexistent name (no confirmation).
        _, existing, _ = self._search(self.sess_bm, h.USER_SALES_BM,
                                      "Customer", h.CUSTOMER_P1)
        _, nonexistent, _ = self._search(self.sess_bm, h.USER_SALES_BM,
                                         "Customer", NONEXISTENT)
        self.assertEqual(
            self._names(existing), self._names(nonexistent),
            "existence oracle: autocomplete confirms cross-unit customer")

    def test_quotation_link_field_no_cross_unit(self) -> None:
        _, results, _ = self._search(self.sess_bm, h.USER_SALES_BM,
                                     "Quotation", "SAL-QTN")
        names = self._names(results)
        self.assertNotIn(self.qtn_p1_name, names,
                         "LEAK: BM user autocompletes P1 quotation")

    def test_global_search_no_cross_unit(self) -> None:
        # Desk global search (awesome bar) — if enabled it must be scoped.
        status, body, elapsed = self.sess_bm.get(
            "/api/method/frappe.utils.global_search.search",
            params={"text": "ISOMARKER-P1"})
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       "global_search text=ISOMARKER-P1",
                       "no cross-unit results", status, body, elapsed)
        if status == 200:
            self.assertNotIn(h.MARKER_P1, body.decode(errors="replace"))
            self.assertNotIn(self.lead_p1_name or "", body.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
