"""Final isolation architecture package (ISOFIX-001, gateway-only)."""
from src.isolation_architecture.policy import (
    Decision,
    FinalArchitectureConfig,
    IsolationDenied,
    IsolationError,
    RoleClass,
    Surface,
    admit,
    classify_role,
    issue_native_credential,
    require_gateway_only,
    write_verdict,
)

__all__ = [
    "Decision",
    "FinalArchitectureConfig",
    "IsolationDenied",
    "IsolationError",
    "RoleClass",
    "Surface",
    "admit",
    "classify_role",
    "issue_native_credential",
    "require_gateway_only",
    "write_verdict",
]
