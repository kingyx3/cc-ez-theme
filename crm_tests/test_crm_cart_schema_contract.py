from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_checkouts as checkouts


class HubSpotCartSchemaContractTests(unittest.TestCase):
    def test_cart_objects_are_plural_but_schema_object_type_is_singular(self) -> None:
        checkouts._validate_hubspot_cart_contract()

        self.assertEqual(
            checkouts.commerce.HUBSPOT_CARTS_URL,
            "https://api.hubapi.com/crm/v3/objects/carts",
        )

        summary = checkouts._endpoint_summary("shop.example")
        self.assertEqual(
            summary["hubspot_cart_collection_endpoint"],
            "https://api.hubapi.com/crm/v3/objects/carts",
        )
        self.assertEqual(
            summary["hubspot_cart_properties_endpoint"],
            "https://api.hubapi.com/crm/v3/properties/cart",
        )
        self.assertEqual(summary["hubspot_cart_schema_object_type"], "cart")

    def test_the_core_module_is_not_mutated_to_carry_the_schema_type(self) -> None:
        # The wrapper used to patch module globals to reach the singular schema
        # type, which leaked into any later caller in the same process.
        self.assertEqual(checkouts.commerce.CART_SCHEMA_OBJECT_TYPE, "carts")


if __name__ == "__main__":
    unittest.main()
