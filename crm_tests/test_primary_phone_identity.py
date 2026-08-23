from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_customer_sync as customer_sync
import easystore_hubspot_preflight as preflight
import easystore_hubspot_sync as base


class PrimaryPhonePreflightTests(unittest.TestCase):
    def test_secondary_mobilephone_does_not_create_a_false_duplicate(self) -> None:
        easystore = [
            {"id": 1, "phone": "9123 4567", "country_code": "SG"},
        ]
        hubspot = [
            {"id": "100", "properties": {"phone": "+6591234567"}},
            {"id": "200", "properties": {"mobilephone": "+6591234567"}},
        ]

        with mock.patch.object(preflight, "check_api_access", lambda **_: None), mock.patch.object(
            preflight,
            "iter_easystore_customers",
            lambda *args, **kwargs: iter(easystore),
        ), mock.patch.object(
            preflight,
            "iter_hubspot_contacts",
            lambda *args, **kwargs: iter(hubspot),
        ):
            summary = preflight.check_identity(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertEqual(summary["ambiguous_hubspot_mobile_numbers"], 0)
        self.assertEqual(summary["hubspot_contact_identity_property"], "phone")

    def test_duplicate_primary_phone_still_fails_closed(self) -> None:
        easystore = [
            {"id": 1, "phone": "9123 4567", "country_code": "SG"},
        ]
        hubspot = [
            {"id": "100", "properties": {"phone": "+6591234567"}},
            {"id": "200", "properties": {"phone": "+65 9123 4567"}},
        ]

        with mock.patch.object(preflight, "check_api_access", lambda **_: None), mock.patch.object(
            preflight,
            "iter_easystore_customers",
            lambda *args, **kwargs: iter(easystore),
        ), mock.patch.object(
            preflight,
            "iter_hubspot_contacts",
            lambda *args, **kwargs: iter(hubspot),
        ):
            with self.assertRaisesRegex(base.SyncError, "primary phone property"):
                preflight.check_identity(
                    store_domain="shop.example",
                    easystore_access_token="es",
                    hubspot_access_token="hs",
                    fallback_dial_code="65",
                )


class PrimaryPhoneCustomerSyncTests(unittest.TestCase):
    def test_production_contact_reader_removes_mobilephone_from_identity_input(self) -> None:
        contacts = [
            {
                "id": "100",
                "properties": {
                    "phone": "+6591234567",
                    "mobilephone": "+6599999999",
                    "email": "shopper@example.com",
                },
            }
        ]

        with mock.patch.object(
            customer_sync,
            "_BASE_ITER_HUBSPOT_CONTACTS",
            lambda _token: iter(contacts),
        ):
            result = list(customer_sync.iter_hubspot_contacts_by_primary_phone("hs"))

        properties = result[0]["properties"]
        self.assertEqual(properties["phone"], "+6591234567")
        self.assertEqual(properties["email"], "shopper@example.com")
        self.assertNotIn("mobilephone", properties)

        # The adapter must not mutate the HubSpot response object in place.
        self.assertEqual(contacts[0]["properties"]["mobilephone"], "+6599999999")

    def test_mobilephone_is_still_written_as_a_convenience_mirror(self) -> None:
        properties = base.customer_properties(
            {"id": 1, "first_name": "Ada"},
            "+6591234567",
        )
        self.assertEqual(properties["phone"], "+6591234567")
        self.assertEqual(properties["mobilephone"], "+6591234567")


if __name__ == "__main__":
    unittest.main()
