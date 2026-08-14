"""Tests for ui/reports/owner view-model and renderer (RPT-001)."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from src.adapters.fixture.erp import FixtureErpAdapter
from src.reports.owner.roll_up import OwnerRollupReport
from ui.reports.owner.roll_up_view import (
    OwnerRollupView,
    build_view,
    render_text,
    to_export_dict,
)

from tests.reports.owner.test_roll_up import (
    _owner_assignment,
    _owner_binding,
    _seed_invoice,
    _seed_payment,
    _t,
)


def _report_with_two_units() -> OwnerRollupReport:
    adapter = FixtureErpAdapter()
    _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                  amount="1000", currency="IDR")
    _seed_invoice(adapter, unit_ref="UNIT-PR1ME", customer_ref="C2",
                  amount="2000", currency="IDR")
    return OwnerRollupReport(adapter=adapter)


class TestOwnerRollupView(unittest.TestCase):
    def test_build_view_exposes_per_unit_rows(self) -> None:
        report = _report_with_two_units()
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment("UNIT-PR1ME"),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        view = build_view(result)
        self.assertIsInstance(view, OwnerRollupView)
        self.assertEqual(len(view.rows), 2)
        self.assertEqual(view.currency, "IDR")
        self.assertEqual(view.owner_open_amount_total, "3000")
        self.assertTrue(view.scoped)
        units = {row["unit_ref"] for row in view.rows}
        self.assertEqual(units, {"UNIT-BANYUMEDIA", "UNIT-PR1ME"})

    def test_render_text_contains_per_unit_and_total(self) -> None:
        report = _report_with_two_units()
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment("UNIT-PR1ME"),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        text = render_text(build_view(result))
        self.assertIn("UNIT-BANYUMEDIA", text)
        self.assertIn("UNIT-PR1ME", text)
        self.assertIn("Owner total: 3000 IDR", text)
        self.assertIn("As of:", text)

    def test_render_text_handles_mixed_currencies(self) -> None:
        adapter = FixtureErpAdapter()
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C1",
                      amount="1000", currency="IDR")
        _seed_invoice(adapter, unit_ref="UNIT-BANYUMEDIA", customer_ref="C2",
                      amount="50", currency="USD")
        report = OwnerRollupReport(adapter=adapter)
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(_owner_assignment("UNIT-BANYUMEDIA"),),
            channel_ref="CHANNEL-WA-1",
        )
        text = render_text(build_view(result))
        self.assertIn("mixed currencies", text.lower())
        self.assertIn("IDR", text)
        self.assertIn("USD", text)

    def test_to_export_dict_is_json_serializable(self) -> None:
        report = _report_with_two_units()
        result = report.query_rollup(
            actor_ref="ACTOR-OWNER",
            at=_t(10),
            binding=_owner_binding(),
            assignments=(
                _owner_assignment("UNIT-BANYUMEDIA"),
                _owner_assignment("UNIT-PR1ME"),
            ),
            channel_ref="CHANNEL-WA-1",
        )
        payload = to_export_dict(build_view(result))
        # Must serialize; if it does, it's redacted + opaque by construction
        encoded = json.dumps(payload)
        self.assertIn("UNIT-BANYUMEDIA", encoded)
        self.assertIn("owner_open_amount_total", encoded)
        self.assertEqual(payload["scoped"], True)

    def test_build_view_rejects_wrong_type(self) -> None:
        with self.assertRaises(TypeError):
            build_view(object())  # type: ignore[arg-type]

    def test_render_text_rejects_wrong_type(self) -> None:
        with self.assertRaises(TypeError):
            render_text(object())  # type: ignore[arg-type]

    def test_to_export_dict_rejects_wrong_type(self) -> None:
        with self.assertRaises(TypeError):
            to_export_dict(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
