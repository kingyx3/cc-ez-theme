from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_ordered_products as ordered_products
import easystore_hubspot_products as products


class OrderedProductSyncTests(unittest.TestCase):
    def test_ordered_variant_skus_include_real_and_synthetic_order_line_skus(self) -> None:
        order = {
            "id": 99,
            "line_items": [
                {"sku": "SKU-1"},
                {"product_id": 10, "variant_id": 20},
            ],
        }

        with patch.object(
            ordered_products.order_sync,
            "iter_easystore_orders_all_statuses",
            return_value=iter([order]),
        ), patch.object(
            ordered_products.orders,
            "complete_order",
            return_value=order,
        ):
            skus, orders_scanned, lines_scanned = ordered_products.ordered_variant_skus(
                "shop.easy.co",
                "token",
            )

        self.assertEqual(skus, {"sku-1", "es-10-20"})
        self.assertEqual(orders_scanned, 1)
        self.assertEqual(lines_scanned, 2)

    def test_sync_excludes_variants_that_never_appeared_on_an_order(self) -> None:
        variants = [
            {"id": 1, "sku": "SOLD"},
            {"id": 2, "sku": "NEVER-SOLD"},
        ]
        selected: list[dict[str, object]] = []

        def fake_product_sync(**_kwargs):
            selected.extend(
                products.product_variants(
                    "shop.easy.co",
                    "easy-token",
                    {"id": 10, "title": "Card"},
                )
            )
            return {"created": 1, "updated": 0}

        with patch.object(
            ordered_products,
            "ordered_variant_snapshots",
            return_value=({"sold": {"sku": "SOLD", "line": {"sku": "SOLD"}}}, 3, 5),
        ), patch.object(
            products,
            "product_variants",
            return_value=variants,
        ) as base_product_variants, patch.object(
            products,
            "sync",
            side_effect=fake_product_sync,
        ):
            summary = ordered_products.sync(
                store_domain="shop.easy.co",
                easystore_access_token="easy-token",
                hubspot_access_token="hubspot-token",
            )
            self.assertIs(products.product_variants, base_product_variants)

        self.assertEqual([variant["sku"] for variant in selected], ["SOLD"])
        self.assertEqual(summary["ordered_product_skus"], 1)
        self.assertEqual(summary["easystore_orders_scanned_for_product_filter"], 3)
        self.assertEqual(summary["easystore_order_lines_scanned_for_product_filter"], 5)
        self.assertEqual(summary["easystore_variants_without_orders_skipped"], 1)
        self.assertEqual(summary["historical_order_products_from_snapshots"], 0)

    def test_sync_creates_inactive_product_from_historical_order_snapshot(self) -> None:
        captured_products: list[dict[str, object]] = []
        captured_properties: list[dict[str, str]] = []

        def fake_product_sync(**_kwargs):
            mapping = products.ProductStatusMapping("hs_status", "active", "inactive")
            for product in products.iter_easystore_products("shop.easy.co", "easy-token"):
                captured_products.append(product)
                product_id = products.nonempty(product.get("id"))
                self.assertIsNotNone(product_id)
                for variant in products.product_variants(
                    "shop.easy.co",
                    "easy-token",
                    product,
                ):
                    sku, _synthetic = products.variant_sku(product_id, variant)
                    captured_properties.append(
                        products.variant_properties(
                            product,
                            variant,
                            sku,
                            field_properties={
                                field.key: field.fallback
                                for field in ordered_products.PRODUCT_SOURCE_DATE_FIELDS
                                if field.fallback is not None
                            },
                            status_mapping=mapping,
                        )
                    )
            return {"created": 1, "updated": 0}

        snapshot = {
            "sku": "RETIRED-SKU",
            "line": {
                "sku": "RETIRED-SKU",
                "title": "Retired Card",
                "price": "19.90",
            },
        }
        with patch.object(
            ordered_products,
            "ordered_variant_snapshots",
            return_value=({"retired-sku": snapshot}, 1, 1),
        ), patch.object(
            products,
            "iter_easystore_products",
            return_value=iter([]),
        ) as base_product_iterator, patch.object(
            products,
            "sync",
            side_effect=fake_product_sync,
        ):
            summary = ordered_products.sync(
                store_domain="shop.easy.co",
                easystore_access_token="easy-token",
                hubspot_access_token="hubspot-token",
            )
            self.assertIs(products.iter_easystore_products, base_product_iterator)

        self.assertEqual(len(captured_products), 1)
        self.assertTrue(captured_products[0]["easystore_historical_order_snapshot"])
        self.assertEqual(captured_properties[0]["name"], "Retired Card")
        self.assertEqual(captured_properties[0]["hs_sku"], "RETIRED-SKU")
        self.assertEqual(captured_properties[0]["price"], "19.90")
        self.assertEqual(captured_properties[0]["hs_status"], "inactive")
        self.assertNotIn("easystore_product_created_at", captured_properties[0])
        self.assertNotIn("easystore_product_modified_at", captured_properties[0])
        self.assertEqual(summary["historical_order_products_from_snapshots"], 1)
        self.assertEqual(summary["historical_order_product_skus"], ["RETIRED-SKU"])

    def test_sync_writes_easystore_product_source_timestamps(self) -> None:
        original_fields = products.PRODUCT_FIELDS
        captured_properties: dict[str, str] = {}

        def fake_product_sync(**_kwargs):
            field_properties = {
                field.key: field.fallback
                for field in ordered_products.PRODUCT_SOURCE_DATE_FIELDS
                if field.fallback is not None
            }
            captured_properties.update(
                products.variant_properties(
                    {
                        "id": 10,
                        "title": "Card",
                        "created_at": "2026-08-20T10:15:30+08:00",
                        "updated_at": "2026-08-23T18:45:00+08:00",
                    },
                    {"id": 20, "sku": "SOLD"},
                    "SOLD",
                    field_properties=field_properties,
                )
            )
            return {"created": 0, "updated": 1}

        with patch.object(
            ordered_products,
            "ordered_variant_snapshots",
            return_value=({"sold": {"sku": "SOLD", "line": {"sku": "SOLD"}}}, 1, 1),
        ), patch.object(products, "sync", side_effect=fake_product_sync):
            ordered_products.sync(
                store_domain="shop.easy.co",
                easystore_access_token="easy-token",
                hubspot_access_token="hubspot-token",
            )

        created = str(
            int(datetime.fromisoformat("2026-08-20T10:15:30+08:00").timestamp() * 1000)
        )
        modified = str(
            int(datetime.fromisoformat("2026-08-23T18:45:00+08:00").timestamp() * 1000)
        )
        self.assertEqual(captured_properties["easystore_product_created_at"], created)
        self.assertEqual(captured_properties["easystore_product_modified_at"], modified)
        self.assertIs(products.PRODUCT_FIELDS, original_fields)

    def test_product_source_date_fields_are_dedicated_datetime_properties(self) -> None:
        created, modified = ordered_products.PRODUCT_SOURCE_DATE_FIELDS

        self.assertEqual(created.sources, ("created_at", "created_on"))
        self.assertEqual(created.fallback, "easystore_product_created_at")
        self.assertEqual(created.kind, "datetime")
        self.assertEqual(
            modified.sources,
            ("updated_at", "modified_at", "updated_on", "modified_on"),
        )
        self.assertEqual(modified.fallback, "easystore_product_modified_at")
        self.assertEqual(modified.kind, "datetime")


if __name__ == "__main__":
    unittest.main()