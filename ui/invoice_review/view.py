"""View-model builders for the finance review screen (UX_SPEC §2).

Pure functions: no I/O, no DOM, no framework. Produces redacted,
JSON-serializable view-models from authorized service results.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


# ---------------------------------------------------------------------------
# View-models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PostConfirmationView:
    heading: str
    warning: str
    effects: tuple[str, ...]
    focus_enter: str
    focus_contained: bool
    focus_return: str
    trigger_label: str


@dataclass(frozen=True, slots=True)
class PostResultView:
    state: str
    message: str
    official_ref: str | None
    recoverable_action: str | None
    reconciliation_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ErrorStateView:
    error_summary: str
    error_links: tuple[str, ...]
    context_preserved: dict[str, Any]
    recoverable_action: str


@dataclass(frozen=True, slots=True)
class DeniedView:
    message: str
    escalation_path: str
    unit_ref: str | None = None
    customer_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AccessibilityContract:
    tab_order: tuple[str, ...]
    focus_visible: bool
    control_roles: dict[str, str]
    accessible_names: dict[str, str]
    error_summary_position: str
    error_links_to_fields: bool
    live_region_polite: bool
    reduced_motion_disables_transitions: bool
    touch_target_min_px: int


@dataclass(frozen=True, slots=True)
class InvoiceReviewView:
    state: str
    unit_ref: str
    unit_display_name: str
    issuer_ref: str
    invoice_type: str
    reference: str
    branding_block: dict[str, Any]
    customer_display: str
    line_items: tuple[dict[str, Any], ...]
    total_amount: str
    currency: str
    due_on: str
    policy_card: dict[str, Any]
    audit: dict[str, Any]
    footer_actions: tuple[str, ...]
    layout_mode: str = "wide"
    table_representation: str = "columns"
    horizontal_overflow: bool = False


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_view(
    preview: dict[str, Any],
    *,
    actor_roles: tuple[str, ...],
    actor_ref: str,
    opener_ref: str,
) -> InvoiceReviewView:
    """Project an authorized draft preview into a review view-model.

    SoD self-post guard is fail-closed (F-03): ``opener_ref`` MUST come from
    the authorized service result, never derived from mutable ``audit_events``.
    POST_INVOICE is offered only when the actor is FINANCE-POSTER and is not
    the draft opener.
    """
    if type(preview) is not dict:
        raise TypeError("preview must be a dict")

    actions: list[str] = []
    if "FINANCE-REVIEWER" in actor_roles:
        actions.append("RETURN_FOR_CORRECTION")
    if "FINANCE-POSTER" in actor_roles and actor_ref != opener_ref:
        actions.append("POST_INVOICE")
    actions.append("CANCEL")

    return InvoiceReviewView(
        state="REVIEW",
        unit_ref=preview["unit_ref"],
        unit_display_name=preview["unit_display_name"],
        issuer_ref=preview["legal_issuer_ref"],
        invoice_type="INVOICE",
        reference=preview["draft_id"],
        branding_block={
            "template_ref": preview["invoice_template_ref"],
            "logo_asset_ref": preview["logo_asset_ref"],
            "configuration_version": preview["configuration_version"],
        },
        customer_display=preview["customer_display"],
        line_items=tuple(preview["lines"]),
        total_amount=preview["total_amount"],
        currency=preview["currency"],
        due_on=preview["due_on"],
        policy_card={
            "ppn_state": "PPN" if preview["tax_profile_ref"] else "NON-PPN",
            "issuer_ref": preview["legal_issuer_ref"],
            "tax_profile_ref": preview["tax_profile_ref"],
            "invoice_series_ref": preview["invoice_series_ref"],
            "receivable_ledger_ref": preview["receivable_ledger_ref"],
            "destination_account_alias": preview["destination_account_alias"],
            "validation_results": ("draft_lines_valid", "identity_resolved"),
        },
        audit={
            "requester_alias": preview["requester_alias"],
            "source_channel": preview["source_channel"],
            "created_at": preview["created_at"],
            "updated_at": preview["updated_at"],
            "events": tuple(preview["audit_events"]),
        },
        footer_actions=tuple(actions),
    )


def build_post_confirmation(view: InvoiceReviewView) -> PostConfirmationView:
    """Confirmation dialog before the irreversible post (§2 Safety)."""
    if type(view) is not InvoiceReviewView:
        raise TypeError("view must be InvoiceReviewView")
    return PostConfirmationView(
        heading="Konfirmasi posting invoice",
        warning="Periksa penerbit dan rekening. Setelah diposting, nomor resmi dan jurnal dibuat oleh ERP.",
        effects=("official_number", "ledger_posting", "tax_issuer", "destination_account"),
        focus_enter="heading",
        focus_contained=True,
        focus_return="trigger",
        trigger_label="Posting invoice",
    )


def build_post_result(
    view: InvoiceReviewView,
    *,
    outcome: str,
    verified: bool,
    official_ref: str | None,
    reason: str | None = None,
    reconciliation_ref: str | None = None,
) -> PostResultView:
    """Truthful post result states (§1.5)."""
    if type(view) is not InvoiceReviewView:
        raise TypeError("view must be InvoiceReviewView")
    if outcome == "POSTED" and verified and official_ref:
        return PostResultView(
            state="posted and verified",
            message=f"Invoice berhasil diposting dan diverifikasi di ERP. Referensi: {official_ref}",
            official_ref=official_ref,
            recoverable_action=None,
        )
    if outcome == "REJECTED":
        return PostResultView(
            state="failed without mutation",
            # Sanitized (F-01): raw service/exception detail is never shown.
            message="Invoice gagal diposting. Tidak ada perubahan yang disimpan.",
            official_ref=None,
            recoverable_action="Perbaiki dan coba lagi",
        )
    # UNCERTAIN or POSTED without read-back verification
    if outcome == "UNCERTAIN":
        uncertain_message = (
            "ERP mungkin telah menerima transaksi, tetapi hasil belum dapat diverifikasi. "
            "Jangan ulangi. Rekonsiliasi sedang diperlukan."
        )
        if reconciliation_ref:
            uncertain_message += f" Referensi rekonsiliasi: {reconciliation_ref}."
        return PostResultView(
            state="reconciliation required",
            message=uncertain_message,
            official_ref=None,
            recoverable_action="Hubungi finance untuk rekonsiliasi",
            reconciliation_ref=reconciliation_ref,
        )
    return PostResultView(
        state="processing",
        message="Posting sedang diproses. Menunggu verifikasi dari ERP.",
        official_ref=None,
        recoverable_action=None,
        reconciliation_ref=None,
    )


def build_error_state(
    view: InvoiceReviewView,
    *,
    error_code: str,
    recoverable_action: str,
) -> ErrorStateView:
    """Error state preserves review context and identifies next action (§2)."""
    if type(view) is not InvoiceReviewView:
        raise TypeError("view must be InvoiceReviewView")
    return ErrorStateView(
        error_summary="Terjadi kesalahan",
        error_links=("preview",),
        context_preserved={
            "draft_id": view.reference,
            "unit_ref": view.unit_ref,
            "error_code": error_code,
        },
        recoverable_action=recoverable_action,
    )


def build_denied_view(*, unit_ref: str | None = None) -> DeniedView:
    """Generic denial; never confirms record existence (§5)."""
    return DeniedView(
        message="Anda tidak memiliki akses untuk tindakan ini pada unit tersebut.",
        escalation_path="Hubungi controller keuangan",
    )


def to_responsive_variant(view: InvoiceReviewView, *, viewport: str) -> InvoiceReviewView:
    """Return compact or wide layout variant (§6)."""
    if type(view) is not InvoiceReviewView:
        raise TypeError("view must be InvoiceReviewView")
    if viewport == "compact":
        return replace(
            view,
            layout_mode="compact",
            table_representation="labeled_cards",
            horizontal_overflow=False,
        )
    return replace(
        view,
        layout_mode="wide",
        table_representation="columns",
        horizontal_overflow=False,
    )


_ACTION_CONTROL_MAP = {
    "RETURN_FOR_CORRECTION": "action_return",
    "POST_INVOICE": "action_post",
    "CANCEL": "action_cancel",
}

_ACTION_ACCESSIBLE_NAMES = {
    "action_return": "Kembalikan untuk koreksi",
    "action_post": "Posting invoice",
    "action_cancel": "Batalkan",
}


def accessibility_contract(view: InvoiceReviewView) -> AccessibilityContract:
    """Keyboard/a11y contract as data (§7).

    Action controls mirror view.footer_actions exactly (F-05): a control that
    is not rendered is never placed in tab order, roles, or accessible names.
    """
    if type(view) is not InvoiceReviewView:
        raise TypeError("view must be InvoiceReviewView")
    action_controls = tuple(
        _ACTION_CONTROL_MAP[action]
        for action in view.footer_actions
        if action in _ACTION_CONTROL_MAP
    )
    return AccessibilityContract(
        tab_order=(
            "unit_selector", "header", "branding_preview", "main_content", "policy_card",
            "audit_section", *action_controls,
        ),
        focus_visible=True,
        control_roles={control: "button" for control in action_controls},
        accessible_names={
            control: _ACTION_ACCESSIBLE_NAMES[control] for control in action_controls
        },
        error_summary_position="top",
        error_links_to_fields=True,
        live_region_polite=False,
        reduced_motion_disables_transitions=True,
        touch_target_min_px=44,
    )
