"""ISOFIX-001 — pinned final-architecture configuration.

Single source of truth for the gateway-only final architecture config.
The sha256 of this dataclass is recorded in the ISOLATION_FINAL verdict;
`test_config_drift.py` proves the hash detects tampering and matches the
live pilot's version.
"""
from __future__ import annotations

import os

from src.isolation_architecture import FinalArchitectureConfig


def final_config() -> FinalArchitectureConfig:
    return FinalArchitectureConfig(
        erpnext_version="16.32.1",
        frappe_version="16.31.0",
        base_url=os.environ.get("ERPNEXT_URL", "http://127.0.0.1:18080"),
        site_name=os.environ.get("ERPNEXT_SITE", "erpnext-pilot.localhost"),
        unit_scoped_roles=("Sales User", "Sales Manager", "Support User"),
        gateway_modules=(
            "src.adapters.erpnext",
            "src.adapters.erpnext_crm",
            "src.crm.port",
            "src.reports.owner",
        ),
    )
