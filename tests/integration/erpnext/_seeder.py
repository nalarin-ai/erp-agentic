"""ERPNext master data seeder for ADP-002 integration fixtures.

Seeds the minimum master data required for the ERPNext adapter contract
tests against the isolated pilot instance (EVAL-002). All refs are
synthetic opaque. Idempotent: existing docs are left untouched.

Seeded entities (depends-on order):
- UOM "Nos" (usually seeded by ERPNext; verify/create)
- Item Group "All Item Groups" (root, is_group=1) → "Services" (leaf)
- Customer Group "All Customer Groups" (root) → "Commercial" (leaf)
- Territory "All Territories" (root) → "Indonesia" (leaf)
- Company UNIT-BM (root for Warehouse/Cost Center)
- Customer CUST-ALPHA
- Item SVC-ADS (service item, no stock)

The seeder NEVER deletes, NEVER mutates live data, and is safe to re-run.
"""
from __future__ import annotations

from typing import Any

from src.adapters.erpnext import ErpNextAdapter
from src.contracts.erp_port import DocumentRejected


# ---------------------------------------------------------------------------
# Synthetic fixture constants (no real data)
# ---------------------------------------------------------------------------

COMPANY_REF = "UNIT-BM"
COMPANY_ABBR = "UBM"
CUSTOMER_REF = "CUST-ALPHA"
ITEM_REF = "SVC-ADS"
UOM_REF = "Nos"
ITEM_GROUP_REF = "Services"
CUSTOMER_GROUP_REF = "Commercial"
TERRITORY_REF = "Indonesia"
CURRENCY = "IDR"
COUNTRY = "Indonesia"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def seed_master_data(adapter: ErpNextAdapter) -> dict[str, bool]:
    """Seed master data into the isolated ERPNext pilot.

    Idempotent: each entity is created only if a GET returns 404.
    Returns a dict of entity -> created_now (True if created this call).
    Raises UncertainOutcome on connection failure; DocumentRejected on
    validation failures other than already-exists.
    """
    created: dict[str, bool] = {}

    created["uom"] = _ensure_uom(adapter, UOM_REF)
    created["warehouse_type_transit"] = _ensure_warehouse_type(adapter, "Transit")
    created["selling_settings_customer_name"] = _ensure_selling_settings_customer_name(adapter)
    created["address_contact_custom_fields"] = _ensure_address_contact_custom_fields(adapter)
    created["fiscal_year"] = _ensure_fiscal_year(adapter, COMPANY_REF)
    created["price_list"] = _ensure_price_list(adapter, "Standard Selling", CURRENCY)
    created["item_group_root"] = _ensure_item_group_root(adapter)
    created["item_group"] = _ensure_item_group(adapter, ITEM_GROUP_REF)
    created["customer_group_root"] = _ensure_customer_group_root(adapter)
    created["customer_group"] = _ensure_customer_group(adapter, CUSTOMER_GROUP_REF)
    created["territory_root"] = _ensure_territory_root(adapter)
    created["territory"] = _ensure_territory(adapter, TERRITORY_REF)
    created["company"] = _ensure_company(adapter, COMPANY_REF, COMPANY_ABBR)
    created["customer"] = _ensure_customer(adapter, CUSTOMER_REF)
    created["item"] = _ensure_item(adapter, ITEM_REF)

    return created


def seed_status(adapter: ErpNextAdapter) -> dict[str, bool]:
    """Check presence of each required entity. Returns name -> exists."""
    return {
        "uom": _exists(adapter, "UOM", UOM_REF),
        "item_group": _exists(adapter, "Item Group", ITEM_GROUP_REF),
        "customer_group": _exists(adapter, "Customer Group", CUSTOMER_GROUP_REF),
        "territory": _exists(adapter, "Territory", TERRITORY_REF),
        "company": _exists(adapter, "Company", COMPANY_REF),
        "customer": _exists(adapter, "Customer", CUSTOMER_REF),
        "item": _exists(adapter, "Item", ITEM_REF),
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _exists(adapter: ErpNextAdapter, doctype: str, name: str) -> bool:
    """Return True if the named doc exists; False on 404."""
    try:
        adapter._get(f"/api/resource/{doctype}/{name}")
        return True
    except DocumentRejected:
        return False


def _create(adapter: ErpNextAdapter, doctype: str, payload: dict[str, Any]) -> None:
    adapter._post(f"/api/resource/{doctype}", payload)


def _ensure_uom(adapter: ErpNextAdapter, name: str) -> bool:
    if _exists(adapter, "UOM", name):
        return False
    _create(adapter, "UOM", {"doctype": "UOM", "uom_name": name})
    return True


def _ensure_warehouse_type(adapter: ErpNextAdapter, name: str) -> bool:
    if _exists(adapter, "Warehouse Type", name):
        return False
    _create(adapter, "Warehouse Type", {"doctype": "Warehouse Type", "name": name})
    return True


def _ensure_selling_settings_customer_name(adapter: ErpNextAdapter) -> bool:
    """Force Customer naming to use `customer_name` field (not naming series).

    ERPNext default names Customers `CUST-.YYYY.-` regardless of the
    `customer_name` we pass. We want the synthetic opaque ref (CUST-ALPHA)
    to BE the document name so the adapter can use it as a stable ref.
    """
    result = adapter._get("/api/resource/Selling Settings/Selling Settings")
    data = result.get("data", {})
    if data.get("cust_master_name") == "Customer Name":
        return False
    adapter._put(
        "/api/resource/Selling Settings/Selling Settings",
        {"cust_master_name": "Customer Name"},
    )
    return True


def _ensure_address_contact_custom_fields(adapter: ErpNextAdapter) -> bool:
    """Ensure Contact.is_billing_contact exists.

    The column is added by `erpnext.setup.install.create_address_and_contact_custom_fields`
    which the setup wizard runs. On a bare pilot site it is missing, causing
    Sales Invoice insert to crash with `Unknown column 'tabContact.is_billing_contact'`.
    We run the install hook via `bench execute` on the backend container.
    Returns True if we invoked the hook, False if the column already exists.
    """
    # Probe: try to read a Contact with the is_billing_contact field.
    # If the column is missing, the query fails with a 500/OperationalError.
    try:
        adapter._get(
            "/api/resource/Contact",
            params={
                "fields": '["name","is_billing_contact"]',
                "limit_page_length": "1",
            },
        )
        return False  # column exists
    except DocumentRejected as e:
        if "is_billing_contact" in str(e):
            # Run the install hook on the backend container
            import subprocess

            subprocess.run(
                [
                    "docker",
                    "exec",
                    "erpnext-pilot-backend",
                    "bench",
                    "--site",
                    "erpnext-pilot.localhost",
                    "execute",
                    "erpnext.setup.install.create_address_and_contact_custom_fields",
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            return True
        raise


def _ensure_fiscal_year(adapter: ErpNextAdapter, company: str) -> bool:
    """Ensure an active Fiscal Year covering today exists for the company."""
    # Check if any active Fiscal Year covers 2026-08-14
    try:
        result = adapter._get(
            "/api/resource/Fiscal Year",
            params={
                "filters": '[["year_start_date","<=","2026-08-14"],["year_end_date",">=","2026-08-14"],["disabled","=",0]]',
                "limit_page_length": "1",
            },
        )
        if result.get("data"):
            return False
    except DocumentRejected:
        pass

    # Create Fiscal Year 2026
    _create(
        adapter,
        "Fiscal Year",
        {
            "doctype": "Fiscal Year",
            "year": "2026",
            "year_start_date": "2026-01-01",
            "year_end_date": "2026-12-31",
            "companies": [{"company": company}],
        },
    )
    return True


def _ensure_price_list(adapter: ErpNextAdapter, name: str, currency: str) -> bool:
    """Ensure a selling Price List exists for the given currency."""
    if _exists(adapter, "Price List", name):
        return False
    _create(
        adapter,
        "Price List",
        {
            "doctype": "Price List",
            "price_list_name": name,
            "currency": currency,
            "buying": 0,
            "selling": 1,
            "enabled": 1,
        },
    )
    return True


def _ensure_item_group_root(adapter: ErpNextAdapter) -> bool:
    if _exists(adapter, "Item Group", "All Item Groups"):
        return False
    _create(
        adapter,
        "Item Group",
        {
            "doctype": "Item Group",
            "item_group_name": "All Item Groups",
            "is_group": 1,
        },
    )
    return True


def _ensure_item_group(adapter: ErpNextAdapter, name: str) -> bool:
    if _exists(adapter, "Item Group", name):
        return False
    _create(
        adapter,
        "Item Group",
        {
            "doctype": "Item Group",
            "item_group_name": name,
            "parent_item_group": "All Item Groups",
            "is_group": 0,
        },
    )
    return True


def _ensure_customer_group_root(adapter: ErpNextAdapter) -> bool:
    if _exists(adapter, "Customer Group", "All Customer Groups"):
        return False
    _create(
        adapter,
        "Customer Group",
        {
            "doctype": "Customer Group",
            "customer_group_name": "All Customer Groups",
            "is_group": 1,
        },
    )
    return True


def _ensure_customer_group(adapter: ErpNextAdapter, name: str) -> bool:
    if _exists(adapter, "Customer Group", name):
        return False
    _create(
        adapter,
        "Customer Group",
        {
            "doctype": "Customer Group",
            "customer_group_name": name,
            "parent_customer_group": "All Customer Groups",
            "is_group": 0,
        },
    )
    return True


def _ensure_territory_root(adapter: ErpNextAdapter) -> bool:
    if _exists(adapter, "Territory", "All Territories"):
        return False
    _create(
        adapter,
        "Territory",
        {
            "doctype": "Territory",
            "territory_name": "All Territories",
            "is_group": 1,
        },
    )
    return True


def _ensure_territory(adapter: ErpNextAdapter, name: str) -> bool:
    if _exists(adapter, "Territory", name):
        return False
    _create(
        adapter,
        "Territory",
        {
            "doctype": "Territory",
            "territory_name": name,
            "parent_territory": "All Territories",
            "is_group": 0,
        },
    )
    return True


def _ensure_company(adapter: ErpNextAdapter, name: str, abbr: str) -> bool:
    if _exists(adapter, "Company", name):
        return False
    _create(
        adapter,
        "Company",
        {
            "doctype": "Company",
            "company_name": name,
            "abbr": abbr,
            "default_currency": CURRENCY,
            "country": COUNTRY,
        },
    )
    return True


def _ensure_customer(adapter: ErpNextAdapter, name: str) -> bool:
    if _exists(adapter, "Customer", name):
        return False
    _create(
        adapter,
        "Customer",
        {
            "doctype": "Customer",
            "customer_name": name,
            "customer_group": CUSTOMER_GROUP_REF,
            "territory": TERRITORY_REF,
        },
    )
    return True


def _ensure_item(adapter: ErpNextAdapter, name: str) -> bool:
    if _exists(adapter, "Item", name):
        return False
    _create(
        adapter,
        "Item",
        {
            "doctype": "Item",
            "item_code": name,
            "item_name": name,
            "item_group": ITEM_GROUP_REF,
            "stock_uom": UOM_REF,
            "is_stock_item": 0,
            "is_sales_item": 1,
        },
    )
    return True
