from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_order_sync as production_orders
import easystore_hubspot_reconcile as reconcile


class TerminalOrderReconciliationTests(unittest.TestCase):
    def tearDown(self) -> None:
        production_orders._ORDER_SOURCE_STATUS_BY_ID.clear()

    def test_retired_source_sku_is_not_archived_from_terminal_history(self) -> None:
        existing = {
            "sku30": {
                "id": "line-30",
                "properties": {
                    "hs_sku": "sku30",
                    "hs_product_id": "retired-product-30",
                },
            },
            "actually-removed": {
                "id": "line-old",
                "properties": {
                    "hs_sku": "ACTUALLY-REMOVED",
                    "hs_product_id": "product-old",
                },
            },
        }

        stale = reconcile.stale_product_backed_line_ids(
            existing,
            {},
            preserve_skus={"sku30"},
        )

        self.assertEqual(stale, ["line-old"])

    def test_deleted_order_with_retired_product_reconciles_without_archiving_it(self) -> None:
        source_order = {
            "id": 112647657,
            "currency": "SGD",
            "line_items": [
                {
                    "sku": "sku30",
                    "title": "Retired product",
                    "quantity": 1,
                    "price": "30.00",
                }
            ],
        }
        existing = {
            "sku30": {
                "id": "line-30",
                "properties": {
                    "hs_sku": "sku30",
                    "hs_product_id": "retired-product-30",
                },
            }
        }
        deleted_urls: list[str] = []

        def fake_iter(_domain, _token):
            production_orders._ORDER_SOURCE_STATUS_BY_ID["112647657"] = "deleted"
            yield source_order

        def fake_http(url, *, method="GET", **kwargs):
            if method == "DELETE":
                deleted_urls.append(url)
            return {}

        with patch.object(
            reconcile.production_orders,
            "iter_easystore_orders_all_statuses",
            side_effect=fake_iter,
        ), patch.object(
            reconcile,
            "hubspot_product_index",
            return_value={},
        ), patch.object(
            reconcile,
            "hubspot_order_index",
            return_value={"112647657": "hs-order-1"},
        ), patch.object(
            reconcile,
            "complete_order",
            side_effect=lambda _domain, _token, order, **kwargs: order,
        ), patch.object(
            reconcile,
            "_existing_order_line_items",
            return_value=existing,
        ), patch.object(
            reconcile,
            "_http_json",
            side_effect=fake_http,
        ):
            summary = reconcile.reconcile(
                store_domain="shop.easy.co",
                easystore_access_token="easy-token",
                hubspot_access_token="hs-token",
            )

        self.assertEqual(summary["easystore_orders_scanned"], 1)
        self.assertEqual(
            summary["terminal_order_lines_without_active_hubspot_product"],
            1,
        )
        self.assertEqual(summary["stale_product_backed_line_items_archived"], 0)
        self.assertEqual(deleted_urls, [])


if __name__ == "__main__":
    unittest.main()
