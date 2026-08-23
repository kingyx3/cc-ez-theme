from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_products as products
import easystore_hubspot_schema as schema


class SemanticNativeFieldTests(unittest.TestCase):
    def test_unique_hubspot_defined_same_type_property_is_preferred(self) -> None:
        field = schema.FieldSpec(
            key="cancelled_at",
            fallback="easystore_order_cancelled_at",
            kind="datetime",
        )
        portal = {
            "hs_cancelled_date": {
                "name": "hs_cancelled_date",
                "label": "Order cancelled at",
                "type": "datetime",
                "hubspotDefined": True,
            }
        }
        self.assertEqual(
            schema.select_semantic_native(field, portal),
            "hs_cancelled_date",
        )

    def test_ambiguous_native_candidates_are_not_guessed(self) -> None:
        field = schema.FieldSpec(
            key="paid_at",
            fallback="easystore_order_paid_at",
            kind="datetime",
        )
        portal = {
            "hs_payment_date": {
                "label": "Payment date",
                "type": "datetime",
                "hubspotDefined": True,
            },
            "hs_payment_updated_date": {
                "label": "Payment updated date",
                "type": "datetime",
                "hubspotDefined": True,
            },
        }
        self.assertIsNone(schema.select_semantic_native(field, portal))

    def test_user_custom_property_is_not_mistaken_for_native(self) -> None:
        field = schema.FieldSpec(
            key="note",
            fallback="easystore_order_note",
        )
        portal = {
            "merchant_order_note": {
                "label": "Order note",
                "type": "string",
                "hubspotDefined": False,
            }
        }
        self.assertIsNone(schema.select_semantic_native(field, portal))

    def test_enumeration_is_not_force_fed_free_form_text(self) -> None:
        field = schema.FieldSpec(
            key="order_status",
            fallback="easystore_order_status",
        )
        portal = {
            "hs_order_status": {
                "label": "Order status",
                "type": "enumeration",
                "hubspotDefined": True,
            }
        }
        self.assertIsNone(schema.select_semantic_native(field, portal))

    def test_resolver_uses_semantic_native_before_provisioning_fallback(self) -> None:
        field = schema.FieldSpec(
            key="cancelled_at",
            fallback="easystore_order_cancelled_at",
            label="EasyStore Order Cancelled",
            description="Cancellation time",
            kind="datetime",
        )
        calls: list[tuple[str, str]] = []

        def http_json(url: str, *, method: str = "GET", **_: object) -> object:
            calls.append((method, url))
            return {
                "results": [
                    {
                        "name": "hs_cancelled_date",
                        "label": "Order cancelled at",
                        "type": "datetime",
                        "hubspotDefined": True,
                    }
                ]
            }

        report: dict[str, object] = {}
        resolved = schema.resolve_fields(
            http_json=http_json,
            access_token="token",
            object_type="order",
            fields=(field,),
            error=RuntimeError,
            report=report,
        )
        self.assertEqual(resolved, {"cancelled_at": "hs_cancelled_date"})
        self.assertEqual(report["semantic_native"], {"cancelled_at": "hs_cancelled_date"})
        self.assertEqual([method for method, _ in calls], ["GET"])


class ProductPublicationTests(unittest.TestCase):
    def test_published_at_controls_publication_state(self) -> None:
        self.assertTrue(
            products.easystore_product_published(
                {"published_at": "2026-08-23T01:02:03+08:00"}
            )
        )
        self.assertFalse(products.easystore_product_published({"published_at": None}))
        self.assertFalse(products.easystore_product_published({"published_at": ""}))
        self.assertIsNone(products.easystore_product_published({"title": "No signal"}))

    def test_product_reader_requests_both_publication_states(self) -> None:
        calls: list[str] = []

        def http_json(url: str, **_: object) -> object:
            calls.append(url)
            query = parse_qs(urlparse(url).query)
            visibility = query.get("visibility", [None])[0]
            if visibility == "published":
                return {"products": [{"id": 1, "title": "Published"}]}
            if visibility == "unpublished":
                return {"products": [{"id": 2, "title": "Unpublished"}]}
            self.fail(f"unexpected visibility filter: {visibility!r}")

        with mock.patch.object(products, "_http_json", side_effect=http_json):
            found = list(products.iter_easystore_products("shop.easy.co", "token"))

        self.assertEqual([item["id"] for item in found], [1, 2])
        self.assertEqual(
            [products.easystore_product_published(item) for item in found],
            [True, False],
        )
        self.assertEqual(
            [parse_qs(urlparse(url).query)["visibility"][0] for url in calls],
            ["published", "unpublished"],
        )

    def test_native_product_status_uses_portal_option_values(self) -> None:
        portal = {
            "hs_product_status": {
                "name": "hs_product_status",
                "label": "Product status",
                "type": "enumeration",
                "hubspotDefined": True,
                "options": [
                    {"label": "Active", "value": "ACTIVE_INTERNAL"},
                    {"label": "Inactive", "value": "INACTIVE_INTERNAL"},
                ],
            }
        }
        with mock.patch.object(products, "property_schema", return_value=portal):
            mapping = products.resolve_product_status_mapping("token")
        self.assertEqual(
            mapping,
            products.ProductStatusMapping(
                "hs_product_status",
                "ACTIVE_INTERNAL",
                "INACTIVE_INTERNAL",
            ),
        )

    def test_unpublished_product_variant_is_written_inactive(self) -> None:
        mapping = products.ProductStatusMapping(
            "hs_product_status",
            "ACTIVE_INTERNAL",
            "INACTIVE_INTERNAL",
        )
        props = products.variant_properties(
            {"id": 10, "title": "Card", "published_at": None},
            {"id": 20, "sku": "SKU-1", "price": "5"},
            "SKU-1",
            status_mapping=mapping,
        )
        self.assertEqual(props["hs_product_status"], "INACTIVE_INTERNAL")

    def test_missing_publication_signal_does_not_invent_status(self) -> None:
        mapping = products.ProductStatusMapping(
            "hs_product_status",
            "ACTIVE_INTERNAL",
            "INACTIVE_INTERNAL",
        )
        props = products.variant_properties(
            {"id": 10, "title": "Card"},
            {"id": 20, "sku": "SKU-1"},
            "SKU-1",
            status_mapping=mapping,
        )
        self.assertNotIn("hs_product_status", props)


if __name__ == "__main__":
    unittest.main()
