"""Unit settings lifecycle view-model (UX_SPEC §12).

Pure functions over versioned settings. Controls derive from the typed schema;
no arbitrary JSON editor. Branding preview is separated from legal/tax/account.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class UnitSettingsView:
    state: str
    unit_code: str
    current_version: int
    effective_from: str | None
    sections: dict[str, dict[str, Any]]
    control_types: dict[str, str]
    allowed_actions: tuple[str, ...]
    read_only: bool
    layout_mode: str = "wide"
    form_representation: str = "two_column"


@dataclass(frozen=True, slots=True)
class BrandingPreviewView:
    template_ref: str
    logo_asset_ref: str
    fields: tuple[str, ...]
    disclaimer: str


@dataclass(frozen=True, slots=True)
class ValidationErrors:
    error_summary: str
    field_errors: dict[str, str]


@dataclass(frozen=True, slots=True)
class ActivationConfirmationView:
    heading: str
    affected_unit: str
    changed_keys: tuple[str, ...]
    effective_time: str | None
    preview_invalidated: bool
    rollback_target: int | None


@dataclass(frozen=True, slots=True)
class VersionConflictView:
    state: str
    message: str
    recoverable_action: str


@dataclass(frozen=True, slots=True)
class UnsavedChangesView:
    state: str
    message: str
    recoverable_action: str


@dataclass(frozen=True, slots=True)
class ActivationResultView:
    state: str
    message: str
    recoverable_action: str | None


@dataclass(frozen=True, slots=True)
class RollbackView:
    state: str
    message: str
    recoverable_action: str


@dataclass(frozen=True, slots=True)
class DeniedView:
    state: str
    message: str
    escalation_path: str


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
# Schema → section mapping (typed, no arbitrary JSON)
# ---------------------------------------------------------------------------

_SECTION_SCHEMA: dict[str, tuple[str, ...]] = {
    "branding": ("logo_asset_ref", "branding_tagline"),
    "documents": ("invoice_template_ref", "quotation_template_ref", "numbering_series_ref"),
    "sales": ("default_currency", "payment_terms_days"),
    "approval": ("approval_threshold_amount",),
    "finance_mappings": (),
    "modules": ("enabled_modules",),
}

_CONTROL_TYPES: dict[str, str] = {
    "default_currency": "select",
    "payment_terms_days": "number",
    "enabled_modules": "checkbox_group",
    "branding_tagline": "text",
    "logo_asset_ref": "text",
    "invoice_template_ref": "text",
    "quotation_template_ref": "text",
    "numbering_series_ref": "text",
    "approval_threshold_amount": "number",
}

_ROLE_ACTIONS = {
    "UNIT-ADMIN": ("EDIT_DRAFT", "VALIDATE", "PREVIEW", "ACTIVATE", "ROLLBACK"),
    "FINANCE-REVIEWER": ("PREVIEW",),
    "OWNER": ("PREVIEW",),
}


def build_view(version: dict[str, Any], *, actor_roles: tuple[str, ...]) -> UnitSettingsView:
    """Project a SettingsVersion into a redacted settings view-model."""
    if type(version) is not dict:
        raise TypeError("version must be a dict")

    sections: dict[str, dict[str, Any]] = {}
    for section, keys in _SECTION_SCHEMA.items():
        sections[section] = {k: version["settings"].get(k) for k in keys}

    actions: list[str] = []
    for role in actor_roles:
        actions.extend(_ROLE_ACTIONS.get(role, ()))
    allowed_actions = tuple(dict.fromkeys(actions))
    read_only = not any(a in allowed_actions for a in ("EDIT_DRAFT", "ACTIVATE", "ROLLBACK"))

    return UnitSettingsView(
        state="READY",
        unit_code=version["unit_code"],
        current_version=version["configuration_version"],
        effective_from=version.get("effective_from"),
        sections=sections,
        # F-06: only schema-known keys get controls — no orphan controls.
        control_types={k: _CONTROL_TYPES[k] for k in version["settings"] if k in _CONTROL_TYPES},
        allowed_actions=allowed_actions,
        read_only=read_only,
    )


def build_denied_view() -> DeniedView:
    return DeniedView(
        state="DENIED",
        message="Anda tidak memiliki akses untuk tindakan ini pada unit tersebut.",
        escalation_path="Hubungi administrator",
    )


def build_branding_preview(view: UnitSettingsView) -> BrandingPreviewView:
    """Branding preview separated from legal issuer/tax/account (§12)."""
    if type(view) is not UnitSettingsView:
        raise TypeError("view must be UnitSettingsView")
    return BrandingPreviewView(
        template_ref=view.sections["documents"]["invoice_template_ref"] or "",
        logo_asset_ref=view.sections["branding"]["logo_asset_ref"] or "",
        fields=("template_ref", "logo_asset_ref", "branding_tagline"),
        disclaimer="Branding unit terpisah dari identitas legal/pajak/rekening.",
    )


def validate_settings(view: UnitSettingsView, updates: dict[str, Any]) -> ValidationErrors:
    """Validate updates against the typed schema; errors identify exact setting."""
    if type(view) is not UnitSettingsView:
        raise TypeError("view must be UnitSettingsView")
    field_errors: dict[str, str] = {}
    for key, value in updates.items():
        if key not in view.control_types:
            field_errors[key] = "Pengaturan tidak dikenal"
            continue
        control = view.control_types[key]
        if control == "number":
            if not isinstance(value, int):
                field_errors[key] = "Harus berupa angka"
            elif key == "payment_terms_days" and not (0 <= value <= 365):
                field_errors[key] = "Harus dalam rentang 0..365"
            elif key == "approval_threshold_amount" and value < 0:
                field_errors[key] = "Harus non-negatif"
        elif control == "select" and key == "default_currency":
            if not isinstance(value, str) or len(value) != 3 or not value.isupper():
                field_errors[key] = "Harus kode mata uang ISO-4217"
        elif control == "checkbox_group" and key == "enabled_modules":
            if not isinstance(value, (tuple, list)):
                field_errors[key] = "Harus berupa daftar modul"
    return ValidationErrors(
        error_summary="Periksa kembali pengaturan",
        field_errors=field_errors,
    )


def build_activation_confirmation(view: UnitSettingsView, draft: dict[str, Any]) -> ActivationConfirmationView:
    """Activation confirmation lists unit, changed keys, effective time, preview
    invalidation, and rollback target (§12)."""
    if type(view) is not UnitSettingsView:
        raise TypeError("view must be UnitSettingsView")
    changed = []
    current = view.sections
    draft_sections: dict[str, dict[str, Any]] = {}
    for section, keys in _SECTION_SCHEMA.items():
        draft_sections[section] = {k: draft["settings"].get(k) for k in keys}
    for section in current:
        for key in current[section]:
            if current[section][key] != draft_sections[section][key]:
                changed.append(key)
    return ActivationConfirmationView(
        heading="Konfirmasi aktivasi pengaturan",
        affected_unit=view.unit_code,
        changed_keys=tuple(changed),
        effective_time=draft.get("created_at"),
        preview_invalidated=True,
        rollback_target=view.current_version,
    )


def build_version_conflict_state(view: UnitSettingsView, *, expected_version: int, actual_version: int) -> VersionConflictView:
    return VersionConflictView(
        state="VERSION_CONFLICT",
        message=f"Pengaturan telah berubah: diharapkan versi {expected_version}, aktif versi {actual_version}.",
        recoverable_action="Muat ulang pengaturan",
    )


def build_unsaved_changes_state(view: UnitSettingsView) -> UnsavedChangesView:
    return UnsavedChangesView(
        state="UNSAVED_CHANGES",
        message="Ada perubahan yang belum disimpan.",
        recoverable_action="Simpan atau batalkan perubahan",
    )


def build_activation_result(view: UnitSettingsView, *, outcome: str, new_version: int | None = None, reason: str | None = None) -> ActivationResultView:
    if outcome == "ACTIVATED":
        return ActivationResultView(
            state="ACTIVATED",
            message=f"Pengaturan versi {new_version} berhasil diaktifkan.",
            recoverable_action=None,
        )
    return ActivationResultView(
        state="FAILED",
        # Sanitized (F-02): raw service/exception detail is never shown.
        message="Aktivasi gagal. Tidak ada perubahan yang disimpan.",
        recoverable_action="Perbaiki dan coba lagi",
    )


def build_rollback_state(view: UnitSettingsView, *, to_version: int) -> RollbackView:
    return RollbackView(
        state="ROLLBACK",
        message=f"Kembali ke versi {to_version}.",
        recoverable_action="Konfirmasi rollback",
    )


def to_responsive_variant(view: UnitSettingsView, *, viewport: str) -> UnitSettingsView:
    if type(view) is not UnitSettingsView:
        raise TypeError("view must be UnitSettingsView")
    if viewport == "compact":
        return replace(view, layout_mode="compact", form_representation="stacked_cards")
    return replace(view, layout_mode="wide", form_representation="two_column")


def accessibility_contract(view: UnitSettingsView) -> AccessibilityContract:
    if type(view) is not UnitSettingsView:
        raise TypeError("view must be UnitSettingsView")
    return AccessibilityContract(
        tab_order=(
            "unit_selector", "section_tabs", "form_fields", "action_validate", "action_preview",
            "action_activate", "action_rollback",
        ),
        focus_visible=True,
        control_roles={
            "action_validate": "button",
            "action_preview": "button",
            "action_activate": "button",
            "action_rollback": "button",
            "section_tabs": "tablist",
        },
        accessible_names={
            "action_validate": "Validasi pengaturan",
            "action_preview": "Pratinjau pengaturan",
            "action_activate": "Aktifkan pengaturan",
            "action_rollback": "Kembalikan versi sebelumnya",
        },
        error_summary_position="top",
        error_links_to_fields=True,
        live_region_polite=False,
        reduced_motion_disables_transitions=True,
        touch_target_min_px=44,
    )


def render_text(view: UnitSettingsView) -> str:
    if type(view) is not UnitSettingsView:
        raise TypeError("view must be UnitSettingsView")
    lines: list[str] = []
    lines.append(f"Pengaturan Unit: {view.unit_code}")
    lines.append(f"Versi: {view.current_version}")
    if view.effective_from:
        lines.append(f"Berlaku sejak: {view.effective_from}")
    lines.append("")
    section_labels = {
        "branding": "Branding",
        "documents": "Dokumen",
        "sales": "Penjualan",
        "approval": "Persetujuan",
        "finance_mappings": "Pemetaan Keuangan",
        "modules": "Modul",
    }
    for section, fields in view.sections.items():
        lines.append(f"{section_labels.get(section, section)}:")
        for key, value in fields.items():
            lines.append(f"  {key}: {value}")
        lines.append("")
    lines.append("Tindakan yang diizinkan: " + ", ".join(view.allowed_actions))
    if view.read_only:
        lines.append("(Mode baca saja)")
    return "\n".join(lines)
