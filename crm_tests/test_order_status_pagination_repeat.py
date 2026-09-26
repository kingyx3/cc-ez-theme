from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_order_sync as production_orders
import easystore_hubspot_orders as orders


class EasyStoreOrderStatusPaginationRepeatTests(unittest.TestCase):
    """orders.json has started repeating pages like checkouts.json already does.

    These pin the recovery path added alongside that failure: a repeated page
    under the normal limit is not immediately fatal if one larger-limit
    request can prove the bucket complete, and it still fails loudly when
    even that larger request cannot prove completeness.
    """

    def tearDown(self) -> None:
        production_orders._ORDER_SOURCE_STATUS_BY_ID.clear()

    def test_repeated_page_recovers_via_larger_limit_when_it_proves_complete(self) -> None:
        page_one = [{"id": str(index)} for index in range(1, orders.EASYSTORE_PAGE_SIZE + 1)]
        # A larger single request answers with the whole bucket, including
        # records a 50-per-page fetch never reached before it started
        # repeating page 1.
        large_limit_answer = page_one + [{"id": "extra-1"}, {"id": "extra-2"}]
        large_limit_calls: list[str] = []

        def fake_http(url: str, **kwargs):
            query = parse_qs(urlparse(url).query)
            status = query["status"][0]
            self.assertEqual(status, "open")
            limit = int(query["limit"][0])
            page = int(query["page"][0])
            if limit == orders.EASYSTORE_PAGE_SIZE:
                # Every page comes back identical: the page parameter does
                # nothing, exactly like checkouts.json.
                return {"orders": page_one}
            large_limit_calls.append(f"page={page}&limit={limit}")
            self.assertEqual(page, 1)
            self.assertEqual(limit, production_orders._LARGE_ORDER_PAGE_LIMIT)
            return {"orders": large_limit_answer}

        def other_status(status: str) -> list[dict[str, str]]:
            return []

        def fake_http_all_statuses(url: str, **kwargs):
            query = parse_qs(urlparse(url).query)
            if query["status"][0] != "open":
                return {"orders": []}
            return fake_http(url, **kwargs)

        stderr = io.StringIO()
        with patch.object(orders, "_http_json", side_effect=fake_http_all_statuses):
            with redirect_stderr(stderr):
                found = list(
                    production_orders.iter_easystore_orders_all_statuses(
                        "shop.easy.co",
                        "easy-token",
                    )
                )

        self.assertEqual(len(large_limit_calls), 1)
        self.assertEqual(
            [order["id"] for order in found],
            [str(index) for index in range(1, orders.EASYSTORE_PAGE_SIZE + 1)]
            + ["extra-1", "extra-2"],
        )
        self.assertIn("recovered the complete bucket", stderr.getvalue())

    def test_repeated_page_still_fails_when_larger_limit_is_also_saturated(self) -> None:
        page_one = [{"id": str(index)} for index in range(1, orders.EASYSTORE_PAGE_SIZE + 1)]
        saturated_large_answer = [
            {"id": str(index)}
            for index in range(1, production_orders._LARGE_ORDER_PAGE_LIMIT + 1)
        ]

        def fake_http(url: str, **kwargs):
            query = parse_qs(urlparse(url).query)
            if query["status"][0] != "open":
                return {"orders": []}
            limit = int(query["limit"][0])
            if limit == orders.EASYSTORE_PAGE_SIZE:
                return {"orders": page_one}
            return {"orders": saturated_large_answer}

        with patch.object(orders, "_http_json", side_effect=fake_http):
            with self.assertRaisesRegex(
                orders.SyncError,
                "cannot be proven",
            ):
                list(
                    production_orders.iter_easystore_orders_all_statuses(
                        "shop.easy.co",
                        "easy-token",
                    )
                )


if __name__ == "__main__":
    unittest.main()
