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


def pipeline_document(
    *,
    pipeline_id: str = "pipeline-live",
    pipeline_label: str = "Order Pipeline",
    processed_state: str | None = "OPEN",
    shipped_state: str = "CLOSED",
) -> dict:
    processed_metadata = (
        {"state": processed_state} if processed_state is not None else {}
    )
    return {
        "results": [
            {
                "id": pipeline_id,
                "label": pipeline_label,
                "archived": False,
                "stages": [
                    {
                        "id": "open-live",
                        "label": "Open",
                        "archived": False,
                        "metadata": {"state": "OPEN"},
                    },
                    {
                        "id": "processed-live",
                        "label": "Processed",
                        "archived": False,
                        "metadata": processed_metadata,
                    },
                    {
                        "id": "shipped-live",
                        "label": "Shipped",
                        "archived": False,
                        "metadata": {"state": shipped_state},
                    },
                    {
                        "id": "delivered-live",
                        "label": "Delivered",
                        "archived": False,
                        "metadata": {"state": "CLOSED"},
                    },
                    {
                        "id": "cancelled-live",
                        "label": "Cancelled",
                        "archived": False,
                        "metadata": {"state": "CLOSED"},
                    },
                ],
            }
        ]
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

    def test_pipeline_api_resolves_pipeline_and_stage_ids_by_label(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(),
        ) as request:
            production_orders.configure_production_order_pipeline("token")

        request.assert_called_once_with(
            production_orders.HUBSPOT_ORDER_PIPELINES_URL,
            headers={"Authorization": "Bearer token"},
        )
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

    def test_closed_processed_stage_routes_payment_only_orders_to_open(self) -> None:
        """Regression for prod run 32860581453: Processed is CLOSED in this portal."""

        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(processed_state="CLOSED"),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["open"], "open-live")
        self.assertEqual(production_orders._STAGE_IDS["processed"], "open-live")

        mapped = production_orders.order_properties_with_pipeline(
            {
                "financial_status": "paid",
                "fulfillment_status": "unfulfilled",
            },
            external_id="1001",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_pipeline_stage"], "open-live")

    def test_unclassified_processed_stage_also_falls_back_to_open(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(processed_state=None),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["processed"], "open-live")

    def test_property_option_visibility_is_not_used_for_pipeline_discovery(self) -> None:
        """Regression for prod run 32854309344: hs_pipeline showed 0 visible options."""

        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(),
        ) as request:
            production_orders.configure_production_order_pipeline("token")

        requested_url = request.call_args.args[0]
        self.assertIn("/crm/pipelines/2026-03/order", requested_url)
        self.assertNotIn("/properties/order/", requested_url)

    def test_multiple_active_order_pipelines_are_rejected(self) -> None:
        response = pipeline_document()
        response["results"].append(
            {
                "id": "pipeline-two",
                "label": "Other Pipeline",
                "archived": False,
                "stages": [],
            }
        )
        with patch.object(orders, "_http_json", return_value=response):
            with self.assertRaisesRegex(orders.SyncError, "exactly one active"):
                production_orders.configure_production_order_pipeline("token")

    def test_archived_pipeline_is_ignored(self) -> None:
        response = pipeline_document()
        response["results"].append(
            {
                "id": "pipeline-old",
                "label": "Old Pipeline",
                "archived": True,
                "stages": [],
            }
        )
        with patch.object(orders, "_http_json", return_value=response):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._PIPELINE_ID, "pipeline-live")

    def test_pipeline_metadata_must_match_expected_closed_state(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(shipped_state="OPEN"),
        ):
            with self.assertRaisesRegex(orders.SyncError, "must be configured as CLOSED"):
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

    def test_processed_stage_must_remain_open_if_written_directly(self) -> None:
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
