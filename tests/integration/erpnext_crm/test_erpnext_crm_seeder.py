"""Idempotency tests for the CRM seeder (CRM-001 slice 2) — RED first."""
from __future__ import annotations

import os
import unittest

from src.adapters.erpnext import ErpNextAdapter, ErpNextConfig


def _config() -> ErpNextConfig:
    return ErpNextConfig(
        base_url=os.environ.get("ERPNEXT_URL", "http://127.0.0.1:18080"),
        site_name=os.environ.get("ERPNEXT_SITE", "erpnext-pilot.localhost"),
        admin_password=os.environ.get(
            "ERPNEXT_ADMIN_PASSWORD",
            "2be0d0946a2e3d841301c45fb19dde011d179fdcc044b3a74893071eac314090",
        ),
        timeout_seconds=30,
    )


class TestCrmSeeder(unittest.TestCase):
    def test_seed_is_idempotent_and_complete(self) -> None:
        from tests.integration.erpnext_crm._seeder import (
            seed_crm_master_data,
            seed_crm_status,
        )

        adapter = ErpNextAdapter(_config(), frozenset({"UNIT-BM", "UNIT-PR1ME"}))
        first = seed_crm_master_data(adapter)
        status = seed_crm_status(adapter)
        self.assertTrue(all(status.values()), f"missing entities: {status}")
        second = seed_crm_master_data(adapter)
        # Second run must create nothing.
        self.assertFalse(any(second.values()), f"second run created: {second}")


if __name__ == "__main__":
    unittest.main()
