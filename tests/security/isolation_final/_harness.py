"""ISOFIX-001 requalification harness (live, gateway-only final architecture).

Reuses ISO-001 primitives (per-user sessions, marker seeding, probe JSONL
recording) but targets the FINAL architecture and records to
docs/evidence/isolation-final/raw/ with `final-` prefixed surfaces so the
ISOLATION_FINAL matrix is generated from a disjoint run boundary.

New final-architecture probes:
- unit-scoped users no longer hold native credentials (user disable
  migration); direct desk/API/files/reports access is DENIED;
- gateway surfaces (CRM port, ERP port) still function and enforce scope
  fail-closed (no cross-unit markers, cross-unit refs denied);
- existence-oracle classes from ISO-001 (403/404 split, File metadata
  enumeration, Customer unscoped enumeration) are CLOSED BY CONSTRUCTION:
  there are no unit-scoped native credentials to probe with.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.security.native_erp import _harness as base

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence" / "isolation-final"
RAW_DIR = EVIDENCE_DIR / "raw"


class FinalProbeRecorder(base.ProbeRecorder):
    """Probe recorder writing to the isolation-final evidence directory."""

    _final_instance: "FinalProbeRecorder | None" = None

    def __init__(self) -> None:
        super().__init__()
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        day = base.datetime.now(base.timezone.utc).strftime("%Y%m%d")
        self.jsonl_path = RAW_DIR / f"probes-{day}.jsonl"

    @classmethod
    def instance(cls) -> "FinalProbeRecorder":
        if cls._final_instance is None:
            cls._final_instance = cls()
        return cls._final_instance


def record_probe(
    surface: str,
    actor: str,
    action: str,
    expected: str,
    status: int | None,
    body: bytes | str = b"",
    *,
    tokens: tuple[str, ...] | list[str] | None = None,
    detail: str = "",
    elapsed_s: float = 0.0,
) -> base.ProbeResult:
    """Record one final-architecture probe row (run_id stamped)."""
    result = base.ProbeResult(
        surface=surface,
        actor=actor,
        action=action,
        expected=expected,
        status=status,
        leaked_markers=base.scan_markers(body, tokens=tokens),
        timing_bucket=base._timing_bucket(elapsed_s),
        detail=detail,
    )
    FinalProbeRecorder.instance().record(result)
    return result


def matrix_summary_for(latest_jsonl: Path) -> dict[str, Any]:
    """Summarize the latest run in a final-architecture JSONL evidence file."""
    rows = [
        json.loads(line)
        for line in latest_jsonl.read_text().splitlines()
        if line.strip()
    ]
    if rows and any("run_id" in r for r in rows):
        latest_run = max(rows, key=lambda r: r["ts"]).get("run_id", "")
        rows = [r for r in rows if r.get("run_id") == latest_run]
    leaks = [r for r in rows if r.get("leaked")]
    by_surface: dict[str, dict[str, int]] = {}
    for r in rows:
        s = by_surface.setdefault(r["surface"], {"probes": 0, "leaks": 0, "denied": 0})
        s["probes"] += 1
        if r.get("leaked"):
            s["leaks"] += 1
        if r.get("status") in (401, 403, 404):
            s["denied"] += 1
    return {
        "total_probes": len(rows),
        "leak_positive_probes": len(leaks),
        "surfaces": by_surface,
    }
