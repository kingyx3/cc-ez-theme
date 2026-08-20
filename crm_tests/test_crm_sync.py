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
            customers, "_http_json", lambda *a, **k: contact_schema
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
                "customer_id": 3,
                "customer_since": 1,
                "orders_count": 1,
                "tags": 1,
                "total_spent": 1,
            },
        )

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
            {"id": 7, "order_count": 2, "total_spend": "SGD 1,000.00"}
        )
        self.assertEqual(values["customer_id"], "7")
        self.assertEqual(values["orders_count"], "2")
        self.assertEqual(values["total_spent"], "1000.00")


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
        self.assertEqual(
            self._created(calls),
            [
                "easystore_order_created_at",
                "easystore_payment_status",
                "easystore_total_amount",
                "easystore_subtotal_amount",
                "easystore_tax_amount",
                "easystore_shipping_amount",
                "easystore_discount_amount",
                "easystore_discount_codes",
                "easystore_order_note",
            ],
        )

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
