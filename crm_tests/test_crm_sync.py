from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_orders as orders
import easystore_hubspot_preflight as preflight
import easystore_hubspot_products as products
from datetime import date

import easystore_hubspot_carts as carts
import easystore_hubspot_reconcile as reconcile
import easystore_hubspot_schema as schema
import easystore_hubspot_sync as customers


class MobileNormalizationTests(unittest.TestCase):
    def test_singapore_local_mobile_gets_country_code(self) -> None:
        self.assertEqual(
            customers.normalize_mobile("9123 4567", "SG", "65"),
            "+6591234567",
        )

    def test_explicit_international_mobile_is_preserved(self) -> None:
        self.assertEqual(
            customers.normalize_mobile("+60 12-345 6789", "SG", "65"),
            "+60123456789",
        )

    def test_00_international_prefix_is_supported(self) -> None:
        self.assertEqual(
            orders.normalize_mobile("0060123456789", "SG", "65"),
            "+60123456789",
        )

    def test_unusable_phone_is_rejected(self) -> None:
        self.assertIsNone(customers.normalize_mobile("123", "SG", "65"))

    def test_placeholder_phone_is_not_a_recorded_mobile(self) -> None:
        for placeholder in ("0000000", "00000000", "1111111111", "-"):
            with self.subTest(placeholder=placeholder):
                self.assertIsNone(
                    customers.normalize_mobile(placeholder, "SG", "65"),
                )
                self.assertIsNone(
                    orders.normalize_mobile(placeholder, "SG", "65"),
                )


class ContactFilterTests(unittest.TestCase):
    def test_customer_without_recorded_mobile_is_filtered_out(self) -> None:
        for customer in (
            {"id": 1},
            {"id": 2, "phone": ""},
            {"id": 3, "phone": "   "},
            {"id": 4, "phone": "n/a"},
            {"id": 5, "phone": "0000000"},
            {"id": 6, "phone": "123"},
        ):
            with self.subTest(customer=customer):
                self.assertIsNone(customers.customer_mobile(customer, "65"))

    def test_customer_with_recorded_mobile_keeps_its_identity(self) -> None:
        self.assertEqual(
            customers.customer_mobile(
                {"id": 7, "phone": "9123 4567", "country_code": "SG"},
                "65",
            ),
            "+6591234567",
        )

    def test_sync_and_preflight_share_one_contact_filter(self) -> None:
        self.assertIs(preflight.customer_mobile, customers.customer_mobile)


class IdentityPreflightTests(unittest.TestCase):
    def test_duplicate_owners_only_returns_real_collisions(self) -> None:
        owners = {
            "+6591111111": {"1"},
            "+6592222222": {"2", "3"},
            "+6593333333": {"4", "4"},
        }
        self.assertEqual(
            preflight.ambiguous_owners(owners),
            {"+6592222222": {"2", "3"}},
        )


class ProductMappingTests(unittest.TestCase):
    def test_variant_sku_uses_real_sku(self) -> None:
        self.assertEqual(
            products.variant_sku("10", {"id": 20, "sku": "ABC-1"}),
            ("ABC-1", False),
        )

    def test_variant_sku_is_stable_when_easystore_sku_is_blank(self) -> None:
        self.assertEqual(
            products.variant_sku("10", {"id": 20, "sku": ""}),
            ("ES-10-20", True),
        )


class HubSpotBatchResponseTests(unittest.TestCase):
    def test_product_batch_requires_all_results(self) -> None:
        response = {
            "status": "COMPLETE",
            "numErrors": 0,
            "errors": [],
            "results": [{"id": "1"}],
        }
        with self.assertRaises(products.SyncError):
            products.assert_batch_success(
                response,
                action="create",
                expected_count=2,
            )

    def test_product_batch_rejects_item_errors_on_successful_http_response(self) -> None:
        response = {
            "status": "COMPLETE",
            "numErrors": 1,
            "errors": [{"message": "bad SKU"}],
            "results": [{"id": "1"}],
        }
        with self.assertRaises(products.SyncError):
            products.assert_batch_success(
                response,
                action="create",
                expected_count=2,
            )

    def test_contact_batch_accepts_complete_full_result_set(self) -> None:
        customers.assert_batch_success(
            {
                "status": "COMPLETE",
                "numErrors": 0,
                "errors": [],
                "results": [{"id": "1"}, {"id": "2"}],
            },
            action="update",
            expected_count=2,
        )

    def test_contact_batch_rejects_pending_response(self) -> None:
        with self.assertRaises(customers.SyncError):
            customers.assert_batch_success(
                {
                    "status": "PENDING",
                    "numErrors": 0,
                    "errors": [],
                    "results": [],
                },
                action="create",
                expected_count=1,
            )


class OrderLineMappingTests(unittest.TestCase):
    def test_line_sku_falls_back_to_product_and_variant_ids(self) -> None:
        self.assertEqual(
            orders._line_sku({"product_id": 10, "variant_id": 20}),
            "ES-10-20",
        )

    def test_desired_lines_are_product_backed_and_group_same_sku(self) -> None:
        order = {
            "id": 99,
            "currency": "SGD",
            "line_items": [
                {"sku": "ABC", "title": "Alpha", "quantity": 1, "price": "12.50"},
                {"sku": "ABC", "title": "Alpha", "quantity": 2, "price": "12.50"},
            ],
        }
        desired = orders.desired_lines(order, {"abc": "777"})
        self.assertEqual(set(desired), {"abc"})
        self.assertEqual(desired["abc"]["hs_product_id"], "777")
        self.assertEqual(desired["abc"]["quantity"], "3")
        self.assertEqual(desired["abc"]["price"], "12.50")
        self.assertEqual(desired["abc"]["hs_line_item_currency_code"], "SGD")

    def test_different_prices_for_same_sku_fail_closed(self) -> None:
        order = {
            "id": 99,
            "line_items": [
                {"sku": "ABC", "quantity": 1, "price": "10"},
                {"sku": "ABC", "quantity": 1, "price": "9"},
            ],
        }
        with self.assertRaises(orders.SyncError):
            orders.desired_lines(order, {"abc": "777"})

    def test_missing_product_fails_instead_of_creating_standalone_line(self) -> None:
        order = {
            "id": 99,
            "line_items": [{"sku": "MISSING", "quantity": 1, "price": "10"}],
        }
        with self.assertRaises(orders.SyncError):
            orders.desired_lines(order, {})


class LineItemDetailTests(unittest.TestCase):
    def _order(self) -> dict[str, object]:
        return {
            "id": 99,
            "currency": "SGD",
            "line_items": [
                {
                    "sku": "ABC",
                    "title": "Alpha",
                    "quantity": 1,
                    "price": "12.50",
                    "total_discount": "-2.50",
                    "total_tax": "0.75",
                    "variant_title": "English",
                }
            ],
        }

    def test_per_line_detail_is_written_when_resolved(self) -> None:
        desired = orders.desired_lines(
            self._order(),
            {"abc": "777"},
            {"discount": "discount", "tax": "tax", "variant": "description"},
        )
        self.assertEqual(desired["abc"]["discount"], "2.50")
        self.assertEqual(desired["abc"]["tax"], "0.75")
        self.assertEqual(desired["abc"]["description"], "English")

    def test_per_line_detail_is_omitted_without_a_resolved_property(self) -> None:
        desired = orders.desired_lines(self._order(), {"abc": "777"})
        self.assertNotIn("discount", desired["abc"])
        self.assertNotIn("tax", desired["abc"])
        self.assertNotIn("description", desired["abc"])
        # The core line item mapping is unchanged.
        self.assertEqual(desired["abc"]["hs_product_id"], "777")
        self.assertEqual(desired["abc"]["price"], "12.50")


class ReconciliationTests(unittest.TestCase):
    def test_only_stale_product_backed_lines_are_archived(self) -> None:
        existing = {
            "keep": {
                "id": "1",
                "properties": {"hs_sku": "KEEP", "hs_product_id": "10"},
            },
            "stale": {
                "id": "2",
                "properties": {"hs_sku": "STALE", "hs_product_id": "20"},
            },
            "manual": {
                "id": "3",
                "properties": {"hs_sku": "MANUAL", "hs_product_id": None},
            },
        }
        desired = {
            "keep": {
                "hs_sku": "KEEP",
                "hs_product_id": "10",
                "name": "Keep",
                "quantity": "1",
            }
        }
        self.assertEqual(
            reconcile.stale_product_backed_line_ids(existing, desired),
            ["2"],
        )


class PropertyResolutionTests(unittest.TestCase):
    def _field(self, **overrides: object) -> schema.FieldSpec:
        defaults = {
            "key": "total_amount",
            "sources": ("total_price",),
            "native": ("hs_total_price",),
            "fallback": "easystore_total_amount",
            "label": "EasyStore Order Total",
            "description": "",
            "kind": "number",
        }
        defaults.update(overrides)
        return schema.FieldSpec(**defaults)

    def test_writable_native_property_is_preferred(self) -> None:
        native = {"hs_total_price": {"name": "hs_total_price", "type": "number"}}
        self.assertEqual(
            schema.select_native(self._field(), native),
            "hs_total_price",
        )

    def test_the_first_usable_native_candidate_wins(self) -> None:
        field = self._field(native=("hs_shipping_cost", "hs_shipping_amount"))
        available = {"hs_shipping_amount": {"type": "number"}}
        self.assertEqual(
            schema.select_native(field, available),
            "hs_shipping_amount",
        )

    def test_calculated_read_only_and_enumeration_natives_are_skipped(self) -> None:
        field = self._field(kind="string")
        for prop in (
            {"type": "string", "calculated": True},
            {"type": "string", "modificationMetadata": {"readOnlyValue": True}},
            {"type": "string", "archived": True},
            {"type": "enumeration"},
            {"type": "number"},
        ):
            with self.subTest(prop=prop):
                self.assertIsNone(
                    schema.select_native(field, {"hs_total_price": prop})
                )

    def test_missing_native_property_falls_back_to_easystore_property(self) -> None:
        for field in orders.ORDER_FIELDS:
            with self.subTest(field=field.key):
                self.assertIsNone(schema.select_native(field, {}))

    def test_property_descriptions_flag_what_cannot_be_written(self) -> None:
        self.assertEqual(
            schema.describe_property("hs_total_price", {"type": "number"}),
            "hs_total_price:number",
        )
        self.assertEqual(
            schema.describe_property(
                "hs_total_price",
                {"type": "number", "calculated": True},
            ),
            "hs_total_price:number[calculated]",
        )
        self.assertEqual(
            schema.describe_property(
                "hs_createdate",
                {"type": "datetime", "modificationMetadata": {"readOnlyValue": True}},
            ),
            "hs_createdate:datetime[read-only]",
        )

    def test_keywords_drop_words_that_describe_every_field(self) -> None:
        field = schema.FieldSpec(key="discount_amount")
        self.assertEqual(schema.field_keywords(field), {"discount"})

    def test_the_portal_is_asked_to_name_its_own_property(self) -> None:
        portal = {
            "hs_discount_total": {"type": "number", "label": "Discount"},
            "hs_total_price": {"type": "number", "label": "Total amount"},
            "easystore_discount_amount": {"type": "number", "label": "EasyStore"},
        }
        hints = schema.matching_properties(portal, {"discount"})
        self.assertEqual(hints, ["hs_discount_total:number"])

    def test_money_values_are_normalized_for_hubspot_numbers(self) -> None:
        self.assertEqual(schema.money_value("SGD 1,234.50"), "1234.50")
        self.assertEqual(schema.money_value(0), "0")
        self.assertEqual(schema.money_value("-5.00", absolute=True), "5.00")
        self.assertIsNone(schema.money_value("free"))
        self.assertIsNone(schema.money_value(None))

    def test_timestamps_become_epoch_milliseconds(self) -> None:
        # The same instant expressed store-local, as UTC, and offset-free.
        for value in (
            "2026-05-01T10:20:30+08:00",
            "2026-05-01T02:20:30Z",
            "2026-05-01 02:20:30",
        ):
            with self.subTest(value=value):
                self.assertEqual(schema.timestamp_value(value), "1777602030000")

    def test_epoch_timestamps_are_scaled_to_milliseconds(self) -> None:
        self.assertEqual(schema.timestamp_value("1777602030"), "1777602030000")
        self.assertEqual(schema.timestamp_value("1777602030000"), "1777602030000")

    def test_dates_are_truncated_to_utc_midnight(self) -> None:
        self.assertEqual(schema.date_value("1993-04-20"), "735264000000")
        self.assertEqual(
            schema.date_value("1993-04-20T15:30:00+08:00"),
            "735264000000",
        )
        self.assertIsNone(schema.date_value("20/04/1993"))

    def test_unparseable_timestamp_is_omitted(self) -> None:
        self.assertIsNone(schema.timestamp_value("last Tuesday"))
        self.assertIsNone(schema.timestamp_value(""))
        self.assertIsNone(schema.timestamp_value(None))


class OrderCommerceFieldTests(unittest.TestCase):
    def _order(self) -> dict[str, object]:
        return {
            "name": "#1002",
            "currency": "SGD",
            "created_at": "2026-05-01T10:20:30+08:00",
            "payment_status_label": "Paid",
            "fulfillment_status": "fulfilled",
            "subtotal_price": "266.00",
            "total_tax": "0.00",
            "total_shipping": "5.00",
            "total_discount": "-12.00",
            "total_price": "259.00",
            "shipping_method": "Standard Delivery",
            "note": "Leave at the door",
            "discount_codes": [{"code": "WELCOME10"}],
            "shipping_address": {
                "address1": "1 Example Road",
                "address2": "#02-03",
                "city": "Singapore",
                "province": "Central",
                "zip": "123456",
                "country": "Singapore",
            },
            "billing_address": {
                "address1": "2 Other Road",
                "city": "Johor Bahru",
                "zip": "80000",
                "country": "Malaysia",
            },
            "fulfillments": [
                {
                    "tracking_number": "TRACK1",
                    "tracking_url": "https://tracking.example/TRACK1",
                }
            ],
        }

    def test_discount_codes_are_collected_without_duplicates(self) -> None:
        self.assertEqual(
            orders._discount_codes(
                {
                    "discount_codes": [{"code": "WELCOME10"}, {"code": "WELCOME10"}],
                    "discount_code": "STAFF",
                }
            ),
            "WELCOME10, STAFF",
        )
        self.assertIsNone(orders._discount_codes({"discount_codes": []}))

    def test_shipping_method_reads_shipping_lines(self) -> None:
        self.assertEqual(
            orders._shipping_method({"shipping_lines": [{"title": "Pickup"}]}),
            "Pickup",
        )
        self.assertIsNone(orders._shipping_method({}))

    def test_money_and_status_fields_map_onto_resolved_properties(self) -> None:
        mapped = orders.order_properties(
            self._order(),
            external_id="1002",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_order_date"], "1777602030000")
        self.assertEqual(mapped["hs_payment_status"], "Paid")
        self.assertEqual(mapped["hs_fulfillment_status"], "fulfilled")
        self.assertEqual(mapped["hs_total_price"], "259.00")
        self.assertEqual(mapped["hs_subtotal_price"], "266.00")
        self.assertEqual(mapped["hs_tax"], "0.00")
        self.assertEqual(mapped["hs_shipping_cost"], "5.00")
        self.assertEqual(mapped["hs_order_discount_amount"], "12.00")
        self.assertEqual(mapped["easystore_discount_codes"], "WELCOME10")
        self.assertEqual(mapped["easystore_order_note"], "Leave at the door")
        self.assertEqual(mapped["hs_shipping_method"], "Standard Delivery")
        self.assertEqual(mapped["hs_shipping_tracking_number"], "TRACK1")
        self.assertEqual(
            mapped["hs_shipping_status_url"],
            "https://tracking.example/TRACK1",
        )

    def test_shipping_and_billing_addresses_are_mapped_separately(self) -> None:
        mapped = orders.order_properties(
            self._order(),
            external_id="1002",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(
            mapped["hs_shipping_address_street"],
            "1 Example Road\n#02-03",
        )
        self.assertEqual(mapped["hs_shipping_address_city"], "Singapore")
        self.assertEqual(mapped["hs_shipping_address_state"], "Central")
        self.assertEqual(mapped["hs_shipping_address_postal_code"], "123456")
        self.assertEqual(mapped["hs_shipping_address_country"], "Singapore")
        self.assertEqual(mapped["hs_billing_address_street"], "2 Other Road")
        self.assertEqual(mapped["hs_billing_address_city"], "Johor Bahru")
        self.assertEqual(mapped["hs_billing_address_postal_code"], "80000")

    def test_billing_address_ships_the_order_when_no_shipping_address_exists(self) -> None:
        mapped = orders.order_properties(
            {"billing_address": {"address1": "2 Other Road", "city": "Johor Bahru"}},
            external_id="1003",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_shipping_address_street"], "2 Other Road")
        self.assertEqual(mapped["hs_shipping_address_city"], "Johor Bahru")

    def test_commerce_fields_can_all_land_on_easystore_properties(self) -> None:
        custom = orders.order_properties(
            self._order(),
            external_id="1002",
            store_domain="cardboardcollective.easy.co",
            field_properties={
                field.key: field.fallback
                for field in orders.ORDER_FIELDS
                if field.fallback is not None
            },
        )
        self.assertEqual(custom["easystore_order_created_at"], "1777602030000")
        self.assertEqual(custom["easystore_payment_status"], "Paid")
        self.assertEqual(custom["easystore_fulfillment_status"], "fulfilled")
        self.assertEqual(custom["easystore_total_amount"], "259.00")
        self.assertEqual(custom["easystore_subtotal_amount"], "266.00")
        self.assertEqual(custom["easystore_tax_amount"], "0.00")
        self.assertEqual(custom["easystore_shipping_amount"], "5.00")
        self.assertEqual(custom["easystore_discount_amount"], "12.00")
        self.assertNotIn("hs_total_price", custom)
        # Shipping detail is native-only, so a portal without it stores nothing.
        self.assertNotIn("hs_shipping_address_street", custom)

    def test_orders_without_commerce_values_omit_the_properties(self) -> None:
        mapped = orders.order_properties(
            {"name": "#1003"},
            external_id="1003",
            store_domain="cardboardcollective.easy.co",
        )
        for field in orders.ORDER_FIELDS:
            with self.subTest(field=field.key):
                self.assertNotIn(
                    orders.DEFAULT_ORDER_FIELD_PROPERTIES[field.key],
                    mapped,
                )

    def test_order_state_and_payment_detail_are_mapped(self) -> None:
        mapped = orders.order_properties(
            {
                "status": "cancelled",
                "payment_method": "Stripe",
                "paid_at": "2026-05-01T02:20:30Z",
                "fulfilled_at": "2026-05-02T02:20:30Z",
                "cancelled_at": "2026-05-03T02:20:30Z",
                "cancel_reason": "Customer changed their mind",
                "total_refunded": "-261.00",
                "source_name": "web",
                "tags": ["preorder", "gift", "preorder"],
            },
            external_id="1004",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_order_status"], "cancelled")
        self.assertEqual(mapped["hs_payment_method"], "Stripe")
        self.assertEqual(mapped["easystore_order_paid_at"], "1777602030000")
        self.assertEqual(mapped["easystore_order_fulfilled_at"], "1777688430000")
        self.assertEqual(mapped["easystore_order_cancelled_at"], "1777774830000")
        self.assertEqual(
            mapped["easystore_order_cancel_reason"],
            "Customer changed their mind",
        )
        self.assertEqual(mapped["easystore_refund_amount"], "261.00")
        self.assertEqual(mapped["easystore_order_channel"], "web")
        self.assertEqual(mapped["easystore_order_tags"], "preorder, gift")

    def test_buyer_and_recipient_detail_stay_on_the_order(self) -> None:
        mapped = orders.order_properties(
            {
                "customer": {
                    "first_name": "Jeremy",
                    "last_name": "Ho",
                    "email": "buyer@example.com",
                    "phone": "9123 4567",
                    "country_code": "SG",
                },
                "shipping_address": {
                    "name": "Reception Desk",
                    "phone": "6555 0000",
                    "address1": "1 Example Road",
                },
                "line_items": [{"quantity": 2}, {"quantity": 3}],
            },
            external_id="1005",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["easystore_order_email"], "buyer@example.com")
        self.assertEqual(mapped["easystore_order_customer_name"], "Jeremy Ho")
        self.assertEqual(mapped["easystore_order_phone"], "+6591234567")
        self.assertEqual(mapped["easystore_shipping_recipient"], "Reception Desk")
        self.assertEqual(mapped["easystore_shipping_phone"], "6555 0000")
        self.assertEqual(mapped["easystore_order_item_count"], "5")

    def test_an_order_number_is_never_mistaken_for_a_buyer_name(self) -> None:
        self.assertIsNone(orders._buyer_name({"name": "#1003"}))
        self.assertEqual(
            orders._buyer_name({"name": "#1003", "customer_name": "Jeremy Ho"}),
            "Jeremy Ho",
        )

    def test_buyer_email_falls_back_through_the_order_and_addresses(self) -> None:
        self.assertEqual(
            orders._buyer_email({"customer": {}, "email": "order@example.com"}),
            "order@example.com",
        )
        self.assertEqual(
            orders._buyer_email({"billing_address": {"email": "billing@example.com"}}),
            "billing@example.com",
        )
        self.assertIsNone(orders._buyer_email({}))

    def test_reported_item_count_wins_over_counting_lines(self) -> None:
        self.assertEqual(
            orders._item_count({"item_count": 9, "line_items": [{"quantity": 1}]}),
            "9",
        )
        self.assertIsNone(orders._item_count({"line_items": []}))

    def test_a_country_only_address_does_not_count_as_an_address(self) -> None:
        # Exactly what EasyStore's order list returned in production: line items
        # and a total present, address present but carrying only a country.
        stub = {
            "id": 1,
            "line_items": [],
            "total_price": "10.00",
            "shipping_address": {"country": "Singapore", "country_code": "SG"},
        }
        self.assertTrue(orders.order_needs_detail(stub))
        # The country still reaches HubSpot; it just is not a delivery address.
        mapped = orders.order_properties(
            stub,
            external_id="1",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_shipping_address_country"], "Singapore")
        self.assertNotIn("hs_shipping_address_street", mapped)

    def test_a_stub_shipping_address_never_hides_a_real_billing_address(self) -> None:
        self.assertEqual(
            orders._delivery_address(
                {
                    "shipping_address": {"country": "SG"},
                    "billing_address": {"address1": "2 Other Road", "city": "JB"},
                }
            ),
            {"address1": "2 Other Road", "city": "JB"},
        )

    def test_payment_and_shipping_method_read_nested_collections(self) -> None:
        self.assertEqual(
            orders._payment_method({"transactions": [{"gateway": "Stripe"}]}),
            "Stripe",
        )
        self.assertEqual(
            orders._payment_method({"payment": {"method": "PayNow"}}),
            "PayNow",
        )
        self.assertIsNone(orders._payment_method({}))
        self.assertEqual(
            orders._shipping_method({"shipment": {"courier": "J&T"}}),
            "J&T",
        )

    def test_thin_listed_orders_are_fetched_in_detail(self) -> None:
        complete = {
            "id": 1,
            "line_items": [],
            "shipping_address": {"city": "Singapore"},
            "total_price": "10.00",
        }
        self.assertFalse(orders.order_needs_detail(complete))
        for thin in (
            {"id": 1, "shipping_address": {"city": "X"}, "total_price": "1"},
            {"id": 1, "line_items": [], "total_price": "1"},
            {"id": 1, "line_items": [], "shipping_address": {"city": "X"}},
        ):
            with self.subTest(thin=sorted(thin)):
                self.assertTrue(orders.order_needs_detail(thin))


class LifecycleStageTests(unittest.TestCase):
    def test_account_without_a_stage_becomes_a_lead(self) -> None:
        self.assertEqual(customers.lifecycle_stage_write(None), "lead")
        self.assertEqual(customers.lifecycle_stage_write(""), "lead")
        self.assertEqual(customers.lifecycle_stage_write("subscriber"), "lead")

    def test_a_buyer_is_never_demoted_back_to_lead(self) -> None:
        for stage in ("lead", "opportunity", "customer", "Customer", "evangelist"):
            with self.subTest(stage=stage):
                self.assertIsNone(customers.lifecycle_stage_write(stage))

    def test_an_order_promotes_its_buyer_to_customer(self) -> None:
        for stage in (None, "", "lead", "salesqualifiedlead"):
            with self.subTest(stage=stage):
                self.assertEqual(
                    orders.lifecycle_stage_write(stage, orders.LIFECYCLE_CUSTOMER),
                    "customer",
                )

    def test_an_existing_customer_is_not_rewritten(self) -> None:
        self.assertIsNone(
            orders.lifecycle_stage_write("customer", orders.LIFECYCLE_CUSTOMER)
        )
        self.assertIsNone(
            orders.lifecycle_stage_write("evangelist", orders.LIFECYCLE_CUSTOMER)
        )

    def test_custom_pipeline_stages_are_left_untouched(self) -> None:
        self.assertIsNone(customers.lifecycle_stage_write("onboarding"))
        self.assertIsNone(
            orders.lifecycle_stage_write("onboarding", orders.LIFECYCLE_CUSTOMER)
        )

    def test_both_stages_share_one_pipeline_ordering(self) -> None:
        self.assertEqual(
            customers.LIFECYCLE_STAGE_RANKS,
            orders.LIFECYCLE_STAGE_RANKS,
        )


class CustomerSyncBatchTests(unittest.TestCase):
    def test_only_customers_with_a_mobile_are_written_as_leads(self) -> None:
        easystore = [
            {
                "id": 1,
                "phone": "9123 4567",
                "country_code": "SG",
                "first_name": "Ada",
                "created_at": "2026-05-01T02:20:30Z",
                "orders_count": 3,
                "total_spent": "266.00",
                "tags": ["vip", "vip", "wholesale"],
            },
            {"id": 2, "phone": "", "first_name": "No Phone"},
            {"id": 3, "phone": "0000000", "first_name": "Placeholder"},
            {"id": 4, "phone": "9123 4568", "country_code": "SG"},
            {"id": 5, "phone": "9123 4569", "country_code": "SG"},
        ]
        hubspot = [
            {
                "id": "100",
                "properties": {"mobilephone": "+6591234568", "lifecyclestage": "lead"},
            },
            {
                "id": "200",
                "properties": {
                    "mobilephone": "+6591234569",
                    "lifecyclestage": "customer",
                },
            },
        ]
        # Every extra customer property already exists in this portal.
        contact_schema = {
            "results": [
                {"name": field.fallback, "type": field.kind}
                for field in customers.CONTACT_FIELDS
            ]
        }
        written: dict[str, list[dict]] = {"create": [], "update": []}

        def fake_batch_write(access_token, action, inputs):
            written[action].extend(inputs)

        with mock.patch.object(
            customers, "iter_easystore_customers", lambda *a, **k: iter(easystore)
        ), mock.patch.object(
            customers, "iter_hubspot_contacts", lambda *a, **k: iter(hubspot)
        ), mock.patch.object(
            customers, "_http_json", _hubspot_only(contact_schema)
        ), mock.patch.object(
            customers, "_batch_write", fake_batch_write
        ):
            summary = customers.sync(
                store_domain="cardboardcollective.easy.co",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertEqual(summary["easystore_customers"], 5)
        self.assertEqual(summary["skipped_without_mobile"], 2)
        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["updated"], 2)

        created = written["create"][0]["properties"]
        self.assertEqual(created["mobilephone"], "+6591234567")
        self.assertEqual(created["lifecyclestage"], "lead")
        self.assertEqual(created["easystore_customer_id"], "1")
        self.assertEqual(created["easystore_customer_since"], "1777602030000")
        self.assertEqual(created["easystore_orders_count"], "3")
        self.assertEqual(created["easystore_total_spent"], "266.00")
        self.assertEqual(created["easystore_customer_tags"], "vip, wholesale")

        updates = {item["id"]: item["properties"] for item in written["update"]}
        # Already a lead: nothing to move.
        self.assertNotIn("lifecyclestage", updates["100"])
        # Already a customer: an account must not demote a buyer.
        self.assertNotIn("lifecyclestage", updates["200"])
        self.assertEqual(summary["lifecycle_stage_leads_assigned"], 1)
        self.assertEqual(
            summary["easystore_customer_field_coverage"],
            {
                "birthday": 0,
                "birthday_day": 0,
                "customer_id": 3,
                "customer_since": 1,
                "gender": 0,
                "last_order_at": 0,
                "next_birthday": 0,
                "note": 0,
                "orders_count": 1,
                "tags": 1,
                "total_spent": 1,
            },
        )

    def test_a_birthday_an_earlier_run_got_wrong_is_cleared(self) -> None:
        # The contact exists and EasyStore reports only a next occurrence, so the
        # 2027 date an earlier run wrote must not simply be left behind.
        easystore = [
            {
                "id": 1,
                "phone": "9123 4567",
                "country_code": "SG",
                "birthday": "2027-01-15",
            }
        ]
        hubspot = [{"id": "100", "properties": {"mobilephone": "+6591234567"}}]
        contact_schema = {
            "results": [
                {"name": field.fallback, "type": field.kind}
                for field in customers.CONTACT_FIELDS
            ]
        }
        written: list[dict] = []

        with mock.patch.object(
            customers, "iter_easystore_customers", lambda *a, **k: iter(easystore)
        ), mock.patch.object(
            customers, "iter_hubspot_contacts", lambda *a, **k: iter(hubspot)
        ), mock.patch.object(
            customers, "_http_json", _hubspot_only(contact_schema)
        ), mock.patch.object(
            customers,
            "_batch_write",
            lambda token, action, inputs: written.extend(inputs),
        ):
            summary = customers.sync(
                store_domain="cardboardcollective.easy.co",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        properties = written[0]["properties"]
        self.assertEqual(properties["easystore_customer_birthday"], "")
        self.assertEqual(properties["easystore_birthday_day"], "01-15")
        self.assertEqual(summary["birthday_property_cleared"], 1)

    def test_a_portal_owned_birthday_property_is_never_cleared(self) -> None:
        # date_of_birth belongs to the portal; a person may maintain it by hand.
        easystore = [
            {
                "id": 1,
                "phone": "9123 4567",
                "country_code": "SG",
                "birthday": "2027-01-15",
            }
        ]
        hubspot = [{"id": "100", "properties": {"mobilephone": "+6591234567"}}]
        contact_schema = {"results": [{"name": "date_of_birth", "type": "date"}]}
        written: list[dict] = []

        with mock.patch.object(
            customers, "iter_easystore_customers", lambda *a, **k: iter(easystore)
        ), mock.patch.object(
            customers, "iter_hubspot_contacts", lambda *a, **k: iter(hubspot)
        ), mock.patch.object(
            customers, "_http_json", _hubspot_only(contact_schema)
        ), mock.patch.object(
            customers,
            "_batch_write",
            lambda token, action, inputs: written.extend(inputs),
        ):
            summary = customers.sync(
                store_domain="cardboardcollective.easy.co",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertNotIn("date_of_birth", written[0]["properties"])
        self.assertEqual(summary["birthday_property_cleared"], 0)

    def test_customer_extras_are_skipped_without_the_schema_scopes(self) -> None:
        easystore = [{"id": 1, "phone": "9123 4567", "country_code": "SG"}]
        written: dict[str, list[dict]] = {"create": [], "update": []}

        with mock.patch.object(
            customers, "iter_easystore_customers", lambda *a, **k: iter(easystore)
        ), mock.patch.object(
            customers, "iter_hubspot_contacts", lambda *a, **k: iter(())
        ), mock.patch.object(
            customers, "_http_json", lambda *a, **k: None
        ), mock.patch.object(
            customers,
            "_batch_write",
            lambda token, action, inputs: written[action].extend(inputs),
        ):
            summary = customers.sync(
                store_domain="cardboardcollective.easy.co",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        created = written["create"][0]["properties"]
        self.assertEqual(created["mobilephone"], "+6591234567")
        self.assertNotIn("easystore_customer_id", created)
        self.assertEqual(summary["hubspot_contact_field_properties"], {})


class CustomerDetailTests(unittest.TestCase):
    def test_a_list_record_missing_the_fields_is_fetched_in_detail(self) -> None:
        # Key presence decides, not a value: a customer legitimately has no
        # birthday, and re-fetching them forever would cost a request each run.
        self.assertTrue(customers.customer_needs_detail({"id": 1, "email": "a@b.c"}))
        self.assertTrue(customers.customer_needs_detail({"id": 1, "birthdate": "1993-04-20"}))
        self.assertTrue(
            customers.customer_needs_detail({"id": 1, "birthdate": "", "attributes": []})
        )
        self.assertFalse(
            customers.customer_needs_detail(
                {"id": 1, "birthdate": "", "attributes": [], "note": ""}
            )
        )

    def test_the_detail_record_replaces_the_thin_one(self) -> None:
        detail = {
            "customer": {
                "id": 1,
                "birthdate": "1993-04-20",
                "attributes": [{"customer_attribute_setting_id": 7, "value": "Instagram"}],
            }
        }
        with mock.patch.object(customers, "_http_json", lambda *a, **k: detail):
            completed = customers.complete_customer(
                "shop.example",
                "token",
                {"id": 1, "email": "a@b.c"},
            )
        self.assertEqual(completed["birthdate"], "1993-04-20")

    def test_a_customer_that_cannot_be_fetched_is_used_as_listed(self) -> None:
        listed = {"id": 1, "email": "a@b.c"}
        with mock.patch.object(customers, "_http_json", lambda *a, **k: None):
            self.assertIs(
                customers.complete_customer("shop.example", "token", listed),
                listed,
            )


class CustomerNoteTests(unittest.TestCase):
    def test_a_note_is_read_from_a_string_a_record_or_a_list(self) -> None:
        self.assertEqual(
            customers.customer_note({"note": "Collects the deluxe sets"}),
            "Collects the deluxe sets",
        )
        self.assertEqual(
            customers.customer_note({"note": {"body": "Prefers pickup"}}),
            "Prefers pickup",
        )
        self.assertEqual(
            customers.customer_note(
                {
                    "notes": [
                        {"note": "Prefers pickup", "created_at": "2026-01-01"},
                        {"note": "VIP"},
                    ]
                }
            ),
            "Prefers pickup\nVIP",
        )

    def test_the_wording_easystore_uses_for_a_remark_is_read_too(self) -> None:
        # EasyStore calls the shopper's own order message a remark
        # (theme/templates/customers/order.liquid renders order.remark).
        for key in ("remark", "remarks", "internal_note", "admin_note", "comment"):
            with self.subTest(key=key):
                self.assertEqual(
                    customers.customer_note({key: "Prefers pickup"}),
                    "Prefers pickup",
                )

    def test_an_empty_note_collection_is_absent_not_a_python_repr(self) -> None:
        # str([]) is "[]", which would have landed in the CRM as the note.
        self.assertIsNone(customers.customer_note({"notes": []}))
        self.assertIsNone(customers.customer_note({"note": ""}))
        self.assertIsNone(customers.customer_note({}))

    def test_no_container_is_ever_written_as_text(self) -> None:
        # The same guard protects every field, not just notes.
        self.assertIsNone(schema.nonempty([]))
        self.assertIsNone(schema.nonempty([{"note": "x"}]))
        self.assertIsNone(schema.nonempty({}))
        self.assertIsNone(schema.nonempty({"body": "x"}))
        self.assertEqual(schema.nonempty(0), "0")
        self.assertEqual(schema.nonempty(" x "), "x")

    def test_a_thin_money_value_triggers_a_detail_fetch_rather_than_a_repr(self) -> None:
        # A money field arriving as a nested object used to stringify; now it
        # reads as absent, which is what asks for the order's detail.
        self.assertTrue(
            orders.order_needs_detail(
                {
                    "id": 1,
                    "line_items": [],
                    "shipping_address": {"city": "Singapore"},
                    "total_price": {"amount": "10.00"},
                }
            )
        )

    def test_an_order_note_reads_the_same_shapes(self) -> None:
        self.assertEqual(
            orders._order_note({"notes": [{"note": "Leave at the door"}]}),
            "Leave at the door",
        )
        self.assertIsNone(orders._order_note({"notes": []}))


class CustomerFieldTests(unittest.TestCase):
    def test_tags_are_normalized_from_lists_strings_and_objects(self) -> None:
        self.assertEqual(
            customers._customer_tags({"tags": ["vip", "vip", " wholesale "]}),
            "vip, wholesale",
        )
        self.assertEqual(
            customers._customer_tags({"tags": "vip, wholesale"}),
            "vip, wholesale",
        )
        self.assertEqual(
            customers._customer_tags({"tags": [{"name": "vip"}]}),
            "vip",
        )
        self.assertIsNone(customers._customer_tags({}))

    def test_customer_extras_are_read_from_easystore_aliases(self) -> None:
        values = customers.customer_field_values(
            {
                "id": 7,
                "order_count": 2,
                "total_spend": "SGD 1,000.00",
                "last_order_at": "2026-05-01T02:20:30Z",
                "note": "Collects the deluxe sets",
            }
        )
        self.assertEqual(values["customer_id"], "7")
        self.assertEqual(values["orders_count"], "2")
        self.assertEqual(values["total_spent"], "1000.00")
        self.assertEqual(values["last_order_at"], "1777602030000")
        self.assertEqual(values["note"], "Collects the deluxe sets")


def _hubspot_only(schema_document: dict) -> object:
    """Answer HubSpot schema reads only, so EasyStore routes stay unmocked.

    The contact stage now reads EasyStore's customer detail and attribute
    settings through the same helper, and answering those with a HubSpot payload
    would make a test pass for the wrong reason.
    """

    def fake_http_json(url, *args, **kwargs):
        return schema_document if "api.hubapi.com" in url else None

    return fake_http_json


class BirthdayTests(unittest.TestCase):
    def test_a_compact_date_is_not_read_as_an_epoch(self) -> None:
        # 19930420 read as epoch seconds lands in August 1970.
        self.assertEqual(schema.date_value("19930420"), schema.date_value("1993-04-20"))

    def test_a_date_keeps_the_calendar_day_it_was_written_with(self) -> None:
        # Converting an offset-bearing midnight to UTC first moved a birthday to
        # the previous day for every store east of Greenwich.
        for value in (
            "1993-04-20",
            "1993-04-20T00:00:00+08:00",
            "1993-04-20T23:30:00-05:00",
        ):
            with self.subTest(value=value):
                self.assertEqual(schema.date_value(value), "735264000000")

    def test_an_impossible_date_is_dropped(self) -> None:
        self.assertIsNone(schema.date_value("19930231"))
        self.assertIsNone(schema.date_value("20/04/1993"))

    def test_nobody_is_born_in_the_future(self) -> None:
        self.assertIsNone(customers.customer_birthday({"birthday": "2099-09-15"}))

    def test_a_future_source_gives_way_to_a_real_birthday(self) -> None:
        # A store that reports the upcoming anniversary in one field and the real
        # date of birth in another must not sync the anniversary.
        self.assertEqual(
            customers.customer_birthday({"birthday": "2099-09-15", "dob": "1993-04-20"}),
            "1993-04-20",
        )

    def test_a_real_birthday_is_kept(self) -> None:
        self.assertEqual(
            customers.customer_birthday({"birthday": "1993-04-20"}),
            "1993-04-20",
        )

    def test_the_real_date_of_birth_field_wins_over_the_occurrence(self) -> None:
        # EasyStore's storefront reads and writes customer.birthdate for a date of
        # birth (theme/templates/customers/account.liquid), while `birthday` comes
        # back as the next occurrence of it.
        values = customers.customer_field_values(
            {"birthdate": "1993-04-20", "birthday": "2027-04-20"}
        )
        self.assertEqual(values["birthday"], schema.date_value("1993-04-20"))
        self.assertEqual(values["birthday_day"], "04-20")

    def test_birthdate_is_read_before_every_other_source(self) -> None:
        self.assertEqual(customers.BIRTHDAY_SOURCES[0], "birthdate")

    def test_easystore_reports_the_next_occurrence_not_the_birth_year(self) -> None:
        # A January birthday, reported in August, comes back dated next year.
        values = customers.customer_field_values({"birthday": "2027-01-15"})
        # No birth year is invented from it...
        self.assertNotIn("birthday", values)
        # ...but the day and month, which are real, are kept.
        self.assertEqual(values["birthday_day"], "01-15")
        # ...and the date is stored as what it actually is.
        self.assertEqual(values["next_birthday"], schema.date_value("2027-01-15"))

    def test_an_occurrence_later_this_year_is_read_the_same_way(self) -> None:
        values = customers.customer_field_values({"birthday": "2026-09-15"})
        self.assertNotIn("birthday", values)
        self.assertEqual(values["birthday_day"], "09-15")

    def test_a_real_date_of_birth_still_syncs_as_one(self) -> None:
        values = customers.customer_field_values({"birthday": "1993-04-20"})
        self.assertEqual(values["birthday"], schema.date_value("1993-04-20"))
        self.assertEqual(values["birthday_day"], "04-20")
        # And it is projected forward, so one property serves campaigns either way.
        self.assertIsNotNone(values["next_birthday"])

    def test_a_date_within_the_last_year_is_an_occurrence_not_a_birth(self) -> None:
        today = date(2026, 8, 20)
        self.assertFalse(customers.is_date_of_birth(date(2026, 3, 1), today))
        self.assertFalse(customers.is_date_of_birth(date(2026, 8, 20), today))
        self.assertTrue(customers.is_date_of_birth(date(2025, 8, 19), today))
        self.assertTrue(customers.is_date_of_birth(date(1993, 4, 20), today))

    def test_the_next_occurrence_of_29_february_lands_on_the_28th(self) -> None:
        self.assertEqual(
            customers._next_occurrence(date(1992, 2, 29), date(2026, 8, 20)),
            date(2027, 2, 28),
        )

    def test_the_next_occurrence_includes_a_birthday_today(self) -> None:
        self.assertEqual(
            customers._next_occurrence(date(1993, 8, 20), date(2026, 8, 20)),
            date(2026, 8, 20),
        )

    def test_diagnostics_report_shape_and_year_without_the_date(self) -> None:
        shapes, years, future = customers.birthday_diagnostics(
            {"birthday": "2099-09-15", "dob": "19930420"}
        )
        self.assertEqual(shapes, ["birthday=####-##-##", "dob=########"])
        self.assertEqual(years, ["birthday=2099", "dob=1993"])
        self.assertEqual(future, 1)
        # The masked shape must not carry the date itself.
        self.assertNotIn("1993", shapes[1])

    def test_an_unparseable_birthday_is_named_as_such(self) -> None:
        _shapes, years, future = customers.birthday_diagnostics({"birthday": "next week"})
        self.assertEqual(years, ["birthday=unparsed"])
        self.assertEqual(future, 0)


class AbandonedCartTests(unittest.TestCase):
    def _checkout(self) -> dict[str, object]:
        return {
            "id": 900,
            "token": "abc123",
            "currency": "sgd",
            "status": "abandoned",
            "created_at": "2026-08-19T20:00:00+08:00",
            "updated_at": "2026-08-19T21:30:00+08:00",
            "total_price": "266.00",
            "subtotal_price": "266.00",
            "total_discount": "-10.00",
            "total_tax": "0.00",
            "total_shipping": "5.00",
            "abandoned_checkout_url": "https://shop.example/checkouts/abc123/recover",
            "customer": {
                "first_name": "Jeremy",
                "last_name": "Ho",
                "email": "shopper@example.com",
                "phone": "9123 4567",
                "country_code": "SG",
            },
            "line_items": [
                {"title": "The Hobbit", "sku": "A", "quantity": 1},
                {"title": "Scenes", "sku": "B", "quantity": 2},
            ],
        }

    def test_a_checkout_maps_onto_hubspot_cart_properties(self) -> None:
        mapped = carts.cart_properties(
            self._checkout(),
            external_id="900",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_external_cart_id"], "900")
        self.assertEqual(mapped["hs_currency_code"], "SGD")
        self.assertEqual(mapped["hs_source_store"], "cardboardcollective.easy.co")
        self.assertEqual(mapped["hs_total_price"], "266.00")
        self.assertEqual(mapped["hs_subtotal_price"], "266.00")
        self.assertEqual(mapped["hs_cart_discount"], "10.00")
        self.assertEqual(mapped["hs_tax"], "0.00")
        self.assertEqual(mapped["hs_shipping_cost"], "5.00")
        self.assertEqual(mapped["hs_external_status"], "abandoned")

    def test_the_cart_records_what_was_left_behind_and_how_to_recover_it(self) -> None:
        mapped = carts.cart_properties(
            self._checkout(),
            external_id="900",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["easystore_cart_items"], "The Hobbit x1; Scenes x2")
        self.assertEqual(mapped["easystore_cart_item_count"], "3")
        self.assertEqual(mapped["easystore_cart_email"], "shopper@example.com")
        self.assertEqual(mapped["easystore_cart_customer_name"], "Jeremy Ho")
        self.assertEqual(mapped["easystore_cart_phone"], "+6591234567")

    def test_the_cart_natives_hubspot_already_defines_are_preferred(self) -> None:
        # HubSpot's Cart object carries the recovery link and both external
        # timestamps itself, so nothing here belongs in an easystore_* property.
        mapped = carts.cart_properties(
            self._checkout(),
            external_id="900",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(
            mapped["hs_cart_url"],
            "https://shop.example/checkouts/abc123/recover",
        )
        self.assertEqual(mapped["hs_external_token"], "abc123")
        self.assertIn("hs_external_created_date", mapped)
        self.assertIn("hs_external_modified_date", mapped)
        for retired in (
            "easystore_cart_recovery_url",
            "easystore_cart_created_at",
            "easystore_cart_abandoned_at",
        ):
            self.assertNotIn(retired, mapped)

    def test_a_checkout_address_lands_on_the_hubspot_cart_address(self) -> None:
        checkout = self._checkout()
        checkout["shipping_address"] = {
            "address1": "1 Marina Boulevard",
            "address2": "#12-01",
            "city": "Singapore",
            "zip": "018989",
            "country": "Singapore",
            "phone": "9123 4567",
        }
        checkout["billing_address"] = {"address1": "2 Other Road", "city": "Johor Bahru"}
        mapped = carts.cart_properties(
            checkout,
            external_id="900",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(
            mapped["hs_shipping_address_street"],
            "1 Marina Boulevard\n#12-01",
        )
        self.assertEqual(mapped["hs_shipping_address_city"], "Singapore")
        self.assertEqual(mapped["hs_shipping_address_postal_code"], "018989")
        self.assertEqual(mapped["hs_shipping_address_phone"], "9123 4567")
        self.assertEqual(mapped["hs_billing_address_street"], "2 Other Road")
        self.assertEqual(mapped["hs_billing_address_city"], "Johor Bahru")

    def test_checkout_discount_codes_reach_the_cart(self) -> None:
        checkout = self._checkout()
        checkout["discount_codes"] = [{"code": "WELCOME10"}, {"code": "WELCOME10"}]
        mapped = carts.cart_properties(
            checkout,
            external_id="900",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_discount_codes"], "WELCOME10")

    def test_a_completed_checkout_is_not_a_cart(self) -> None:
        # It is already an Order; syncing it here would double-count revenue.
        for completed in (
            {"id": 1, "order_id": 55},
            {"id": 2, "order": {"id": 55}},
            {"id": 3, "completed_at": "2026-08-19T21:00:00+08:00"},
            {"id": 4, "status": "completed"},
            {"id": 5, "status": "Paid"},
        ):
            with self.subTest(completed=sorted(completed)):
                self.assertFalse(carts.is_abandoned(completed))
        self.assertTrue(carts.is_abandoned(self._checkout()))

    def test_the_shopper_is_resolved_with_the_crm_identity_rule(self) -> None:
        self.assertEqual(carts.cart_mobile(self._checkout(), "65"), "+6591234567")
        self.assertEqual(
            carts.cart_mobile({"billing_address": {"phone": "9123 4568"}}, "65"),
            "+6591234568",
        )
        self.assertIsNone(carts.cart_mobile({}, "65"))

    def test_a_portal_without_the_cart_object_is_skipped_not_failed(self) -> None:
        with mock.patch.object(carts, "_http_json", lambda *a, **k: None):
            summary = carts.sync(
                store_domain="cardboardcollective.easy.co",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )
        self.assertEqual(summary, {"hubspot_cart_object": "unavailable"})

    def test_every_checkout_route_is_tried_before_giving_up(self) -> None:
        attempted: list[str] = []

        def fake_http_json(url, **kwargs):
            attempted.append(url.split("/api/3.0/")[-1].split("?")[0])
            return None

        with mock.patch.object(carts, "_http_json", fake_http_json):
            route, records, probes = carts.iter_easystore_checkouts(
                "shop.example",
                "token",
            )

        self.assertIsNone(route)
        self.assertEqual(list(records), [])
        self.assertEqual(attempted, list(carts.CHECKOUT_ROUTES))
        self.assertEqual(list(probes), list(carts.CHECKOUT_ROUTES))

    def test_the_route_that_answers_is_the_one_used(self) -> None:
        def fake_http_json(url, **kwargs):
            if "abandoned_checkouts.json" in url:
                return {"abandoned_checkouts": [{"id": 900}]}
            return None

        with mock.patch.object(carts, "_http_json", fake_http_json):
            route, records, probes = carts.iter_easystore_checkouts(
                "shop.example",
                "token",
            )
            found = [record["id"] for record in records]

        self.assertEqual(route, "abandoned_checkouts.json")
        self.assertEqual(found, [900])
        # The routes after the answering one are not probed at all.
        self.assertEqual(list(probes), ["checkouts.json", "abandoned_checkouts.json"])

    def test_a_route_that_never_answers_does_not_fail_the_sync(self) -> None:
        # The production symptom: EasyStore let the read hang on checkouts.json
        # until it timed out, which took the whole workflow down with it.
        def fake_http_json(url, **kwargs):
            if "checkouts.json" in url and "abandoned" not in url:
                raise carts.SyncError(
                    f"GET {url} failed: The read operation timed out"
                )
            if "abandoned_checkouts.json" in url:
                return {"abandoned_checkouts": [{"id": 900}]}
            return None

        with mock.patch.object(carts, "_http_json", fake_http_json):
            route, records, probes = carts.iter_easystore_checkouts(
                "shop.example",
                "token",
            )
            found = [record["id"] for record in records]

        self.assertEqual(route, "abandoned_checkouts.json")
        self.assertEqual(found, [900])
        self.assertIn("timed out", probes["checkouts.json"])

    def test_a_probe_is_one_record_on_a_short_leash(self) -> None:
        seen: list[dict[str, object]] = []

        def fake_http_json(url, **kwargs):
            seen.append({"url": url, **kwargs})
            return None

        with mock.patch.object(carts, "_http_json", fake_http_json):
            carts.iter_easystore_checkouts("shop.example", "token")

        for call in seen:
            self.assertIn(f"limit={carts.CHECKOUT_PROBE_LIMIT}", call["url"])
            self.assertEqual(call["retries"], carts.CHECKOUT_PROBE_RETRIES)
            self.assertEqual(call["timeout"], carts.CHECKOUT_PROBE_TIMEOUT)

    def test_an_empty_route_never_hides_one_holding_checkouts(self) -> None:
        def fake_http_json(url, **kwargs):
            if "carts.json" in url and "abandoned" not in url:
                return {"carts": [{"id": 900}]}
            return {"checkouts": []}

        with mock.patch.object(carts, "_http_json", fake_http_json):
            route, records, _probes = carts.iter_easystore_checkouts(
                "shop.example",
                "token",
            )
            found = [record["id"] for record in records]

        self.assertEqual(route, "carts.json")
        self.assertEqual(found, [900])

    def test_an_empty_route_is_reported_when_no_route_holds_checkouts(self) -> None:
        with mock.patch.object(carts, "_http_json", lambda url, **k: {"checkouts": []}):
            route, records, probes = carts.iter_easystore_checkouts(
                "shop.example",
                "token",
            )

        self.assertEqual(route, "checkouts.json")
        self.assertEqual(list(records), [])
        self.assertEqual(probes["checkouts.json"], "answered with no records")

    def test_nothing_to_sync_reads_no_hubspot_identities(self) -> None:
        # Scanning every contact and cart to match zero checkouts is pure cost.
        def fake_http_json(url, **kwargs):
            if "properties/carts" in url:
                return {"results": [{"name": "hs_external_cart_id", "type": "string"}]}
            return {"checkouts": []}

        def fail(*args, **kwargs):
            raise AssertionError("HubSpot was scanned with nothing to sync")

        with mock.patch.object(carts, "_http_json", fake_http_json):
            with mock.patch.object(carts, "hubspot_cart_index", fail):
                summary = carts.sync(
                    store_domain="cardboardcollective.easy.co",
                    easystore_access_token="es",
                    hubspot_access_token="hs",
                    fallback_dial_code="65",
                )

        self.assertEqual(summary["easystore_checkout_route"], "checkouts.json")
        self.assertEqual(summary["easystore_checkouts_scanned"], 0)

    # The Cart schema this portal actually reports, copied from a sync run. Only
    # the properties this stage reasons about are listed; a mistyped or read-only
    # native shows up here so the resolver's choice is checked against reality
    # rather than against what HubSpot's docs imply.
    PORTAL_CART_SCHEMA = (
        ("hs_billing_address_city", "string", False),
        ("hs_billing_address_country", "string", False),
        ("hs_billing_address_phone", "string", False),
        ("hs_billing_address_postal_code", "string", False),
        ("hs_billing_address_state", "string", False),
        ("hs_billing_address_street", "string", False),
        ("hs_buyer_accepts_marketing", "bool", False),
        ("hs_cart_discount", "number", False),
        ("hs_cart_name", "string", False),
        ("hs_cart_url", "string", False),
        ("hs_currency_code", "enumeration", False),
        ("hs_discount_codes", "string", False),
        ("hs_external_cart_id", "string", False),
        ("hs_external_created_date", "datetime", False),
        ("hs_external_modified_date", "datetime", False),
        ("hs_external_status", "string", False),
        ("hs_external_token", "string", False),
        ("hs_homecurrency_amount", "number", True),
        ("hs_landing_site", "string", False),
        ("hs_lastmodifieddate", "datetime", True),
        ("hs_referring_site", "string", False),
        ("hs_shipping_address_city", "string", False),
        ("hs_shipping_address_country", "string", False),
        ("hs_shipping_address_phone", "string", False),
        ("hs_shipping_address_postal_code", "string", False),
        ("hs_shipping_address_state", "string", False),
        ("hs_shipping_address_street", "string", False),
        ("hs_shipping_cost", "number", False),
        ("hs_source_store", "string", False),
        ("hs_subtotal_price", "number", False),
        ("hs_tags", "string", False),
        ("hs_tax", "number", False),
        ("hs_total_price", "number", False),
        ("hs_total_weight", "string", False),
    )

    def test_the_live_cart_schema_resolves_to_hubspots_own_properties(self) -> None:
        results = [
            {"name": name, "type": kind, "modificationMetadata": {"readOnlyValue": ro}}
            for name, kind, ro in self.PORTAL_CART_SCHEMA
        ]

        def fake_http_json(url, *, method="GET", **kwargs):
            if method == "GET" and url.endswith("/properties/carts"):
                return {"results": results}
            raise AssertionError(f"unexpected {method} {url}")

        resolved = schema.resolve_fields(
            http_json=fake_http_json,
            access_token="hs",
            object_type=carts.CART_OBJECT_TYPE,
            fields=tuple(
                field for field in carts.CART_FIELDS if not field.fallback
            ),
            error=carts.SyncError,
        )

        self.assertEqual(
            resolved,
            {
                "token": "hs_external_token",
                "discount_codes": "hs_discount_codes",
                "landing_site": "hs_landing_site",
                "referring_site": "hs_referring_site",
                "total_weight": "hs_total_weight",
                "shipping_address_street": "hs_shipping_address_street",
                "shipping_address_city": "hs_shipping_address_city",
                "shipping_address_state": "hs_shipping_address_state",
                "shipping_address_postal_code": "hs_shipping_address_postal_code",
                "shipping_address_country": "hs_shipping_address_country",
                "shipping_address_phone": "hs_shipping_address_phone",
                "billing_address_street": "hs_billing_address_street",
                "billing_address_city": "hs_billing_address_city",
                "billing_address_state": "hs_billing_address_state",
                "billing_address_postal_code": "hs_billing_address_postal_code",
                "billing_address_country": "hs_billing_address_country",
                "billing_address_phone": "hs_billing_address_phone",
            },
        )

    def test_duplicate_hubspot_carts_fail_closed(self) -> None:
        existing = [
            {"id": "1", "properties": {"hs_external_cart_id": "900"}},
            {"id": "2", "properties": {"hs_external_cart_id": "900"}},
        ]
        with mock.patch.object(
            carts, "iter_hubspot_objects", lambda *a, **k: iter(existing)
        ):
            with self.assertRaises(carts.SyncError):
                carts.hubspot_cart_index("token")


class CustomerAttributeTests(unittest.TestCase):
    def test_attributes_are_read_from_both_easystore_shapes(self) -> None:
        self.assertEqual(
            customers.customer_attributes(
                {
                    "custom_fields": [
                        {"label": "How did you find us?", "value": "Instagram"},
                        {"name": "Favourite set", "value": ["Hobbit", "LOTR"]},
                        {"value": "no label so no property"},
                    ],
                    "attributes": {"Newsletter frequency": "Weekly"},
                }
            ),
            {
                "How did you find us?": "Instagram",
                "Favourite set": "Hobbit, LOTR",
                "Newsletter frequency": "Weekly",
            },
        )

    def test_an_answer_keyed_by_setting_id_is_still_synchronized(self) -> None:
        # EasyStore answers carry the id of the shop attribute setting, not its
        # question: {"customer_attribute_setting_id": 7, "value": "Instagram"}.
        customer = {"attributes": [{"customer_attribute_setting_id": 7, "value": "Instagram"}]}
        self.assertEqual(
            customers.customer_attributes(customer),
            {"setting 7": "Instagram"},
        )
        self.assertEqual(
            customers.attribute_property_name("setting 7"),
            "easystore_attr_setting_7",
        )

    def test_the_shop_wording_names_the_property_when_it_is_known(self) -> None:
        customer = {"attributes": [{"customer_attribute_setting_id": 7, "value": "Instagram"}]}
        self.assertEqual(
            customers.customer_attributes(customer, {"7": "How did you find us?"}),
            {"How did you find us?": "Instagram"},
        )

    def test_attribute_titles_come_from_the_route_that_answers(self) -> None:
        def fake_http_json(url, *, allow_statuses=None, **kwargs):
            # Only the second candidate answers, so the loop has to reach it.
            if url.endswith("/attribute_settings.json"):
                return {
                    "attribute_settings": [
                        {"id": 7, "title": "How did you find us?"},
                        {"id": 8, "name": "Favourite set"},
                        {"id": 9},
                    ]
                }
            return None

        with mock.patch.object(customers, "_http_json", fake_http_json):
            route, titles = customers.fetch_attribute_titles("shop.example", "token")

        self.assertEqual(route, "attribute_settings.json")
        self.assertEqual(titles, {"7": "How did you find us?", "8": "Favourite set"})

    def test_answers_still_sync_when_no_route_names_them(self) -> None:
        with mock.patch.object(customers, "_http_json", lambda *a, **k: None):
            route, titles = customers.fetch_attribute_titles("shop.example", "token")
        self.assertIsNone(route)
        self.assertEqual(titles, {})

    def test_blank_answers_are_not_attributes(self) -> None:
        self.assertEqual(
            customers.customer_attributes(
                {"custom_fields": [{"label": "Referral", "value": "  "}]}
            ),
            {},
        )
        self.assertEqual(customers.customer_attributes({}), {})

    def test_attribute_property_names_are_slugged(self) -> None:
        self.assertEqual(
            customers.attribute_property_name("How did you find us?"),
            "easystore_attr_how_did_you_find_us",
        )
        self.assertIsNone(customers.attribute_property_name("???"))
        self.assertLessEqual(
            len(customers.attribute_property_name("x" * 200)),
            customers.PROPERTY_NAME_LIMIT,
        )

    def test_attribute_fields_are_alphabetical_and_deduplicated(self) -> None:
        fields, skipped = customers.attribute_fields(
            ["Referral source", "referral source!", "Birthday month"]
        )
        self.assertEqual(
            [field.fallback for field in fields],
            ["easystore_attr_birthday_month", "easystore_attr_referral_source"],
        )
        # The second label slugs to a name already claimed by the first.
        self.assertEqual(skipped, ["referral source!"])

    def test_the_attribute_limit_is_reported_not_silent(self) -> None:
        labels = [f"Question {index:03d}" for index in range(40)]
        fields, skipped = customers.attribute_fields(labels)
        self.assertEqual(len(fields), customers.ATTRIBUTE_LIMIT)
        self.assertEqual(len(skipped), 40 - customers.ATTRIBUTE_LIMIT)

    def test_birthday_and_gender_are_mapped(self) -> None:
        values = customers.customer_field_values(
            {"birthday": "1993-04-20", "gender": "male"}
        )
        # HubSpot date properties hold UTC midnight, not an instant.
        self.assertEqual(values["birthday"], "735264000000")
        self.assertEqual(values["gender"], "male")

    def test_an_unparseable_birthday_is_dropped(self) -> None:
        self.assertNotIn(
            "birthday",
            customers.customer_field_values({"birthday": "20/04/1993"}),
        )

    def test_attributes_reach_hubspot_through_resolved_properties(self) -> None:
        customer = {
            "id": 42,
            "phone": "9123 4567",
            "country_code": "SG",
            "custom_fields": [{"label": "How did you find us?", "value": "Instagram"}],
        }
        fields, _skipped = customers.attribute_fields(
            customers.customer_attributes(customer)
        )
        mapping = {field.key: field.fallback for field in fields}
        properties = customers.customer_properties(customer, "+6591234567", mapping)
        self.assertEqual(
            properties["easystore_attr_how_did_you_find_us"],
            "Instagram",
        )

    def test_a_run_provisions_a_property_for_each_discovered_attribute(self) -> None:
        easystore = [
            {
                "id": 1,
                "phone": "9123 4567",
                "country_code": "SG",
                "custom_fields": [
                    {"label": "How did you find us?", "value": "Instagram"}
                ],
            }
        ]
        created: list[str] = []

        def fake_http_json(
            url,
            *,
            method="GET",
            headers=None,
            payload=None,
            allow_statuses=None,
            **kwargs,
        ):
            if method == "POST" and isinstance(payload, dict) and "name" in payload:
                created.append(payload["name"])
                return {"name": payload["name"]}
            if url.endswith("/crm/v3/properties/contacts") and method == "GET":
                return {"results": []}
            if "/properties/contacts/groups/" in url:
                return {"name": schema.PROPERTY_GROUP}
            return {}

        written: list[dict] = []
        with mock.patch.object(
            customers, "iter_easystore_customers", lambda *a, **k: iter(easystore)
        ), mock.patch.object(
            customers, "iter_hubspot_contacts", lambda *a, **k: iter(())
        ), mock.patch.object(
            customers, "_http_json", fake_http_json
        ), mock.patch.object(
            customers,
            "_batch_write",
            lambda token, action, inputs: written.extend(inputs),
        ):
            summary = customers.sync(
                store_domain="cardboardcollective.easy.co",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertIn("easystore_attr_how_did_you_find_us", created)
        self.assertEqual(
            written[0]["properties"]["easystore_attr_how_did_you_find_us"],
            "Instagram",
        )
        self.assertEqual(summary["easystore_customer_attributes_found"], 1)
        self.assertEqual(
            summary["easystore_customer_field_coverage"][
                "attribute:How did you find us?"
            ],
            1,
        )


class CatalogueFieldTests(unittest.TestCase):
    def test_product_url_prefers_the_reported_url(self) -> None:
        self.assertEqual(
            products._product_url({"url": "https://shop.example/products/hobbit"}),
            "https://shop.example/products/hobbit",
        )

    def test_product_url_is_built_from_a_handle_and_the_store_domain(self) -> None:
        self.assertEqual(
            products._product_url({"handle": "hobbit"}, "cardboardcollective.easy.co"),
            "https://cardboardcollective.easy.co/products/hobbit",
        )
        self.assertIsNone(products._product_url({"handle": "hobbit"}))

    def test_product_type_falls_back_to_the_easystore_category(self) -> None:
        self.assertEqual(
            products._product_type({"product_type": "Trading cards"}),
            "Trading cards",
        )
        self.assertEqual(
            products._product_type({"categories": [{"name": "Trading cards"}]}),
            "Trading cards",
        )
        self.assertEqual(
            products._product_type({"category": {"title": "Board games"}}),
            "Board games",
        )
        self.assertIsNone(products._product_type({}))

    def test_observed_keys_collects_names_and_never_values(self) -> None:
        seen: set[str] = set()
        schema.observed_keys(seen, {"id": 1, "email": "buyer@example.com"})
        schema.observed_keys(seen, None)
        self.assertEqual(seen, {"id", "email"})

    def test_product_image_is_found_wherever_easystore_nests_it(self) -> None:
        self.assertEqual(
            products._product_image({"image": {"src": "https://img.example/a.png"}}),
            "https://img.example/a.png",
        )
        self.assertEqual(
            products._product_image({"images": [{"url": "https://img.example/b.png"}]}),
            "https://img.example/b.png",
        )
        self.assertIsNone(products._product_image({}))

    def test_catalogue_fields_are_written_only_when_resolved(self) -> None:
        product = {
            "id": 10,
            "title": "The Hobbit",
            "handle": "hobbit",
            "product_type": "Trading cards",
            "image": {"src": "https://img.example/a.png"},
        }
        variant = {"id": 20, "sku": "ABC-1", "price": "118.00"}

        plain = products.variant_properties(product, variant, "ABC-1")
        self.assertNotIn("hs_url", plain)

        mapped = products.variant_properties(
            product,
            variant,
            "ABC-1",
            {"url": "hs_url", "image": "hs_images", "product_type": "hs_product_type"},
            "cardboardcollective.easy.co",
        )
        self.assertEqual(
            mapped["hs_url"],
            "https://cardboardcollective.easy.co/products/hobbit",
        )
        self.assertEqual(mapped["hs_images"], "https://img.example/a.png")
        self.assertEqual(mapped["hs_product_type"], "Trading cards")


class ContactIndexTests(unittest.TestCase):
    def test_contacts_are_indexed_by_mobile_and_lifecycle_stage(self) -> None:
        contacts = [
            {
                "id": "1",
                "properties": {
                    "mobilephone": "9123 4567",
                    "phone": "+6591234567",
                    "lifecyclestage": "lead",
                },
            },
            {"id": "2", "properties": {"phone": "0000000"}},
        ]
        with mock.patch.object(
            orders, "iter_hubspot_objects", lambda *a, **k: iter(contacts)
        ):
            index = orders.hubspot_contact_index("token", "65")

        self.assertEqual(index.by_phone["+6591234567"], {"1"})
        self.assertEqual(index.lifecycle_by_id, {"1": "lead"})


class FieldProvisioningTests(unittest.TestCase):
    def _fake_api(
        self,
        schema_results: list[dict[str, object]] | None,
        *,
        forbidden: bool = False,
    ) -> tuple[object, list]:
        calls: list[tuple[str, str, object]] = []

        def fake_http_json(
            url,
            *,
            method="GET",
            headers=None,
            payload=None,
            allow_statuses=None,
            **kwargs,
        ):
            calls.append((method, url, payload))
            if forbidden:
                if allow_statuses and 403 in allow_statuses:
                    return None
                raise orders.SyncError(f"{method} {url} failed with HTTP 403")
            if url.endswith("/crm/v3/properties/order") and method == "GET":
                return {"results": schema_results}
            if "/properties/order/groups/" in url:
                return {"name": schema.PROPERTY_GROUP}
            return {}

        return fake_http_json, calls

    def _created(self, calls: list) -> list[str]:
        return [
            payload["name"]
            for method, _url, payload in calls
            if method == "POST" and isinstance(payload, dict) and "name" in payload
        ]

    def _resolve(self, fake_http_json, **overrides):
        arguments = {
            "http_json": fake_http_json,
            "access_token": "token",
            "object_type": "order",
            "fields": orders.ORDER_FIELDS,
            "error": orders.SyncError,
        }
        arguments.update(overrides)
        return schema.resolve_fields(**arguments)

    def test_unusable_native_properties_are_provisioned_as_easystore_fields(self) -> None:
        fake_http_json, calls = self._fake_api(
            [
                {"name": "hs_fulfillment_status", "type": "string"},
                {"name": "hs_total_price", "type": "number", "calculated": True},
                {"name": "hs_shipping_address_city", "type": "string"},
            ]
        )
        resolved = self._resolve(fake_http_json)

        self.assertEqual(resolved["fulfillment_status"], "hs_fulfillment_status")
        self.assertEqual(resolved["total_amount"], "easystore_total_amount")
        self.assertEqual(resolved["shipping_address_city"], "hs_shipping_address_city")
        # Native-only fields the portal lacks are skipped, not duplicated.
        self.assertNotIn("shipping_address_street", resolved)
        self.assertNotIn("tracking_number", resolved)
        created = self._created(calls)
        # Every commerce fact without a usable native property is provisioned,
        # in declaration order, and nothing else is.
        self.assertEqual(
            created,
            [
                field.fallback
                for field in orders.ORDER_FIELDS
                if field.fallback is not None
                and field.key not in {"fulfillment_status"}
            ],
        )
        self.assertIn("easystore_total_amount", created)
        self.assertNotIn("easystore_fulfillment_status", created)
        # Native-only fields never provision a custom property.
        for field in orders.ORDER_FIELDS:
            if field.fallback is None:
                with self.subTest(field=field.key):
                    self.assertNotIn(field.key + "_property", created)

    def test_existing_easystore_property_is_reused_without_recreating(self) -> None:
        fake_http_json, calls = self._fake_api(
            [{"name": "easystore_payment_status", "type": "string"}]
        )
        resolved = self._resolve(fake_http_json)

        self.assertEqual(resolved["payment_status"], "easystore_payment_status")
        self.assertNotIn("easystore_payment_status", self._created(calls))

    def test_conflicting_easystore_property_fails_closed(self) -> None:
        fake_http_json, _calls = self._fake_api(
            [{"name": "easystore_total_amount", "type": "enumeration"}]
        )
        with self.assertRaises(orders.SyncError):
            self._resolve(fake_http_json)

    def test_invalid_schema_response_fails_closed(self) -> None:
        fake_http_json, _calls = self._fake_api(None)
        with self.assertRaises(orders.SyncError):
            self._resolve(fake_http_json)

    def test_a_required_stage_fails_when_the_schema_is_forbidden(self) -> None:
        fake_http_json, _calls = self._fake_api([], forbidden=True)
        with self.assertRaises(orders.SyncError):
            self._resolve(fake_http_json)

    def test_the_report_carries_the_inventory_and_naming_hints(self) -> None:
        fake_http_json, _calls = self._fake_api(
            [
                {"name": "hs_fulfillment_status", "type": "string"},
                # The portal's discount property under a name the sync does not
                # know: this is what the hints exist to surface.
                {
                    "name": "hs_order_level_discount",
                    "type": "number",
                    "label": "Discount",
                },
            ]
        )
        report: dict[str, object] = {}
        resolved = self._resolve(fake_http_json, report=report)

        self.assertEqual(resolved["discount_amount"], "easystore_discount_amount")
        self.assertIn("hs_order_level_discount:number", report["inventory"])
        self.assertEqual(
            report["hints"]["discount_amount"],
            ["hs_order_level_discount:number"],
        )
        # A field that resolved natively needs no hint.
        self.assertNotIn("fulfillment_status", report["hints"])

    def test_an_optional_stage_skips_fields_when_the_schema_is_forbidden(self) -> None:
        fake_http_json, calls = self._fake_api([], forbidden=True)
        self.assertEqual(self._resolve(fake_http_json, optional=True), {})
        self.assertEqual(self._created(calls), [])


class OrderPropertyTests(unittest.TestCase):
    def test_order_properties_include_shipping_and_tracking(self) -> None:
        mapped = orders.order_properties(
            {
                "name": "#1001",
                "currency": "sgd",
                "fulfillment_status": "fulfilled",
                "shipping_address": {
                    "address1": "1 Example Road",
                    "address2": "#02-03",
                    "city": "Singapore",
                    "zip": "123456",
                },
                "fulfillments": [
                    {
                        "tracking_number": "TRACK1",
                        "tracking_url": "https://tracking.example/TRACK1",
                    }
                ],
            },
            external_id="1001",
            store_domain="https://cardboardcollective.easy.co/",
        )
        self.assertEqual(mapped["easystore_order_id"], "1001")
        self.assertEqual(mapped["hs_currency_code"], "SGD")
        self.assertEqual(mapped["hs_source_store"], "cardboardcollective.easy.co")
        self.assertEqual(
            mapped["hs_shipping_address_street"],
            "1 Example Road\n#02-03",
        )
        self.assertEqual(mapped["hs_shipping_tracking_number"], "TRACK1")


if __name__ == "__main__":
    unittest.main()


class EasyStorePaginationGuardTests(unittest.TestCase):
    """Every EasyStore list read must be unable to loop on a repeated page.

    checkouts.json is known to ignore `page` and serve page 2 identical to
    page 1. A loop that only stops on a short page would spend the whole job
    timeout re-reading page 1 and rewriting those records in HubSpot on every
    lap, so the same guard covers every list endpoint.
    """

    @staticmethod
    def _page(count, start=0):
        return [{"id": str(index)} for index in range(start, start + count)]

    def test_pages_are_yielded_until_a_short_page(self) -> None:
        pages = {1: self._page(50), 2: self._page(50, start=50), 3: self._page(7, start=100)}
        seen = list(
            schema.iter_easystore_pages(
                lambda page: pages.get(page, []),
                page_size=50,
                what="orders.json",
                error=orders.SyncError,
            )
        )
        self.assertEqual(len(seen), 107)

    def test_an_empty_first_page_ends_the_read(self) -> None:
        calls = []

        def fetch(page):
            calls.append(page)
            return []

        self.assertEqual(
            list(
                schema.iter_easystore_pages(
                    fetch, page_size=50, what="products.json", error=orders.SyncError
                )
            ),
            [],
        )
        self.assertEqual(calls, [1])

    def test_a_repeated_page_raises_instead_of_looping(self) -> None:
        full = self._page(50)
        calls = []

        def fetch(page):
            calls.append(page)
            return full

        with self.assertRaisesRegex(orders.SyncError, "page parameter does nothing"):
            list(
                schema.iter_easystore_pages(
                    fetch, page_size=50, what="orders.json", error=orders.SyncError
                )
            )
        # Page 1 served, page 2 recognised as the same records, then it stopped.
        self.assertEqual(calls, [1, 2])

    def test_the_error_names_the_endpoint(self) -> None:
        full = self._page(50)
        with self.assertRaisesRegex(orders.SyncError, "products.json"):
            list(
                schema.iter_easystore_pages(
                    lambda page: full,
                    page_size=50,
                    what="products.json",
                    error=orders.SyncError,
                )
            )

    def test_records_without_ids_still_terminate(self) -> None:
        # A collection whose records carry no id is compared by position, so an
        # endpoint replaying it is still caught rather than looping forever.
        full = [{"cart_token": f"c{index}"} for index in range(50)]
        with self.assertRaises(orders.SyncError):
            list(
                schema.iter_easystore_pages(
                    lambda page: full,
                    page_size=50,
                    what="checkouts.json",
                    error=orders.SyncError,
                )
            )

    def test_every_easystore_list_read_uses_the_guard(self) -> None:
        # A new list endpoint added without the guard is the bug this prevents.
        import easystore_hubspot_carts
        import easystore_hubspot_commerce
        import easystore_hubspot_customer_sync
        import easystore_hubspot_products
        import easystore_hubspot_sync

        for module in (
            orders,
            easystore_hubspot_products,
            easystore_hubspot_sync,
            easystore_hubspot_customer_sync,
            easystore_hubspot_commerce,
            easystore_hubspot_carts,
        ):
            source = Path(module.__file__).read_text()
            for line_number, line in enumerate(source.splitlines(), 1):
                if "api/3.0/" in line and "?page=" in line or "\"page\": page" in line:
                    self.assertIn(
                        "iter_easystore_pages",
                        source,
                        f"{module.__name__}:{line_number} pages an EasyStore "
                        "collection without the repeated-page guard",
                    )
