"""ISOFIX-001 fixture migration seeder (live, admin, synthetic only).

Implements the gateway-only migration on the isolated pilot:

- For every ISO-001 unit-scoped synthetic user (sales BM / sales P1):
  disable the account (enabled=0) so no native session can be established,
  and delete every User Permission row for that user so no native scoping
  residue remains.
- The migration is idempotent (safe to re-run) and admin-only.
- Owner fixture (`iso-owner@example.test`) remains enabled for gateway
  roll-up evidence; the deactivated fixture stays disabled.

Evidence rows are recorded via the final probe recorder.
"""
from __future__ import annotations

import json

from tests.security.isolation_final import _harness as fh
from tests.security.native_erp import _harness as h


def _admin_list_user_permissions(username: str) -> list[str]:
    status, body = h.admin_get(
        "/api/resource/User Permission",
        params={
            "filters": json.dumps([["User Permission", "user", "=", username]]),
            "fields": json.dumps(["name"]),
            "limit_page_length": "500",
        },
    )
    if status != 200:
        return []
    try:
        return [row["name"] for row in json.loads(body).get("data", [])]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def _admin_delete(doctype: str, name: str) -> int:
    status, _body, _elapsed = h.admin_session().request(
        "DELETE", f"/api/resource/{doctype}/{name}"
    )
    return status


def _admin_get_user_enabled(username: str) -> int | None:
    status, body = h.admin_get(f"/api/resource/User/{username}")
    if status != 200:
        return None
    try:
        return int(json.loads(body).get("data", {}).get("enabled", 0))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def migrate_unit_user_to_gateway_only(username: str) -> dict[str, bool]:
    """Disable one unit user + purge its User Permissions. Idempotent."""
    outcome = {"disabled": False, "permissions_purged": False}
    if _admin_get_user_enabled(username) == 1:
        status, _ = h.admin_put("User", username, {"enabled": 0})
        outcome["disabled"] = status == 200 and _admin_get_user_enabled(username) == 0
    else:
        outcome["disabled"] = _admin_get_user_enabled(username) == 0
    names = _admin_list_user_permissions(username)
    ok = True
    for name in names:
        if _admin_delete("User Permission", name) not in (200, 202, 404):
            ok = False
    outcome["permissions_purged"] = ok and not _admin_list_user_permissions(username)
    return outcome


def ensure_final_architecture_seeded() -> None:
    """Disable both unit-scoped sales users and purge their permissions."""
    for username in (h.USER_SALES_BM, h.USER_SALES_P1):
        outcome = migrate_unit_user_to_gateway_only(username)
        fh.record_probe(
            surface="final-migration",
            actor="Administrator",
            action=f"gateway-only migration for {username}",
            expected="user disabled and User Permissions purged",
            status=200 if all(outcome.values()) else None,
            body="",
            detail=json.dumps(outcome, sort_keys=True),
        )
