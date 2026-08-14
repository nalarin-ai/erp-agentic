"""Generic safe import contract tests (MIG-001).

R-005/R-008: hostile/synthetic CSV inputs must be quarantined, size/row/
decompression-limited, formula-neutralized, deduplicated, and dry-run with
zero provider writes. Synthetic opaque refs only.
"""
from __future__ import annotations

import io
import unittest
import zipfile

from src.imports.csv_import import (
    ImportRejected,
    ImportSummary,
    SafeCsvImporter,
)


def _csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    for row in rows:
        buf.write(",".join(row) + "\n")
    return buf.getvalue().encode("utf-8")


class SafeCsvImporterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.importer = SafeCsvImporter(max_bytes=4096, max_rows=100)

    # -- happy path ------------------------------------------------------------

    def test_valid_csv_dry_run_produces_summary_without_writes(self) -> None:
        data = _csv([
            ["invoice_ref", "customer_ref", "amount", "currency"],
            ["DRAFT-001", "CUST-ALPHA", "1000000", "IDR"],
            ["DRAFT-002", "CUST-BETA", "250000", "IDR"],
        ])
        summary = self.importer.dry_run(data)
        self.assertIsInstance(summary, ImportSummary)
        self.assertEqual(summary.accepted_rows, 2)
        self.assertEqual(summary.rejected_rows, 0)
        self.assertEqual(summary.provider_writes, 0)

    # -- size / row / decompression limits --------------------------------------

    def test_oversize_payload_rejected(self) -> None:
        data = b"x" * 5000
        with self.assertRaises(ImportRejected):
            self.importer.dry_run(data)

    def test_too_many_rows_rejected(self) -> None:
        rows = [["a", "b", "c", "d"]] * 150
        with self.assertRaises(ImportRejected):
            self.importer.dry_run(_csv(rows))

    def test_zip_bomb_rejected_by_ratio(self) -> None:
        # highly compressible payload inside a real zip container
        payload = b"A" * 1_000_000
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("data.csv", payload)
        with self.assertRaises(ImportRejected):
            self.importer.dry_run(buf.getvalue())

    def test_path_traversal_header_rejected(self) -> None:
        data = _csv([["../etc/passwd", "b", "c", "d"], ["1", "2", "3", "4"]])
        with self.assertRaises(ImportRejected):
            self.importer.dry_run(data)

    # -- formula neutralization -------------------------------------------------

    def test_formula_cells_are_neutralized_not_executed(self) -> None:
        data = _csv([
            ["invoice_ref", "customer_ref", "amount", "currency"],
            ["=CMD|' /C calc'!A0", "CUST-ALPHA", "1000000", "IDR"],
            ["+1+1", "CUST-BETA", "100", "IDR"],
        ])
        summary = self.importer.dry_run(data)
        self.assertEqual(summary.accepted_rows, 2)
        self.assertTrue(all(not cell.startswith(("=", "+", "-", "@"))
                            for row in summary.preview for cell in row))

    # MIG-QA-01: whitespace-prefixed formulas must be neutralized too.
    def test_whitespace_prefixed_formula_is_neutralized(self) -> None:
        data = _csv([
            ["invoice_ref", "customer_ref", "amount", "currency"],
            ["  =CMD|' /C calc'!A0", "CUST-ALPHA", "1000000", "IDR"],
        ])
        summary = self.importer.dry_run(data)
        self.assertEqual(summary.accepted_rows, 1)
        cell = summary.preview[0][0]
        self.assertFalse(cell.lstrip().startswith("="), f"formula survived: {cell!r}")

    # MIG-QA-02: zip entry filenames are traversal-checked before unpacking.
    def test_zip_entry_filename_traversal_rejected(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.csv", "a,b,c,d\n1,2,3,4\n")
        with self.assertRaises(ImportRejected):
            self.importer.dry_run(buf.getvalue())

    # -- dedupe -----------------------------------------------------------------

    def test_duplicate_invoice_refs_deduped(self) -> None:
        data = _csv([
            ["invoice_ref", "customer_ref", "amount", "currency"],
            ["DRAFT-001", "CUST-ALPHA", "1000000", "IDR"],
            ["DRAFT-001", "CUST-ALPHA", "1000000", "IDR"],
        ])
        summary = self.importer.dry_run(data)
        self.assertEqual(summary.accepted_rows, 1)
        self.assertEqual(summary.duplicate_rows, 1)

    # -- redacted errors ----------------------------------------------------------

    def test_rejected_rows_do_not_leak_raw_cell_values(self) -> None:
        data = _csv([
            ["invoice_ref", "customer_ref", "amount", "currency"],
            ["DRAFT-001", "CUST-ALPHA", "not-a-number", "IDR"],
        ])
        summary = self.importer.dry_run(data)
        self.assertEqual(summary.rejected_rows, 1)
        joined = " ".join(str(err) for err in summary.errors)
        self.assertNotIn("not-a-number", joined)

    # -- zero-write guarantee -----------------------------------------------------

    def test_dry_run_performs_no_provider_calls(self) -> None:
        data = _csv([
            ["invoice_ref", "customer_ref", "amount", "currency"],
            ["DRAFT-001", "CUST-ALPHA", "1000000", "IDR"],
        ])
        summary = self.importer.dry_run(data)
        self.assertEqual(summary.provider_writes, 0)
        self.assertEqual(summary.quarantined, 0)

    # -- hostile format coverage -----------------------------------------------------

    def test_xlsx_magic_bytes_rejected_fail_closed(self) -> None:
        # XLSX is a zip container; with an .xlsx-style multi-entry structure it
        # must be rejected (no sandboxed XLSX parser in this lane).
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", "<xml/>")
            zf.writestr("xl/worksheets/sheet1.xml", "<xml/>")
        with self.assertRaises(ImportRejected):
            self.importer.dry_run(buf.getvalue())

    def test_encrypted_zip_rejected(self) -> None:
        # A zip we cannot read must fail closed, never partially parse.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data.csv", "a,b,c,d\n1,2,3,4\n")
        raw = bytearray(buf.getvalue())
        # corrupt the central directory to simulate an unreadable/encrypted blob
        raw[:4] = b"PK\x05\x06"
        with self.assertRaises(Exception):
            self.importer.dry_run(bytes(raw))

    def test_utf8_decode_error_fails_closed(self) -> None:
        with self.assertRaises(ImportRejected):
            self.importer.dry_run(b"\xff\xfe\x00invalid")

    # -- batch / reconciliation / reversal contract -----------------------------------

    def test_committed_batch_is_bounded_and_reconciled(self) -> None:
        from src.imports.batch import BatchResult
        data = _csv([
            ["invoice_ref", "customer_ref", "amount", "currency"],
            ["DRAFT-001", "CUST-ALPHA", "1000000", "IDR"],
            ["DRAFT-002", "CUST-BETA", "250000", "IDR"],
        ])
        result: BatchResult = self.importer.commit_batch(data)
        self.assertEqual(result.posted, 2)
        self.assertEqual(result.reconciled, 2)
        self.assertEqual(result.provider_writes, 2)  # real commit path counts writes
        self.assertEqual(result.unreconciled_refs, ())

    def test_commit_batch_reversal_is_compensating_not_destructive(self) -> None:
        data = _csv([
            ["invoice_ref", "customer_ref", "amount", "currency"],
            ["DRAFT-001", "CUST-ALPHA", "1000000", "IDR"],
        ])
        result = self.importer.commit_batch(data)
        reversal = self.importer.reverse_batch(result.batch_ref)
        self.assertTrue(reversal.compensating)
        self.assertFalse(reversal.destructive)
        self.assertEqual(reversal.reversed_count, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
