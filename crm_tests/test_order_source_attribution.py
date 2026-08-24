from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cloudflare_hubspot_order_attribution as attribution


DAY = attribution.MILLISECONDS_PER_DAY


class OrderIdentityTests(unittest.TestCase):
    def test_top_level_customer_id_wins(self) -> None:
        self.assertEqual(
            attribution.order_customer_id({"customer_id": 7, "customer": {"id": 9}}),
            "7",
        )

    def test_nested_customer_id_is_supported(self) -> None:
        self.assertEqual(attribution.order_customer_id({"customer": {"id": 9}}), "9")

    def test_timestamp_without_offset_is_treated_as_singapore_time(self) -> None:
        self.assertEqual(
            attribution.epoch_millis("2026-08-24 12:00:00"),
            attribution.epoch_millis("2026-08-24T12:00:00+08:00"),
        )


class LastTrackedTouchTests(unittest.TestCase):
    def test_latest_touch_before_order_wins(self) -> None:
        order_at = 100 * DAY
        touches = [
            {"source": "old", "clicked_at": 80 * DAY, "bound_at": 80 * DAY},
            {"source": "winner", "clicked_at": 99 * DAY, "bound_at": 99 * DAY},
            {"source": "after", "clicked_at": 101 * DAY, "bound_at": 101 * DAY},
        ]
        self.assertEqual(
            attribution.latest_touch_for_order(touches, order_at=order_at, window_days=30)[
                "source"
            ],
            "winner",
        )

    def test_touch_bound_after_order_cannot_retroactively_claim_it(self) -> None:
        order_at = 100 * DAY
        touches = [{"source": "late", "clicked_at": 99 * DAY, "bound_at": 101 * DAY}]
        self.assertIsNone(
            attribution.latest_touch_for_order(touches, order_at=order_at, window_days=30)
        )

    def test_touch_outside_window_is_not_used(self) -> None:
        order_at = 100 * DAY
        touches = [{"source": "old", "clicked_at": 69 * DAY, "bound_at": 69 * DAY}]
        self.assertIsNone(
            attribution.latest_touch_for_order(touches, order_at=order_at, window_days=30)
        )

    def test_no_touch_never_falls_back_to_contact_acquisition(self) -> None:
        values = attribution.touch_values(
            None,
            window_days=30,
            status="no_recent_tracked_touch",
        )
        self.assertEqual(values["status"], "no_recent_tracked_touch")
        self.assertEqual(values["model"], "last_tracked_touch")
        self.assertNotIn("source", values)
        self.assertNotIn("campaign", values)

    def test_hubspot_snapshot_contains_no_click_id(self) -> None:
        values = attribution.touch_values(
            {
                "source": "facebook",
                "medium": "social",
                "campaign": "rf",
                "content": "post-a",
                "clicked_at": 99 * DAY,
                "click_id": "d1-only",
            },
            window_days=30,
            status="attributed",
        )
        self.assertNotIn("click_id", values)
        self.assertFalse(any(field.key == "click_id" for field in attribution.FIELDS))


class SyncTests(unittest.TestCase):
    FIELD_PROPERTIES = {
        "source": "cc_order_source",
        "medium": "cc_order_medium",
        "campaign": "cc_order_campaign",
        "content": "cc_order_content",
        "clicked_at": "cc_order_touch_at",
        "model": "cc_order_attribution_model",
        "window_days": "cc_order_attribution_window_days",
        "status": "cc_order_attribution_status",
    }

    def test_each_order_gets_its_own_latest_touch(self) -> None:
        orders = [
            {"id": 1, "customer_id": 7, "created_at": "2026-08-10T12:00:00+08:00"},
            {"id": 2, "customer_id": 7, "created_at": "2026-08-24T12:00:00+08:00"},
        ]
        first_at = attribution.order_created_at(orders[0])
        second_at = attribution.order_created_at(orders[1])
        assert first_at is not None and second_at is not None

        touches = {
            "7": [
                {
                    "customer_id": "7",
                    "bound_at": first_at - DAY,
                    "clicked_at": first_at - DAY,
                    "source": "facebook",
                    "medium": "social",
                    "campaign": "signup",
                    "content": "post-a",
                },
                {
                    "customer_id": "7",
                    "bound_at": second_at - DAY,
                    "clicked_at": second_at - DAY,
                    "source": "whatsapp",
                    "medium": "messaging",
                    "campaign": "restock",
                    "content": "vip",
                },
            ]
        }
        hubspot = {
            "1": {"id": "hs-1", "properties": {"easystore_order_id": "1"}},
            "2": {"id": "hs-2", "properties": {"easystore_order_id": "2"}},
        }
        captured: list[dict] = []

        with (
            mock.patch.object(attribution, "resolve_fields", return_value=self.FIELD_PROPERTIES),
            mock.patch.object(
                attribution.orders,
                "iter_easystore_orders",
                return_value=iter(orders),
            ),
            mock.patch.object(
                attribution,
                "fetch_customer_touches",
                return_value=(touches, 1),
            ),
            mock.patch.object(attribution, "hubspot_order_records", return_value=hubspot),
            mock.patch.object(
                attribution,
                "batch_update_orders",
                side_effect=lambda _token, inputs: captured.extend(inputs) or len(inputs),
            ),
        ):
            summary = attribution.sync(
                store_domain="cardboard.sg",
                easystore_access_token="easy",
                hubspot_access_token="hub",
                account_id="cf",
                api_token="token",
                window_days=30,
            )

        self.assertEqual(summary["orders_with_eligible_touch"], 2)
        by_id = {item["id"]: item["properties"] for item in captured}
        self.assertEqual(by_id["hs-1"]["cc_order_source"], "facebook")
        self.assertEqual(by_id["hs-2"]["cc_order_source"], "whatsapp")
        self.assertEqual(by_id["hs-2"]["cc_order_campaign"], "restock")
        self.assertFalse(any("click_id" in key for props in by_id.values() for key in props))

    def test_existing_attribution_snapshot_is_never_overwritten(self) -> None:
        order = {"id": 1, "customer_id": 7, "created_at": "2026-08-24T12:00:00+08:00"}
        order_at = attribution.order_created_at(order)
        assert order_at is not None
        touches = {
            "7": [
                {
                    "customer_id": "7",
                    "bound_at": order_at - 1,
                    "clicked_at": order_at - 1,
                    "source": "whatsapp",
                }
            ]
        }
        hubspot = {
            "1": {
                "id": "hs-1",
                "properties": {
                    "easystore_order_id": "1",
                    "cc_order_source": "facebook",
                    "cc_order_attribution_status": "attributed",
                },
            }
        }

        with (
            mock.patch.object(attribution, "resolve_fields", return_value=self.FIELD_PROPERTIES),
            mock.patch.object(
                attribution.orders,
                "iter_easystore_orders",
                return_value=iter([order]),
            ),
            mock.patch.object(
                attribution,
                "fetch_customer_touches",
                return_value=(touches, 1),
            ),
            mock.patch.object(attribution, "hubspot_order_records", return_value=hubspot),
            mock.patch.object(attribution, "batch_update_orders", return_value=0) as batch,
        ):
            summary = attribution.sync(
                store_domain="cardboard.sg",
                easystore_access_token="easy",
                hubspot_access_token="hub",
                account_id="cf",
                api_token="token",
            )

        self.assertEqual(summary["hubspot_orders_already_attributed"], 1)
        batch.assert_called_once_with("hub", [])

    def test_no_touch_status_can_upgrade_if_a_valid_pre_order_binding_appears(self) -> None:
        order = {"id": 1, "customer_id": 7, "created_at": "2026-08-24T12:00:00+08:00"}
        order_at = attribution.order_created_at(order)
        assert order_at is not None
        touches = {
            "7": [
                {
                    "customer_id": "7",
                    "bound_at": order_at - 2,
                    "clicked_at": order_at - 3,
                    "source": "instagram",
                }
            ]
        }
        hubspot = {
            "1": {
                "id": "hs-1",
                "properties": {
                    "easystore_order_id": "1",
                    "cc_order_attribution_status": "no_recent_tracked_touch",
                },
            }
        }
        captured = []
        with (
            mock.patch.object(attribution, "resolve_fields", return_value=self.FIELD_PROPERTIES),
            mock.patch.object(
                attribution.orders,
                "iter_easystore_orders",
                return_value=iter([order]),
            ),
            mock.patch.object(
                attribution,
                "fetch_customer_touches",
                return_value=(touches, 1),
            ),
            mock.patch.object(attribution, "hubspot_order_records", return_value=hubspot),
            mock.patch.object(
                attribution,
                "batch_update_orders",
                side_effect=lambda _token, inputs: captured.extend(inputs) or len(inputs),
            ),
        ):
            attribution.sync(
                store_domain="cardboard.sg",
                easystore_access_token="easy",
                hubspot_access_token="hub",
                account_id="cf",
                api_token="token",
            )
        self.assertEqual(captured[0]["properties"]["cc_order_source"], "instagram")
        self.assertEqual(captured[0]["properties"]["cc_order_attribution_status"], "attributed")


if __name__ == "__main__":
    unittest.main()
