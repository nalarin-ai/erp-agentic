"""ISO-001 probes: private attachments / files.

A private file attached to another unit's Lead must not be downloadable by
a cross-unit user: direct URL → 403/404, no bytes, and the File document
itself must not be readable.
"""
from __future__ import annotations

import json
import unittest

from tests.security.native_erp import _harness as h


class TestNativeAttachmentFile(h.IsolationProbeTestCase):
    SURFACE = "attachment_file"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        flt = json.dumps([["file_name", "=", h.ATTACHMENT_NAME],
                          ["attached_to_doctype", "=", "Lead"]])
        status, body = h.admin_get(
            "/api/resource/File",
            params={"filters": flt,
                    "fields": json.dumps(["name", "file_url"])})
        data = json.loads(body).get("data") or []
        if not data:
            raise RuntimeError("attachment fixture missing")
        cls.file_doc = data[0]

    def test_private_file_direct_url_denied_cross_unit(self) -> None:
        url = self.file_doc["file_url"]  # /private/files/iso-private-bm-001.txt
        status, body, elapsed = self.sess_p1.get(url)
        h.record_probe(self.SURFACE, h.USER_SALES_P1,
                       f"GET {url} (cross-unit)", "403/404 no bytes",
                       status, body, elapsed)
        self.assertIn(status, (403, 404),
                      f"cross-unit private file returned {status}")
        self.assertNotIn(h.MARKER_BM.encode(), body,
                         "LEAK: cross-unit user downloaded private file bytes")

    def test_private_file_direct_url_allowed_in_unit(self) -> None:
        url = self.file_doc["file_url"]
        status, body, elapsed = self.sess_bm.get(url)
        h.record_probe(self.SURFACE, h.USER_SALES_BM,
                       f"GET {url} (in-unit)", "200 own-unit file",
                       status, body, elapsed)
        self.assertEqual(status, 200)
        # Content was seeded base64-encoded; Frappe stores and serves the
        # decoded bytes for text content. Accept either form.
        self.assertTrue(
            h.MARKER_BM.encode() in body or
            h.MARKER_BM.encode() in __import__("base64").b64decode(body),
            "in-unit user cannot read own private file")

    def test_file_doc_read_denied_cross_unit(self) -> None:
        status, body, elapsed = self.sess_p1.get(
            f"/api/resource/File/{self.file_doc['name']}")
        h.record_probe(self.SURFACE, h.USER_SALES_P1,
                       f"GET /api/resource/File/{self.file_doc['name']}",
                       "deny/no-leak", status, body, elapsed)
        self.assertIn(status, (403, 404))
        self.assertNotIn(h.MARKER_BM, body.decode(errors="replace"))

    def test_file_list_no_cross_unit_attachment(self) -> None:
        status, body, elapsed = self.sess_p1.get(
            "/api/resource/File",
            params={"filters": json.dumps(
                        [["attached_to_doctype", "=", "Lead"]]),
                    "fields": json.dumps(["name", "file_name",
                                          "attached_to_name"])})
        h.record_probe(self.SURFACE, h.USER_SALES_P1,
                       "GET /api/resource/File (lead attachments)",
                       "no cross-unit rows", status, body, elapsed)
        if status == 200:
            text = body.decode(errors="replace")
            self.assertNotIn(h.ATTACHMENT_NAME, text,
                             "LEAK: P1 user enumerates BM lead attachment")


if __name__ == "__main__":
    unittest.main()
