from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_commerce_safe as safe


class HubSpotCartSchemaContractTests(unittest.TestCase):
    def test_cart_objects_are_plural_but_schema_object_type_is_singular(self) -> None:
        safe._validate_hubspot_cart_endpoint()

        self.assertEqual(
            safe.commerce.HUBSPOT_CARTS_URL,
            "https://api.hubapi.com/crm/v3/objects/carts",
        )
        self.assertEqual(safe.commerce.CART_SCHEMA_OBJECT_TYPE, "cart")

        summary = safe._endpoint_summary("shop.example")
        self.assertEqual(
            summary["hubspot_cart_collection_endpoint"],
            "https://api.hubapi.com/crm/v3/objects/carts",
        )
        self.assertEqual(
            summary["hubspot_cart_properties_endpoint"],
            "https://api.hubapi.com/crm/v3/properties/cart",
        )
        self.assertEqual(summary["hubspot_cart_schema_object_type"], "cart")


if __name__ == "__main__":
    unittest.main()
