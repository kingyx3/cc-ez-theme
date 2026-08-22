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
            "email": "shopper@example.com",
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

        contact_index = SimpleNamespace(
            by_phone={}, by_email={}, by_easystore_customer_id={}, lifecycle_by_id={}
        )
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


class UnpaidCartSubsetTests(unittest.TestCase):
    """Every Cart in the CRM reads ``unpaid``, and that is the source, not a bug.

    EasyStore's ``checkouts.json`` serves open sessions only: production run
    32539291543 read 1267 records whose only state field was
    ``financial_status``, all of them ``unpaid``, with no ``status``,
    ``completed_at`` or ``order_id`` field anywhere in the payload and no order
    sharing a ``cart_token`` with any of them. These tests pin the two things
    that follow: the distribution of raw status values is reported so the claim
    stays checkable, and a paid session - if this collection ever serves one -
    is left to the Order stage instead of becoming a second copy of the revenue.
    """

    @staticmethod
    def _checkout(token: str, **extra: object) -> dict:
        return {
            "cart_token": token,
            "currency_code": "SGD",
            "email": f"{token}@example.com",
            "line_items": [
                {"sku": "SKU-A", "product_name": "Alpha", "quantity": 1, "price": "10"}
            ],
            **extra,
        }

    def _run(self, checkouts: list[dict], **kwargs) -> tuple[dict, list[dict]]:
        upserted: list[dict] = []

        def fake_upsert(_token, _existing_id, properties):
            upserted.append(properties)
            return f"cart-{len(upserted)}", True

        contact_index = SimpleNamespace(
            by_phone={}, by_email={}, by_easystore_customer_id={}, lifecycle_by_id={}
        )
        with mock.patch.object(
            carts, "cart_object_available", lambda *_: True
        ), mock.patch.object(
            carts, "iter_orders_for_cart_links", lambda *a, **k: iter(())
        ), mock.patch.object(
            carts, "iter_documented_checkouts", lambda *a, **k: iter(checkouts)
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
            carts, "hubspot_cart_index", lambda *a, **k: {}
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
                **kwargs,
            )
        return summary, upserted

    def test_the_raw_status_distribution_is_reported(self) -> None:
        summary, _ = self._run(
            [
                self._checkout("c1", financial_status="unpaid"),
                self._checkout("c2", financial_status="unpaid"),
                self._checkout("c3", financial_status="pending"),
                self._checkout("c4"),
            ]
        )

        self.assertEqual(
            summary["easystore_checkout_status_counts"],
            {"unpaid": 2, "(no status field)": 1, "pending": 1},
        )
        # All four are unpaid carts, so the count and the distribution agree.
        self.assertEqual(summary["easystore_checkouts_abandoned"], 4)

    def test_a_paid_checkout_is_left_to_the_order_stage(self) -> None:
        summary, upserted = self._run(
            [
                self._checkout("c1", financial_status="unpaid"),
                self._checkout("c2", financial_status="paid"),
            ]
        )

        self.assertEqual(
            [properties["hs_external_cart_id"] for properties in upserted], ["c1"]
        )
        self.assertEqual(summary["easystore_checkouts_converted"], 1)
        self.assertEqual(summary["checkouts_skipped_as_completed"], 1)
        self.assertFalse(summary["completed_checkouts_kept_as_carts"])
        self.assertEqual(summary["easystore_checkout_status_counts"]["paid"], 1)

    def test_partial_payments_and_authorizations_are_not_abandoned(self) -> None:
        for status in ("partially_paid", "Partially_Refunded", "authorized"):
            with self.subTest(status=status):
                self.assertFalse(
                    carts.is_abandoned({"cart_token": "c", "financial_status": status})
                )

    def test_a_pending_payment_is_still_an_abandoned_cart(self) -> None:
        # Nothing has been collected, so it stays in the recovery funnel.
        self.assertTrue(
            carts.is_abandoned({"cart_token": "c", "financial_status": "pending"})
        )


if __name__ == "__main__":
    unittest.main()


class CartContactAssociationConsistencyTests(unittest.TestCase):
    """Cart→Contact must be resolved for every Cart that can be resolved at all.

    Production run 32539291543 linked 26 of 1267 Carts. Mobile was the only key
    the association read, and only 31 of those checkouts carried a phone at all
    - an abandoned checkout is usually a session that got as far as an email.
    Email is therefore read as a second key, and every Cart is accounted for by
    one of five outcomes so a run says why the rest are unlinked.
    """

    @staticmethod
    def _checkout(token: str, **extra: object) -> dict:
        return {
            "cart_token": token,
            "financial_status": "unpaid",
            "line_items": [{"sku": "SKU-A", "quantity": 1, "price": "10"}],
            **extra,
        }

    def _run(self, checkouts: list[dict], contacts, **kwargs) -> tuple[dict, list[tuple]]:
        links: list[tuple] = []
        counter = {"n": 0}

        def fake_upsert(_token, _existing_id, _properties):
            counter["n"] += 1
            return f"cart-{counter['n']}", True

        def fake_associate(_token, cart_id, object_type, object_id, type_id):
            links.append((cart_id, object_type, object_id, type_id))

        with mock.patch.object(
            carts, "cart_object_available", lambda *_: True
        ), mock.patch.object(
            carts, "iter_orders_for_cart_links", lambda *a, **k: iter(())
        ), mock.patch.object(
            carts, "iter_documented_checkouts", lambda *a, **k: iter(checkouts)
        ), mock.patch.object(
            carts, "hubspot_contact_index", lambda *a, **k: contacts
        ), mock.patch.object(
            carts,
            "resolve_fields",
            lambda **k: dict(carts.cart_mapping.DEFAULT_CART_FIELD_PROPERTIES),
        ), mock.patch.object(
            carts, "resolve_line_item_fields", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "hubspot_product_index", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "hubspot_cart_index", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "hubspot_order_index", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "upsert_cart", fake_upsert
        ), mock.patch.object(
            carts, "associate_cart", fake_associate
        ), mock.patch.object(
            carts, "sync_cart_line_items", lambda **k: (0, 0, 0)
        ), mock.patch.object(
            carts, "link_carts_to_orders", lambda **k: 0
        ):
            summary = carts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
                **kwargs,
            )
        return summary, links

    def test_an_email_only_checkout_is_associated_to_its_contact(self) -> None:
        contacts = SimpleNamespace(
            by_phone={},
            by_email={"shopper@example.com": {"contact-9"}},
            by_easystore_customer_id={},
            lifecycle_by_id={},
        )
        summary, links = self._run(
            [self._checkout("c1", email="Shopper@Example.com")], contacts
        )

        self.assertEqual(
            links,
            [("cart-1", "contact", "contact-9", carts.CART_CONTACT_ASSOCIATION_TYPE_ID)],
        )
        self.assertEqual(summary["cart_contact_associations_ensured"], 1)
        self.assertEqual(summary["cart_contact_associations_by_email"], 1)
        self.assertEqual(summary["cart_contact_associations_by_mobile"], 0)

    def test_mobile_stays_the_identity_when_both_keys_resolve(self) -> None:
        contacts = SimpleNamespace(
            by_phone={"+6591234567": {"by-phone"}},
            by_email={"shopper@example.com": {"by-email"}},
            by_easystore_customer_id={},
            lifecycle_by_id={},
        )
        summary, links = self._run(
            [
                self._checkout(
                    "c1", phone="91234567", email="shopper@example.com"
                )
            ],
            contacts,
        )

        self.assertEqual([link[2] for link in links], ["by-phone"])
        self.assertEqual(summary["cart_contact_associations_by_mobile"], 1)
        self.assertEqual(summary["cart_contact_associations_by_email"], 0)

    def test_an_ambiguous_email_is_reported_and_never_guessed(self) -> None:
        contacts = SimpleNamespace(
            by_phone={},
            by_email={"shared@example.com": {"contact-1", "contact-2"}},
            by_easystore_customer_id={},
            lifecycle_by_id={},
        )
        summary, links = self._run(
            [self._checkout("c1", email="shared@example.com")], contacts
        )

        self.assertEqual(links, [])
        self.assertEqual(summary["carts_with_ambiguous_contact_email"], 1)
        self.assertEqual(summary["cart_contact_associations_ensured"], 0)

    def test_every_written_cart_is_accounted_for_exactly_once(self) -> None:
        contacts = SimpleNamespace(
            by_phone={"+6591234567": {"c-phone"}, "+6598765432": {"c-a", "c-b"}},
            by_email={
                "known@example.com": {"c-email"},
                "shared@example.com": {"c-x", "c-y"},
            },
            by_easystore_customer_id={},
            lifecycle_by_id={},
        )
        summary, links = self._run(
            [
                self._checkout("c1", phone="91234567"),
                self._checkout("c2", email="known@example.com"),
                self._checkout("c3", phone="98765432"),
                self._checkout("c4", email="shared@example.com"),
                self._checkout("c5"),
                self._checkout("c6", email="stranger@example.com"),
            ],
            contacts,
            recoverable_only=False,
        )

        self.assertEqual(len(links), 2)
        self.assertEqual(summary["cart_contact_associations_ensured"], 2)
        self.assertEqual(summary["carts_with_ambiguous_contact_mobile"], 1)
        self.assertEqual(summary["carts_with_ambiguous_contact_email"], 1)
        self.assertEqual(summary["carts_with_no_shopper_identity"], 1)
        self.assertEqual(summary["carts_whose_shopper_is_not_a_hubspot_contact"], 1)
        self.assertEqual(
            summary["cart_contact_association_accounted_for"],
            summary["hubspot_carts_created"] + summary["hubspot_carts_updated"],
        )

    def test_the_contact_index_reads_email_case_insensitively(self) -> None:
        requested: list[str] = []

        def fake_objects(_url, _token, properties):
            requested.append(properties)
            return iter(
                (
                    {
                        "id": "contact-1",
                        "properties": {
                            "email": "Shopper@Example.COM",
                            "mobilephone": "91234567",
                        },
                    },
                )
            )

        with mock.patch.object(orders, "iter_hubspot_objects", fake_objects):
            index = orders.hubspot_contact_index("hs", "65")

        self.assertIn("email", requested[0])
        self.assertEqual(index.by_email["shopper@example.com"], {"contact-1"})
        self.assertEqual(index.by_phone["+6591234567"], {"contact-1"})


if __name__ == "__main__":
    unittest.main()


class RecoverableCartFilterTests(unittest.TestCase):
    """1267 API records against 15 in EasyStore's own abandoned checkout list.

    ``checkouts.json`` serves every session the storefront opened, most of them
    anonymous or empty: of the 1267 in run 32539291543, 717 held line items and
    41 carried an email. EasyStore's admin list is the recoverable subset - it
    has a billing name, email, phone and item columns on every row - so a Cart
    is written only when there is something in it and someone to send it to.
    """

    def _run(self, checkouts: list[dict], **kwargs) -> tuple[dict, list[str]]:
        written: list[str] = []

        def fake_upsert(_token, _existing_id, properties):
            written.append(properties["hs_external_cart_id"])
            return f"cart-{len(written)}", True

        contacts = SimpleNamespace(
            by_phone={}, by_email={}, by_easystore_customer_id={}, lifecycle_by_id={}
        )
        with mock.patch.object(
            carts, "cart_object_available", lambda *_: True
        ), mock.patch.object(
            carts, "iter_orders_for_cart_links", lambda *a, **k: iter(())
        ), mock.patch.object(
            carts, "iter_documented_checkouts", lambda *a, **k: iter(checkouts)
        ), mock.patch.object(
            carts, "hubspot_contact_index", lambda *a, **k: contacts
        ), mock.patch.object(
            carts,
            "resolve_fields",
            lambda **k: dict(carts.cart_mapping.DEFAULT_CART_FIELD_PROPERTIES),
        ), mock.patch.object(
            carts, "resolve_line_item_fields", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "hubspot_product_index", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "hubspot_cart_index", lambda *a, **k: {"already-there": "cart-old"}
        ), mock.patch.object(
            carts, "hubspot_order_index", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "upsert_cart", fake_upsert
        ), mock.patch.object(
            carts, "associate_cart", lambda *a, **k: None
        ), mock.patch.object(
            carts, "sync_cart_line_items", lambda **k: (0, 0, 0)
        ), mock.patch.object(
            carts, "link_carts_to_orders", lambda **k: 0
        ):
            summary = carts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
                **kwargs,
            )
        return summary, written

    @staticmethod
    def _sessions() -> list[dict]:
        line = [{"sku": "SKU-A", "quantity": 1, "price": "10"}]
        return [
            {"cart_token": "real", "email": "shopper@example.com", "line_items": line},
            {"cart_token": "empty-cart", "email": "shopper@example.com", "line_items": []},
            {"cart_token": "anonymous", "line_items": line},
        ]

    def test_only_a_cart_with_items_and_a_shopper_is_written(self) -> None:
        summary, written = self._run(self._sessions())

        self.assertEqual(written, ["real"])
        self.assertEqual(summary["easystore_checkouts_scanned"], 3)
        self.assertEqual(summary["easystore_checkouts_recoverable"], 1)
        self.assertEqual(summary["checkouts_without_line_items"], 1)
        self.assertEqual(summary["checkouts_without_a_contactable_buyer"], 1)
        self.assertTrue(summary["abandoned_cart_filter_applied"])

    def test_carts_left_over_from_earlier_runs_are_reported_not_deleted(self) -> None:
        summary, _ = self._run(self._sessions())

        self.assertEqual(summary["hubspot_carts_not_qualified_by_this_run"], 1)
        self.assertEqual(summary["stale_product_backed_cart_line_items_removed"], 0)

    def test_the_filter_can_be_turned_off(self) -> None:
        summary, written = self._run(self._sessions(), recoverable_only=False)

        self.assertEqual(sorted(written), ["anonymous", "empty-cart", "real"])
        self.assertEqual(summary["checkouts_without_line_items"], 0)
        self.assertFalse(summary["abandoned_cart_filter_applied"])


class DirectCustomerAssociationTests(unittest.TestCase):
    """A store without guest checkout should not have to guess the shopper."""

    def test_an_easystore_customer_id_is_read_from_either_shape(self) -> None:
        self.assertEqual(carts.checkout_customer_id({"customer_id": 4321}), "4321")
        self.assertEqual(
            carts.checkout_customer_id({"customer": {"id": 4321}}), "4321"
        )
        self.assertIsNone(carts.checkout_customer_id({"email": "a@b.co"}))

    def test_the_customer_id_wins_over_the_typed_email_and_phone(self) -> None:
        links: list[str] = []
        contacts = SimpleNamespace(
            by_phone={"+6591234567": {"by-phone"}},
            by_email={"typed@example.com": {"by-email"}},
            by_easystore_customer_id={"4321": {"by-customer-id"}},
            lifecycle_by_id={},
        )
        checkout = {
            "cart_token": "cart-1",
            "customer": {"id": 4321},
            "email": "typed@example.com",
            "phone": "91234567",
            "line_items": [{"sku": "SKU-A", "quantity": 1, "price": "10"}],
        }

        with mock.patch.object(
            carts, "cart_object_available", lambda *_: True
        ), mock.patch.object(
            carts, "iter_orders_for_cart_links", lambda *a, **k: iter(())
        ), mock.patch.object(
            carts, "iter_documented_checkouts", lambda *a, **k: iter((checkout,))
        ), mock.patch.object(
            carts, "hubspot_contact_index", lambda *a, **k: contacts
        ), mock.patch.object(
            carts,
            "resolve_fields",
            lambda **k: dict(carts.cart_mapping.DEFAULT_CART_FIELD_PROPERTIES),
        ), mock.patch.object(
            carts, "resolve_line_item_fields", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "hubspot_product_index", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "hubspot_cart_index", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "hubspot_order_index", lambda *a, **k: {}
        ), mock.patch.object(
            carts, "upsert_cart", lambda *a, **k: ("cart-hs", True)
        ), mock.patch.object(
            carts,
            "associate_cart",
            lambda _t, _c, _type, object_id, _id: links.append(object_id),
        ), mock.patch.object(
            carts, "sync_cart_line_items", lambda **k: (0, 0, 0)
        ), mock.patch.object(
            carts, "link_carts_to_orders", lambda **k: 0
        ):
            summary = carts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertEqual(links, ["by-customer-id"])
        self.assertEqual(
            summary["cart_contact_associations_by_easystore_customer_id"], 1
        )
        self.assertEqual(summary["cart_contact_associations_by_email"], 0)
        self.assertEqual(summary["cart_contact_associations_by_mobile"], 0)

    def test_the_contact_index_reads_the_easystore_customer_id(self) -> None:
        def fake_objects(_url, _token, properties):
            self.assertIn(orders.CONTACT_EASYSTORE_ID_PROPERTY, properties)
            return iter(
                (
                    {
                        "id": "contact-1",
                        "properties": {
                            orders.CONTACT_EASYSTORE_ID_PROPERTY: "4321",
                            "email": "shopper@example.com",
                        },
                    },
                )
            )

        with mock.patch.object(orders, "iter_hubspot_objects", fake_objects):
            index = orders.hubspot_contact_index("hs", "65")

        self.assertEqual(index.by_easystore_customer_id["4321"], {"contact-1"})


if __name__ == "__main__":
    unittest.main()
