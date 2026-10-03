import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import easystore_hubspot_products as products


class ProductInventoryTests(unittest.TestCase):
    def test_variant_inventory_is_written_to_resolved_property(self):
        props = products.variant_properties(
            {"id": 1, "title": "Box"},
            {"id": 2, "sku": "BOX-1", "inventory_quantity": 17},
            "BOX-1",
            field_properties={"inventory_quantity": "easystore_inventory_quantity"},
        )
        self.assertEqual(props["easystore_inventory_quantity"], "17")

    def test_zero_stock_is_synchronized(self):
        props = products.variant_properties(
            {"id": 1, "title": "Box"},
            {"id": 2, "sku": "BOX-1", "inventory_quantity": 0},
            "BOX-1",
            field_properties={"inventory_quantity": "easystore_inventory_quantity"},
        )
        self.assertEqual(props["easystore_inventory_quantity"], "0")

    def test_missing_inventory_leaves_property_untouched(self):
        props = products.variant_properties(
            {"id": 1, "title": "Box"},
            {"id": 2, "sku": "BOX-1"},
            "BOX-1",
            field_properties={"inventory_quantity": "easystore_inventory_quantity"},
        )
        self.assertNotIn("easystore_inventory_quantity", props)


if __name__ == "__main__":
    unittest.main()
