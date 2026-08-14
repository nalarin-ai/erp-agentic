"""ISO-001 probes: reports, query-report exports, print/PDF surfaces.

Cross-unit rows must be absent from standard reports and exports. Export of
zero rows is fine; export of cross-unit rows is a FAIL (leak evidence).
"""
from __future__ import annotations

import json
import unittest

from tests.security.native_erp import _harness as h


class TestNativeReportExport(h.IsolationProbeTestCase):
    SURFACE = "report_export"

    def test_query_report_lead_scoped(self) -> None:
        # Standard ERPNext "Lead Details" report; if the report name differs
        # in v16, a 4xx for missing report is recorded and asserted denied.
        status, body, elapsed = self.sess_bm.post(
            "/api/method/frappe.desk.query_report.run",
            data={"report_name": "Lead Details", "filters": {},
                  "ignore_prepared_report": 1})
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       "query_report.run Lead Details",
                       "no cross-unit rows", status, body, elapsed)
        if status == 200:
            text = body.decode(errors="replace")
            self.assertNotIn(h.MARKER_P1, text)
            self.assertNotIn(self.lead_p1_name or "", text)

    def test_reportview_export_csv_scoped(self) -> None:
        # Desk list "Export" path for reportview.
        status, body, elapsed = self.sess_bm.post(
            "/api/method/frappe.desk.reportview.export_query",
            form={"doctype": "Lead", "file_format_type": "CSV",
                  "fields": json.dumps([["name", "Lead"], ["company", "Lead"]]),
                  "filters": "[]", "visible_columns": "[]"})
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       "reportview.export_query Lead CSV",
                       "no cross-unit rows", status, body, elapsed)
        if status == 200:
            text = body.decode(errors="replace")
            self.assertNotIn(h.MARKER_P1, text)
            self.assertNotIn(self.lead_p1_name or "", text)

    def test_print_pdf_cross_unit_denied(self) -> None:
        # Print/PDF of the cross-unit quotation must not render for BM user.
        path = (f"/api/method/frappe.utils.print_format.download_pdf"
                f"?doctype=Quotation&name={self.qtn_p1_name}&format=Standard")
        status, body, elapsed = self.sess_bm.get(path)
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       f"download_pdf Quotation {self.qtn_p1_name}",
                       "deny/no-leak", status, body, elapsed)
        text = body.decode(errors="replace")
        self.assertNotIn(h.MARKER_P1, text,
                         "LEAK: cross-unit quotation printable as PDF")
        self.assertNotIn(h.CUSTOMER_P1, text)

    def test_printview_page_no_disclosure(self) -> None:
        status, body, elapsed = self.sess_bm.get(
            f"/printview?doctype=Quotation&name={self.qtn_p1_name}"
            f"&format=Standard&no_letterhead=1")
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       f"printview Quotation {self.qtn_p1_name}",
                       "deny/no-leak", status, body, elapsed)
        self.assertNotIn(h.MARKER_P1, body.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
