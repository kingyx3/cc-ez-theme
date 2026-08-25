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
    "refunded": "stage-refunded",
}


def pipeline_document(
    *,
    pipeline_id: str = "pipeline-live",
    pipeline_label: str = "Order Pipeline",
    open_label: str = "Open",
    open_state: str | None = "OPEN",
    processed_state: str | None = "OPEN",
    shipped_state: str | None = "CLOSED",
    delivered_state: str | None = "CLOSED",
    cancelled_state: str | None = "CLOSED",
    refunded_state: str | None = "CLOSED",
    include_processed: bool = True,
    include_shipped: bool = True,
    include_delivered: bool = True,
    include_cancelled: bool = True,
    include_refunded: bool = False,
) -> dict:
    def metadata(state: str | None) -> dict:
        return {"state": state} if state is not None else {}

    stages = [
        {
            "id": "open-live",
            "label": open_label,
            "displayOrder": 0,
            "archived": False,
            "metadata": metadata(open_state),
        }
    ]
    optional = (
        (
            include_processed,
            {
                "id": "processed-live",
                "label": "Processed",
                "displayOrder": 1,
                "archived": False,
                "metadata": metadata(processed_state),
            },
        ),
        (
            include_shipped,
            {
                "id": "shipped-live",
                "label": "Shipped",
                "displayOrder": 2,
                "archived": False,
                "metadata": metadata(shipped_state),
            },
        ),
        (
            include_delivered,
            {
                "id": "delivered-live",
                "label": "Delivered",
                "displayOrder": 3,
                "archived": False,
                "metadata": metadata(delivered_state),
            },
        ),
        (
            include_cancelled,
            {
                "id": "cancelled-live",
                "label": "Cancelled",
                "displayOrder": 4,
                "archived": False,
                "metadata": metadata(cancelled_state),
            },
        ),
        (
            include_refunded,
            {
                "id": "refunded-live",
                "label": "Refunded",
                "displayOrder": 5,
                "archived": False,
                "metadata": metadata(refunded_state),
            },
        ),
    )
    stages.extend(stage for include, stage in optional if include)
    return {
        "results": [
            {
                "id": pipeline_id,
                "label": pipeline_label,
                "archived": False,
                "stages": stages,
            }
        ]
    }


class HubSpotOrderPipelineStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_pipeline_id = production_orders._PIPELINE_ID
        self.original_stage_ids = dict(production_orders._STAGE_IDS)
        self.original_expected_closed = dict(production_orders._STAGE_EXPECTED_CLOSED)
        self.original_labels_by_id = dict(production_orders._STAGE_LABELS_BY_ID)
        self.original_validated = set(production_orders._VALIDATED_STAGE_IDS)
        production_orders._PIPELINE_ID = "pipeline-1"
        production_orders._STAGE_IDS = dict(TEST_STAGE_IDS)
        production_orders._STAGE_EXPECTED_CLOSED = {
            "stage-open": False,
            "stage-processed": False,
            "stage-shipped": True,
            "stage-delivered": True,
            "stage-cancelled": True,
            "stage-refunded": True,
        }
        production_orders._STAGE_LABELS_BY_ID = {
            stage_id: production_orders.ORDER_STAGE_LABELS[key]
            for key, stage_id in TEST_STAGE_IDS.items()
        }
        production_orders._VALIDATED_STAGE_IDS.clear()

    def tearDown(self) -> None:
        production_orders._PIPELINE_ID = self.original_pipeline_id
        production_orders._STAGE_IDS = self.original_stage_ids
        production_orders._STAGE_EXPECTED_CLOSED = self.original_expected_closed
        production_orders._STAGE_LABELS_BY_ID = self.original_labels_by_id
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
            (
                {
                    "status": "closed",
                    "financial_status": "refunded",
                    "fulfillment_status": "unfulfilled",
                },
                "refunded",
            ),
            ({"status": "fulfilled", "financial_status": "paid"}, "shipped"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(
                    production_orders.easystore_order_pipeline_stage(source),
                    expected,
                )

    def test_pipeline_api_resolves_live_portal_and_safe_refund_fallback(self) -> None:
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
                "refunded": "cancelled-live",
            },
        )

    def test_real_portal_processed_closed_cancelled_open_is_supported(self) -> None:
        """Regression for the two production failures observed after PRs 188/189."""

        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(
                processed_state="CLOSED",
                cancelled_state="OPEN",
            ),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["processed"], "open-live")
        self.assertEqual(production_orders._STAGE_IDS["cancelled"], "cancelled-live")
        self.assertEqual(production_orders._STAGE_IDS["refunded"], "cancelled-live")
        self.assertFalse(production_orders._STAGE_EXPECTED_CLOSED["cancelled-live"])
        self.assertTrue(production_orders._STAGE_EXPECTED_CLOSED["shipped-live"])
        self.assertTrue(production_orders._STAGE_EXPECTED_CLOSED["delivered-live"])

    def test_closed_processed_stage_routes_payment_only_orders_to_open(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(processed_state="CLOSED"),
        ):
            production_orders.configure_production_order_pipeline("token")

        mapped = production_orders.order_properties_with_pipeline(
            {
                "financial_status": "paid",
                "fulfillment_status": "unfulfilled",
            },
            external_id="1001",
            store_domain="cardboardcollective.easy.co",
        )
        self.assertEqual(mapped["hs_pipeline_stage"], "open-live")

    def test_missing_processed_stage_also_routes_payment_only_orders_to_open(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(include_processed=False),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["processed"], "open-live")

    def test_unclassified_processed_stage_also_falls_back_to_open(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(processed_state=None),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["processed"], "open-live")

    def test_renamed_open_stage_uses_earliest_live_open_stage(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(open_label="New"),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["open"], "open-live")
        self.assertEqual(production_orders._STAGE_LABELS_BY_ID["open-live"], "New")

    def test_missing_cancelled_stage_preserves_source_status_on_open_stage(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(include_cancelled=False),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["cancelled"], "open-live")
        self.assertEqual(production_orders._STAGE_IDS["refunded"], "open-live")

    def test_native_refunded_stage_is_used_when_available(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(include_refunded=True),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["refunded"], "refunded-live")
        self.assertTrue(production_orders._STAGE_EXPECTED_CLOSED["refunded-live"])

    def test_property_option_visibility_is_not_used_for_pipeline_discovery(self) -> None:
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

    def test_open_shipped_stage_falls_back_to_closed_delivered_stage(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(shipped_state="OPEN"),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["shipped"], "delivered-live")
        self.assertEqual(production_orders._STAGE_IDS["delivered"], "delivered-live")

    def test_missing_shipped_stage_can_use_closed_delivered_stage(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(include_shipped=False),
        ):
            production_orders.configure_production_order_pipeline("token")

        self.assertEqual(production_orders._STAGE_IDS["shipped"], "delivered-live")

    def test_no_closed_fulfillment_stage_fails_before_writing_orders(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(
                shipped_state="OPEN",
                delivered_state="OPEN",
            ),
        ):
            with self.assertRaisesRegex(
                orders.SyncError,
                "no CLOSED fulfillment-complete stage",
            ):
                production_orders.configure_production_order_pipeline("token")

    def test_no_open_holding_stage_is_a_real_configuration_error(self) -> None:
        with patch.object(
            orders,
            "_http_json",
            return_value=pipeline_document(
                open_state="CLOSED",
                processed_state="CLOSED",
                shipped_state="CLOSED",
                delivered_state="CLOSED",
                cancelled_state="CLOSED",
            ),
        ):
            with self.assertRaisesRegex(orders.SyncError, "no stage classified OPEN"):
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

    def test_closed_stage_requires_calculated_flag_and_closed_date(self) -> None:
        response = {
            "properties": {
                "hs_pipeline_stage": "stage-shipped",
                "hs_is_closed": "true",
                "hs_closed_date": "2026-08-25T15:00:00Z",
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
        requested_url = request.call_args.args[0]
        self.assertIn("hs_closed_date", requested_url)
        self.assertIn("stage-shipped", production_orders._VALIDATED_STAGE_IDS)

    def test_calculated_stage_fields_are_retried_until_they_settle(self) -> None:
        stale = {
            "properties": {
                "hs_pipeline_stage": "stage-shipped",
                "hs_is_closed": "false",
                "hs_closed_date": None,
            }
        }
        settled = {
            "properties": {
                "hs_pipeline_stage": "stage-shipped",
                "hs_is_closed": "true",
                "hs_closed_date": "2026-08-25T15:00:00Z",
            }
        }
        with (
            patch.object(orders, "_http_json", side_effect=[stale, settled]) as request,
            patch.object(production_orders.time, "sleep") as sleep,
        ):
            production_orders._validate_order_stage_state(
                "token",
                "order-1",
                "stage-shipped",
            )

        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()
        self.assertIn("stage-shipped", production_orders._VALIDATED_STAGE_IDS)

    def test_closed_stage_without_closed_date_fails_after_bounded_retry(self) -> None:
        response = {
            "properties": {
                "hs_pipeline_stage": "stage-shipped",
                "hs_is_closed": "true",
                "hs_closed_date": None,
            }
        }
        with (
            patch.object(orders, "_http_json", return_value=response) as request,
            patch.object(production_orders.time, "sleep"),
        ):
            with self.assertRaisesRegex(orders.SyncError, "hs_closed_date"):
                production_orders._validate_order_stage_state(
                    "token",
                    "order-1",
                    "stage-shipped",
                )

        self.assertEqual(request.call_count, production_orders.STAGE_VALIDATION_ATTEMPTS)

    def test_shipped_stage_lifecycle_drift_fails_after_bounded_retry(self) -> None:
        response = {
            "properties": {
                "hs_pipeline_stage": "stage-shipped",
                "hs_is_closed": "false",
                "hs_closed_date": None,
            }
        }
        with (
            patch.object(orders, "_http_json", return_value=response),
            patch.object(production_orders.time, "sleep"),
        ):
            with self.assertRaisesRegex(orders.SyncError, "expected CLOSED"):
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
                "hs_closed_date": "2026-08-25T15:00:00Z",
            }
        }
        with (
            patch.object(orders, "_http_json", return_value=response),
            patch.object(production_orders.time, "sleep"),
        ):
            with self.assertRaisesRegex(orders.SyncError, "expected OPEN"):
                production_orders._validate_order_stage_state(
                    "token",
                    "order-1",
                    "stage-processed",
                )

    def test_cancelled_open_state_is_verified_without_forcing_closed(self) -> None:
        production_orders._STAGE_EXPECTED_CLOSED["stage-cancelled"] = False
        response = {
            "properties": {
                "hs_pipeline_stage": "stage-cancelled",
                "hs_is_closed": "false",
                "hs_closed_date": None,
            }
        }
        with patch.object(orders, "_http_json", return_value=response):
            production_orders._validate_order_stage_state(
                "token",
                "order-1",
                "stage-cancelled",
            )

        self.assertIn("stage-cancelled", production_orders._VALIDATED_STAGE_IDS)

    def test_unknown_pipeline_state_is_learned_from_first_persisted_write(self) -> None:
        production_orders._STAGE_EXPECTED_CLOSED["stage-cancelled"] = None
        response = {
            "properties": {
                "hs_pipeline_stage": "stage-cancelled",
                "hs_is_closed": "false",
                "hs_closed_date": None,
            }
        }
        with patch.object(orders, "_http_json", return_value=response):
            production_orders._validate_order_stage_state(
                "token",
                "order-1",
                "stage-cancelled",
            )

        self.assertFalse(
            production_orders._STAGE_EXPECTED_CLOSED["stage-cancelled"]
        )


if __name__ == "__main__":
    unittest.main()
