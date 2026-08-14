"""Plain-text renderer for the receivables view-model."""
from __future__ import annotations

from ui.receivables.view import ReceivablesView


def render_text(view: ReceivablesView) -> str:
    """Render receivables screen as plain text; no new data introduced."""
    if type(view) is not ReceivablesView:
        raise TypeError("view must be ReceivablesView")

    lines: list[str] = []
    lines.append("Piutang")
    lines.append(f"Status: {view.state}")
    if view.state == "EMPTY":
        lines.append(f"  {view.empty_message}")
        return "\n".join(lines)

    lines.append("Filter:")
    for name, spec in view.filters.items():
        default = spec.get("default") or "-"
        locked = " (terkunci)" if spec.get("locked") else ""
        lines.append(f"  {name}: {default}{locked}")
    lines.append("")

    if view.layout_mode == "compact":
        lines.append("[Kartu] Daftar piutang")
    else:
        lines.append("Daftar piutang")
    for row in view.rows:
        lines.append(f"  {row['invoice_ref']} | {row['customer_display']} | {row['unit_ref']}")
        lines.append(
            f"    Jatuh tempo: {row['due_on']} | Sisa: {row['open_amount']} {row['currency']} | "
            f"{row['status_label']} ({row['status_tone']})"
        )
        lines.append(f"    Tindakan: {', '.join(row['allowed_actions'])}")
    lines.append("")
    lines.append(f"Total sisa piutang: {view.total_open_amount} {view.currency or ''}")
    return "\n".join(lines)
