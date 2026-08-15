"""ISOFIX-001 configuration drift and verdict-writer tests (TDD RED→GREEN).

The pinned final-architecture config hash must:
- be deterministic and order-insensitive for role/module tuples;
- change when ANY field drifts (version, URL, site, roles, modules);
- match the live pilot's actual ERPNext/frappe versions (fail-closed on
  version drift between pin and runtime).

The verdict writer must write atomically, fail-closed on bad verdicts,
and round-trip its payload.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.isolation_architecture import FinalArchitectureConfig, write_verdict
from src.isolation_architecture.config import final_config


class TestConfigHash(unittest.TestCase):
    def test_hash_deterministic(self) -> None:
        self.assertEqual(final_config().sha256(), final_config().sha256())

    def test_hash_order_insensitive_for_tuples(self) -> None:
        a = final_config()
        b = FinalArchitectureConfig(
            erpnext_version=a.erpnext_version,
            frappe_version=a.frappe_version,
            base_url=a.base_url,
            site_name=a.site_name,
            unit_scoped_roles=tuple(reversed(a.unit_scoped_roles)),
            gateway_modules=tuple(reversed(a.gateway_modules)),
        )
        self.assertEqual(a.sha256(), b.sha256())

    def test_hash_detects_version_drift(self) -> None:
        a = final_config()
        drifted = FinalArchitectureConfig(
            erpnext_version="16.32.2",
            frappe_version=a.frappe_version,
            base_url=a.base_url,
            site_name=a.site_name,
            unit_scoped_roles=a.unit_scoped_roles,
            gateway_modules=a.gateway_modules,
        )
        self.assertNotEqual(a.sha256(), drifted.sha256())

    def test_hash_detects_role_set_drift(self) -> None:
        a = final_config()
        drifted = FinalArchitectureConfig(
            erpnext_version=a.erpnext_version,
            frappe_version=a.frappe_version,
            base_url=a.base_url,
            site_name=a.site_name,
            unit_scoped_roles=a.unit_scoped_roles + ("Sales Master Manager",),
            gateway_modules=a.gateway_modules,
        )
        self.assertNotEqual(a.sha256(), drifted.sha256())

    def test_hash_detects_gateway_module_drift(self) -> None:
        a = final_config()
        drifted = FinalArchitectureConfig(
            erpnext_version=a.erpnext_version,
            frappe_version=a.frappe_version,
            base_url=a.base_url,
            site_name=a.site_name,
            unit_scoped_roles=a.unit_scoped_roles,
            gateway_modules=a.gateway_modules[:-1],
        )
        self.assertNotEqual(a.sha256(), drifted.sha256())


class TestLiveVersionPin(unittest.TestCase):
    """Fail-closed drift check: pin must match the live pilot versions."""

    def test_live_versions_match_pin(self) -> None:
        from tests.security.native_erp import _harness as h

        status, body = h.admin_get("/api/method/frappe.utils.get_installed_apps_info")
        if status != 200:
            # Older route name fallback: read versions via /api/method/ping
            # is impossible; use the about endpoint used by ISO-001 harness.
            status, body = h.admin_get(
                "/api/method/frappe.utils.change_log.get_versions"
            )
        self.assertEqual(status, 200, "version endpoint must be reachable")
        text = body.decode(errors="replace")
        cfg = final_config()
        self.assertIn(cfg.frappe_version, text, "frappe pin drift vs live pilot")
        self.assertIn(cfg.erpnext_version, text, "erpnext pin drift vs live pilot")


class TestVerdictWriter(unittest.TestCase):
    def test_write_verdict_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = write_verdict(
                Path(tmp),
                verdict="PASS",
                config=final_config(),
                matrix_summary={"total_probes": 1, "leak_positive_probes": 0},
                findings=[],
                run_id="test-run-1",
            )
            payload = json.loads(target.read_text())
            self.assertEqual(payload["verdict"], "PASS")
            self.assertEqual(payload["config_sha256"], final_config().sha256())
            self.assertEqual(payload["schema_version"], 1)

    def test_write_verdict_rejects_invalid_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_verdict(
                    Path(tmp),
                    verdict="PASS_WITH_FINDINGS",
                    config=final_config(),
                    matrix_summary={},
                    findings=[],
                    run_id="test-run-1",
                )

    def test_write_verdict_atomic_no_tmp_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_verdict(
                Path(tmp),
                verdict="FAIL",
                config=final_config(),
                matrix_summary={"total_probes": 0, "leak_positive_probes": 0},
                findings=["x"],
                run_id="test-run-1",
            )
            names = sorted(p.name for p in Path(tmp).iterdir())
            self.assertEqual(names, ["isolation_final.json"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
