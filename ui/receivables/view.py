"""View-model builders for the receivables screen (UX_SPEC §3, §4, §5)."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


# ---------------------------------------------------------------------------
# View-models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReceivablesView:
    state: str
    filters: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    total_open_amount: str
    currency: str | None
    scoped: bool
    empty_message: str | None = None
    layout_mode: str = "wide"
    table_representation: str = "columns"
    horizontal_overflow: bool = False


@dataclass(frozen=True, slots=True)
class OwnerRollupView:
    is_aggregation: bool
    aggregation_label: str
    unit_rows: tuple[dict[str, Any], ...]
    owner_total: str | None
    currency: str | None
    as_of: str


@dataclass(frozen=True, slots=True)
class PaymentEvidenceFormView:
    fields: tuple[str, ...]
    invoice_ref: str
    remaining_balance: str
    currency: str
    account_policy_message: str
    allowed_accounts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PaymentEvidenceErrors:
    error_summary: str
    field_errors: dict[str, str]


@dataclass(frozen=True, slots=True)
class DuplicateEvidenceView:
    state: str
    message: str
    existing_record_alias: str | None
    existing_record_status: str | None
    conflict_path: str | None


@dataclass(frozen=True, slots=True)
class DeniedView:
    message: str
    escalation_path: str


@dataclass(frozen=True, slots=True)
class LoadingView:
    state: str
    skeleton_rows: int


@dataclass(frozen=True, slots=True)
class OfflineView:
    state: str
    message: str
    recoverable_action: str


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


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


_STATUS_LABEL = {
    "OPEN": ("Terbuka", "warning"),
    "PARTIALLY_PAID": ("Sebagian dibayar", "info"),
    "PAID": ("Lunas", "success"),
    "OVERDUE": ("Jatuh tempo", "danger"),
}


def build_view(
    aging_result: dict[str, Any],
    *,
    actor_roles: tuple[str, ...],
    assignments: tuple[dict[str, Any], ...],
) -> ReceivablesView:
    """Project an authorized AgingResult into a redacted receivables view-model."""
    if type(aging_result) is not dict:
        raise TypeError("aging_result must be a dict")

    active_units = sorted({a["unit_ref"] for a in assignments if a.get("active")})
    default_unit = active_units[0] if len(active_units) == 1 else None

    filters = {
        "unit": {"default": default_unit, "locked": len(active_units) == 1, "options": tuple(active_units)},
        "issuer": {"default": None, "locked": False},
        "sales_owner": {"default": None, "locked": "OWNER" not in actor_roles},
        "customer": {"default": None, "locked": False},
        "status": {"default": "OPEN", "locked": False},
        "aging_bucket": {"default": None, "locked": False},
        "due_date": {"default": None, "locked": False},
    }

    rows = []
    for entry in aging_result["entries"]:
        status_label, status_tone = _STATUS_LABEL.get(entry["receivable_status"], ("Tidak diketahui", "neutral"))
        rows.append({
            "invoice_ref": entry["invoice_ref"],
            "unit_ref": entry["unit_ref"],
            "customer_ref": entry["customer_ref"],
            "customer_display": entry["customer_display"],
            "currency": entry["currency"],
            "total_amount": entry["total_amount"],
            "open_amount": entry["open_amount"],
            "due_on": entry["due_on"],
            "status_label": status_label,
            "status_tone": status_tone,
            "allowed_actions": ("record_payment", "view_detail"),
        })

    return ReceivablesView(
        state="EMPTY" if not rows else "READY",
        filters=filters,
        rows=tuple(rows),
        total_open_amount=aging_result["total_open_amount"],
        currency=aging_result["currency"],
        scoped=aging_result["scoped"],
        empty_message="Tidak ada piutang jatuh tempo" if not rows else None,
    )


def build_owner_rollup_view(rollup: dict[str, Any]) -> OwnerRollupView:
    """Owner roll-up explicitly labeled as aggregation, never merged ledger.

    F-09: the owner total is surfaced only when the service guarantees a
    single currency (both owner_open_amount_total AND currency present).
    Mixed/unknown currency ⇒ no summed total is ever presented.
    """
    if type(rollup) is not dict:
        raise TypeError("rollup must be a dict")
    owner_total = rollup["owner_open_amount_total"]
    currency = rollup["currency"]
    if owner_total is None or currency is None:
        owner_total = None
        currency = None
    return OwnerRollupView(
        is_aggregation=True,
        aggregation_label="Agregasi lintas unit (bukan ledger gabungan)",
        unit_rows=tuple(rollup["per_unit"]),
        owner_total=owner_total,
        currency=currency,
        as_of=rollup["as_of"],
    )


def build_denied_view() -> DeniedView:
    """Generic denial; never confirms record existence (§5)."""
    return DeniedView(
        message="Anda tidak memiliki akses untuk tindakan ini pada unit tersebut.",
        escalation_path="Hubungi controller keuangan",
    )


def build_loading_view() -> LoadingView:
    return LoadingView(state="LOADING", skeleton_rows=3)


def build_offline_view() -> OfflineView:
    return OfflineView(
        state="OFFLINE",
        message="Tidak dapat terhubung ke server. Data mungkin belum termuat.",
        recoverable_action="Coba lagi",
    )


def build_payment_evidence_form(
    *,
    invoice_ref: str,
    remaining_balance: str,
    currency: str,
    account_policy: dict[str, Any],
) -> PaymentEvidenceFormView:
    """Payment evidence form view-model (§4)."""
    return PaymentEvidenceFormView(
        fields=(
            "invoice", "amount", "currency", "payment_date", "account_alias",
            "reference_alias", "evidence_upload", "note",
        ),
        invoice_ref=invoice_ref,
        remaining_balance=remaining_balance,
        currency=currency,
        account_policy_message=(
            f"Rekening yang diizinkan: {', '.join(account_policy['allowed_accounts'])}. "
            f"Maksimum: {account_policy['max_amount']} {currency}."
        ),
        allowed_accounts=tuple(account_policy["allowed_accounts"]),
    )


def validate_payment_evidence(
    form: PaymentEvidenceFormView,
    values: dict[str, str],
) -> PaymentEvidenceErrors:
    """Validate form values; return linked field errors (§4, §7)."""
    if type(form) is not PaymentEvidenceFormView:
        raise TypeError("form must be PaymentEvidenceFormView")
    field_errors: dict[str, str] = {}
    if values.get("invoice") != form.invoice_ref:
        field_errors["invoice"] = "Invoice tidak sesuai"
    # F-07: defensive parsing — malformed form data yields field errors, never raises.
    try:
        remaining = int(form.remaining_balance)
    except (TypeError, ValueError):
        remaining = None
    if remaining is None:
        field_errors["amount"] = "Sisa tagihan tidak valid"
    else:
        try:
            amount = int(values.get("amount", "0"))
        except (TypeError, ValueError):
            field_errors["amount"] = "Jumlah harus berupa angka"
        else:
            if amount <= 0 or amount > remaining:
                field_errors["amount"] = f"Maksimum sisa tagihan {form.remaining_balance} {form.currency}"
    if values.get("currency") != form.currency:
        field_errors["currency"] = "Mata uang tidak sesuai"
    allowed_accounts = form.allowed_accounts
    account_alias = values.get("account_alias")
    if account_alias is None:
        field_errors["account_alias"] = "Rekening wajib diisi"
    elif account_alias not in allowed_accounts:
        field_errors["account_alias"] = "Rekening tidak diizinkan"
    if not values.get("payment_date"):
        field_errors["payment_date"] = "Tanggal pembayaran wajib diisi"
    if not values.get("evidence_upload"):
        field_errors["evidence_upload"] = "Bukti pembayaran wajib diunggah"
    return PaymentEvidenceErrors(
        error_summary="Periksa kembali isian Anda",
        field_errors=field_errors,
    )


def build_duplicate_evidence_state(
    form: PaymentEvidenceFormView,
    *,
    scope: str,
    existing_alias: str | None,
    existing_status: str | None,
) -> DuplicateEvidenceView:
    """Duplicate evidence handling (§11).

    Same-scope: show only alias/status the actor is independently allowed to view.
    Cross-scope: controller conflict path, zero disclosure of other-scope data.
    """
    if type(form) is not PaymentEvidenceFormView:
        raise TypeError("form must be PaymentEvidenceFormView")
    if scope == "same":
        if existing_alias and existing_status:
            message = f"Bukti pembayaran sudah ada: {existing_alias} (status: {existing_status})."
        else:
            # F-04: never render "None"/empty alias into user-facing copy.
            message = "Bukti pembayaran untuk invoice ini sudah ada."
        return DuplicateEvidenceView(
            state="duplicate_same_scope",
            message=message,
            existing_record_alias=existing_alias,
            existing_record_status=existing_status,
            conflict_path=None,
        )
    return DuplicateEvidenceView(
        state="duplicate_cross_scope",
        message="Terjadi konflik data. Silakan hubungi controller untuk penyelesaian.",
        existing_record_alias=None,
        existing_record_status=None,
        conflict_path="controller_review",
    )


def to_responsive_variant(view: ReceivablesView, *, viewport: str) -> ReceivablesView:
    """Return compact or wide layout variant (§6)."""
    if type(view) is not ReceivablesView:
        raise TypeError("view must be ReceivablesView")
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


def accessibility_contract(view: ReceivablesView) -> AccessibilityContract:
    """Keyboard/a11y contract as data (§7)."""
    if type(view) is not ReceivablesView:
        raise TypeError("view must be ReceivablesView")
    return AccessibilityContract(
        tab_order=(
            "unit_selector", "filter_bar", "receivables_table", "pagination", "summary",
        ),
        focus_visible=True,
        control_roles={
            "receivables_table": "table",
            "filter_unit": "combobox",
            "filter_status": "combobox",
        },
        accessible_names={
            "filter_unit": "Filter unit",
            "filter_status": "Filter status",
            "receivables_table": "Daftar piutang",
        },
        error_summary_position="top",
        error_links_to_fields=True,
        live_region_polite=False,
        reduced_motion_disables_transitions=True,
        touch_target_min_px=44,
    )
