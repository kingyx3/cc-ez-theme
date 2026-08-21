from __future__ import annotations

import sys
import unittest
from pathlib import Path
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
        self.assertEqual(snapshot.page_size, 50)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["url"],
            "https://shop.example/api/3.0/checkouts.json?page=1&limit=50",
        )
        self.assertNotIn("sort=", str(calls[0]["url"]))
        self.assertNotIn("created_at_min", str(calls[0]["url"]))
        self.assertNotIn("skus=", str(calls[0]["url"]))
        self.assertEqual(calls[0]["headers"], {"EasyStore-Access-Token": "secret"})
        self.assertEqual(calls[0]["timeout"], checkouts.CHECKOUT_READ_TIMEOUT_SECONDS)
        self.assertEqual(calls[0]["retries"], checkouts.CHECKOUT_READ_RETRIES)

    def test_collection_paginates_until_a_short_page(self) -> None:
        calls: list[str] = []
        page_size = checkouts.CHECKOUT_PAGE_SIZES[0]
        full_page = [
            {
                "id": index,
                "cart_token": f"cart-{index}",
                "financial_status": "unpaid",
                "line_items": [],
            }
            for index in range(page_size)
        ]

        def fake_http(url, **kwargs):
            calls.append(url)
            if "page=1" in url:
                return {"checkouts": full_page}
            return {
                "checkouts": [
                    {
                        "id": 99,
                        "cart_token": "cart-99",
                        "financial_status": "paid",
                        "line_items": [],
                    }
                ]
            }

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual(len(snapshot.records), page_size + 1)
        self.assertEqual(snapshot.records[-1]["cart_token"], "cart-99")
        self.assertEqual(snapshot.pages_read, 2)
        self.assertTrue(calls[0].endswith(f"page=1&limit={page_size}"))
        self.assertTrue(calls[1].endswith(f"page=2&limit={page_size}"))

    def test_a_timing_out_page_size_falls_back_to_the_smallest_request(self) -> None:
        calls: list[str] = []

        def fake_http(url, **kwargs):
            calls.append(url)
            if "limit=50" in url:
                raise SyncError("read timed out") from TimeoutError("timed out")
            if "page=1" in url:
                return {
                    "checkouts": [
                        {
                            "cart_token": "cart-1",
                            "financial_status": "unpaid",
                            "line_items": [],
                        }
                    ]
                }
            return {"checkouts": []}

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual([item["cart_token"] for item in snapshot.records], ["cart-1"])
        self.assertEqual(snapshot.page_size, 1)
        self.assertTrue(calls[0].endswith("page=1&limit=50"))
        self.assertTrue(calls[1].endswith("page=1&limit=1"))
        self.assertIn("limit=50", snapshot.attempts[0])
        self.assertIn("did not answer", snapshot.attempts[0])

    def test_no_page_size_answering_names_every_attempted_request(self) -> None:
        def fake_http(url, **kwargs):
            raise SyncError("The read operation timed out") from TimeoutError()

        with mock.patch.object(checkouts, "_http_json", fake_http):
            with self.assertRaises(checkouts.CheckoutSourceUnavailable) as raised:
                checkouts.read_checkout_snapshot("shop.example", "secret")

        message = str(raised.exception)
        self.assertIn("no sort/date/product filters", message)
        for page_size in checkouts.CHECKOUT_PAGE_SIZES:
            self.assertIn(f"limit={page_size}", message)

    def test_a_rejected_request_is_not_treated_as_an_outage(self) -> None:
        # A 401/403 is a token or scope problem. Falling back to another page
        # size or degrading to a green run would hide it.
        from urllib.error import HTTPError

        def fake_http(url, **kwargs):
            raise SyncError("failed with HTTP 401") from HTTPError(
                url, 401, "Unauthorized", {}, None
            )

        with mock.patch.object(checkouts, "_http_json", fake_http):
            with self.assertRaisesRegex(SyncError, "HTTP 401") as raised:
                checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertNotIsInstance(
            raised.exception,
            checkouts.CheckoutSourceUnavailable,
        )


def _page(count: int, *, start: int = 0) -> dict[str, object]:
    return {
        "checkouts": [
            {
                "id": index,
                "cart_token": f"cart-{index}",
                "financial_status": "unpaid",
                "line_items": [],
            }
            for index in range(start, start + count)
        ]
    }


class IgnoredPageParameterTests(unittest.TestCase):
    """This store's checkouts.json answers but serves page 2 identical to page 1.

    Failing there means never syncing a Cart, and looping on it never
    terminates, so a repeated page ends pagination and `limit` proves the
    snapshot instead.
    """

    def test_a_repeated_page_escalates_the_limit_instead_of_failing(self) -> None:
        calls: list[str] = []
        first = checkouts.CHECKOUT_PAGE_SIZES[0]
        bigger = checkouts.CHECKOUT_LIMIT_ESCALATION[0]

        def fake_http(url, **kwargs):
            calls.append(url)
            if f"limit={bigger}" in url:
                return _page(first + 7)
            return _page(first)

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertFalse(snapshot.page_parameter_honored)
        self.assertTrue(snapshot.complete)
        self.assertEqual(len(snapshot.records), first + 7)
        self.assertEqual(snapshot.page_size, bigger)
        self.assertTrue(calls[0].endswith(f"page=1&limit={first}"))
        self.assertTrue(calls[1].endswith(f"page=2&limit={first}"))
        self.assertTrue(calls[2].endswith(f"page=1&limit={bigger}"))

    def test_the_same_count_at_a_larger_limit_is_not_claimed_complete(self) -> None:
        # Either the store holds exactly this many checkouts or the endpoint caps
        # the limit. Both are consistent with the answer, so neither is claimed.
        first = checkouts.CHECKOUT_PAGE_SIZES[0]

        with mock.patch.object(checkouts, "_http_json", return_value=_page(first)):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertFalse(snapshot.page_parameter_honored)
        self.assertFalse(snapshot.complete)
        self.assertEqual(len(snapshot.records), first)
        self.assertIn("capping the limit", snapshot.completeness)

    def test_a_refused_escalation_keeps_the_snapshot_that_arrived(self) -> None:
        from urllib.error import HTTPError

        first = checkouts.CHECKOUT_PAGE_SIZES[0]

        def fake_http(url, **kwargs):
            if f"limit={first}" not in url:
                raise SyncError("failed with HTTP 400: limit too large") from HTTPError(
                    url, 400, "Bad Request", {}, None
                )
            return _page(first)

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual(len(snapshot.records), first)
        self.assertFalse(snapshot.complete)
        self.assertIn("refused", snapshot.completeness)

    def test_every_limit_saturating_still_returns_what_arrived(self) -> None:
        largest = checkouts.CHECKOUT_LIMIT_ESCALATION[-1]

        def fake_http(url, **kwargs):
            limit = int(url.rsplit("limit=", 1)[1])
            return _page(limit)

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual(len(snapshot.records), largest)
        self.assertFalse(snapshot.complete)
        self.assertIn("saturated", snapshot.completeness)

    def test_a_later_page_timing_out_keeps_the_page_that_answered(self) -> None:
        # Production run 32483557524: page 1 served 50 checkouts, page 2 hung
        # until it timed out, and discarding page 1 over it synced no carts.
        calls: list[str] = []
        first = checkouts.CHECKOUT_PAGE_SIZES[0]
        bigger = checkouts.CHECKOUT_LIMIT_ESCALATION[0]

        def fake_http(url, **kwargs):
            calls.append(url)
            if "page=2" in url:
                raise SyncError("The read operation timed out") from TimeoutError()
            if f"limit={bigger}" in url:
                return _page(first + 12)
            return _page(first)

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual(len(snapshot.records), first + 12)
        self.assertTrue(snapshot.complete)
        self.assertIn("page 2 did not answer", snapshot.pagination)
        self.assertTrue(calls[-1].endswith(f"page=1&limit={bigger}"))

    def test_page_one_timing_out_is_still_an_outage(self) -> None:
        def fake_http(url, **kwargs):
            raise SyncError("The read operation timed out") from TimeoutError()

        with mock.patch.object(checkouts, "_http_json", fake_http):
            with self.assertRaises(checkouts.CheckoutSourceUnavailable):
                checkouts.read_checkout_snapshot("shop.example", "secret")

    def test_a_later_page_timing_out_with_no_bigger_limit_keeps_page_one(self) -> None:
        first = checkouts.CHECKOUT_PAGE_SIZES[0]

        def fake_http(url, **kwargs):
            if f"limit={first}" in url and "page=1" in url:
                return _page(first)
            raise SyncError("The read operation timed out") from TimeoutError()

        with mock.patch.object(checkouts, "_http_json", fake_http):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual(len(snapshot.records), first)
        self.assertFalse(snapshot.complete)

    def test_one_short_page_with_page_ignored_is_complete(self) -> None:
        with mock.patch.object(checkouts, "_http_json", return_value=_page(3)):
            snapshot = checkouts.read_checkout_snapshot("shop.example", "secret")

        self.assertEqual(len(snapshot.records), 3)
        self.assertTrue(snapshot.complete)

    def test_an_unproven_snapshot_is_annotated_and_still_synchronized(self) -> None:
        snapshot = checkouts.CheckoutSnapshot(
            records=({"cart_token": "cart-1", "line_items": []},),
            pages_read=1,
            details_fetched=0,
            complete=False,
            completeness="limit=1000 came back saturated",
        )
        with mock.patch.object(
            checkouts, "read_checkout_snapshot", return_value=snapshot
        ), mock.patch.object(
            checkouts.commerce, "sync", return_value={"hubspot_carts_created": 1}
        ) as cart_sync, mock.patch.object(
            checkouts.sys, "stderr", new_callable=mock.MagicMock
        ) as stderr:
            summary = checkouts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        cart_sync.assert_called_once()
        annotation = "".join(str(call.args[0]) for call in stderr.write.call_args_list)
        self.assertIn("::warning title=EasyStore Checkout snapshot not proven complete::", annotation)
        self.assertEqual(summary["hubspot_carts_created"], 1)
        self.assertFalse(summary["easystore_checkout_snapshot_proven_complete"])
        self.assertIn("saturated", summary["easystore_checkout_snapshot_completeness"])

    def test_unknown_response_shape_is_not_treated_as_empty(self) -> None:
        with mock.patch.object(checkouts, "_http_json", return_value={"products": []}):
            with self.assertRaisesRegex(SyncError, "without a checkout collection"):
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
        def fake_http(url, **kwargs):
            if "/checkouts/cart-1.json" in url:
                return {"checkout": {"cart_token": "cart-1", "financial_status": "unpaid"}}
            if "page=1" in url:
                return {"checkouts": [{"cart_token": "cart-1", "financial_status": "unpaid"}]}
            return {"checkouts": []}

        with mock.patch.object(checkouts, "_http_json", fake_http):
            with self.assertRaisesRegex(SyncError, "omitted line_items"):
                checkouts.read_checkout_snapshot("shop.example", "secret")

    def test_a_detail_outage_never_exposes_a_partial_snapshot(self) -> None:
        def fake_http(url, **kwargs):
            if "/checkouts/" in url and "checkouts.json" not in url:
                raise SyncError("detail timed out") from TimeoutError()
            if "page=1" in url:
                return {
                    "checkouts": [
                        {"cart_token": "cart-1", "line_items": []},
                        {"cart_token": "cart-2"},
                    ]
                }
            return {"checkouts": []}

        with mock.patch.object(checkouts, "_http_json", fake_http):
            with self.assertRaises(checkouts.CheckoutSourceUnavailable):
                checkouts.read_checkout_snapshot("shop.example", "secret")


class HubSpotCartProjectionTests(unittest.TestCase):
    def test_every_checkout_session_reaches_the_cart_writer(self) -> None:
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
            pages_read=1,
            details_fetched=0,
        )
        seen: dict[str, object] = {}

        def fake_commerce_sync(**kwargs):
            seen.update(kwargs)
            records = list(kwargs["checkouts"])
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

        # The snapshot is handed over as data, not by patching the core module,
        # and paid sessions are kept because a HubSpot Cart is a shopping
        # session rather than an abandonment record.
        self.assertEqual(
            [item["cart_token"] for item in seen["checkouts"]],
            ["open-cart", "paid-cart"],
        )
        self.assertTrue(seen["include_completed"])
        self.assertEqual(seen["cart_schema_object_type"], "cart")
        self.assertEqual(summary["hubspot_carts_created"], 2)
        self.assertEqual(summary["easystore_checkouts_abandoned_or_open"], 1)
        self.assertEqual(summary["easystore_checkouts_completed_or_paid"], 1)
        self.assertEqual(summary["easystore_checkout_status"], "available")
        self.assertFalse(summary["cart_source_is_orders"])
        self.assertFalse(summary["easystore_checkout_product_style_filters_sent"])

    def test_checkout_status_and_abandoned_flag_reach_the_cart(self) -> None:
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
        self.assertEqual(mapped["easystore_cart_is_abandoned"], "true")

        converted = checkouts.commerce.cart_properties(
            {"cart_token": "cart-2", "financial_status": "paid", "order_id": 55},
            cart_token="cart-2",
            store_domain="shop.example",
            field_properties=dict(
                checkouts.commerce.cart_mapping.DEFAULT_CART_FIELD_PROPERTIES
            ),
            fallback_dial_code="65",
        )
        self.assertEqual(converted["easystore_cart_is_abandoned"], "false")


if __name__ == "__main__":
    unittest.main()
