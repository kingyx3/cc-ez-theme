from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_customer_sync as production
import easystore_hubspot_sync as base


class RetiredClickIdAttributeTests(unittest.TestCase):
    def test_click_id_variants_are_filtered_from_customer_attributes(self) -> None:
        customer = {
            "custom_fields": {
                "Click ID": "01234567-89ab-cdef-0123-456789abcdef",
                "Favourite game": "Pokemon",
            }
        }
        attributes = production.customer_attributes_without_click_id(customer)
        self.assertNotIn("Click ID", attributes)
        self.assertEqual(attributes["Favourite game"], "Pokemon")

    def test_other_machine_looking_values_are_not_removed_by_value(self) -> None:
        customer = {
            "custom_fields": {
                "Referral token": "01234567-89ab-cdef-0123-456789abcdef",
            }
        }
        self.assertEqual(
            production.customer_attributes_without_click_id(customer),
            {"Referral token": "01234567-89ab-cdef-0123-456789abcdef"},
        )

    def test_production_refinement_installs_the_filter(self) -> None:
        original = base.customer_attributes
        try:
            production._install_refinements(None)
            self.assertIs(base.customer_attributes, production.customer_attributes_without_click_id)
        finally:
            base.customer_attributes = original

    def test_contact_field_resolver_no_longer_provisions_click_id_separately(self) -> None:
        resolver = mock.Mock(return_value={"customer_id": "easystore_customer_id"})
        with mock.patch.object(production, "_BASE_RESOLVE_CONTACT_FIELDS", resolver):
            resolved = production.resolve_contact_fields(
                "hub-token",
                attribute_labels=("Favourite game",),
                report={},
            )
        self.assertEqual(resolved, {"customer_id": "easystore_customer_id"})
        resolver.assert_called_once_with("hub-token", ("Favourite game",), {})

    def test_sync_summary_names_the_retired_attribute_without_hubspot_property(self) -> None:
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

        self.assertIn("click id", summary["retired_customer_attributes_not_synced"])
        self.assertNotIn("easystore_click_id_hubspot_property", summary)
        self.assertNotIn("easystore_click_id_property_ready", summary)


if __name__ == "__main__":
    unittest.main()
