"""ISO-001 evidence matrix generator.

Reads the raw JSONL probe log for today and writes
docs/evidence/native-isolation/matrix.md summarizing per-surface results.

Run AFTER the probe suites:
    python3 -m tests.security.native_erp.make_matrix
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

from tests.security.native_erp import _harness as h


def main() -> None:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    jsonl = h.RAW_DIR / f"probes-{day}.jsonl"
    if not jsonl.exists():
        raise SystemExit(f"no probe log at {jsonl}")
    rows = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]

    # The recorder appends per suite run within the same UTC day. The matrix
    # summarizes exactly ONE run — the most recent one — so repeated runs do
    # not inflate counts (QA F-2/F-4/F-5 closure). Rows written after the
    # F-5 fix carry an explicit `run_id`; group by it. Legacy rows without
    # `run_id` fall back to the timestamp-gap heuristic so old evidence files
    # remain readable.
    if rows:
        if any("run_id" in r for r in rows):
            # Pick the run_id of the chronologically latest row (run_id
            # prefixes are second-resolution timestamps; two recorders in
            # the same second would otherwise order by random uuid suffix).
            latest_row = max(rows, key=lambda r: r["ts"])
            latest_run = latest_row.get("run_id", "")
            rows = [r for r in rows if r.get("run_id") == latest_run]
        else:
            ts_sorted = sorted(r["ts"] for r in rows)
            cutoff = ts_sorted[-1]
            from datetime import datetime as _dt
            for prev in reversed(ts_sorted[:-1]):
                if (_dt.fromisoformat(cutoff) - _dt.fromisoformat(prev)).total_seconds() > 120:
                    break
                cutoff = prev
            rows = [r for r in rows if r["ts"] >= cutoff]

    by_surface: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    leaks = [r for r in rows if r["leaked"]]
    for r in rows:
        by_surface[r["surface"]]["probes"] += 1
        if r["leaked"]:
            by_surface[r["surface"]]["leak_probes"] += 1
        if r["status"] in (401, 403, 404):
            by_surface[r["surface"]]["denied"] += 1

    lines = [
        "# ISO-001 Native ERP Isolation — Probe Matrix",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Target: {h.BASE_URL} (site `{h.SITE_NAME}`), "
        f"ERPNext pinned v{h.PINNED_ERPNEXT_VERSION}",
        f"- Raw evidence: `raw/probes-{day}.jsonl` ({len(rows)} probes, latest run)",
        "",
        "| Surface | Probes | Leak-positive probes | Denied (401/403/404) |",
        "|---|---|---|---|",
    ]
    for surface in sorted(by_surface):
        s = by_surface[surface]
        lines.append(
            f"| {surface} | {s['probes']} | {s['leak_probes']} | {s['denied']} |")

    lines += [
        "",
        "## Leak-positive probes (markers observed in response bodies)",
        "",
        "| Surface | Actor | Action | Status | Markers |",
        "|---|---|---|---|---|",
    ]
    for r in leaks:
        lines.append(
            f"| {r['surface']} | {r['actor']} | {r['action']} | "
            f"{r['status']} | {', '.join(r['leaked_markers'])} |")
    if not leaks:
        lines.append("| — | — | — | — | — |")

    h.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = h.EVIDENCE_DIR / "matrix.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(rows)} probes, {len(leaks)} leak-positive)")


if __name__ == "__main__":
    main()
