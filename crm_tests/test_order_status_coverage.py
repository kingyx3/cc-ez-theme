from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_order_sync as production_orders
import easystore_hubspot_orders as orders


class EasyStoreOrderStatusCoverageTests(unittest.TestCase):
    def test_iterator_reads_all_statuses_and_deduplicates(self) -> None:
        by_status = {
            "open": [{"id": 1, "status": "open"}, {"id": 2, "status": "open"}],
            "cancelled": [{"id": 3, "status": "cancelled"}],
            # Deliberately overlap id=2 to prove a transient API overlap cannot
            # cause the same HubSpot Order to be processed twice.
            "archived": [{"id": 2, "status": "archived"}, {"id": 4, "status": "archived"}],
            "deleted": [{"id": 5, "status": "deleted"}],
        }
        requested_statuses: list[str] = []

        def fake_http(url: str, **kwargs):
            query = parse_qs(urlparse(url).query)
            status = query["status"][0]
            requested_statuses.append(status)
            self.assertEqual(query["page"], ["1"])
            self.assertEqual(query["limit"], [str(orders.EASYSTORE_PAGE_SIZE)])
            self.assertEqual(query["sort"], ["id.asc"])
            self.assertEqual(
                kwargs["headers"],
                {"EasyStore-Access-Token": "easy-token"},
            )
            return {"orders": by_status[status]}

        with patch.object(orders, "_http_json", side_effect=fake_http):
            found = list(
                production_orders.iter_easystore_orders_all_statuses(
                    "shop.easy.co",
                    "easy-token",
                )
            )

        self.assertEqual(
            requested_statuses,
            list(production_orders.EASYSTORE_SYNC_ORDER_STATUSES),
        )
        self.assertEqual(
            production_orders.EASYSTORE_SYNC_ORDER_STATUSES,
            ("open", "cancelled", "archived", "deleted"),
        )
        self.assertEqual([str(order["id"]) for order in found], ["1", "2", "3", "4", "5"])

    def test_main_installs_complete_iterator_only_for_the_run(self) -> None:
        original_iterator = orders.iter_easystore_orders
        observed: list[object] = []

        def fake_core_main(argv):
            observed.append(orders.iter_easystore_orders)
            self.assertEqual(argv, ["--example"])
            return 23

        with patch.object(
            production_orders,
            "_STATUS_COMPLETE_CORE_MAIN",
            side_effect=fake_core_main,
        ):
            result = production_orders.main(["--example"])

        self.assertEqual(result, 23)
        self.assertEqual(observed, [production_orders.iter_easystore_orders_all_statuses])
        self.assertIs(orders.iter_easystore_orders, original_iterator)


if __name__ == "__main__":
    unittest.main()
