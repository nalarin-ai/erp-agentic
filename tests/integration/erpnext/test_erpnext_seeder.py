"""RED-first test for ADP-002 ERPNext master data seeding.

This test verifies that the seeder module can populate the isolated
ERPNext pilot with the minimum master data required by the adapter
contract tests. It fails until the seeder module is implemented.
"""
from __future__ import annotations

import os
import unittest

from src.adapters.erpnext import ErpNextAdapter, ErpNextConfig


def _config() -> ErpNextConfig:
    return ErpNextConfig(
        base_url=os.environ.get("ERPNEXT_URL", "http://127.0.0.1:18080"),
        site_name=os.environ.get("ERPNEXT_SITE", "erpnext-pilot.localhost"),
        admin_password=os.environ.get("ERPNEXT_ADMIN_PASSWORD", "2be0d0946a2e3d841301c45fb19dde011d179fdcc044b3a74893071eac314090"),
        timeout_seconds=30,
    )


class TestErpNextSeeder(unittest.TestCase):
    """Verify master-data seeding for integration fixtures."""

    def test_seeder_module_importable(self) -> None:
        """RED: seeder module must exist and expose seed_master_data."""
        from tests.integration.erpnext import _seeder  # noqa: F401
        self.assertTrue(hasattr(_seeder, "seed_master_data"))

    def test_seed_master_data_creates_required_entities(self) -> None:
        """RED: seeding must create Company, Customer, Item, UOM, etc."""
        from tests.integration.erpnext._seeder import seed_master_data, seed_status

        adapter = ErpNextAdapter(_config(), frozenset({"UNIT-BM"}))
        created = seed_master_data(adapter)
        status = seed_status(adapter)

        # After seeding, every required entity must exist
        self.assertTrue(status["company"], "Company UNIT-BM must exist")
        self.assertTrue(status["customer"], "Customer CUST-ALPHA must exist")
        self.assertTrue(status["item"], "Item SVC-ADS must exist")
        self.assertTrue(status["uom"], "UOM Nos must exist")
        self.assertTrue(status["item_group"], "Item Group Services must exist")
        self.assertTrue(status["customer_group"], "Customer Group Commercial must exist")
        self.assertTrue(status["territory"], "Territory Indonesia must exist")

        # created flags must be booleans
        for key, value in created.items():
            self.assertIsInstance(value, bool, f"created[{key}] must be bool")

    def test_seed_master_data_idempotent(self) -> None:
        """RED: re-running seed must not fail and must report created=False."""
        from tests.integration.erpnext._seeder import seed_master_data

        adapter = ErpNextAdapter(_config(), frozenset({"UNIT-BM"}))
        first = seed_master_data(adapter)
        second = seed_master_data(adapter)

        # Second run must create nothing
        for key, value in second.items():
            self.assertFalse(value, f"second run must not create {key}")


if __name__ == "__main__":
    unittest.main()
