"""ISOFIX-001 evidence matrix generator (final architecture).

Reads the raw JSONL probe log for today under
docs/evidence/isolation-final/raw/ and writes matrix.md summarizing the
latest run only (run_id grouped), mirroring the ISO-001 generator.

Run AFTER the final probe suites:
    python3 -m tests.security.isolation_final.make_matrix
"""
from __future__ import annotations

from datetime import datetime, timezone

from tests.security.isolation_final import _harness as fh
from tests.security.native_erp import _harness as h


def main() -> dict:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    jsonl = fh.RAW_DIR / f"probes-{day}.jsonl"
    if not jsonl.exists():
        raise SystemExit(f"no probe log at {jsonl}")

    summary = fh.matrix_summary_for(jsonl)
    by_surface = summary["surfaces"]

    lines = [
        "# ISOFIX-001 Final Isolation Architecture — Probe Matrix",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Target: {h.BASE_URL} (site `{h.SITE_NAME}`), "
        f"ERPNext pinned v{h.PINNED_ERPNEXT_VERSION} (gateway-only final architecture)",
        f"- Raw evidence: `raw/probes-{day}.jsonl` "
        f"({summary['total_probes']} probes, latest run)",
        "",
        "| Surface | Probes | Leak-positive probes | Denied (401/403/404) |",
        "|---|---|---|---|",
    ]
    for surface in sorted(by_surface):
        s = by_surface[surface]
        lines.append(f"| {surface} | {s['probes']} | {s['leaks']} | {s['denied']} |")

    lines += [
        "",
        f"**Leak-positive probes (latest run): {summary['leak_positive_probes']}**",
        "",
    ]
    if summary["leak_positive_probes"] == 0:
        lines.append("No leak-positive probes — every final-architecture surface clean.")

    fh.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = fh.EVIDENCE_DIR / "matrix.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote {out} ({summary['total_probes']} probes, "
        f"{summary['leak_positive_probes']} leak-positive)"
    )
    return summary


if __name__ == "__main__":
    main()
