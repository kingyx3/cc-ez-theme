from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_checkouts as checkouts
from easystore_hubspot_orders import SyncError


class EasyStoreCheckoutCollectionContractTests(unittest.TestCase):
    def test_collection_uses_only_page_and_limit(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_http(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return {"checkouts": []}

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual(snapshot.records, ())
        self.assertEqual(snapshot.pages_read, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["url"],
            "https://shop.example/api/3.0/checkouts.json?page=1&limit=1",
        )
        self.assertNotIn("sort=", str(calls[0]["url"]))
        self.assertNotIn("created_at_min", str(calls[0]["url"]))
        self.assertNotIn("skus=", str(calls[0]["url"]))
        self.assertEqual(calls[0]["headers"], {"EasyStore-Access-Token": "secret"})
        self.assertEqual(calls[0]["timeout"], checkouts.CHECKOUT_READ_TIMEOUT_SECONDS)
        self.assertEqual(calls[0]["retries"], checkouts.CHECKOUT_READ_RETRIES)

    def test_collection_paginates_one_record_at_a_time(self) -> None:
        calls: list[str] = []

        def fake_http(url, **kwargs):
            calls.append(url)
            if "page=1" in url:
                return {
                    "checkouts": [
                        {
                            "id": 1,
                            "cart_token": "cart-1",
                            "financial_status": "unpaid",
                            "line_items": [],
                        }
                    ]
                }
            if "page=2" in url:
                return {
                    "checkouts": [
                        {
                            "id": 2,
                            "cart_token": "cart-2",
                            "financial_status": "paid",
                            "line_items": [],
                        }
                    ]
                }
            return {"checkouts": []}

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual([item["cart_token"] for item in snapshot.records], ["cart-1", "cart-2"])
        self.assertEqual(snapshot.pages_read, 3)
        self.assertTrue(calls[0].endswith("page=1&limit=1"))
        self.assertTrue(calls[1].endswith("page=2&limit=1"))
        self.assertTrue(calls[2].endswith("page=3&limit=1"))

    def test_repeated_page_is_rejected(self) -> None:
        response = {
            "checkouts": [
                {
                    "id": 1,
                    "cart_token": "cart-1",
                    "financial_status": "unpaid",
                    "line_items": [],
                }
            ]
        }
        with mock.patch.object(checkouts, "_http_json", return_value=response):
            with self.assertRaisesRegex(SyncError, "repeated a page"):
                checkouts.read_checkout_snapshot("shop.example", "secret")

    def test_unknown_response_shape_is_not_treated_as_empty(self) -> None:
        with mock.patch.object(checkouts, "_http_json", return_value={"products": []}):
            with self.assertRaisesRegex(SyncError, "without a checkout collection"):
                checkouts.read_checkout_snapshot("shop.example", "secret")

    def test_minimal_request_failure_names_the_exact_contract(self) -> None:
        with mock.patch.object(
            checkouts,
            "_http_json",
            side_effect=SyncError("The read operation timed out"),
        ):
            with self.assertRaisesRegex(
                SyncError,
                "minimal documented request.*no sort/date/product filters",
            ):
                checkouts.read_checkout_snapshot("shop.example", "secret")


class EasyStoreCheckoutDetailTests(unittest.TestCase):
    def test_missing_lines_hydrates_by_cart_token(self) -> None:
        calls: list[str] = []

        def fake_http(url, **kwargs):
            calls.append(url)
            if "checkouts.json" in url:
                if "page=1" in url:
                    return {
                        "checkouts": [
                            {
                                "id": 9,
                                "cart_token": "cart/a",
                                "financial_status": "unpaid",
                            }
                        ]
                    }
                return {"checkouts": []}
            return {
                "checkout": {
                    "cart_token": "cart/a",
                    "financial_status": "unpaid",
                    "line_items": [{"sku": "SKU-1", "quantity": 2}],
                }
            }

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual(snapshot.details_fetched, 1)
        self.assertEqual(snapshot.records[0]["id"], 9)
        self.assertEqual(snapshot.records[0]["line_items"][0]["sku"], "SKU-1")
        self.assertEqual(
            calls[-1],
            "https://shop.example/api/3.0/checkouts/cart%2Fa.json",
        )

    def test_detail_without_line_items_fails_before_cart_reconciliation(self) -> None:
        responses = iter(
            [
                {"checkouts": [{"cart_token": "cart-1", "financial_status": "unpaid"}]},
                {"checkouts": []},
                {"checkout": {"cart_token": "cart-1", "financial_status": "unpaid"}},
            ]
        )

        # Collection page 1, collection page 2, then detail. The implementation
        # hydrates only after all collection pages are buffered.
        def fake_http(url, **kwargs):
            if "/checkouts/cart-1.json" in url:
                return {"checkout": {"cart_token": "cart-1", "financial_status": "unpaid"}}
            return next(responses)

        with mock.patch.object(checkouts, "_http_json", fake_http):
            with self.assertRaisesRegex(SyncError, "omitted line_items"):
                checkouts.read_checkout_snapshot("shop.example", "secret")


class HubSpotCartProjectionTests(unittest.TestCase):
    def test_all_checkout_sessions_are_sent_to_cart_writer(self) -> None:
        snapshot = checkouts.CheckoutSnapshot(
            records=(
                {
                    "cart_token": "open-cart",
                    "financial_status": "unpaid",
                    "line_items": [],
                },
                {
                    "cart_token": "paid-cart",
                    "financial_status": "paid",
                    "line_items": [],
                },
            ),
            pages_read=3,
            details_fetched=0,
        )
        seen: list[dict[str, object]] = []

        def fake_commerce_sync(**kwargs):
            records = list(
                checkouts.commerce.iter_documented_checkouts(
                    kwargs["store_domain"], kwargs["easystore_access_token"]
                )
            )
            seen.extend(records)
            # The wrapper deliberately overrides only the old skip predicate;
            # raw financial_status remains on each record for property mapping.
            self.assertTrue(checkouts.commerce.is_abandoned(records[0]))
            self.assertTrue(checkouts.commerce.is_abandoned(records[1]))
            return {
                "easystore_checkouts_scanned": len(records),
                "hubspot_carts_created": len(records),
                "checkouts_skipped_as_completed": 0,
            }

        with mock.patch.object(
            checkouts,
            "read_checkout_snapshot",
            return_value=snapshot,
        ), mock.patch.object(checkouts.commerce, "sync", fake_commerce_sync):
            summary = checkouts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertEqual([item["cart_token"] for item in seen], ["open-cart", "paid-cart"])
        self.assertEqual(seen[0]["financial_status"], "unpaid")
        self.assertEqual(seen[1]["financial_status"], "paid")
        self.assertEqual(summary["hubspot_carts_created"], 2)
        self.assertEqual(summary["easystore_checkouts_abandoned_or_open"], 1)
        self.assertEqual(summary["easystore_checkouts_completed_or_paid"], 1)
        self.assertFalse(summary["cart_source_is_orders"])
        self.assertFalse(summary["easystore_checkout_product_style_filters_sent"])

    def test_checkout_status_still_maps_to_hubspot_external_status(self) -> None:
        mapped = checkouts.commerce.cart_properties(
            {
                "cart_token": "cart-1",
                "financial_status": "unpaid",
                "currency_code": "SGD",
            },
            cart_token="cart-1",
            store_domain="shop.example",
            field_properties=dict(
                checkouts.commerce.cart_mapping.DEFAULT_CART_FIELD_PROPERTIES
            ),
            fallback_dial_code="65",
        )
        self.assertEqual(mapped["hs_external_cart_id"], "cart-1")
        self.assertEqual(mapped["hs_external_status"], "unpaid")

    def test_checkout_wrapper_restores_core_predicate_after_sync(self) -> None:
        original = checkouts.commerce.is_abandoned
        snapshot = checkouts.CheckoutSnapshot(records=(), pages_read=1, details_fetched=0)
        with mock.patch.object(
            checkouts,
            "read_checkout_snapshot",
            return_value=snapshot,
        ), mock.patch.object(
            checkouts.commerce,
            "sync",
            return_value={},
        ):
            checkouts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )
        self.assertIs(checkouts.commerce.is_abandoned, original)


if __name__ == "__main__":
    unittest.main()
