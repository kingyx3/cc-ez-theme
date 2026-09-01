from __future__ import annotations

import sys
import unittest
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
            "ordered_variant_skus",
            return_value=({"sold"}, 3, 5),
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


if __name__ == "__main__":
    unittest.main()
