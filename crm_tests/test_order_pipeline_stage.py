from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_order_sync as production_orders
import easystore_hubspot_orders as orders


TEST_STAGE_IDS = {
    "open": "stage-open",
    "processed": "stage-processed",
    "shipped": "stage-shipped",
    "delivered": "stage-delivered",
    "cancelled": "stage-cancelled",
}


class HubSpotOrderPipelineStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_pipeline_id = production_orders._PIPELINE_ID
        self.original_stage_ids = dict(production_orders._STAGE_IDS)
        self.original_validated = set(production_orders._VALIDATED_STAGE_IDS)
        production_orders._PIPELINE_ID = "pipeline-1"
        production_orders._STAGE_IDS = dict(TEST_STAGE_IDS)
        production_orders._VALIDATED_STAGE_IDS.clear()

    def tearDown(self) -> None:
        production_orders._PIPELINE_ID = self.original_pipeline_id
        production_orders._STAGE_IDS = self.original_stage_ids
        production_orders._VALIDATED_STAGE_IDS.clear()
        production_orders._VALIDATED_STAGE_IDS.update(self.original_validated)

    def test_easystore_states_map_conservatively_onto_order_pipeline(self) -> None:
        cases = (
            (
                {"financial_status": "unpaid", "fulfillment_status": "unfulfilled"},
                "open",
            ),
            (
                {"financial_status": "paid", "fulfillment_status": "unfulfilled"},
                "processed",
            ),
            (
                {
                    "financial_status": "paid",
                    "fulfillment_status": "partially_fulfilled",
                },
                "processed",
            ),
            (
                {"financial_status": "paid", "fulfillment_status": "fulfilled"},
                "shipped",
            ),
            (
                {"financial_status": "paid", "fulfillment_status": "delivered"},
                "delivered",
            ),
            (
                {
                    "status": "cancelled",
                    "financial_status": "unpaid",
                    "fulfillment_status": "restocked",
                },
                "cancelled",
            ),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(
                    production_orders.easystore_order_pipeline_stage(source),
                    expected,
                )

    def test_refund_without_cancelled_or_refunded_stage_fails_closed(self) -> None:
        with self.assertRaisesRegex(orders.SyncError, "no Refunded stage"):
            production_orders.easystore_order_pipeline_stage(
                {
                    "status": "closed",
                    "financial_status": "refunded",
                    "fulfillment_status": "unfulfilled",
                }
            )

    def test_live_schema_resolves_pipeline_and_stage_ids_by_label(self) -> None:
        pipeline_property = {
            "options": [
                {
                    "label": "Order Pipeline",
                    "value": "pipeline-live",
                    "hidden": False,
                }
            ]
        }
        stage_property = {
            "options": [
                {"label": "Open", "value": "open-live", "hidden": False},
                {
                    "label": "Processed",
                    "value": "processed-live",
                    "hidden": False,
                },
                {
                    "label": "Shipped",
                    "value": "shipped-live",
                    "hidden": False,
                },
                {
                    "label": "Delivered",
                    "value": "delivered-live",
                    "hidden": False,
                },
                {
                    "label": "Cancelled",
                    "value": "cancelled-live",
                    "hidden": False,
                },
            ]
        }

        with patch.object(
            orders,
            "_http_json",
            side_effect=[pipeline_property, stage_property],
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._PIPELINE_ID, "pipeline-live")
        self.assertEqual(
            production_orders._STAGE_IDS,
            {
                "open": "open-live",
                "processed": "processed-live",
                "shipped": "shipped-live",
                "delivered": "delivered-live",
                "cancelled": "cancelled-live",
            },
        )

    def test_multiple_visible_order_pipelines_are_rejected(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value={
                "options": [
                    {"label": "Order Pipeline", "value": "one"},
                    {"label": "Other Pipeline", "value": "two"},
                ]
            },
        ):
            with self.assertRaisesRegex(orders.SyncError, "exactly one visible"):
                production_orders.configure_production_order_pipeline("token")

    def test_order_projection_writes_native_pipeline_and_stage(self) -> None:
        mapped = production_orders.order_properties_with_pipeline(
            {
                "financial_status": "paid",
                "fulfillment_status": "fulfilled",
            },
            external_id="1001",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_pipeline"], "pipeline-1")
        self.assertEqual(mapped["hs_pipeline_stage"], "stage-shipped")

    def test_closed_stage_is_verified_from_hubspots_calculated_flag(self) -> None:
        response = {
            "properties": {
                "hs_pipeline_stage": "stage-shipped",
                "hs_is_closed": "true",
            }
        }
        with patch.object(orders, "_http_json", return_value=response) as request:
            production_orders._validate_order_stage_state(
                "token",
                "order-1",
                "stage-shipped",
            )
            production_orders._validate_order_stage_state(
                "token",
                "order-2",
                "stage-shipped",
            )

        request.assert_called_once()
        self.assertIn("stage-shipped", production_orders._VALIDATED_STAGE_IDS)

    def test_shipped_stage_must_actually_be_closed_in_hubspot(self) -> None:
        response = {
            "properties": {
                "hs_pipeline_stage": "stage-shipped",
                "hs_is_closed": "false",
            }
        }
        with patch.object(orders, "_http_json", return_value=response):
            with self.assertRaisesRegex(orders.SyncError, "must be configured as CLOSED"):
                production_orders._validate_order_stage_state(
                    "token",
                    "order-1",
                    "stage-shipped",
                )

    def test_processed_stage_must_remain_open_in_hubspot(self) -> None:
        response = {
            "properties": {
                "hs_pipeline_stage": "stage-processed",
                "hs_is_closed": "true",
            }
        }
        with patch.object(orders, "_http_json", return_value=response):
            with self.assertRaisesRegex(orders.SyncError, "must be configured as OPEN"):
                production_orders._validate_order_stage_state(
                    "token",
                    "order-1",
                    "stage-processed",
                )


if __name__ == "__main__":
    unittest.main()
