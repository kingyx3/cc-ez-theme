from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_orders as orders
import easystore_hubspot_preflight as preflight
import easystore_hubspot_products as products
import easystore_hubspot_reconcile as reconcile
import easystore_hubspot_sync as customers


class MobileNormalizationTests(unittest.TestCase):
    def test_singapore_local_mobile_gets_country_code(self) -> None:
        self.assertEqual(
            customers.normalize_mobile("9123 4567", "SG", "65"),
            "+6591234567",
        )

    def test_explicit_international_mobile_is_preserved(self) -> None:
        self.assertEqual(
            customers.normalize_mobile("+60 12-345 6789", "SG", "65"),
            "+60123456789",
        )

    def test_00_international_prefix_is_supported(self) -> None:
        self.assertEqual(
            orders.normalize_mobile("0060123456789", "SG", "65"),
            "+60123456789",
        )

    def test_unusable_phone_is_rejected(self) -> None:
        self.assertIsNone(customers.normalize_mobile("123", "SG", "65"))


class IdentityPreflightTests(unittest.TestCase):
    def test_duplicate_owners_only_returns_real_collisions(self) -> None:
        owners = {
            "+6591111111": {"1"},
            "+6592222222": {"2", "3"},
            "+6593333333": {"4", "4"},
        }
        self.assertEqual(
            preflight.ambiguous_owners(owners),
            {"+6592222222": {"2", "3"}},
        )


class ProductMappingTests(unittest.TestCase):
    def test_variant_sku_uses_real_sku(self) -> None:
        self.assertEqual(
            products.variant_sku("10", {"id": 20, "sku": "ABC-1"}),
            ("ABC-1", False),
        )

    def test_variant_sku_is_stable_when_easystore_sku_is_blank(self) -> None:
        self.assertEqual(
            products.variant_sku("10", {"id": 20, "sku": ""}),
            ("ES-10-20", True),
        )


class OrderLineMappingTests(unittest.TestCase):
    def test_line_sku_falls_back_to_product_and_variant_ids(self) -> None:
        self.assertEqual(
            orders._line_sku({"product_id": 10, "variant_id": 20}),
            "ES-10-20",
        )

    def test_desired_lines_are_product_backed_and_group_same_sku(self) -> None:
        order = {
            "id": 99,
            "currency": "SGD",
            "line_items": [
                {"sku": "ABC", "title": "Alpha", "quantity": 1, "price": "12.50"},
                {"sku": "ABC", "title": "Alpha", "quantity": 2, "price": "12.50"},
            ],
        }
        desired = orders.desired_lines(order, {"abc": "777"})
        self.assertEqual(set(desired), {"abc"})
        self.assertEqual(desired["abc"]["hs_product_id"], "777")
        self.assertEqual(desired["abc"]["quantity"], "3")
        self.assertEqual(desired["abc"]["price"], "12.50")
        self.assertEqual(desired["abc"]["hs_line_item_currency_code"], "SGD")

    def test_different_prices_for_same_sku_fail_closed(self) -> None:
        order = {
            "id": 99,
            "line_items": [
                {"sku": "ABC", "quantity": 1, "price": "10"},
                {"sku": "ABC", "quantity": 1, "price": "9"},
            ],
        }
        with self.assertRaises(orders.SyncError):
            orders.desired_lines(order, {"abc": "777"})

    def test_missing_product_fails_instead_of_creating_standalone_line(self) -> None:
        order = {
            "id": 99,
            "line_items": [{"sku": "MISSING", "quantity": 1, "price": "10"}],
        }
        with self.assertRaises(orders.SyncError):
            orders.desired_lines(order, {})


class ReconciliationTests(unittest.TestCase):
    def test_only_stale_product_backed_lines_are_archived(self) -> None:
        existing = {
            "keep": {
                "id": "1",
                "properties": {"hs_sku": "KEEP", "hs_product_id": "10"},
            },
            "stale": {
                "id": "2",
                "properties": {"hs_sku": "STALE", "hs_product_id": "20"},
            },
            "manual": {
                "id": "3",
                "properties": {"hs_sku": "MANUAL", "hs_product_id": None},
            },
        }
        desired = {
            "keep": {
                "hs_sku": "KEEP",
                "hs_product_id": "10",
                "name": "Keep",
                "quantity": "1",
            }
        }
        self.assertEqual(
            reconcile.stale_product_backed_line_ids(existing, desired),
            ["2"],
        )


class OrderPropertyTests(unittest.TestCase):
    def test_order_properties_include_shipping_and_tracking(self) -> None:
        mapped = orders.order_properties(
            {
                "name": "#1001",
                "currency": "sgd",
                "fulfillment_status": "fulfilled",
                "shipping_address": {
                    "address1": "1 Example Road",
                    "address2": "#02-03",
                    "city": "Singapore",
                    "zip": "123456",
                },
                "fulfillments": [
                    {
                        "tracking_number": "TRACK1",
                        "tracking_url": "https://tracking.example/TRACK1",
                    }
                ],
            },
            external_id="1001",
            store_domain="https://cardboardcollective.easy.co/",
        )
        self.assertEqual(mapped["easystore_order_id"], "1001")
        self.assertEqual(mapped["hs_currency_code"], "SGD")
        self.assertEqual(mapped["hs_source_store"], "cardboardcollective.easy.co")
        self.assertEqual(
            mapped["hs_shipping_address_street"],
            "1 Example Road\n#02-03",
        )
        self.assertEqual(mapped["hs_shipping_tracking_number"], "TRACK1")


if __name__ == "__main__":
    unittest.main()
