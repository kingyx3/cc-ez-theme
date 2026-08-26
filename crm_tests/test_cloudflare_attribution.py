"""Tests for Contact acquisition and native ad IDs from Cloudflare touch history."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cloudflare_hubspot_attribution as attribution


DAY = attribution.MILLISECONDS_PER_DAY


class AcquisitionTouchTests(unittest.TestCase):
    def test_latest_click_before_signup_wins_even_if_binding_happens_after_signup(self) -> None:
        signup_at = 100 * DAY
        touches = [
            {"source": "facebook", "clicked_at": 90 * DAY, "bound_at": 101 * DAY},
            {"source": "whatsapp", "clicked_at": 99 * DAY, "bound_at": 102 * DAY},
            {"source": "instagram", "clicked_at": 101 * DAY, "bound_at": 101 * DAY},
        ]
        selected = attribution.latest_touch_before_signup(
            touches,
            signup_at=signup_at,
            window_days=30,
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected["source"], "whatsapp")

    def test_click_outside_window_is_not_acquisition(self) -> None:
        signup_at = 100 * DAY
        self.assertIsNone(
            attribution.latest_touch_before_signup(
                [{"source": "facebook", "clicked_at": 69 * DAY, "bound_at": 70 * DAY}],
                signup_at=signup_at,
                window_days=30,
            )
        )

    def test_hubspot_acquisition_values_contain_no_internal_click_id(self) -> None:
        values = attribution.acquisition_values(
            {
                "source": "facebook",
                "medium": "social",
                "campaign": "rf",
                "content": "post-a",
                "path": "/fb",
                "country": "SG",
                "clicked_at": 99 * DAY,
                "click_id": "internal-only",
            },
            window_days=30,
        )
        self.assertEqual(values["source"], "facebook")
        self.assertEqual(values["content"], "post-a")
        self.assertEqual(values["status"], "attributed")
        self.assertNotIn("click_id", values)
        self.assertFalse(any(field.key == "click_id" for field in attribution.FIELDS))

    def test_no_touch_is_a_retryable_status(self) -> None:
        values = attribution.acquisition_values(None, window_days=30)
        self.assertEqual(values["status"], "no_recent_tracked_touch")
        self.assertEqual(values["model"], "last_tracked_touch_before_signup")
        self.assertNotIn("source", values)


class NativeAdClickTests(unittest.TestCase):
    FIELD_PROPERTIES = {
        "google_click_id": "hs_google_click_id",
        "facebook_click_id": "hs_facebook_click_id",
        "tiktok_click_id": "hs_tiktok_click_id",
        "linkedin_click_id": "hs_linkedin_click_id",
        "google_click_at": "cc_google_click_at",
        "facebook_click_at": "cc_facebook_click_at",
        "tiktok_click_at": "cc_tiktok_click_at",
        "linkedin_click_at": "cc_linkedin_click_at",
    }

    def test_field_specs_target_hubspots_native_conversion_properties(self) -> None:
        mapping = {field.key: field.native for field in attribution.AD_CLICK_FIELDS}
        self.assertEqual(mapping["google_click_id"], ("hs_google_click_id",))
        self.assertEqual(mapping["facebook_click_id"], ("hs_facebook_click_id",))
        self.assertEqual(mapping["tiktok_click_id"], ("hs_tiktok_click_id",))
        self.assertEqual(mapping["linkedin_click_id"], ("hs_linkedin_click_id",))
        self.assertTrue(all(field.fallback is None for field in attribution.AD_CLICK_FIELDS))

    def test_latest_vendor_click_per_parameter_wins(self) -> None:
        rows = [
            {
                "parameter": "gclid",
                "identifier": "older",
                "clicked_at": 100,
                "bound_at": 110,
            },
            {
                "parameter": "gclid",
                "identifier": "newer",
                "clicked_at": 200,
                "bound_at": 210,
            },
            {
                "parameter": "gbraid",
                "identifier": "preserved-in-d1-only",
                "clicked_at": 300,
                "bound_at": 310,
            },
        ]
        latest = attribution.latest_ad_clicks(rows)
        self.assertEqual(latest["gclid"]["identifier"], "newer")
        self.assertNotIn("gbraid", latest)

    def test_empty_native_field_is_populated_with_companion_timestamp(self) -> None:
        changes, updated, preserved = attribution.ad_click_property_changes(
            [
                {
                    "parameter": "gclid",
                    "identifier": "CaseSensitive-GCLID",
                    "clicked_at": 200,
                    "bound_at": 210,
                }
            ],
            existing={},
            field_properties=self.FIELD_PROPERTIES,
        )
        self.assertEqual(changes["hs_google_click_id"], "CaseSensitive-GCLID")
        self.assertEqual(changes["cc_google_click_at"], "200")
        self.assertEqual(updated, ["gclid"])
        self.assertEqual(preserved, [])

    def test_unknown_existing_native_value_is_not_overwritten(self) -> None:
        changes, updated, preserved = attribution.ad_click_property_changes(
            [
                {
                    "parameter": "fbclid",
                    "identifier": "from-d1",
                    "clicked_at": 200,
                    "bound_at": 210,
                }
            ],
            existing={"hs_facebook_click_id": "from-hubspot"},
            field_properties=self.FIELD_PROPERTIES,
        )
        self.assertEqual(changes, {})
        self.assertEqual(updated, [])
        self.assertEqual(preserved, ["fbclid"])

    def test_newer_d1_click_overwrites_value_written_by_this_integration(self) -> None:
        changes, updated, preserved = attribution.ad_click_property_changes(
            [
                {
                    "parameter": "ttclid",
                    "identifier": "new-tiktok",
                    "clicked_at": 1_800_000_000_000,
                    "bound_at": 1_800_000_000_010,
                }
            ],
            existing={
                "hs_tiktok_click_id": "old-tiktok",
                "cc_tiktok_click_at": "1700000000000",
            },
            field_properties=self.FIELD_PROPERTIES,
        )
        self.assertEqual(changes["hs_tiktok_click_id"], "new-tiktok")
        self.assertEqual(changes["cc_tiktok_click_at"], "1800000000000")
        self.assertEqual(updated, ["ttclid"])
        self.assertEqual(preserved, [])


class D1TouchReadTests(unittest.TestCase):
    def test_query_joins_customer_history_to_source_clicks_without_signup_bound_cutoff(self) -> None:
        calls = []

        def fake_http(url, *, payload=None, **kwargs):
            calls.append((url, payload))
            return {
                "success": True,
                "result": [
                    {
                        "results": [
                            {
                                "customer_id": "7",
                                "bound_at": 101 * DAY,
                                "source": "facebook",
                                "medium": "social",
                                "campaign": "rf",
                                "content": "post-a",
                                "path": "/fb",
                                "country": "SG",
                                "clicked_at": 99 * DAY,
                            }
                        ]
                    }
                ],
            }

        with mock.patch.object(attribution, "_http_json", side_effect=fake_http):
            touches, queries = attribution.fetch_customer_touches(
                account_id="acct",
                api_token="token",
                database_id="db",
                customer_ids=["7"],
                earliest_signup_at=100 * DAY,
                latest_signup_at=100 * DAY,
                window_days=30,
            )

        self.assertEqual(queries, 1)
        self.assertEqual(touches["7"][0]["source"], "facebook")
        sql = calls[0][1]["sql"]
        self.assertIn("customer_touches", sql)
        self.assertIn("source_clicks", sql)
        self.assertIn("COALESCE(sc.bot, 0) = 0", sql)
        self.assertNotIn("ct.bound_at <=", sql)

    def test_ad_query_reads_latest_native_ids_from_normalized_identifier_table(self) -> None:
        calls = []

        def fake_http(url, *, payload=None, **kwargs):
            calls.append((url, payload))
            return {
                "success": True,
                "result": [
                    {
                        "results": [
                            {
                                "customer_id": "7",
                                "bound_at": 102 * DAY,
                                "parameter": "gclid",
                                "identifier": "Google-123",
                                "clicked_at": 101 * DAY,
                            }
                        ]
                    }
                ],
            }

        with mock.patch.object(attribution, "_http_json", side_effect=fake_http):
            clicks, queries = attribution.fetch_customer_ad_clicks(
                account_id="acct",
                api_token="token",
                database_id="db",
                customer_ids=["7"],
            )

        self.assertEqual(queries, 1)
        self.assertEqual(clicks["7"][0]["identifier"], "Google-123")
        sql = calls[0][1]["sql"]
        self.assertIn("source_click_identifiers", sql)
        self.assertIn("ROW_NUMBER() OVER", sql)
        self.assertIn("'gclid'", sql)
        self.assertNotIn("'gbraid'", sql)
        self.assertNotIn("'wbraid'", sql)


class ContactLockTests(unittest.TestCase):
    FIELD_PROPERTIES = {
        "source": "cc_acquisition_source",
        "medium": "cc_acquisition_medium",
        "campaign": "cc_acquisition_campaign",
        "content": "cc_acquisition_content",
        "path": "cc_acquisition_entry_path",
        "country": "cc_acquisition_country",
        "clicked_at": "cc_acquisition_at",
        "model": "cc_acquisition_attribution_model",
        "window_days": "cc_acquisition_attribution_window_days",
        "status": "cc_acquisition_status",
    }

    def test_real_acquisition_is_locked_without_reading_a_click_id_property(self) -> None:
        existing = {"cc_acquisition_source": "facebook"}
        self.assertTrue(attribution.acquisition_locked(existing, self.FIELD_PROPERTIES))
        self.assertFalse(
            attribution.acquisition_locked(
                {"cc_acquisition_status": "no_recent_tracked_touch"},
                self.FIELD_PROPERTIES,
            )
        )


class SyncTests(unittest.TestCase):
    FIELD_PROPERTIES = ContactLockTests.FIELD_PROPERTIES
    AD_FIELD_PROPERTIES = NativeAdClickTests.FIELD_PROPERTIES

    @staticmethod
    def contact(contact_id: str, customer_id: str, created_at: str, **extra):
        return {
            "id": contact_id,
            "properties": {
                attribution.CUSTOMER_ID_PROPERTY: customer_id,
                attribution.CUSTOMER_CREATED_AT_PROPERTY: created_at,
                **extra,
            },
        }

    def run_sync(self, contacts, touches, ad_clicks=None):
        written = []
        schema = {
            attribution.CUSTOMER_ID_PROPERTY: object(),
            attribution.CUSTOMER_CREATED_AT_PROPERTY: object(),
        }
        with (
            mock.patch.object(attribution, "property_schema", return_value=schema),
            mock.patch.object(
                attribution,
                "resolve_fields",
                side_effect=[self.FIELD_PROPERTIES, self.AD_FIELD_PROPERTIES],
            ),
            mock.patch.object(attribution, "iter_hubspot_contacts", return_value=iter(contacts)),
            mock.patch.object(
                attribution,
                "fetch_customer_touches",
                return_value=(touches, 1),
            ),
            mock.patch.object(
                attribution,
                "fetch_customer_ad_clicks",
                return_value=(ad_clicks or {}, 1),
            ),
            mock.patch.object(
                attribution,
                "_batch_write",
                side_effect=lambda _token, _action, inputs: written.extend(inputs),
            ),
        ):
            summary = attribution.sync(
                account_id="acct",
                api_token="cf-token",
                database_id="db",
                hubspot_access_token="hs-token",
                window_days=30,
            )
        return summary, written

    def test_contact_is_attributed_by_customer_id_and_signup_timestamp(self) -> None:
        signup_at = attribution.epoch_millis("2026-08-24T12:00:00+08:00")
        assert signup_at is not None
        contacts = [self.contact("501", "7", "2026-08-24T12:00:00+08:00")]
        touches = {
            "7": [
                {
                    "customer_id": "7",
                    "bound_at": signup_at + 1000,
                    "clicked_at": signup_at - 1000,
                    "source": "whatsapp",
                    "medium": "messaging",
                    "campaign": "rf",
                    "content": "vip",
                    "path": "/wa",
                    "country": "SG",
                }
            ]
        }

        summary, written = self.run_sync(contacts, touches)
        self.assertEqual(summary["contacts_with_eligible_touch"], 1)
        self.assertEqual(written[0]["id"], "501")
        props = written[0]["properties"]
        self.assertEqual(props["cc_acquisition_source"], "whatsapp")
        self.assertEqual(props["cc_acquisition_campaign"], "rf")
        self.assertEqual(props["cc_acquisition_content"], "vip")
        self.assertEqual(props["cc_acquisition_status"], "attributed")
        self.assertFalse(any(key == "click_id" for key in props))

    def test_existing_acquisition_is_not_overwritten_but_new_ad_id_can_update(self) -> None:
        contacts = [
            self.contact(
                "501",
                "7",
                "2026-08-24T12:00:00+08:00",
                cc_acquisition_source="facebook",
            )
        ]
        ad_clicks = {
            "7": [
                {
                    "customer_id": "7",
                    "bound_at": 500,
                    "clicked_at": 400,
                    "parameter": "gclid",
                    "identifier": "Google-New",
                }
            ]
        }
        summary, written = self.run_sync(contacts, {}, ad_clicks)
        self.assertEqual(summary["contacts_already_attributed"], 1)
        self.assertEqual(summary["contacts_with_native_ad_click_updates"], 1)
        self.assertEqual(written[0]["properties"]["hs_google_click_id"], "Google-New")
        self.assertNotIn("cc_acquisition_source", written[0]["properties"])

    def test_no_touch_status_can_later_upgrade_to_attributed(self) -> None:
        signup_at = attribution.epoch_millis("2026-08-24T12:00:00+08:00")
        assert signup_at is not None
        contacts = [
            self.contact(
                "501",
                "7",
                "2026-08-24T12:00:00+08:00",
                cc_acquisition_status="no_recent_tracked_touch",
            )
        ]
        touches = {
            "7": [
                {
                    "customer_id": "7",
                    "bound_at": signup_at + 5000,
                    "clicked_at": signup_at - 5000,
                    "source": "instagram",
                }
            ]
        }
        summary, written = self.run_sync(contacts, touches)
        self.assertEqual(summary["contacts_with_eligible_touch"], 1)
        self.assertEqual(written[0]["properties"]["cc_acquisition_source"], "instagram")
        self.assertEqual(written[0]["properties"]["cc_acquisition_status"], "attributed")

    def test_duplicate_easystore_customer_id_is_not_guessed_for_either_sync(self) -> None:
        contacts = [
            self.contact("501", "7", "2026-08-24T12:00:00+08:00"),
            self.contact("502", "7", "2026-08-24T12:00:00+08:00"),
        ]
        summary, written = self.run_sync(contacts, {}, {"7": []})
        self.assertEqual(summary["contacts_with_duplicate_easystore_customer_id"], 2)
        self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()
