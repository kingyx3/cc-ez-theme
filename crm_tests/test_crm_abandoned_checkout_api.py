from __future__ import annotations

from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_abandoned_checkouts as abandoned
from easystore_hubspot_orders import SyncError


class AbandonedCheckoutApiTests(unittest.TestCase):
    FIXED_NOW = datetime(2026, 8, 21, 10, 0, 0, tzinfo=timezone.utc)

    def test_window_matches_easystore_ninety_day_abandoned_checkout_retention(self) -> None:
        self.assertEqual(
            abandoned.checkout_window_start(self.FIXED_NOW),
            "2026-05-23 10:00:00",
        )

    def test_collection_uses_checkout_api_recent_window_small_page_and_stable_sort(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_http(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return {"checkouts": []}

        with mock.patch.object(abandoned, "_http_json", fake_http):
            snapshot = abandoned.read_abandoned_checkout_snapshot(
                "shop.example",
                "es",
                now=self.FIXED_NOW,
            )

        self.assertEqual(snapshot.records, ())
        self.assertEqual(snapshot.page_size, 10)
        self.assertEqual(snapshot.listed_count, 0)
        self.assertEqual(len(calls), 1)
        parsed = urlparse(str(calls[0]["url"]))
        self.assertEqual(parsed.path, "/api/3.0/checkouts.json")
        query = parse_qs(parsed.query)
        self.assertEqual(query["page"], ["1"])
        self.assertEqual(query["limit"], ["10"])
        self.assertEqual(query["sort"], ["id.desc"])
        self.assertEqual(query["created_at_min"], ["2026-05-23 10:00:00"])
        self.assertEqual(calls[0]["timeout"], 15)
        self.assertEqual(calls[0]["retries"], 0)

    def test_paid_or_completed_checkouts_are_not_sent_to_cart_sync(self) -> None:
        response = {
            "checkouts": [
                {
                    "cart_token": "abandoned-1",
                    "financial_status": "unpaid",
                    "line_items": [],
                },
                {
                    "cart_token": "paid-1",
                    "financial_status": "paid",
                    "line_items": [],
                },
                {
                    "cart_token": "completed-1",
                    "completed_at": "2026-08-20T10:00:00+08:00",
                    "line_items": [],
                },
            ]
        }
        with mock.patch.object(abandoned, "_http_json", return_value=response):
            snapshot = abandoned.read_abandoned_checkout_snapshot(
                "shop.example",
                "es",
                now=self.FIXED_NOW,
            )

        self.assertEqual(snapshot.listed_count, 3)
        self.assertEqual(
            [record["cart_token"] for record in snapshot.records],
            ["abandoned-1"],
        )

    def test_missing_lines_hydrates_real_checkout_by_cart_token_only_for_abandoned(self) -> None:
        calls: list[str] = []

        def fake_http(url, **kwargs):
            calls.append(url)
            if "/checkouts.json?" in url:
                return {
                    "checkouts": [
                        {"cart_token": "cart/a", "financial_status": "unpaid"},
                        {"cart_token": "paid", "financial_status": "paid"},
                    ]
                }
            return {
                "checkout": {
                    "cart_token": "cart/a",
                    "financial_status": "unpaid",
                    "line_items": [{"sku": "SKU-1", "quantity": 2}],
                }
            }

        with mock.patch.object(abandoned, "_http_json", fake_http):
            snapshot = abandoned.read_abandoned_checkout_snapshot(
                "shop.example",
                "es",
                now=self.FIXED_NOW,
            )

        self.assertEqual(snapshot.details_fetched, 1)
        self.assertEqual(len(snapshot.records), 1)
        self.assertEqual(snapshot.records[0]["line_items"][0]["sku"], "SKU-1")
        self.assertEqual(
            calls[1],
            "https://shop.example/api/3.0/checkouts/cart%2Fa.json",
        )
        self.assertEqual(len(calls), 2)

    def test_collection_timeout_restarts_snapshot_with_smaller_page(self) -> None:
        requested_limits: list[str] = []

        def fake_http(url, **kwargs):
            parsed = urlparse(url)
            if parsed.path.endswith("checkouts.json"):
                limit = parse_qs(parsed.query)["limit"][0]
                requested_limits.append(limit)
                if limit == "10":
                    raise SyncError("read operation timed out")
                return {"checkouts": []}
            raise AssertionError(url)

        with mock.patch.object(abandoned, "_http_json", fake_http):
            snapshot = abandoned.read_abandoned_checkout_snapshot(
                "shop.example",
                "es",
                now=self.FIXED_NOW,
            )

        self.assertEqual(requested_limits, ["10", "5"])
        self.assertEqual(snapshot.page_size, 5)

    def test_persistent_checkout_api_failure_is_visible_not_a_green_empty_sync(self) -> None:
        with mock.patch.object(
            abandoned,
            "_http_json",
            side_effect=SyncError("read operation timed out"),
        ):
            with self.assertRaisesRegex(
                SyncError, "could not be read with any safe page size"
            ):
                abandoned.read_abandoned_checkout_snapshot(
                    "shop.example",
                    "es",
                    now=self.FIXED_NOW,
                )

    def test_sync_passes_only_checkout_snapshot_and_reports_orders_are_not_source(self) -> None:
        snapshot = abandoned.CheckoutSnapshot(
            records=(
                {
                    "cart_token": "cart-1",
                    "financial_status": "unpaid",
                    "line_items": [],
                },
            ),
            pages_read=1,
            details_fetched=0,
            listed_count=2,
            page_size=5,
            created_at_min="2026-05-23 10:00:00",
        )

        def fake_sync(**kwargs):
            records = list(
                abandoned.commerce.iter_documented_checkouts(
                    kwargs["store_domain"], kwargs["easystore_access_token"]
                )
            )
            return {
                "easystore_checkouts_scanned": len(records),
                "hubspot_carts_created": len(records),
            }

        with mock.patch.object(
            abandoned,
            "read_abandoned_checkout_snapshot",
            return_value=snapshot,
        ), mock.patch.object(abandoned.commerce, "sync", fake_sync):
            summary = abandoned.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertEqual(summary["easystore_checkouts_scanned"], 1)
        self.assertEqual(summary["hubspot_carts_created"], 1)
        self.assertEqual(summary["easystore_abandoned_checkout_source"], "checkouts")
        self.assertFalse(summary["cart_source_is_orders"])
        self.assertEqual(summary["easystore_checkouts_listed"], 2)
        self.assertEqual(summary["easystore_abandoned_checkouts_buffered"], 1)


if __name__ == "__main__":
    unittest.main()
