from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_admin_checkouts as admin
import easystore_hubspot_carts as carts
import easystore_hubspot_commerce as commerce


LINE = [{"sku": "SKU-A", "quantity": 2, "price": "84.0"}]


def _record(**overrides) -> dict:
    record = {
        "id": 114004107,
        "created_at": "2026-08-21T09:38:24.000+08:00",
        "customer_id": 41597490,
        "amount": "168.0",
        "total_line_items_price": "168.0",
        "currency": "SGD",
        "cart_token": "cart-1",
        "is_processed": False,
        "is_recovered": False,
        "is_deleted": False,
        "first_name": "Chestnutay",
        "last_name": None,
        "email": "chester@example.com",
        "phone": "6588143218",
        "url": "https://cardboard.sg/sf/checkout/cart-1",
        "channel": "storefront",
    }
    record.update(overrides)
    return record


def _admin_body(records: list[dict]) -> dict:
    return {
        "params": {
            "page": 1,
            "limit": 50,
            "page_count": 1,
            "total_count": len(records),
        },
        "data": {"checkouts": records, "is_empty": not records},
    }


class AdminPublicLineJoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_fields = carts.CART_FIELDS

    def tearDown(self) -> None:
        carts.CART_FIELDS = self.original_fields

    def test_public_collection_lines_join_by_cart_token_with_separate_tokens(self) -> None:
        calls: list[tuple[str, dict[str, str]]] = []

        def serve(url, *, headers, **_kwargs):
            calls.append((url, headers))
            if url.startswith(admin.ADMIN_CHECKOUTS_URL):
                return _admin_body([_record()])
            if admin.PUBLIC_CHECKOUT_PATH in url:
                return {
                    "checkouts": [
                        {
                            "cart_token": "not-this-cart",
                            "line_items": [{"sku": "WRONG", "quantity": 1}],
                        },
                        {"cart_token": "cart-1", "line_items": LINE},
                    ]
                }
            raise AssertionError(f"unexpected URL {url}")

        with mock.patch.dict(
            admin.os.environ,
            {"EASYSTORE_STORE_DOMAIN": "shop.example"},
            clear=False,
        ), mock.patch.object(admin, "_http_json", serve):
            read = admin.read_admin_checkouts("public-token", "admin-token")

        self.assertEqual(read.records[0]["line_items"], LINE)
        checkout = admin.as_checkout(read.records[0])
        self.assertEqual(checkout["line_items"], LINE)
        self.assertNotIn(commerce.LINE_ITEMS_UNAVAILABLE_KEY, checkout)

        admin_request = next(call for call in calls if call[0].startswith(admin.ADMIN_CHECKOUTS_URL))
        public_request = next(call for call in calls if admin.PUBLIC_CHECKOUT_PATH in call[0])
        self.assertEqual(admin_request[1]["EasyStore-Access-Token"], "admin-token")
        self.assertNotIn("public-token", repr(admin_request[1]))
        self.assertEqual(public_request[1]["EasyStore-Access-Token"], "public-token")
        self.assertNotIn("admin-token", repr(public_request[1]))
        self.assertTrue(any("matched 1 of 1" in attempt for attempt in read.attempts))

    def test_unmatched_admin_cart_keeps_existing_hubspot_lines_safe(self) -> None:
        def serve(url, *, headers, **_kwargs):
            if url.startswith(admin.ADMIN_CHECKOUTS_URL):
                return _admin_body([_record(cart_token="missing")])
            if admin.PUBLIC_CHECKOUT_PATH in url:
                return {"checkouts": [{"cart_token": "other", "line_items": LINE}]}
            raise AssertionError(f"unexpected URL {url}")

        with mock.patch.dict(
            admin.os.environ,
            {"EASYSTORE_STORE_DOMAIN": "shop.example"},
            clear=False,
        ), mock.patch.object(admin, "_http_json", serve):
            read = admin.read_admin_checkouts("public-token", "admin-token")

        checkout = admin.as_checkout(read.records[0])
        self.assertEqual(checkout["line_items"], [])
        self.assertTrue(checkout[commerce.LINE_ITEMS_UNAVAILABLE_KEY])
        self.assertTrue(any("missing=1" in attempt for attempt in read.attempts))

    def test_admin_created_at_keeps_native_first_cart_mapping(self) -> None:
        def serve(url, *, headers, **_kwargs):
            if url.startswith(admin.ADMIN_CHECKOUTS_URL):
                return _admin_body([_record()])
            if admin.PUBLIC_CHECKOUT_PATH in url:
                return {"checkouts": [{"cart_token": "cart-1", "line_items": LINE}]}
            raise AssertionError(f"unexpected URL {url}")

        with mock.patch.dict(
            admin.os.environ,
            {"EASYSTORE_STORE_DOMAIN": "shop.example"},
            clear=False,
        ), mock.patch.object(admin, "_http_json", serve):
            read = admin.read_admin_checkouts("public-token", "admin-token")

        created = next(field for field in carts.CART_FIELDS if field.key == "created_at")
        self.assertEqual(created.native, ("hs_external_created_date",))
        self.assertEqual(created.fallback, "easystore_cart_created_at")
        self.assertEqual(created.label, "EasyStore Cart Started")

        values = carts.cart_field_values(admin.as_checkout(read.records[0]), "65")
        self.assertEqual(values["created_at"], "1787276304000")


if __name__ == "__main__":
    unittest.main()
