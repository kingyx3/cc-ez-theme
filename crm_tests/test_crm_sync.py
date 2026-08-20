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


class OrderCommerceFieldTests(unittest.TestCase):
    def _schema(self, **properties: dict[str, object]) -> dict[str, dict[str, object]]:
        return dict(properties)

    def test_writable_native_property_is_preferred(self) -> None:
        field = orders.OrderField(
            key="total_amount",
            sources=("total_price",),
            native=("hs_total_price",),
            fallback="easystore_total_amount",
            label="EasyStore Order Total",
            description="",
            kind="number",
        )
        schema = self._schema(hs_total_price={"name": "hs_total_price", "type": "number"})
        self.assertEqual(orders.select_order_property(field, schema), "hs_total_price")

    def test_calculated_read_only_and_enumeration_natives_are_skipped(self) -> None:
        field = orders.OrderField(
            key="payment_status",
            sources=("payment_status",),
            native=("hs_payment_status",),
            fallback="easystore_payment_status",
            label="EasyStore Payment Status",
            description="",
        )
        for prop in (
            {"name": "hs_payment_status", "type": "string", "calculated": True},
            {
                "name": "hs_payment_status",
                "type": "string",
                "modificationMetadata": {"readOnlyValue": True},
            },
            {"name": "hs_payment_status", "type": "enumeration"},
        ):
            with self.subTest(prop=prop):
                self.assertIsNone(
                    orders.select_order_property(
                        field,
                        self._schema(hs_payment_status=prop),
                    )
                )

    def test_missing_native_property_falls_back_to_easystore_property(self) -> None:
        for field in orders.ORDER_FIELDS:
            with self.subTest(field=field.key):
                self.assertIsNone(orders.select_order_property(field, {}))

    def test_money_values_are_normalized_for_hubspot_numbers(self) -> None:
        self.assertEqual(orders._money("SGD 1,234.50"), "1234.50")
        self.assertEqual(orders._money(0), "0")
        self.assertEqual(orders._money("-5.00", absolute=True), "5.00")
        self.assertIsNone(orders._money("free"))
        self.assertIsNone(orders._money(None))

    def test_order_timestamps_become_epoch_milliseconds(self) -> None:
        # The same instant expressed store-local, as UTC, and offset-free.
        for value in (
            "2026-05-01T10:20:30+08:00",
            "2026-05-01T02:20:30Z",
            "2026-05-01 02:20:30",
        ):
            with self.subTest(value=value):
                self.assertEqual(orders._timestamp(value), "1777602030000")

    def test_epoch_order_timestamps_are_scaled_to_milliseconds(self) -> None:
        self.assertEqual(orders._timestamp("1777602030"), "1777602030000")
        self.assertEqual(orders._timestamp("1777602030000"), "1777602030000")

    def test_unparseable_order_timestamp_is_omitted(self) -> None:
        self.assertIsNone(orders._timestamp("last Tuesday"))
        self.assertIsNone(orders._timestamp(""))
        self.assertIsNone(orders._timestamp(None))

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

    def test_commerce_fields_are_mapped_onto_resolved_properties(self) -> None:
        order = {
            "name": "#1002",
            "currency": "SGD",
            "created_at": "2026-05-01T10:20:30+08:00",
            "payment_status_label": "Paid",
            "fulfillment_status": "fulfilled",
            "total_price": "88.00",
            "total_discount": "-12.00",
            "discount_codes": [{"code": "WELCOME10"}],
        }
        mapped = orders.order_properties(
            order,
            external_id="1002",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_order_date"], "1777602030000")
        self.assertEqual(mapped["hs_payment_status"], "Paid")
        self.assertEqual(mapped["hs_fulfillment_status"], "fulfilled")
        self.assertEqual(mapped["hs_total_price"], "88.00")
        self.assertEqual(mapped["hs_order_discount_amount"], "12.00")
        self.assertEqual(mapped["easystore_discount_codes"], "WELCOME10")

        custom = orders.order_properties(
            order,
            external_id="1002",
            store_domain="cardboardcollective.easy.co",
            field_properties={
                field.key: field.fallback for field in orders.ORDER_FIELDS
            },
        )
        self.assertEqual(custom["easystore_order_created_at"], "1777602030000")
        self.assertEqual(custom["easystore_payment_status"], "Paid")
        self.assertEqual(custom["easystore_fulfillment_status"], "fulfilled")
        self.assertEqual(custom["easystore_total_amount"], "88.00")
        self.assertEqual(custom["easystore_discount_amount"], "12.00")
        self.assertNotIn("hs_total_price", custom)

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
            {"id": 1, "phone": "9123 4567", "country_code": "SG", "first_name": "Ada"},
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
        written: dict[str, list[dict]] = {"create": [], "update": []}

        def fake_batch_write(access_token, action, inputs):
            written[action].extend(inputs)

        with mock.patch.object(
            customers, "iter_easystore_customers", lambda *a, **k: iter(easystore)
        ), mock.patch.object(
            customers, "iter_hubspot_contacts", lambda *a, **k: iter(hubspot)
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

        updates = {item["id"]: item["properties"] for item in written["update"]}
        # Already a lead: nothing to move.
        self.assertNotIn("lifecyclestage", updates["100"])
        # Already a customer: an account must not demote a buyer.
        self.assertNotIn("lifecyclestage", updates["200"])
        self.assertEqual(summary["lifecycle_stage_leads_assigned"], 1)


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


class OrderPropertyProvisioningTests(unittest.TestCase):
    def _fake_api(self, schema_results: list[dict[str, object]]) -> tuple[object, list]:
        calls: list[tuple[str, str, object]] = []

        def fake_http_json(url, *, method="GET", headers=None, payload=None, **kwargs):
            calls.append((method, url, payload))
            if url.endswith("/crm/v3/properties/order") and method == "GET":
                return {"results": schema_results}
            if "/properties/order/groups/" in url:
                return {"name": orders.PROPERTY_GROUP}
            return {}

        return fake_http_json, calls

    def test_unusable_native_properties_are_provisioned_as_easystore_fields(self) -> None:
        fake_http_json, calls = self._fake_api(
            [
                {"name": "hs_fulfillment_status", "type": "string"},
                {"name": "hs_total_price", "type": "number", "calculated": True},
            ]
        )
        with mock.patch.object(orders, "_http_json", fake_http_json):
            resolved = orders.ensure_order_field_properties("token")

        self.assertEqual(resolved["fulfillment_status"], "hs_fulfillment_status")
        self.assertEqual(resolved["total_amount"], "easystore_total_amount")
        self.assertEqual(
            [
                payload["name"]
                for method, _url, payload in calls
                if method == "POST" and isinstance(payload, dict) and "name" in payload
            ],
            [
                "easystore_order_created_at",
                "easystore_payment_status",
                "easystore_total_amount",
                "easystore_discount_amount",
                "easystore_discount_codes",
            ],
        )

    def test_existing_easystore_property_is_reused_without_recreating(self) -> None:
        fake_http_json, calls = self._fake_api(
            [{"name": "easystore_payment_status", "type": "string"}]
        )
        with mock.patch.object(orders, "_http_json", fake_http_json):
            resolved = orders.ensure_order_field_properties("token")

        self.assertEqual(resolved["payment_status"], "easystore_payment_status")
        self.assertNotIn(
            "easystore_payment_status",
            [
                payload["name"]
                for method, _url, payload in calls
                if method == "POST" and isinstance(payload, dict) and "name" in payload
            ],
        )

    def test_conflicting_easystore_property_fails_closed(self) -> None:
        fake_http_json, _calls = self._fake_api(
            [{"name": "easystore_total_amount", "type": "enumeration"}]
        )
        with mock.patch.object(orders, "_http_json", fake_http_json):
            with self.assertRaises(orders.SyncError):
                orders.ensure_order_field_properties("token")

    def test_invalid_schema_response_fails_closed(self) -> None:
        with mock.patch.object(orders, "_http_json", lambda *a, **k: {"results": None}):
            with self.assertRaises(orders.SyncError):
                orders.order_property_schema("token")


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
