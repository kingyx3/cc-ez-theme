from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_customer_sync as production
import easystore_hubspot_sync as base


class ClickIdPropertyContractTests(unittest.TestCase):
    def test_click_id_has_one_canonical_hubspot_property(self) -> None:
        self.assertEqual(
            base.attribute_property_name(production.CLICK_ID_ATTRIBUTE_LABEL),
            production.CLICK_ID_HUBSPOT_PROPERTY,
        )
        self.assertEqual(
            production.CLICK_ID_FIELD_KEY,
            "attribute:Click ID",
        )

    def test_customer_attribute_value_maps_to_click_id_property(self) -> None:
        click_id = "01234567-89ab-cdef-0123-456789abcdef"
        properties = base.customer_properties(
            {
                "custom_fields": {
                    production.CLICK_ID_ATTRIBUTE_LABEL: click_id,
                }
            },
            "+6591234567",
            {
                production.CLICK_ID_FIELD_KEY: production.CLICK_ID_HUBSPOT_PROPERTY,
            },
        )

        self.assertEqual(
            properties[production.CLICK_ID_HUBSPOT_PROPERTY],
            click_id,
        )


class ClickIdSchemaProvisioningTests(unittest.TestCase):
    def test_click_id_property_is_provisioned_before_any_customer_has_a_value(self) -> None:
        resolver = mock.Mock(
            side_effect=[
                {"customer_id": "easystore_customer_id"},
                {
                    production.CLICK_ID_FIELD_KEY: production.CLICK_ID_HUBSPOT_PROPERTY,
                },
            ]
        )
        with mock.patch.object(
            production,
            "_BASE_RESOLVE_CONTACT_FIELDS",
            resolver,
        ):
            resolved = production.resolve_contact_fields(
                "hub-token",
                attribute_labels=(),
                report={},
            )

        self.assertEqual(
            resolved[production.CLICK_ID_FIELD_KEY],
            production.CLICK_ID_HUBSPOT_PROPERTY,
        )
        self.assertEqual(resolver.call_count, 2)
        self.assertEqual(resolver.call_args_list[0].args[1], ())
        self.assertEqual(
            resolver.call_args_list[1].args[1],
            (production.CLICK_ID_ATTRIBUTE_LABEL,),
        )
        self.assertIsNone(resolver.call_args_list[1].args[2])

    def test_canonical_click_id_mapping_wins_over_a_legacy_discovery(self) -> None:
        resolver = mock.Mock(
            side_effect=[
                {
                    production.CLICK_ID_FIELD_KEY: "easystore_attr_clickid",
                },
                {
                    production.CLICK_ID_FIELD_KEY: production.CLICK_ID_HUBSPOT_PROPERTY,
                },
            ]
        )
        with mock.patch.object(
            production,
            "_BASE_RESOLVE_CONTACT_FIELDS",
            resolver,
        ):
            resolved = production.resolve_contact_fields("hub-token")

        self.assertEqual(
            resolved[production.CLICK_ID_FIELD_KEY],
            production.CLICK_ID_HUBSPOT_PROPERTY,
        )

    def test_missing_schema_scope_keeps_any_mapping_the_main_pass_resolved(self) -> None:
        resolver = mock.Mock(
            side_effect=[
                {
                    production.CLICK_ID_FIELD_KEY: production.CLICK_ID_HUBSPOT_PROPERTY,
                },
                {},
            ]
        )
        with mock.patch.object(
            production,
            "_BASE_RESOLVE_CONTACT_FIELDS",
            resolver,
        ):
            resolved = production.resolve_contact_fields("hub-token")

        self.assertEqual(
            resolved[production.CLICK_ID_FIELD_KEY],
            production.CLICK_ID_HUBSPOT_PROPERTY,
        )


class ClickIdSyncSummaryTests(unittest.TestCase):
    def test_summary_reports_property_readiness_and_tagged_contacts(self) -> None:
        fake_summary = {
            "hubspot_contact_field_properties": {
                production.CLICK_ID_FIELD_KEY: production.CLICK_ID_HUBSPOT_PROPERTY,
            },
            "easystore_customer_field_coverage": {
                production.CLICK_ID_FIELD_KEY: 3,
            },
            "ambiguous_hubspot_mobile_numbers": 0,
        }
        with (
            mock.patch.object(
                production,
                "native_date_of_birth_storage_type",
                return_value=None,
            ),
            mock.patch.object(production, "_install_refinements"),
            mock.patch.object(base, "sync", return_value=fake_summary.copy()),
        ):
            summary = production.sync(
                store_domain="cardboard.sg",
                easystore_access_token="easy-token",
                hubspot_access_token="hub-token",
                fallback_dial_code="65",
            )

        self.assertEqual(
            summary["easystore_click_id_hubspot_property"],
            production.CLICK_ID_HUBSPOT_PROPERTY,
        )
        self.assertTrue(summary["easystore_click_id_property_ready"])
        self.assertEqual(summary["easystore_click_id_contacts"], 3)
        self.assertEqual(
            summary["easystore_click_id_attribute_label"],
            production.CLICK_ID_ATTRIBUTE_LABEL,
        )

    def test_summary_is_not_ready_when_schema_access_cannot_resolve_the_property(self) -> None:
        fake_summary = {
            "hubspot_contact_field_properties": {},
            "easystore_customer_field_coverage": {},
            "ambiguous_hubspot_mobile_numbers": 0,
        }
        with (
            mock.patch.object(
                production,
                "native_date_of_birth_storage_type",
                return_value=None,
            ),
            mock.patch.object(production, "_install_refinements"),
            mock.patch.object(base, "sync", return_value=fake_summary.copy()),
        ):
            summary = production.sync(
                store_domain="cardboard.sg",
                easystore_access_token="easy-token",
                hubspot_access_token="hub-token",
                fallback_dial_code="65",
            )

        self.assertFalse(summary["easystore_click_id_property_ready"])
        self.assertIsNone(summary["easystore_click_id_hubspot_property"])
        self.assertEqual(summary["easystore_click_id_contacts"], 0)


if __name__ == "__main__":
    unittest.main()
