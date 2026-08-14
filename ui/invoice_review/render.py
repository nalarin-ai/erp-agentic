"""Plain-text renderer for the finance review view-model."""
from __future__ import annotations

from ui.invoice_review.view import InvoiceReviewView


def render_text(view: InvoiceReviewView) -> str:
    """Render review screen as plain text; no new data introduced."""
    if type(view) is not InvoiceReviewView:
        raise TypeError("view must be InvoiceReviewView")

    lines: list[str] = []
    lines.append("Review Invoice")
    lines.append(f"Status: {view.state}")
    lines.append(f"Unit: {view.unit_display_name} ({view.unit_ref})")
    lines.append(f"Jenis: {view.invoice_type}")
    lines.append(f"Referensi: {view.reference}")
    lines.append("")
    lines.append("Branding:")
    lines.append(f"  Template: {view.branding_block['template_ref']}")
    lines.append(f"  Logo: {view.branding_block['logo_asset_ref']}")
    lines.append(f"  Versi konfigurasi: {view.branding_block['configuration_version']}")
    lines.append("")
    if view.layout_mode == "compact":
        lines.append("[Kartu] Pelanggan dan item")
    else:
        lines.append("Pelanggan dan item")
    lines.append(f"  Pelanggan: {view.customer_display}")
    for item in view.line_items:
        lines.append(
            f"  - {item['description']}: {item['quantity']} x {item['unit_price_amount']} {item['currency']}"
        )
    lines.append(f"  Total: {view.total_amount} {view.currency}")
    lines.append(f"  Jatuh tempo: {view.due_on}")
    lines.append("")
    lines.append("Kebijakan:")
    lines.append(f"  PPN: {view.policy_card['ppn_state']}")
    lines.append(f"  Penerbit: {view.policy_card['issuer_ref']}")
    lines.append(f"  Seri: {view.policy_card['invoice_series_ref']}")
    lines.append(f"  Ledger: {view.policy_card['receivable_ledger_ref']}")
    lines.append(f"  Rekening tujuan: {view.policy_card['destination_account_alias']}")
    lines.append("")
    lines.append("Audit:")
    lines.append(f"  Peminta: {view.audit['requester_alias']}")
    lines.append(f"  Sumber: {view.audit['source_channel']}")
    lines.append(f"  Dibuat: {view.audit['created_at']}")
    lines.append(f"  Diubah: {view.audit['updated_at']}")
    lines.append("")
    lines.append("Tindakan:")
    for action in view.footer_actions:
        lines.append(f"  - {action}")
    return "\n".join(lines)
