from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_admin_checkouts as admin
import easystore_hubspot_carts as cart_mapping
import easystore_hubspot_checkouts as checkouts
import easystore_hubspot_commerce as commerce


def _record(**overrides) -> dict:
    """One abandoned checkout, shaped exactly as the admin API answered."""

    record = {
        "id": 114004107,
        "created_at": "2026-08-21T09:38:24.000+08:00",
        "product_catalog_id": None,
        "customer_id": 41597490,
        "location_id": None,
        "source_name": "SF",
        "source_type": "online_store",
        "client_info": "chrome",
        "landing_site": None,
        "referring_site": "https://cardboard.sg/collections/ready-to-play",
        "amount": "168.0",
        "total_line_items_price": "168.0",
        "currency": "SGD",
        "credit_used": "0.0",
        "credit_earn": "0.0",
        "cart_token": "b146ae44-9b04-4ab0-8bd7-2adef14bdda0",
        "is_processed": False,
        "is_recovered": False,
        "is_deleted": False,
        "first_name": "Chestnutay",
        "last_name": None,
        "email": "chester.tayf@gmail.com",
        "phone": "6588143218",
        "referral": None,
        "url": "https://cardboard.sg/sf/checkout/b146ae44-9b04-4ab0-8bd7-2adef14bdda0",
        "channel": "storefront",
    }
    record.update(overrides)
    return record


def _body(records: list[dict], *, total: int | None = None, pages: int = 1) -> dict:
    return {
        "params": {
            "page": 1,
            "limit": 50,
            "page_count": pages,
            "total_count": total if total is not None else len(records),
        },
        "data": {"checkouts": records, "is_empty": not records},
    }


class AdminCollectionRequestTests(unittest.TestCase):
    """The request is shaped as the EasyStore admin itself sends it."""

    def test_the_url_and_query_match_the_observed_request(self) -> None:
        url = admin._page_url(1)

        self.assertTrue(url.startswith(admin.ADMIN_CHECKOUTS_URL + "?"))
        self.assertIn("page=1", url)
        self.assertIn("limit=50", url)
        self.assertIn("start_date=", url)
        self.assertIn("end_date=", url)
        self.assertIn("sort=created_at.desc", url)

    def test_each_credential_shape_is_tried_until_one_is_accepted(self) -> None:
        seen: list[dict] = []

        def refuse_then_accept(_url, *, headers, **_kwargs):
            seen.append(headers)
            if len(seen) == 1:
                return None  # 401/403/404 come back as None
            return _body([_record()])

        with mock.patch.object(admin, "_http_json", refuse_then_accept):
            read = admin.read_admin_checkouts("app-token")

        self.assertEqual(len(read.records), 1)
        self.assertIn("EasyStore-Access-Token", seen[0])
        self.assertEqual(seen[1]["Authorization"], "Bearer app-token")
        self.assertEqual(read.authentication, "app token as Bearer")
        self.assertIn("refused the credential", read.attempts[0])

    def test_a_dedicated_admin_token_is_tried_before_the_app_token(self) -> None:
        seen: list[dict] = []

        def accept(_url, *, headers, **_kwargs):
            seen.append(headers)
            return _body([_record()])

        with mock.patch.object(admin, "_http_json", accept):
            read = admin.read_admin_checkouts("app-token", "admin-token")

        self.assertEqual(seen[0]["EasyStore-Access-Token"], "admin-token")
        self.assertEqual(read.authentication, "admin token as EasyStore-Access-Token")

    def test_a_route_that_accepts_nothing_is_reported_not_raised_blindly(self) -> None:
        with mock.patch.object(admin, "_http_json", lambda *a, **k: None):
            with self.assertRaises(admin.AdminSourceUnavailable) as caught:
                admin.read_admin_checkouts("app-token")

        # Every credential tried is named, so a fix is a one-line change.
        self.assertEqual(len(caught.exception.attempts), 2)
        self.assertIn("refused the credential", caught.exception.attempts[0])

    def test_a_transport_failure_ends_the_read_without_retrying_credentials(
        self,
    ) -> None:
        calls: list[str] = []

        def die(url, **_kwargs):
            calls.append(url)
            raise admin.SyncError("The read operation timed out")

        with mock.patch.object(admin, "_http_json", die):
            with self.assertRaises(admin.AdminSourceUnavailable) as caught:
                admin.read_admin_checkouts("app-token")

        self.assertEqual(len(calls), 1)
        self.assertIn("timed out", caught.exception.attempts[0])


class AdminCollectionPaginationTests(unittest.TestCase):
    """This collection declares its own size, so completeness is a fact."""

    def test_declared_total_count_is_checked_against_what_arrived(self) -> None:
        with mock.patch.object(
            admin, "_http_json", lambda *a, **k: _body([_record()], total=15)
        ):
            read = admin.read_admin_checkouts("app-token")

        self.assertEqual(read.total_count, 15)
        self.assertEqual(len(read.records), 1)
        self.assertFalse(read.complete)

    def test_a_single_full_page_is_complete(self) -> None:
        records = [_record(id=index, cart_token=f"cart-{index}") for index in range(15)]
        with mock.patch.object(
            admin, "_http_json", lambda *a, **k: _body(records, total=15)
        ):
            read = admin.read_admin_checkouts("app-token")

        self.assertEqual(len(read.records), 15)
        self.assertTrue(read.complete)
        self.assertEqual(read.pages_read, 1)

    def test_every_declared_page_is_read(self) -> None:
        pages = {
            "page=1": [_record(id=1, cart_token="a")],
            "page=2": [_record(id=2, cart_token="b")],
        }

        def serve(url, **_kwargs):
            for marker, records in pages.items():
                if marker in url:
                    return _body(records, total=2, pages=2)
            return _body([], total=2, pages=2)

        with mock.patch.object(admin, "_http_json", serve):
            read = admin.read_admin_checkouts("app-token")

        self.assertEqual(read.pages_read, 2)
        self.assertEqual([item["id"] for item in read.records], [1, 2])
        self.assertTrue(read.complete)

    def test_a_repeated_page_stops_instead_of_looping(self) -> None:
        # The public route does exactly this; the admin one must not be trusted
        # to be different just because it reports a page_count.
        calls: list[str] = []

        def serve(url, **_kwargs):
            calls.append(url)
            return _body([_record()], total=99, pages=99)

        with mock.patch.object(admin, "_http_json", serve):
            read = admin.read_admin_checkouts("app-token")

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(read.records), 1)
        self.assertTrue(any("repeated records" in line for line in read.attempts))

    def test_a_nonsense_page_count_cannot_spin_the_job(self) -> None:
        served = {"pages": 0}

        def serve(url, **_kwargs):
            served["pages"] += 1
            return _body(
                [_record(id=served["pages"], cart_token=f"cart-{served['pages']}")],
                total=10_000,
                pages=10_000,
            )

        with mock.patch.object(admin, "_http_json", serve):
            read = admin.read_admin_checkouts("app-token")

        self.assertEqual(read.pages_read, admin.ADMIN_PAGE_CEILING)


class AdminRecordShapeTests(unittest.TestCase):
    """The admin record is renamed into the shape the Cart writer already reads."""

    def test_the_customer_the_session_belongs_to_is_carried_through(self) -> None:
        checkout = admin.as_checkout(_record())

        self.assertEqual(commerce.checkout_customer_id(checkout), "41597490")
        self.assertEqual(cart_mapping.cart_email(checkout), "chester.tayf@gmail.com")
        self.assertEqual(cart_mapping.cart_mobile(checkout, "65"), "+6588143218")
        self.assertEqual(commerce.checkout_cart_token(checkout), _record()["cart_token"])

    def test_the_money_and_the_recovery_link_are_mapped(self) -> None:
        values = cart_mapping.cart_field_values(admin.as_checkout(_record()), "65")

        self.assertEqual(values["total_amount"], "168.0")
        self.assertEqual(values["subtotal_amount"], "168.0")
        self.assertEqual(values["token"], _record()["cart_token"])
        self.assertIn("/sf/checkout/", values["recovery_url"])
        self.assertEqual(values["buyer_name"], "Chestnutay")
        # Datetimes reach HubSpot as epoch milliseconds, so the admin
        # timestamp's +08:00 offset has to survive the conversion.
        expected = datetime.datetime(
            2026, 8, 21, 9, 38, 24, tzinfo=datetime.timezone(datetime.timedelta(hours=8))
        )
        self.assertEqual(
            values["created_at"], str(int(expected.timestamp() * 1000))
        )

    def test_an_open_session_is_abandoned_and_a_recovered_one_is_not(self) -> None:
        self.assertTrue(cart_mapping.is_abandoned(admin.as_checkout(_record())))
        self.assertFalse(
            cart_mapping.is_abandoned(
                admin.as_checkout(_record(is_recovered=True, is_processed=True))
            )
        )

    def test_a_deleted_checkout_is_dropped(self) -> None:
        kept = admin.as_checkouts(
            (_record(id=1), _record(id=2, is_deleted=True))
        )

        self.assertEqual([item["id"] for item in kept], [1])

    def test_null_fields_are_left_out_rather_than_written_as_empty(self) -> None:
        checkout = admin.as_checkout(_record(email=None, landing_site=None))

        self.assertNotIn("email", checkout)
        self.assertNotIn("landing_site", checkout)
        self.assertIsNone(cart_mapping.cart_email(checkout))
        # The phone is still there, so the shopper is still contactable.
        self.assertEqual(cart_mapping.cart_mobile(checkout, "65"), "+6588143218")


class AdminSnapshotIntegrationTests(unittest.TestCase):
    """What the checkout stage does with the admin collection."""

    LINE = [{"sku": "SKU-A", "quantity": 1, "price": "168.0"}]

    def _snapshot(self, detail):
        with mock.patch.object(
            checkouts.admin_source,
            "read_admin_checkouts",
            return_value=admin.AdminCheckoutRead(
                records=(_record(),),
                total_count=1,
                pages_read=1,
                authentication="app token as EasyStore-Access-Token",
                attempts=("app token: answered 1 of 1 checkout(s) over 1 page(s)",),
            ),
        ), mock.patch.object(checkouts, "_http_json", detail):
            return checkouts.read_admin_snapshot("shop.example", "es")

    def test_line_items_are_hydrated_from_the_detail_route(self) -> None:
        snapshot, report = self._snapshot(
            lambda *a, **k: {"checkout": {"line_items": self.LINE}}
        )

        self.assertEqual(snapshot.records[0]["line_items"], self.LINE)
        self.assertEqual(snapshot.details_fetched, 1)
        self.assertTrue(snapshot.complete)
        self.assertEqual(
            report["easystore_checkout_source"], "admin_api_abandoned_checkouts"
        )
        self.assertEqual(report["easystore_admin_checkouts_declared"], 1)
        self.assertIn("customer_id", snapshot.customer_reference)

    def test_a_cart_survives_a_detail_route_that_will_not_answer(self) -> None:
        def die(*_args, **_kwargs):
            raise checkouts.SyncError("The read operation timed out")

        snapshot, _ = self._snapshot(die)

        # The Cart is still written - an abandoned cart missing from the CRM is
        # worse than one whose items are not itemized - and it is marked so the
        # writer leaves any Line Items an earlier run wrote alone.
        self.assertEqual(len(snapshot.records), 1)
        self.assertTrue(
            snapshot.records[0][commerce.LINE_ITEMS_UNAVAILABLE_KEY]
        )
        self.assertEqual(snapshot.details_fetched, 0)

    def test_a_refused_admin_collection_falls_back_and_says_so(self) -> None:
        with mock.patch.object(
            checkouts.admin_source,
            "read_admin_checkouts",
            side_effect=admin.AdminSourceUnavailable(
                "No credential was accepted by EasyStore's admin checkout list.",
                ("app token as Bearer: refused the credential",),
            ),
        ):
            snapshot, report = checkouts.read_admin_snapshot("shop.example", "es")

        self.assertIsNone(snapshot)
        self.assertEqual(report["easystore_admin_checkout_status"], "unavailable")
        self.assertIn("refused", report["easystore_admin_checkout_attempts"][0])

    def test_the_admin_snapshot_is_written_without_the_recoverable_filter(self) -> None:
        # EasyStore has already decided what an abandoned cart is here, so the
        # stage must not second-guess the list by filtering it again.
        snapshot = checkouts.CheckoutSnapshot(
            records=(admin.as_checkout(_record()),),
            pages_read=1,
            details_fetched=1,
        )
        with mock.patch.object(
            checkouts,
            "read_admin_snapshot",
            return_value=(snapshot, {"easystore_admin_checkout_status": "available"}),
        ), mock.patch.object(
            checkouts.commerce, "sync", return_value={}
        ) as cart_sync, mock.patch.object(
            checkouts, "read_checkout_snapshot"
        ) as public:
            checkouts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        public.assert_not_called()
        self.assertFalse(cart_sync.call_args.kwargs["recoverable_only"])
        self.assertFalse(cart_sync.call_args.kwargs["include_completed"])

    def test_the_public_collection_keeps_its_filter(self) -> None:
        snapshot = checkouts.CheckoutSnapshot(
            records=({"cart_token": "c1", "financial_status": "unpaid"},),
            pages_read=1,
            details_fetched=0,
        )
        with mock.patch.object(
            checkouts,
            "read_admin_snapshot",
            return_value=(None, {"easystore_admin_checkout_status": "unavailable"}),
        ), mock.patch.object(
            checkouts, "read_checkout_snapshot", return_value=snapshot
        ), mock.patch.object(
            checkouts.commerce, "sync", return_value={}
        ) as cart_sync:
            checkouts.sync(
                store_domain="shop.example",
                easystore_access_token="es",
                hubspot_access_token="hs",
                fallback_dial_code="65",
            )

        self.assertTrue(cart_sync.call_args.kwargs["recoverable_only"])


if __name__ == "__main__":
    unittest.main()
