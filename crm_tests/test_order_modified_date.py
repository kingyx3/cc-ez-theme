from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_order_sync as production_orders
import easystore_hubspot_orders as orders


class HubSpotOrderModifiedDateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_fields = orders.ORDER_FIELDS
        self.original_derivations = dict(orders.ORDER_FIELD_DERIVATIONS)
        self.original_defaults = dict(orders.DEFAULT_ORDER_FIELD_PROPERTIES)
        production_orders.configure_production_order_mapping()

    def tearDown(self) -> None:
        orders.ORDER_FIELDS = self.original_fields
        orders.ORDER_FIELD_DERIVATIONS.clear()
        orders.ORDER_FIELD_DERIVATIONS.update(self.original_derivations)
        orders.DEFAULT_ORDER_FIELD_PROPERTIES = self.original_defaults

    def test_production_mapping_targets_native_external_modified_date(self) -> None:
        modified = next(
            field for field in orders.ORDER_FIELDS if field.key == "modified_at"
        )
        self.assertEqual(
            modified.sources,
            (
                "updated_at",
                "modified_at",
                "updated_on",
                "modified_on",
                "last_modified_at",
            ),
        )
        self.assertEqual(modified.native, ("hs_external_modified_date",))
        self.assertIsNone(modified.fallback)
        self.assertEqual(modified.kind, "datetime")
        self.assertEqual(
            orders.DEFAULT_ORDER_FIELD_PROPERTIES["modified_at"],
            "hs_external_modified_date",
        )

    def test_easystore_updated_at_populates_hubspot_modified_date(self) -> None:
        mapped = orders.order_properties(
            {"updated_at": "2026-08-25T10:20:30+08:00"},
            external_id="1003",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(
            mapped["hs_external_modified_date"],
            "1787624430000",
        )
        self.assertNotIn("hs_lastmodifieddate", mapped)
        self.assertNotIn("easystore_order_modified_at", mapped)

    def test_missing_list_modified_date_forces_one_order_detail_read(self) -> None:
        listed = {
            "id": "1004",
            "line_items": [{"id": "line-1"}],
            "total_price": "20.00",
        }
        detailed = {
            **listed,
            "updated_at": "2026-08-25T11:00:00+08:00",
        }

        with (
            patch.object(
                production_orders,
                "_BASE_COMPLETE_ORDER",
                side_effect=[listed, detailed],
            ) as complete,
            patch.object(orders, "order_needs_detail", return_value=False),
        ):
            result = production_orders.complete_order_with_modified_date(
                "cardboardcollective.easy.co",
                "token",
                listed,
            )

        self.assertEqual(result, detailed)
        self.assertEqual(complete.call_count, 2)
        forced_detail_order = complete.call_args_list[1].args[2]
        self.assertNotIn("line_items", forced_detail_order)

    def test_list_modified_date_avoids_extra_detail_read(self) -> None:
        listed = {
            "id": "1005",
            "updated_at": "2026-08-25T11:00:00+08:00",
        }

        with patch.object(
            production_orders,
            "_BASE_COMPLETE_ORDER",
            return_value=listed,
        ) as complete:
            result = production_orders.complete_order_with_modified_date(
                "cardboardcollective.easy.co",
                "token",
                listed,
            )

        self.assertEqual(result, listed)
        complete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
