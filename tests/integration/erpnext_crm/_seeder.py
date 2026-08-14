"""ERPNext CRM seeder for CRM-001 integration fixtures.

Ensures the isolated pilot has the master data and custom fields needed
by the ERPNext CRM adapter contract tests:
- Company UNIT-PR1ME (second unit for isolation testing)
- Lead custom fields: custom_owner_actor_ref, custom_contact_channel,
  custom_contact_handle, custom_archived
- Quotation custom field: custom_crm_total_amount

Idempotent: existing docs are left untouched. NEVER deletes, NEVER
mutates live data.
"""
from __future__ import annotations

from typing import Any

from src.adapters.erpnext import ErpNextAdapter
from src.contracts.erp_port import DocumentRejected, UncertainOutcome


def _exists(adapter: ErpNextAdapter, doctype: str, name: str) -> bool:
    try:
        adapter._get(f"/api/resource/{doctype}/{name}")
        return True
    except DocumentRejected:
        return False


def _create(adapter: ErpNextAdapter, doctype: str, data: dict[str, Any]) -> bool:
    """Create a doc. Returns True if created now, False if it already existed."""
    name = data.get("name") or data.get("company_name") or ""
    if name and _exists(adapter, doctype, str(name)):
        return False
    try:
        adapter._post(f"/api/resource/{doctype}", data)
        return True
    except DocumentRejected as e:
        # Duplicate / link-validation races: treat already-exists as OK.
        if "Duplicate" in str(e) or "already exists" in str(e):
            return False
        raise


def _ensure_company(adapter: ErpNextAdapter, name: str, abbr: str) -> bool:
    if _exists(adapter, "Company", name):
        return False
    return _create(
        adapter,
        "Company",
        {
            "company_name": name,
            "abbr": abbr,
            "default_currency": "IDR",
            "country": "Indonesia",
        },
    )


def _ensure_custom_field(
    adapter: ErpNextAdapter, name: str, data: dict[str, Any]
) -> bool:
    if _exists(adapter, "Custom Field", name):
        return False
    return _create(adapter, "Custom Field", {"name": name, **data})


def seed_crm_master_data(adapter: ErpNextAdapter) -> dict[str, bool]:
    """Seed CRM master data + custom fields into the isolated pilot."""
    created: dict[str, bool] = {}
    created["company_unit_pr1me"] = _ensure_company(adapter, "UNIT-PR1ME", "UP1")
    created["cf_lead_owner"] = _ensure_custom_field(
        adapter,
        "Lead-custom_owner_actor_ref",
        {
            "dt": "Lead",
            "fieldname": "custom_owner_actor_ref",
            "fieldtype": "Data",
            "label": "CRM Owner Actor Ref",
        },
    )
    created["cf_lead_channel"] = _ensure_custom_field(
        adapter,
        "Lead-custom_contact_channel",
        {
            "dt": "Lead",
            "fieldname": "custom_contact_channel",
            "fieldtype": "Data",
            "label": "CRM Contact Channel",
        },
    )
    created["cf_lead_handle"] = _ensure_custom_field(
        adapter,
        "Lead-custom_contact_handle",
        {
            "dt": "Lead",
            "fieldname": "custom_contact_handle",
            "fieldtype": "Data",
            "label": "CRM Contact Handle",
        },
    )
    created["cf_lead_archived"] = _ensure_custom_field(
        adapter,
        "Lead-custom_archived",
        {
            "dt": "Lead",
            "fieldname": "custom_archived",
            "fieldtype": "Check",
            "label": "CRM Archived",
        },
    )
    created["cf_quotation_total"] = _ensure_custom_field(
        adapter,
        "Quotation-custom_crm_total_amount",
        {
            "dt": "Quotation",
            "fieldname": "custom_crm_total_amount",
            "fieldtype": "Data",
            "label": "CRM Total Amount",
        },
    )
    created["cf_quotation_customer_ref"] = _ensure_custom_field(
        adapter,
        "Quotation-custom_crm_customer_ref",
        {
            "dt": "Quotation",
            "fieldname": "custom_crm_customer_ref",
            "fieldtype": "Data",
            "label": "CRM Customer Ref",
        },
    )
    return created


def seed_crm_status(adapter: ErpNextAdapter) -> dict[str, bool]:
    return {
        "company_unit_pr1me": _exists(adapter, "Company", "UNIT-PR1ME"),
        "cf_lead_owner": _exists(adapter, "Custom Field", "Lead-custom_owner_actor_ref"),
        "cf_lead_channel": _exists(
            adapter, "Custom Field", "Lead-custom_contact_channel"
        ),
        "cf_lead_handle": _exists(
            adapter, "Custom Field", "Lead-custom_contact_handle"
        ),
        "cf_lead_archived": _exists(adapter, "Custom Field", "Lead-custom_archived"),
        "cf_quotation_total": _exists(
            adapter, "Custom Field", "Quotation-custom_crm_total_amount"
        ),
        "cf_quotation_customer_ref": _exists(
            adapter, "Custom Field", "Quotation-custom_crm_customer_ref"
        ),
    }
