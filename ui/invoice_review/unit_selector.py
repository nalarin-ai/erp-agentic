"""Unit selector view-model (UX_SPEC §1, §7).

Pure functions over assignment data. Only assigned active units are exposed;
empty/revoked/stale states are safe and never reveal other units.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class UnitSelectorView:
    state: str
    units: tuple[dict[str, Any], ...]
    active_unit_label: str | None
    message: str | None
    escalation_path: str | None
    recoverable_action: str | None
    layout_mode: str = "wide"
    list_representation: str = "dropdown_menu"


@dataclass(frozen=True, slots=True)
class SwitchConfirmationView:
    heading: str
    warning: str | None
    draft_exists: bool
    effects: tuple[str, ...]
    focus_return: str


@dataclass(frozen=True, slots=True)
class AccessibilityContract:
    tab_order: tuple[str, ...]
    focus_visible: bool
    control_roles: dict[str, str]
    accessible_names: dict[str, str]
    dismissable: bool
    focus_return: str
    touch_target_min_px: int
    reduced_motion_disables_transitions: bool


_UNIT_LABELS = {
    "UNIT-BANYUMEDIA": "Banyumedia",
    "UNIT-CONTRACTOR": "Contractor",
    "UNIT-BALONESIA": "Balonesia",
}


def _label(unit_ref: str) -> str:
    return _UNIT_LABELS.get(unit_ref, unit_ref)


def build_view(
    assignments: tuple[dict[str, Any], ...],
    *,
    actor_ref: str,
    current_unit_ref: str | None,
    stale: bool = False,
) -> UnitSelectorView:
    """Build unit selector view-model from authorized assignments."""
    if type(assignments) is not tuple:
        raise TypeError("assignments must be a tuple")
    if stale:
        return UnitSelectorView(
            state="STALE",
            units=(),
            active_unit_label=None,
            message="Konteks unit tidak valid. Muat ulang untuk melanjutkan.",
            escalation_path=None,
            recoverable_action="Muat ulang",
        )
    active = [a for a in assignments if a.get("actor_ref") == actor_ref and a.get("active")]
    if not active:
        if any(a.get("actor_ref") == actor_ref for a in assignments):
            return UnitSelectorView(
                state="REVOKED",
                units=(),
                active_unit_label=None,
                message="Akses unit telah dinonaktifkan. Hubungi administrator.",
                escalation_path="Hubungi administrator",
                recoverable_action=None,
            )
        return UnitSelectorView(
            state="EMPTY",
            units=(),
            active_unit_label=None,
            message="Anda belum memiliki akses unit. Hubungi administrator.",
            escalation_path="Hubungi administrator",
            recoverable_action=None,
        )

    units = tuple(
        {"unit_ref": a["unit_ref"], "label": _label(a["unit_ref"]), "selected": a["unit_ref"] == current_unit_ref}
        for a in active
    )
    if len(active) == 1:
        return UnitSelectorView(
            state="SINGLE_UNIT",
            units=units,
            active_unit_label=_label(active[0]["unit_ref"]),
            message=None,
            escalation_path=None,
            recoverable_action=None,
        )
    if current_unit_ref is None:
        return UnitSelectorView(
            state="SELECT_REQUIRED",
            units=units,
            active_unit_label=None,
            message="Pilih satu unit untuk melanjutkan.",
            escalation_path=None,
            recoverable_action=None,
        )
    if current_unit_ref not in {a["unit_ref"] for a in active}:
        # Current unit context is not among assigned units: treat as stale.
        # Never echo the foreign ref or its label (no cross-unit disclosure).
        return UnitSelectorView(
            state="STALE",
            units=(),
            active_unit_label=None,
            message="Konteks unit tidak valid. Muat ulang untuk melanjutkan.",
            escalation_path=None,
            recoverable_action="Muat ulang",
        )
    return UnitSelectorView(
        state="READY",
        units=units,
        active_unit_label=_label(current_unit_ref),
        message=None,
        escalation_path=None,
        recoverable_action=None,
    )


def build_switch_confirmation(
    view: UnitSelectorView,
    *,
    target_unit_ref: str,
    draft_exists: bool,
) -> SwitchConfirmationView:
    """Unit switch confirmation (§1)."""
    if type(view) is not UnitSelectorView:
        raise TypeError("view must be UnitSelectorView")
    if target_unit_ref not in {u["unit_ref"] for u in view.units}:
        # Generic denial: never confirm whether the target unit exists.
        raise ValueError("Unit tujuan tidak tersedia untuk akun ini.")
    warning = None
    if draft_exists:
        warning = "Ada perubahan yang belum disimpan. Beralih unit akan menghapus hasil pencarian scoped dan membatalkan pratinjau."
    return SwitchConfirmationView(
        heading="Konfirmasi ganti unit",
        warning=warning,
        draft_exists=draft_exists,
        effects=("clear_scoped_results", "invalidate_preview_hash", "reload_options"),
        focus_return="unit_control",
    )


def to_responsive_variant(view: UnitSelectorView, *, viewport: str) -> UnitSelectorView:
    """Return compact or wide layout variant (§6)."""
    if type(view) is not UnitSelectorView:
        raise TypeError("view must be UnitSelectorView")
    if viewport == "compact":
        return replace(view, layout_mode="compact", list_representation="dropdown_sheet")
    return replace(view, layout_mode="wide", list_representation="dropdown_menu")


def accessibility_contract(view: UnitSelectorView) -> AccessibilityContract:
    """Keyboard/a11y contract as data (§7)."""
    if type(view) is not UnitSelectorView:
        raise TypeError("view must be UnitSelectorView")
    tab_order = ["unit_selector_button", "unit_list"]
    tab_order.extend(f"unit_option_{i}" for i in range(len(view.units)))
    return AccessibilityContract(
        tab_order=tuple(tab_order),
        focus_visible=True,
        control_roles={
            "unit_selector_button": "button",
            "unit_list": "listbox",
            "unit_option": "option",
        },
        accessible_names={
            "unit_selector_button": "Pilih unit aktif",
            "unit_list": "Daftar unit yang tersedia",
        },
        dismissable=True,
        focus_return="unit_control",
        touch_target_min_px=44,
        reduced_motion_disables_transitions=True,
    )


def render_text(view: UnitSelectorView) -> str:
    """Render unit selector as plain text."""
    if type(view) is not UnitSelectorView:
        raise TypeError("view must be UnitSelectorView")
    lines: list[str] = []
    if view.active_unit_label:
        lines.append(f"Unit aktif: {view.active_unit_label}")
    else:
        lines.append("Unit aktif: -")
    if view.message:
        lines.append(f"  {view.message}")
    if view.units:
        lines.append("Unit tersedia:")
        for unit in view.units:
            marker = "*" if unit["selected"] else " "
            lines.append(f"  {marker} {unit['label']} ({unit['unit_ref']})")
    if view.escalation_path:
        lines.append(f"  Eskalasi: {view.escalation_path}")
    return "\n".join(lines)
