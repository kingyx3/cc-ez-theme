from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_commerce_safe as safe
from easystore_hubspot_orders import SyncError


class CheckoutEndpointContractTests(unittest.TestCase):
    def test_collection_uses_documented_checkout_endpoint_and_max_page_size(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_http(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return {"checkouts": []}

        with mock.patch.object(safe, "_http_json", fake_http):
            snapshot = safe.read_checkout_snapshot("shop.example", "es")

        self.assertEqual(snapshot.records, ())
        self.assertEqual(snapshot.pages_read, 1)
        self.assertEqual(snapshot.details_fetched, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["retries"], safe.CHECKOUT_READ_RETRIES)
        self.assertEqual(calls[0]["timeout"], safe.CHECKOUT_READ_TIMEOUT_SECONDS)
        self.assertEqual(
            calls[0]["url"],
            "https://shop.example/api/3.0/checkouts.json?page=1&limit=50",
        )

    def test_detail_uses_cart_token_endpoint_and_hydrates_line_items(self) -> None:
        calls: list[str] = []

        def fake_http(url, **kwargs):
            calls.append(url)
            if url.endswith("checkouts.json?page=1&limit=50"):
                return {"checkouts": [{"id": 99, "cart_token": "cart/a"}]}
            return {
                "checkout": {
                    "cart_token": "cart/a",
                    "line_items": [{"sku": "SKU-1", "quantity": 2}],
                }
            }

        with mock.patch.object(safe, "_http_json", fake_http):
            snapshot = safe.read_checkout_snapshot("shop.example", "es")

        self.assertEqual(snapshot.pages_read, 1)
        self.assertEqual(snapshot.details_fetched, 1)
        self.assertEqual(snapshot.records[0]["id"], 99)
        self.assertEqual(snapshot.records[0]["line_items"][0]["sku"], "SKU-1")
        self.assertEqual(
            calls[1],
            "https://shop.example/api/3.0/checkouts/cart%2Fa.json",
        )

    def test_unknown_collection_shape_is_not_treated_as_empty_store(self) -> None:
        with mock.patch.object(safe, "_http_json", return_value={"products": []}):
            with self.assertRaisesRegex(SyncError, "without a checkout collection"):
                safe.read_checkout_snapshot("shop.example", "es")

    def test_checkout_detail_without_line_items_is_not_safe_to_reconcile(self) -> None:
        responses = iter(
            [
                {"checkouts": [{"cart_token": "cart-1"}]},
                {"checkout": {"cart_token": "cart-1"}},
            ]
        )
        with mock.patch.object(safe, "_http_json", side_effect=lambda *a, **k: next(responses)):
            with self.assertRaisesRegex(SyncError, "omitted line_items"):
                safe.read_checkout_snapshot("shop.example", "es")

    def test_hubspot_cart_endpoint_matches_current_carts_api(self) -> None:
        safe._validate_hubspot_cart_endpoint()
        self.assertEqual(
            safe.commerce.HUBSPOT_CARTS_URL,
            "https://api.hubapi.com/crm/v3/objects/carts",
        )


class CheckoutSnapshotSafetyTests(unittest.TestCase):
    def test_later_page_failure_does_not_expose_partial_checkout_data(self) -> None:
        first_page = [
            {"cart_token": f"cart-{index}", "line_items": []}
            for index in range(safe.CHECKOUT_PAGE_SIZE)
        ]
        calls = 0

        def fake_http(url, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"checkouts": first_page}
            raise SyncError("second page timed out")

        with mock.patch.object(safe, "_http_json", fake_http):
            with self.assertRaisesRegex(SyncError, "second page timed out"):
                safe.read_checkout_snapshot("shop.example", "es")

    def test_detail_failure_invalidates_the_whole_snapshot(self) -> None:
        responses = iter(
            [
                {
                    "checkouts": [
                        {"cart_token": "cart-1", "line_items": []},
                        {"cart_token": "cart-2"},
                    ]
                },
                SyncError("checkout detail timed out"),
            ]
        )

        def fake_http(*args, **kwargs):
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value

        with mock.patch.object(safe, "_http_json", fake_http):
            with self.assertRaisesRegex(SyncError, "detail timed out"):
                safe.read_checkout_snapshot("shop.example", "es")


class CheckoutOutageBehaviorTests(unittest.TestCase):
    def test_timeout_skips_cart_upserts_but_keeps_order_link_refresh(self) -> None:
        link_summary = {
            "easystore_orders_scanned_for_cart_links": 7,
            "cart_order_associations_ensured": 2,
        }
        with mock.patch.object(
            safe,
            "read_checkout_snapshot",
            side_effect=SyncError("The read operation timed out"),
        ), mock.patch.object(
            safe,
            "link_existing_carts_to_orders",
            return_value=link_summary,
        ) as link_existing, mock.patch.object(
            safe.commerce,
            "sync",
        ) as strict_sync:
            summary = safe.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        strict_sync.assert_not_called()
        link_existing.assert_called_once()
        self.assertEqual(summary["easystore_checkout_status"], "unavailable")
        self.assertEqual(summary["easystore_checkouts_scanned"], 0)
        self.assertEqual(summary["cart_order_associations_ensured"], 2)
        self.assertTrue(summary["hubspot_cart_upserts_skipped"])
        self.assertTrue(summary["hubspot_cart_line_item_sync_skipped"])
        self.assertIn("timed out", summary["easystore_checkout_error"])
        self.assertEqual(
            summary["easystore_checkout_collection_endpoint"],
            "https://shop.example/api/3.0/checkouts.json",
        )

    def test_available_snapshot_is_passed_to_strict_cart_sync(self) -> None:
        snapshot = safe.CheckoutSnapshot(
            records=(
                {
                    "cart_token": "cart-1",
                    "financial_status": "unpaid",
                    "line_items": [],
                },
            ),
            pages_read=1,
            details_fetched=0,
        )

        def fake_commerce_sync(**kwargs):
            records = list(
                safe.commerce.iter_documented_checkouts(
                    kwargs["store_domain"], kwargs["easystore_access_token"]
                )
            )
            return {
                "easystore_checkout_route": "checkouts.json",
                "easystore_checkouts_scanned": len(records),
            }

        with mock.patch.object(
            safe, "read_checkout_snapshot", return_value=snapshot
        ), mock.patch.object(safe.commerce, "sync", fake_commerce_sync):
            summary = safe.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertEqual(summary["easystore_checkout_status"], "available")
        self.assertEqual(summary["easystore_checkouts_scanned"], 1)
        self.assertEqual(summary["easystore_checkouts_buffered"], 1)
        self.assertEqual(summary["easystore_checkout_pages_read"], 1)
        self.assertFalse(summary["hubspot_cart_upserts_skipped"])

    def test_non_checkout_integrity_errors_still_escape(self) -> None:
        snapshot = safe.CheckoutSnapshot(records=(), pages_read=1, details_fetched=0)
        with mock.patch.object(
            safe, "read_checkout_snapshot", return_value=snapshot
        ), mock.patch.object(
            safe.commerce,
            "sync",
            side_effect=SyncError("duplicate HubSpot cart identity"),
        ):
            with self.assertRaisesRegex(SyncError, "duplicate HubSpot"):
                safe.sync(
                    store_domain="shop.example",
                    easystore_access_token="es",
                    hubspot_access_token="hs",
                    fallback_dial_code="65",
                )


if __name__ == "__main__":
    unittest.main()
