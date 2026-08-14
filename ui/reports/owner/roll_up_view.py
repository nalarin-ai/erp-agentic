"""View-model + renderer for the owner financial roll-up (RPT-001).

This repo has no web framework in the UI layer; ``ui/`` modules are pure
functions that turn a service result into a redacted view-model or a
plain-text rendering. No provider internals, no credentials, no cross-unit
data: everything here is derived from ``OwnerRollupResult``, which is
already authorized and scoped server-side.

Invariants:
- Opaque refs only (UNIT-*, INV-*, etc.).
- Per-unit breakdown + owner total; per-currency rows preserved.
- As-of timestamps are surfaced so reviewers can see staleness.
- When currencies are mixed, the owner-level total is rendered as an
  em-dash placeholder — never silently summed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.reports.owner.roll_up import OwnerRollupResult


# ---------------------------------------------------------------------------
# View-model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OwnerRollupView:
    """Redacted view-model for one owner roll-up rendering."""

    as_of: str
    currency: str | None
    owner_open_amount_total: str | None
    scoped: bool
    rows: tuple[dict[str, Any], ...]  # per-unit rows


def build_view(result: OwnerRollupResult) -> OwnerRollupView:
    """Project an authorized roll-up result into a redacted view-model."""
    if type(result) is not OwnerRollupResult:
        raise TypeError("result must be OwnerRollupResult")
    rows: list[dict[str, Any]] = []
    for unit in result.per_unit:
        rows.append(
            {
                "unit_ref": unit.unit_ref,
                "open_amount_total": unit.open_amount_total,
                "currency": unit.currency,
                "open_invoice_count": unit.open_invoice_count,
                "invoice_refs": list(unit.invoice_refs),
                "as_of": unit.as_of,
                "per_currency": [
                    {
                        "currency": c.currency,
                        "open_amount_total": c.open_amount_total,
                        "open_invoice_count": c.open_invoice_count,
                    }
                    for c in unit.per_currency
                ],
            }
        )
    return OwnerRollupView(
        as_of=result.as_of,
        currency=result.currency,
        owner_open_amount_total=result.owner_open_amount_total,
        scoped=result.scoped,
        rows=tuple(rows),
    )


# ---------------------------------------------------------------------------
# Plain-text renderer (CLI / log-friendly)
# ---------------------------------------------------------------------------


def render_text(view: OwnerRollupView) -> str:
    """Render the view-model as plain text.

    The renderer must not introduce data that isn't already in the view;
    it's purely presentational. Cross-currency totals are rendered as a
    placeholder line per currency — never silently summed.
    """
    if type(view) is not OwnerRollupView:
        raise TypeError("view must be OwnerRollupView")

    lines: list[str] = []
    lines.append("Owner financial roll-up")
    lines.append(f"As of: {view.as_of}")
    lines.append(f"Scoped: {'yes' if view.scoped else 'no'}")
    if view.currency is not None:
        lines.append(f"Currency: {view.currency}")
    else:
        lines.append("Currency: (mixed)")
    lines.append("")
    lines.append("Per-unit:")
    if not view.rows:
        lines.append("  (no authorized units)")
    for row in view.rows:
        lines.append(
            f"  - {row['unit_ref']}: open={row['open_amount_total']} "
            f"{row['currency'] or ''} ({row['open_invoice_count']} open) "
            f"as_of={row['as_of']}"
        )
        for c in row["per_currency"]:
            lines.append(
                f"      {c['currency']}: {c['open_amount_total']} "
                f"({c['open_invoice_count']} invoices)"
            )
    lines.append("")
    if view.owner_open_amount_total is not None:
        lines.append(
            f"Owner total: {view.owner_open_amount_total} {view.currency or ''}"
        )
    else:
        lines.append("Owner total: (mixed currencies — see per-currency rows)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON-safe export (opaque refs only)
# ---------------------------------------------------------------------------


def to_export_dict(view: OwnerRollupView) -> dict[str, Any]:
    """JSON-serializable export of the view-model.

    Redaction is already inherited from ``OwnerRollupResult``: the service
    never populates fields it isn't authorized to disclose. This export
    therefore contains only opaque refs, canonical decimals, and timestamps.
    """
    if type(view) is not OwnerRollupView:
        raise TypeError("view must be OwnerRollupView")
    return {
        "as_of": view.as_of,
        "currency": view.currency,
        "owner_open_amount_total": view.owner_open_amount_total,
        "scoped": view.scoped,
        "per_unit": [
            {
                "unit_ref": row["unit_ref"],
                "open_amount_total": row["open_amount_total"],
                "currency": row["currency"],
                "open_invoice_count": row["open_invoice_count"],
                "invoice_refs": list(row["invoice_refs"]),
                "as_of": row["as_of"],
                "per_currency": [dict(c) for c in row["per_currency"]],
            }
            for row in view.rows
        ],
    }
