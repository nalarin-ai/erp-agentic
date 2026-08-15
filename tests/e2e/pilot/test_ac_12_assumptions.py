"""MVP-AC-12: assumptions documented; production blocked pending sign-off.

Criteria (TRACEABILITY_MATRIX.md section D; PILOT-001, EXP-001): the pilot
report must state its explicit assumptions and keep production BLOCKED until
a qualified EXP-001/PROD-001 sign-off exists. This is a light property guard
over the evidence document — the authoritative content lives in
``docs/evidence/pilot/ac-12.md``.

The test fails closed if the document is missing or loses any required
marker (production-blocked statement, covered-AC list, backlog findings).
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "evidence" / "pilot" / "ac-12.md"


class TestAc12AssumptionsReport(unittest.TestCase):
    def test_ac12_document_exists(self) -> None:
        self.assertTrue(DOC.is_file(),
                        f"missing evidence doc: {DOC.relative_to(REPO_ROOT)}")

    def _text(self) -> str:
        return DOC.read_text(encoding="utf-8")

    def test_production_blocked_statement_present(self) -> None:
        text = self._text().lower()
        self.assertIn("production", text)
        self.assertIn("blocked", text)
        # Must name the gate that production is waiting on.
        self.assertIn("exp-001", text)
        self.assertIn("prod-001", text)
        self.assertIn("sign-off", text.replace("sign off", "sign-off"))

    def test_covered_ac_list_present(self) -> None:
        text = self._text()
        for ac in ("MVP-AC-01", "MVP-AC-11", "MVP-AC-14", "MVP-AC-15"):
            self.assertIn(ac, text,
                          f"ac-12.md must reference covered {ac}")

    def test_backlog_findings_section_present(self) -> None:
        text = self._text().lower()
        self.assertIn("finding", text)
        # Assumptions must be explicit (fixture adapters vs live ERPNext,
        # synthetic refs, harness code-map workaround).
        self.assertIn("assumption", text)
        self.assertIn("fixture", text)
        self.assertIn("synthetic", text)

    def test_production_not_marked_approved(self) -> None:
        """Fail-closed: the document must never assert production approval
        while the sign-off gate is open."""
        text = self._text().lower()
        self.assertNotIn("production approved", text)
        self.assertNotIn("prod approved", text)


if __name__ == "__main__":
    unittest.main()
