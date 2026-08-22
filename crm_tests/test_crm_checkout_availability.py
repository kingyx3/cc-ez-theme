from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_checkouts as checkouts
from easystore_hubspot_orders import SyncError


OUTAGE = checkouts.CheckoutSourceUnavailable(
    "EasyStore served no Checkout collection for any documented page size. "
    "limit=50: The read operation timed out"
)


class CheckoutOutageBehaviorTests(unittest.TestCase):
    """One unreachable EasyStore endpoint must not fail the whole CRM sync.

    Products, Customers, Orders and reconciliation have already written to
    HubSpot by the time carts run. Failing the step over a source outage leaves a
    red run that says nothing about the data that did land, and hides the next
    real failure.
    """

    def test_outage_skips_cart_upserts_but_keeps_order_link_refresh(self) -> None:
        link_summary = {
            "easystore_orders_scanned_for_cart_links": 7,
            "cart_order_associations_ensured": 2,
        }
        with mock.patch.object(
            checkouts,
            "read_checkout_snapshot",
            side_effect=OUTAGE,
        ), mock.patch.object(
            checkouts,
            "link_existing_carts_to_orders",
            return_value=link_summary,
        ) as link_existing, mock.patch.object(
            checkouts.commerce,
            "sync",
        ) as strict_sync:
            summary = checkouts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        strict_sync.assert_not_called()
        link_existing.assert_called_once()
        self.assertEqual(summary["easystore_checkout_status"], "unavailable")
        self.assertEqual(summary["easystore_checkouts_scanned"], 0)
        self.assertEqual(summary["cart_order_associations_ensured"], 2)
        self.assertTrue(summary["hubspot_cart_upserts_skipped"])
        self.assertTrue(summary["hubspot_cart_line_item_sync_skipped"])
        self.assertIn("timed out", summary["easystore_checkout_error"])
        self.assertEqual(
            summary["easystore_checkout_collection_endpoint"],
            "https://shop.example/api/3.0/checkouts.json",
        )

    def test_outage_is_annotated_on_the_run(self) -> None:
        with mock.patch.object(
            checkouts, "read_checkout_snapshot", side_effect=OUTAGE
        ), mock.patch.object(
            checkouts, "link_existing_carts_to_orders", return_value={}
        ), mock.patch.object(
            checkouts.sys, "stderr", new_callable=mock.MagicMock
        ) as stderr:
            checkouts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        annotation = "".join(
            str(call.args[0]) for call in stderr.write.call_args_list
        )
        self.assertIn("::warning title=EasyStore Checkout API unavailable::", annotation)

    def test_outage_can_be_made_fatal(self) -> None:
        with mock.patch.object(
            checkouts, "read_checkout_snapshot", side_effect=OUTAGE
        ), mock.patch.object(checkouts.commerce, "sync") as strict_sync:
            with self.assertRaises(checkouts.CheckoutSourceUnavailable):
                checkouts.sync(
                    store_domain="shop.example",
                    easystore_access_token="es",
                    hubspot_access_token="hs",
                    fallback_dial_code="65",
                    require_checkouts=True,
                )

        strict_sync.assert_not_called()

    def test_required_checkouts_flag_is_read_from_the_environment(self) -> None:
        with mock.patch.dict(
            checkouts.os.environ,
            {"EASYSTORE_CHECKOUTS_REQUIRED": "1"},
        ), mock.patch.object(checkouts, "sync", return_value={}) as sync:
            checkouts.main(
                [
                    "--store-domain",
                    "shop.example",
                    "--easystore-token",
                    "es",
                    "--hubspot-token",
                    "hs",
                ]
            )

        self.assertTrue(sync.call_args.kwargs["require_checkouts"])

    def test_an_outage_exits_the_step_successfully_with_a_summary(self) -> None:
        with mock.patch.object(
            checkouts, "read_checkout_snapshot", side_effect=OUTAGE
        ), mock.patch.object(
            checkouts, "link_existing_carts_to_orders", return_value={}
        ):
            exit_code = checkouts.main(
                [
                    "--store-domain",
                    "shop.example",
                    "--easystore-token",
                    "es",
                    "--hubspot-token",
                    "hs",
                ]
            )

        self.assertEqual(exit_code, 0)

    def test_a_broken_contract_still_fails_the_step(self) -> None:
        # A response that arrived and did not match the documented shape is a
        # data-integrity problem, not an outage.
        with mock.patch.object(
            checkouts,
            "read_checkout_snapshot",
            side_effect=SyncError("returned JSON without a checkout collection"),
        ):
            exit_code = checkouts.main(
                [
                    "--store-domain",
                    "shop.example",
                    "--easystore-token",
                    "es",
                    "--hubspot-token",
                    "hs",
                ]
            )

        self.assertEqual(exit_code, 1)

    def test_hubspot_integrity_errors_still_escape(self) -> None:
        snapshot = checkouts.CheckoutSnapshot(records=(), pages_read=1, details_fetched=0)
        with mock.patch.object(
            checkouts, "read_checkout_snapshot", return_value=snapshot
        ), mock.patch.object(
            checkouts.commerce,
            "sync",
            side_effect=SyncError("duplicate HubSpot cart identity"),
        ):
            with self.assertRaisesRegex(SyncError, "duplicate HubSpot"):
                checkouts.sync(
                    store_domain="shop.example",
                    easystore_access_token="es",
                    hubspot_access_token="hs",
                    fallback_dial_code="65",
                )


class CartOrderLinkRefreshTests(unittest.TestCase):
    def test_link_refresh_uses_the_singular_schema_object_type(self) -> None:
        with mock.patch.object(
            checkouts.commerce,
            "cart_object_available",
            return_value=False,
        ) as available:
            summary = checkouts.link_existing_carts_to_orders(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
            )

        available.assert_called_once_with("hs", "cart")
        self.assertEqual(summary["hubspot_cart_object"], "unavailable")
        self.assertEqual(summary["cart_order_associations_ensured"], 0)

    def test_existing_carts_are_linked_to_the_orders_they_became(self) -> None:
        orders = [{"id": "1001", "cart_token": "cart-1"}]
        with mock.patch.object(
            checkouts.commerce, "cart_object_available", return_value=True
        ), mock.patch.object(
            checkouts.commerce, "iter_orders_for_cart_links", return_value=iter(orders)
        ), mock.patch.object(
            checkouts.commerce, "hubspot_cart_index", return_value={"cart-1": "77"}
        ), mock.patch.object(
            checkouts.commerce, "hubspot_order_index", return_value={"1001": "88"}
        ), mock.patch.object(
            checkouts.commerce, "associate_cart"
        ) as associate:
            summary = checkouts.link_existing_carts_to_orders(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
            )

        associate.assert_called_once_with(
            "hs",
            "77",
            "order",
            "88",
            checkouts.commerce.CART_ORDER_ASSOCIATION_TYPE_ID,
        )
        self.assertEqual(summary["easystore_orders_scanned_for_cart_links"], 1)
        self.assertEqual(summary["cart_order_associations_ensured"], 1)


if __name__ == "__main__":
    unittest.main()


class UnpaidSubsetOnlyTests(unittest.TestCase):
    def test_the_production_entrypoint_asks_for_the_unpaid_subset_only(self) -> None:
        snapshot = checkouts.CheckoutSnapshot(
            records=({"cart_token": "c1", "financial_status": "unpaid"},),
            pages_read=1,
            details_fetched=0,
        )
        with mock.patch.object(
            checkouts, "read_checkout_snapshot", return_value=snapshot
        ), mock.patch.object(
            checkouts.commerce, "sync", return_value={}
        ) as cart_sync:
            summary = checkouts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertFalse(cart_sync.call_args.kwargs["include_completed"])
        self.assertEqual(summary["easystore_checkouts_abandoned_or_open"], 1)
        self.assertEqual(summary["easystore_checkouts_completed_or_paid"], 0)
        self.assertIn("unpaid", summary["hubspot_cart_source_semantics"])

    def test_a_paid_session_in_the_feed_is_annotated_not_written(self) -> None:
        snapshot = checkouts.CheckoutSnapshot(
            records=(
                {"cart_token": "c1", "financial_status": "unpaid"},
                {"cart_token": "c2", "financial_status": "paid"},
            ),
            pages_read=1,
            details_fetched=0,
        )
        with mock.patch.object(
            checkouts, "read_checkout_snapshot", return_value=snapshot
        ), mock.patch.object(
            checkouts.commerce, "sync", return_value={}
        ), mock.patch("sys.stderr") as stderr:
            summary = checkouts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        printed = "".join(
            call.args[0] for call in stderr.write.call_args_list if call.args
        )
        self.assertIn("Paid EasyStore Checkouts left to the Order stage", printed)
        self.assertEqual(summary["easystore_checkouts_completed_or_paid"], 1)
