from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_commerce as carts
import easystore_hubspot_customer_sync as customer_sync
import easystore_hubspot_orders as orders


class CartIdentityRegressionTests(unittest.TestCase):
    def test_cart_token_is_the_only_cart_identity(self) -> None:
        checkout = {
            "id": 900,
            "token": "checkout-session-token",
            "cart_token": "cart-uuid",
        }
        self.assertEqual(carts.checkout_cart_token(checkout), "cart-uuid")
        self.assertIsNone(carts.checkout_cart_token({"id": 900, "token": "checkout"}))

    def test_paid_financial_status_is_not_abandoned(self) -> None:
        self.assertFalse(
            carts.is_abandoned({"cart_token": "cart", "financial_status": "paid"})
        )
        self.assertTrue(
            carts.is_abandoned({"cart_token": "cart", "financial_status": "unpaid"})
        )

    def test_financial_status_is_written_to_cart_status(self) -> None:
        checkout = {
            "cart_token": "cart-uuid",
            "financial_status": "unpaid",
            "currency_code": "SGD",
        }
        mapped = carts.cart_properties(
            checkout,
            cart_token="cart-uuid",
            store_domain="shop.example",
            field_properties=dict(carts.cart_mapping.DEFAULT_CART_FIELD_PROPERTIES),
            fallback_dial_code="65",
        )
        self.assertEqual(mapped["hs_external_status"], "unpaid")

    def test_documented_checkout_endpoint_is_used_directly(self) -> None:
        seen: list[str] = []

        def fake_http(url, **kwargs):
            seen.append(url)
            return {"checkouts": [{"cart_token": "cart-1"}]}

        with mock.patch.object(carts, "_http_json", fake_http):
            found = list(carts.iter_documented_checkouts("shop.example", "token"))

        self.assertEqual(found, [{"cart_token": "cart-1"}])
        self.assertEqual(len(seen), 1)
        self.assertIn("/api/3.0/checkouts.json?", seen[0])
        self.assertNotIn("abandoned_checkouts", seen[0])

    def test_hubspot_cart_endpoint_uses_carts_object(self) -> None:
        self.assertTrue(carts.HUBSPOT_CARTS_URL.endswith("/crm/v3/objects/carts"))


class CartLineItemRegressionTests(unittest.TestCase):
    def test_cart_line_item_is_created_and_associated_with_type_590(self) -> None:
        calls: list[tuple[str, str, object]] = []

        def fake_http(url, *, method="GET", payload=None, **kwargs):
            calls.append((method, url, payload))
            if method == "POST" and url == carts.HUBSPOT_LINE_ITEMS_URL:
                return {"id": "line-77"}
            return {}

        desired = {
            "sku-a": {
                "name": "Alpha",
                "hs_sku": "SKU-A",
                "hs_product_id": "product-1",
                "quantity": "2",
                "price": "10.00",
            }
        }
        with mock.patch.object(
            carts, "existing_cart_line_items", lambda *a, **k: {}
        ), mock.patch.object(carts, "_http_json", fake_http):
            result = carts.sync_cart_line_items(
                access_token="hs",
                cart_id="cart-1",
                desired=desired,
            )

        self.assertEqual(result, (1, 0, 0))
        association_urls = [url for method, url, _ in calls if method == "PUT"]
        self.assertEqual(len(association_urls), 1)
        self.assertIn("/line_items/line-77/590", association_urls[0])

    def test_stale_product_backed_cart_line_is_removed_but_manual_line_is_kept(self) -> None:
        existing = {
            "stale": {
                "id": "line-1",
                "properties": {"hs_sku": "STALE", "hs_product_id": "product-1"},
            },
            "manual": {
                "id": "line-2",
                "properties": {"hs_sku": "MANUAL", "hs_product_id": None},
            },
        }
        deleted: list[str] = []

        def fake_http(url, *, method="GET", **kwargs):
            if method == "DELETE":
                deleted.append(url)
            return {}

        with mock.patch.object(
            carts, "existing_cart_line_items", lambda *a, **k: existing
        ), mock.patch.object(carts, "_http_json", fake_http):
            result = carts.sync_cart_line_items(
                access_token="hs",
                cart_id="cart-1",
                desired={},
            )

        self.assertEqual(result, (0, 0, 1))
        self.assertEqual(deleted, [f"{carts.HUBSPOT_LINE_ITEMS_URL}/line-1"])


class CustomerNoteSeparationTests(unittest.TestCase):
    def test_customer_note_and_note2_are_both_preserved(self) -> None:
        self.assertEqual(
            customer_sync.customer_note(
                {"note": "Prefers pickup", "note2": "VIP collector"}
            ),
            "Prefers pickup\nVIP collector",
        )

    def test_customer_note_does_not_guess_order_note_aliases(self) -> None:
        self.assertIsNone(
            customer_sync.customer_note(
                {
                    "remark": "order remark",
                    "remarks": "order remarks",
                    "comment": "not a customer note field",
                    "description": "not a customer note field",
                }
            )
        )
        self.assertEqual(customer_sync.CUSTOMER_NOTE_SOURCES, ("note", "note2"))

    def test_order_note_and_nested_customer_note_are_separate(self) -> None:
        record = {
            "note": "Order staff note",
            "remark": "Customer checkout remark",
            "customer": {"note": "Customer CRM note", "note2": "VIP"},
        }
        self.assertEqual(orders._order_note(record), "Order staff note")
        self.assertIsNone(
            orders._order_note({"customer": {"note": "Customer CRM note"}})
        )
        self.assertEqual(
            customer_sync.customer_note(record["customer"]),
            "Customer CRM note\nVIP",
        )

    def test_customer_fallback_reads_nested_customer_not_order_note(self) -> None:
        document = {
            "orders": [
                {
                    "id": 50,
                    "note": "ORDER NOTE MUST NOT REACH CONTACT",
                    "remark": "ORDER REMARK MUST NOT REACH CONTACT",
                    "customer": {
                        "id": 7,
                        "note": "Customer note",
                        "note2": "Customer note 2",
                    },
                }
            ]
        }

        customer_sync.customer_note_fallback_index.cache_clear()
        with mock.patch.object(customer_sync, "_http_json", lambda *a, **k: document):
            indexed = customer_sync.customer_note_fallback_index(
                "shop.example",
                "token",
            )
        customer_sync.customer_note_fallback_index.cache_clear()

        self.assertEqual(
            customer_sync.customer_note(indexed["7"]),
            "Customer note\nCustomer note 2",
        )
        self.assertNotIn("ORDER NOTE", customer_sync.customer_note(indexed["7"]))
        self.assertNotIn("ORDER REMARK", customer_sync.customer_note(indexed["7"]))

    def test_direct_customer_note_fields_win_over_nested_customer_fallback(self) -> None:
        listed = {
            "id": 7,
            "birthdate": "",
            "attributes": [],
            "note": "",
            "note2": "Direct customer note",
        }
        with mock.patch.object(
            customer_sync,
            "customer_note_fallback_index",
            side_effect=AssertionError("fallback should not be read"),
        ):
            completed = customer_sync.complete_customer(
                "shop.example",
                "token",
                listed,
            )
        self.assertEqual(completed["note"], "")
        self.assertEqual(completed["note2"], "Direct customer note")

    def test_missing_note_alone_does_not_force_customer_detail_fetch(self) -> None:
        self.assertFalse(
            customer_sync.customer_needs_detail(
                {"id": 7, "birthdate": "", "attributes": []}
            )
        )
        self.assertTrue(customer_sync.customer_needs_detail({"id": 7}))


class CartOrderAssociationRegressionTests(unittest.TestCase):
    def test_order_cart_token_links_cart_to_order_with_type_592(self) -> None:
        links: list[tuple[str, str, str, int]] = []

        def fake_associate(_token, cart_id, object_type, object_id, association_type_id):
            links.append((cart_id, object_type, object_id, association_type_id))

        with mock.patch.object(carts, "associate_cart", fake_associate):
            linked = carts.link_carts_to_orders(
                orders=[{"id": 55, "cart_token": "cart-uuid"}],
                hubspot_access_token="hs",
                carts_by_token={"cart-uuid": "cart-hs"},
                hubspot_orders={"55": "order-hs"},
            )

        self.assertEqual(linked, 1)
        self.assertEqual(
            links,
            [("cart-hs", "order", "order-hs", carts.CART_ORDER_ASSOCIATION_TYPE_ID)],
        )

    def test_sync_migrates_old_checkout_id_to_cart_token_without_duplication(self) -> None:
        checkout = {
            "id": 900,
            "token": "checkout-token",
            "cart_token": "cart-uuid",
            "financial_status": "unpaid",
            "currency_code": "SGD",
            "line_items": [
                {
                    "sku": "SKU-A",
                    "product_name": "Alpha",
                    "quantity": 1,
                    "price": "10.00",
                }
            ],
        }
        upserts: list[tuple[str | None, dict[str, str]]] = []

        def fake_upsert(_token, existing_id, properties):
            upserts.append((existing_id, properties))
            return "cart-hs", False

        contact_index = SimpleNamespace(by_phone={}, lifecycle_by_id={})
        with mock.patch.object(
            carts, "cart_object_available", lambda *_: True
        ), mock.patch.object(
            carts, "iter_orders_for_cart_links", lambda *a, **k: iter(())
        ), mock.patch.object(
            carts, "iter_documented_checkouts", lambda *a, **k: iter((checkout,))
        ), mock.patch.object(
            carts, "hubspot_contact_index", lambda *a, **k: contact_index
        ), mock.patch.object(
            carts,
            "resolve_fields",
            lambda **k: dict(carts.cart_mapping.DEFAULT_CART_FIELD_PROPERTIES),
        ), mock.patch.object(
            carts, "resolve_line_item_fields", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "hubspot_product_index", lambda *a, **k: {"sku-a": "product-1"}
        ), mock.patch.object(
            carts, "hubspot_cart_index", lambda *a, **k: {"900": "cart-hs"}
        ), mock.patch.object(
            carts, "hubspot_order_index", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "upsert_cart", fake_upsert
        ), mock.patch.object(
            carts, "sync_cart_line_items", lambda **k: (1, 0, 0)
        ), mock.patch.object(
            carts, "link_carts_to_orders", lambda **k: 0
        ):
            summary = carts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertEqual(upserts[0][0], "cart-hs")
        self.assertEqual(upserts[0][1]["hs_external_cart_id"], "cart-uuid")
        self.assertEqual(upserts[0][1]["hs_external_status"], "unpaid")
        self.assertEqual(summary["hubspot_carts_migrated_to_cart_token"], 1)
        self.assertEqual(summary["hubspot_cart_line_items_created"], 1)

    def test_conflicting_legacy_cart_ids_fail_closed(self) -> None:
        checkout = {"id": 900, "token": "old-token", "cart_token": "new-token"}
        with self.assertRaises(carts.SyncError):
            carts._legacy_cart_owner(
                checkout,
                {"900": "cart-a", "old-token": "cart-b"},
            )


if __name__ == "__main__":
    unittest.main()


class RetiredProductCartLineTests(unittest.TestCase):
    """A Checkout may reference a variant that has since left the catalogue.

    Open and abandoned Checkouts reach back over the whole catalogue's history,
    so some name products that can no longer have a HubSpot Product. Production
    run 32485932896 refused all 1246 of this store's Checkouts over one such
    line, writing no Carts at all.
    """

    @staticmethod
    def _checkout() -> dict:
        return {
            "cart_token": "cart-1",
            "financial_status": "unpaid",
            "line_items": [
                {"sku": "LIVE-1", "quantity": 1, "price": "10.00"},
                {"sku": "ES-16616396-76964637", "quantity": 2, "price": "20.00"},
            ],
        }

    def test_an_order_line_without_a_product_still_fails_the_order_stage(self) -> None:
        with self.assertRaisesRegex(orders.SyncError, "no matching HubSpot Product"):
            orders.desired_lines(self._checkout(), {"live-1": "p1"})

    def test_a_cart_line_without_a_product_is_skipped_and_reported(self) -> None:
        unmatched: list[str] = []
        desired = orders.desired_lines(
            self._checkout(),
            {"live-1": "p1"},
            record="checkout",
            unmatched_lines=unmatched,
        )

        self.assertEqual(sorted(desired), ["live-1"])
        self.assertEqual(unmatched, ["ES-16616396-76964637"])

    def test_a_line_without_any_identity_is_skipped_for_carts_too(self) -> None:
        unmatched: list[str] = []
        desired = orders.desired_lines(
            {"cart_token": "cart-1", "line_items": [{"quantity": 1}]},
            {},
            record="checkout",
            unmatched_lines=unmatched,
        )

        self.assertEqual(desired, {})
        self.assertEqual(unmatched, ["<no SKU or product/variant IDs>"])

    def test_error_text_names_the_record_type(self) -> None:
        with self.assertRaisesRegex(orders.SyncError, "EasyStore checkout 7 line SKU"):
            orders.desired_lines(
                {"id": 7, "line_items": [{"sku": "GONE"}]},
                {},
                record="checkout",
            )

    def test_stale_cart_lines_are_kept_when_a_line_could_not_be_mapped(self) -> None:
        # "Gone from the Checkout" and "product retired" look identical once a
        # line is missing from `desired`, so deleting on that guess would throw
        # away a Cart line the shopper really had.
        existing = {
            "retired": {
                "id": "L9",
                "properties": {"hs_sku": "RETIRED", "hs_product_id": "p9"},
            }
        }
        deletes: list[str] = []

        def fake_http(url, *, method="GET", **kwargs):
            if method == "DELETE":
                deletes.append(url)
            return {"id": "new"}

        with mock.patch.object(carts, "existing_cart_line_items", return_value=existing), \
             mock.patch.object(carts, "_http_json", fake_http):
            _, _, removed = carts.sync_cart_line_items(
                access_token="hs",
                cart_id="C1",
                desired={},
                remove_stale=False,
            )
        self.assertEqual(removed, 0)
        self.assertEqual(deletes, [])

        with mock.patch.object(carts, "existing_cart_line_items", return_value=existing), \
             mock.patch.object(carts, "_http_json", fake_http):
            _, _, removed = carts.sync_cart_line_items(
                access_token="hs",
                cart_id="C1",
                desired={},
                remove_stale=True,
            )
        self.assertEqual(removed, 1)
        self.assertEqual(len(deletes), 1)
