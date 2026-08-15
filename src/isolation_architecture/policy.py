"""ISOFIX-001 — final isolation architecture (gateway-only).

ISO-001 verdict REQUIRES_GATEWAY_ONLY (ADR-001): unit-scoped roles MUST NOT
hold direct native ERPNext desk/API credentials. All unit access flows
through the proven gateway/adapter layer. This module enforces that policy
fail-closed at the admission boundary:

- role taxonomy: unit-scoped vs operator vs owner/controller;
- admission decision per (role, surface) — native surfaces DENIED for
  unit-scoped roles, gateway surfaces ALLOWED;
- native credential issuance guard — issuing a native credential to a
  unit-scoped role is denied fail-closed;
- evidence writer for the ISOLATION_FINAL verdict.

Pure policy module: no network, no credentials, no secrets.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


class IsolationError(RuntimeError):
    """Base error for final isolation architecture."""


class IsolationDenied(IsolationError):
    """Fail-closed denial with generic static message (no reason echo)."""


class RoleClass(StrEnum):
    """Actor role taxonomy for isolation admission."""

    UNIT_SCOPED = "UNIT_SCOPED"      # sales / single-operating-unit roles
    OPERATOR = "OPERATOR"            # non-unit-scoped ops roles (separate control)
    OWNER_CONTROLLER = "OWNER_CONTROLLER"  # explicit cross-unit roll-up


class Surface(StrEnum):
    """Access surface taxonomy."""

    NATIVE_DESK = "NATIVE_DESK"          # /app desk UI
    NATIVE_API = "NATIVE_API"            # /api/resource, /api/method, etc.
    NATIVE_FILES = "NATIVE_FILES"        # /private/files, File doctype metadata
    NATIVE_REPORTS = "NATIVE_REPORTS"    # query-report / export / print
    GATEWAY_ERP_PORT = "GATEWAY_ERP_PORT"    # src/adapters/erpnext (ErpPort)
    GATEWAY_CRM_PORT = "GATEWAY_CRM_PORT"    # src/crm port + erpnext_crm adapter
    GATEWAY_REPORTS = "GATEWAY_REPORTS"      # RPT-001 owner roll-up service


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


_ROLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]{0,63}$")
_ROLE_CLASS: dict[str, RoleClass] = {
    "Sales User": RoleClass.UNIT_SCOPED,
    "Sales Manager": RoleClass.UNIT_SCOPED,
    "Support User": RoleClass.UNIT_SCOPED,
    "Operator": RoleClass.OPERATOR,
    "System Manager": RoleClass.OPERATOR,
    "Owner": RoleClass.OWNER_CONTROLLER,
    "Controller": RoleClass.OWNER_CONTROLLER,
}

# Fail-closed admission matrix: unit-scoped roles may ONLY use gateway
# surfaces. Operator roles may use native surfaces under a separate ops
# control. Owner/controller roll-up flows exclusively through the gateway
# roll-up service (server-side, auditable).
_MATRIX: dict[tuple[RoleClass, Surface], Decision] = {
    (RoleClass.UNIT_SCOPED, Surface.NATIVE_DESK): Decision.DENY,
    (RoleClass.UNIT_SCOPED, Surface.NATIVE_API): Decision.DENY,
    (RoleClass.UNIT_SCOPED, Surface.NATIVE_FILES): Decision.DENY,
    (RoleClass.UNIT_SCOPED, Surface.NATIVE_REPORTS): Decision.DENY,
    (RoleClass.UNIT_SCOPED, Surface.GATEWAY_ERP_PORT): Decision.ALLOW,
    (RoleClass.UNIT_SCOPED, Surface.GATEWAY_CRM_PORT): Decision.ALLOW,
    (RoleClass.UNIT_SCOPED, Surface.GATEWAY_REPORTS): Decision.DENY,
    (RoleClass.OPERATOR, Surface.NATIVE_DESK): Decision.ALLOW,
    (RoleClass.OPERATOR, Surface.NATIVE_API): Decision.ALLOW,
    (RoleClass.OPERATOR, Surface.NATIVE_FILES): Decision.ALLOW,
    (RoleClass.OPERATOR, Surface.NATIVE_REPORTS): Decision.ALLOW,
    (RoleClass.OPERATOR, Surface.GATEWAY_ERP_PORT): Decision.ALLOW,
    (RoleClass.OPERATOR, Surface.GATEWAY_CRM_PORT): Decision.ALLOW,
    (RoleClass.OPERATOR, Surface.GATEWAY_REPORTS): Decision.DENY,
    (RoleClass.OWNER_CONTROLLER, Surface.NATIVE_DESK): Decision.DENY,
    (RoleClass.OWNER_CONTROLLER, Surface.NATIVE_API): Decision.DENY,
    (RoleClass.OWNER_CONTROLLER, Surface.NATIVE_FILES): Decision.DENY,
    (RoleClass.OWNER_CONTROLLER, Surface.NATIVE_REPORTS): Decision.DENY,
    (RoleClass.OWNER_CONTROLLER, Surface.GATEWAY_ERP_PORT): Decision.ALLOW,
    (RoleClass.OWNER_CONTROLLER, Surface.GATEWAY_CRM_PORT): Decision.ALLOW,
    (RoleClass.OWNER_CONTROLLER, Surface.GATEWAY_REPORTS): Decision.ALLOW,
}

_DENIAL_MESSAGE = "Access denied by final isolation architecture."


def _normalize_role(role: str) -> str:
    if not isinstance(role, str):
        raise IsolationDenied(_DENIAL_MESSAGE)
    return role.strip()


def classify_role(role: str) -> RoleClass:
    """Classify an ERPNext role name into the isolation taxonomy.

    Fail-closed: unknown or malformed roles are denied, never defaulted
    into a permissive class. Comparison is case-sensitive and exact after
    surrounding-whitespace normalization (NFKC/casefold is intentionally
    NOT used for identity: 'sales user' is not 'Sales User').
    """
    normalized = _normalize_role(role)
    if not normalized or not _ROLE_PATTERN.fullmatch(normalized):
        raise IsolationDenied(_DENIAL_MESSAGE)
    role_class = _ROLE_CLASS.get(normalized)
    if role_class is None:
        raise IsolationDenied(_DENIAL_MESSAGE)
    return role_class


def admit(role: str, surface: Surface) -> Decision:
    """Return ALLOW/DENY for (role, surface). Fail-closed on any invalid input.

    Denial is audited by callers via durable audit (FND-004 lane); this
    pure function never raises for a merely-denied (valid) combination —
    it returns Decision.DENY. It raises IsolationDenied only for invalid
    inputs (unknown role, malformed role, non-Surface value).
    """
    role_class = classify_role(role)
    if not isinstance(surface, Surface):
        raise IsolationDenied(_DENIAL_MESSAGE)
    decision = _MATRIX.get((role_class, surface))
    if decision is None:  # defensive: matrix is total; fail-closed anyway
        raise IsolationDenied(_DENIAL_MESSAGE)
    return decision


def require_gateway_only(role: str, surface: Surface) -> None:
    """Raise IsolationDenied unless admission is ALLOW."""
    if admit(role, surface) is not Decision.ALLOW:
        raise IsolationDenied(_DENIAL_MESSAGE)


def issue_native_credential(role: str, username: str) -> None:
    """Guard: native credential issuance to unit-scoped roles is denied.

    `username` is accepted only for audit correlation; it is never echoed
    in error messages. Fail-closed on unknown roles or any unit-scoped
    class. Operator-class issuance is allowed here but remains governed by
    a separate ops control outside this module.
    """
    role_class = classify_role(role)
    if role_class is RoleClass.UNIT_SCOPED:
        raise IsolationDenied(_DENIAL_MESSAGE)
    if not isinstance(username, str) or not username.strip():
        raise IsolationDenied(_DENIAL_MESSAGE)


@dataclass(frozen=True)
class FinalArchitectureConfig:
    """Pinned final-architecture configuration (hashable evidence anchor)."""

    erpnext_version: str
    frappe_version: str
    base_url: str
    site_name: str
    unit_scoped_roles: tuple[str, ...]
    gateway_modules: tuple[str, ...]

    def sha256(self) -> str:
        payload = json.dumps(
            {
                "erpnext_version": self.erpnext_version,
                "frappe_version": self.frappe_version,
                "base_url": self.base_url,
                "site_name": self.site_name,
                "unit_scoped_roles": sorted(self.unit_scoped_roles),
                "gateway_modules": sorted(self.gateway_modules),
            },
            sort_keys=True,
        ).encode()
        return hashlib.sha256(payload).hexdigest()


def write_verdict(
    evidence_dir: Path,
    *,
    verdict: str,
    config: FinalArchitectureConfig,
    matrix_summary: dict[str, Any],
    findings: list[str],
    run_id: str,
) -> Path:
    """Write ISOLATION_FINAL verdict JSON atomically. Fail-closed schema.

    `run_id` binds the verdict to exactly one probe run so a stale verdict
    cannot survive newer raw evidence.
    """
    if verdict not in {"PASS", "FAIL"}:
        raise ValueError("verdict must be PASS or FAIL")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(evidence_dir, Path):
        evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "verdict": verdict,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_sha256": config.sha256(),
        "config": {
            "erpnext_version": config.erpnext_version,
            "frappe_version": config.frappe_version,
            "base_url": config.base_url,
            "site_name": config.site_name,
        },
        "matrix_summary": matrix_summary,
        "findings": findings,
    }
    target = evidence_dir / "isolation_final.json"
    tmp = evidence_dir / ".isolation_final.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target
