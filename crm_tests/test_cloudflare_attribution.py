"""Tests for the Cloudflare click to HubSpot contact join.

The join is the one stage that reads two systems that know nothing about each
other, so what is asserted here is mostly refusal: a click id that no D1 row
matches, a value a browser could have tampered with, and an acquisition that
HubSpot already recorded all have to leave the CRM alone.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cloudflare_hubspot_attribution as attribution


CLICK_A = "11111111-2222-3333-4444-555555555555"
CLICK_B = "66666666-7777-8888-9999-aaaaaaaaaaaa"


def click_row(click_id: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "click_id": click_id,
        "source": "carousell",
        "medium": "marketplace",
        "campaign": "always-on",
        "path": "/go/ca",
        "country": "SG",
        "clicked_at": 1750000000000,
        "bot": 0,
        "bot_reason": "",
    }
    row.update(overrides)
    return row


def contact(contact_id: str, **properties: Any) -> dict[str, Any]:
    return {"id": contact_id, "properties": {"hs_object_id": contact_id, **properties}}


class FakeApi:
    """Answers the HubSpot and Cloudflare calls the stage makes.

    Requests are recorded so a test can assert what was *not* sent, which is
    where the fail-closed behaviour actually lives.
    """

    def __init__(
        self,
        *,
        contacts: list[dict[str, Any]] | None = None,
        clicks: list[dict[str, Any]] | None = None,
        recorded: dict[str, str] | None = None,
        schema: list[dict[str, Any]] | None = None,
        d1_error: str | None = None,
        legacy_d1: bool = False,
    ) -> None:
        self.contacts = contacts or []
        self.clicks = clicks or []
        self.recorded = recorded or {}
        # A contact cannot hold a property the portal has never defined, so a
        # portal whose contacts carry click ids defines the click-id property.
        # The read side filters on it, and HubSpot 400s a filter naming a
        # property it does not know.
        self.schema = (
            schema
            if schema is not None
            else [
                {
                    "name": attribution.DEFAULT_CLICK_ID_PROPERTIES[0],
                    "type": "string",
                    "fieldType": "text",
                }
            ]
        )
        self.d1_error = d1_error
        self.legacy_d1 = legacy_d1
        self.calls: list[tuple[str, Any]] = []
        self.created_properties: list[dict[str, Any]] = []
        self.d1_statements: list[str] = []

    def __call__(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        payload: Any = None,
        **_: Any,
    ) -> Any:
        self.calls.append((url, payload))

        if "/d1/database/" in url:
            return self._d1(payload)
        if url.endswith("/contacts/search"):
            return self._search(payload)
        if url.endswith("/contacts/batch/read"):
            return self._batch_read(payload)
        if url.endswith("/properties/contacts"):
            if method == "POST":
                self.created_properties.append(payload)
                return {"name": payload["name"]}
            return {"results": self.schema}
        if "/properties/contacts/groups" in url:
            return None if method == "GET" else {}
        raise AssertionError(f"unexpected request to {url}")

    def _d1(self, payload: Any) -> Any:
        sql = payload["sql"]
        self.d1_statements.append(sql)
        if self.d1_error and "bot" in sql:
            return {"success": False, "errors": [{"message": self.d1_error}]}
        wanted = set(payload["params"])
        rows = []
        for row in self.clicks:
            if row["click_id"] not in wanted:
                continue
            if self.legacy_d1:
                row = {k: v for k, v in row.items() if k not in {"bot", "bot_reason"}}
            rows.append(row)
        return {"success": True, "result": [{"results": rows}]}

    def _search(self, payload: Any) -> Any:
        groups = payload["filterGroups"]
        wanted = {group["filters"][0]["propertyName"] for group in groups}
        after = int(groups[0]["filters"][1]["value"])
        limit = payload["limit"]

        matching = [
            found
            for found in self.contacts
            if int(found["id"]) > after
            and any(name in found["properties"] for name in wanted)
        ]
        matching.sort(key=lambda found: int(found["id"]))
        return {"results": matching[:limit]}

    def _batch_read(self, payload: Any) -> Any:
        ids = [item["id"] for item in payload["inputs"]]
        prop = payload["properties"][0]
        return {
            "results": [
                {"id": found, "properties": {prop: self.recorded[found]}}
                for found in ids
                if found in self.recorded
            ]
        }


class Harness:
    """Run `sync` against a FakeApi with the batch writer captured."""

    def __init__(self, api: FakeApi) -> None:
        self.api = api
        self.writes: list[list[dict[str, Any]]] = []

    def run(self, **overrides: Any) -> dict[str, Any]:
        original_http = attribution._http_json
        original_write = attribution._batch_write
        attribution._http_json = self.api
        attribution._batch_write = lambda token, action, inputs: self.writes.append(
            list(inputs)
        )
        try:
            arguments = {
                "account_id": "acct",
                "api_token": "cf-token",
                "database_id": "db",
                "hubspot_access_token": "hs-token",
                "click_id_properties": attribution.DEFAULT_CLICK_ID_PROPERTIES,
            }
            arguments.update(overrides)
            return attribution.sync(**arguments)
        finally:
            attribution._http_json = original_http
            attribution._batch_write = original_write

    @property
    def written(self) -> list[dict[str, Any]]:
        return [item for batch in self.writes for item in batch]


class ClickIdValidationTests(unittest.TestCase):
    def test_a_worker_minted_uuid_is_accepted_and_lowercased(self) -> None:
        self.assertEqual(
            attribution.valid_click_id("  11111111-2222-3333-4444-555555555555 "),
            CLICK_A,
        )
        self.assertEqual(
            attribution.valid_click_id(CLICK_A.upper()),
            CLICK_A,
        )

    def test_anything_that_is_not_a_click_id_is_refused(self) -> None:
        # The attribute is filled by a script in a browser, so the CRM can hold
        # whatever a shopper managed to put in the form.
        for value in (
            None,
            "",
            "   ",
            "instagram",
            "1' OR '1'='1",
            CLICK_A[:-1],
            CLICK_A + "0",
            ["a"],
            {"a": 1},
            True,
        ):
            self.assertIsNone(attribution.valid_click_id(value), repr(value))


class ContactClickIdTests(unittest.TestCase):
    def test_the_first_populated_candidate_property_is_used(self) -> None:
        found = contact("1", easystore_attr_clickid=CLICK_B)
        self.assertEqual(
            attribution.click_id_of(found, ("easystore_attr_click_id", "easystore_attr_clickid")),
            (CLICK_B, False),
        )

    def test_an_untagged_contact_is_not_a_fault(self) -> None:
        self.assertEqual(
            attribution.click_id_of(contact("1"), ("easystore_attr_click_id",)),
            (None, False),
        )
        self.assertEqual(
            attribution.click_id_of({"id": "1"}, ("easystore_attr_click_id",)),
            (None, False),
        )

    def test_a_populated_but_unusable_value_is_reported_as_one(self) -> None:
        found = contact("1", easystore_attr_click_id="Instagram")
        self.assertEqual(
            attribution.click_id_of(found, ("easystore_attr_click_id",)),
            (None, True),
        )

    def test_a_blank_value_does_not_mask_the_next_candidate(self) -> None:
        found = contact(
            "1",
            easystore_attr_click_id="  ",
            easystore_attr_clickid=CLICK_A,
        )
        self.assertEqual(
            attribution.click_id_of(
                found,
                ("easystore_attr_click_id", "easystore_attr_clickid"),
            ),
            (CLICK_A, False),
        )


class ContactPagingTests(unittest.TestCase):
    def test_every_page_is_walked_by_contact_id(self) -> None:
        api = FakeApi(
            contacts=[
                contact(str(number), easystore_attr_click_id=CLICK_A)
                for number in range(1, 251)
            ]
        )
        original = attribution._http_json
        attribution._http_json = api
        try:
            found = list(
                attribution.iter_hubspot_contacts(
                    "token",
                    ("easystore_attr_click_id",),
                )
            )
        finally:
            attribution._http_json = original

        # HubSpot's search cannot page past 10,000 records with a cursor, so the
        # contact id is the cursor and every page must advance it.
        self.assertEqual(len(found), 250)
        self.assertEqual([item["id"] for item in found[:3]], ["1", "2", "3"])
        cursors = [
            payload["filterGroups"][0]["filters"][1]["value"]
            for _, payload in api.calls
        ]
        self.assertEqual(cursors, ["0", "100", "200"])

    def test_a_page_that_cannot_advance_the_cursor_stops(self) -> None:
        api = FakeApi()
        api._search = lambda payload: {"results": [{"properties": {}}] * 100}
        original = attribution._http_json
        attribution._http_json = api
        try:
            found = list(
                attribution.iter_hubspot_contacts("token", ("easystore_attr_click_id",))
            )
        finally:
            attribution._http_json = original

        self.assertEqual(found, [])
        self.assertEqual(len(api.calls), 1)

    def test_more_candidate_properties_than_hubspot_allows_is_refused(self) -> None:
        # HubSpot's search takes five filter groups. Six would come back as an
        # opaque 400 mid-run, after the stage had already reported progress.
        with self.assertRaises(attribution.SyncError):
            list(
                attribution.iter_hubspot_contacts(
                    "token",
                    tuple(f"prop_{number}" for number in range(6)),
                )
            )
        with self.assertRaises(attribution.SyncError):
            list(attribution.iter_hubspot_contacts("token", ()))

    def test_an_empty_portal_costs_one_request(self) -> None:
        api = FakeApi()
        original = attribution._http_json
        attribution._http_json = api
        try:
            self.assertEqual(
                list(
                    attribution.iter_hubspot_contacts(
                        "token",
                        ("easystore_attr_click_id",),
                    )
                ),
                [],
            )
        finally:
            attribution._http_json = original
        self.assertEqual(len(api.calls), 1)


class D1ReadTests(unittest.TestCase):
    def test_a_failed_query_is_an_error_rather_than_an_empty_result(self) -> None:
        api = FakeApi(d1_error="D1_ERROR: table is locked")
        original = attribution._http_json
        attribution._http_json = api
        try:
            with self.assertRaises(attribution.SyncError) as raised:
                attribution.fetch_clicks(
                    account_id="acct",
                    api_token="token",
                    database_id="db",
                    click_ids=[CLICK_A],
                    summary={},
                )
        finally:
            attribution._http_json = original
        self.assertIn("table is locked", str(raised.exception))

    def test_a_database_without_the_bot_migration_still_joins(self) -> None:
        api = FakeApi(
            clicks=[click_row(CLICK_A)],
            d1_error="no such column: bot",
            legacy_d1=True,
        )
        summary: dict[str, Any] = {}
        original = attribution._http_json
        attribution._http_json = api
        try:
            found = attribution.fetch_clicks(
                account_id="acct",
                api_token="token",
                database_id="db",
                click_ids=[CLICK_A],
                summary=summary,
            )
        finally:
            attribution._http_json = original

        self.assertIn(CLICK_A, found)
        self.assertIs(summary["d1_bot_columns_missing"], True)
        self.assertEqual(summary["d1_queries"], 1)
        self.assertNotIn("bot", api.d1_statements[-1])

    def test_click_ids_are_read_in_batches_rather_than_one_query_each(self) -> None:
        clicks = [
            click_row(f"{number:08d}-0000-0000-0000-000000000000")
            for number in range(200)
        ]
        api = FakeApi(clicks=clicks)
        summary: dict[str, Any] = {}
        original = attribution._http_json
        attribution._http_json = api
        try:
            found = attribution.fetch_clicks(
                account_id="acct",
                api_token="token",
                database_id="db",
                click_ids=[row["click_id"] for row in clicks],
                summary=summary,
            )
        finally:
            attribution._http_json = original

        self.assertEqual(len(found), 200)
        self.assertEqual(summary["d1_queries"], 3)


class AttributionValueTests(unittest.TestCase):
    def test_a_click_row_becomes_the_values_hubspot_stores(self) -> None:
        values = attribution.attribution_values(click_row(CLICK_A))
        self.assertEqual(values["source"], "carousell")
        self.assertEqual(values["medium"], "marketplace")
        self.assertEqual(values["campaign"], "always-on")
        self.assertEqual(values["path"], "/go/ca")
        self.assertEqual(values["country"], "SG")
        # HubSpot datetime properties take epoch milliseconds, which is what the
        # Worker already wrote.
        self.assertEqual(values["clicked_at"], "1750000000000")
        self.assertNotIn("bot_reason", values)

    def test_blank_and_unparseable_facts_are_left_out(self) -> None:
        values = attribution.attribution_values(
            click_row(CLICK_A, country="", clicked_at="not a time", campaign=None)
        )
        self.assertNotIn("country", values)
        self.assertNotIn("clicked_at", values)
        self.assertNotIn("campaign", values)

    def test_an_automated_click_carries_its_reason(self) -> None:
        values = attribution.attribution_values(
            click_row(CLICK_A, bot=1, bot_reason="user-agent")
        )
        self.assertEqual(values["bot_reason"], "user-agent")


class SyncTests(unittest.TestCase):
    def test_a_resolvable_click_is_written_onto_the_contact(self) -> None:
        api = FakeApi(
            contacts=[contact("501", easystore_attr_click_id=CLICK_A)],
            clicks=[click_row(CLICK_A)],
        )
        harness = Harness(api)
        summary = harness.run()

        self.assertEqual(summary["contacts_updated"], 1)
        self.assertEqual(summary["attributed_by_source"], {"carousell": 1})
        self.assertEqual(summary["attributed_by_campaign"], {"always-on": 1})
        self.assertEqual(summary["click_ids_resolved"], 1)
        self.assertEqual(summary["click_ids_not_found_in_d1"], 0)

        written = harness.written
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["id"], "501")
        self.assertEqual(
            written[0]["properties"],
            {
                "cc_acquisition_click_id": CLICK_A,
                "cc_acquisition_source": "carousell",
                "cc_acquisition_medium": "marketplace",
                "cc_acquisition_campaign": "always-on",
                "cc_acquisition_entry_path": "/go/ca",
                "cc_acquisition_country": "SG",
                "cc_acquisition_at": "1750000000000",
            },
        )

    def test_the_properties_are_provisioned_in_their_own_group(self) -> None:
        api = FakeApi(
            contacts=[contact("1", easystore_attr_click_id=CLICK_A)],
            clicks=[click_row(CLICK_A)],
        )
        Harness(api).run()

        groups = {payload["groupName"] for payload in api.created_properties}
        # Filing a Cloudflare fact under "EasyStore Sync" would leave nobody able
        # to tell which system reported it.
        self.assertEqual(groups, {"cloudflare_attribution"})
        self.assertIn(
            "cc_acquisition_click_id",
            {payload["name"] for payload in api.created_properties},
        )

    def test_a_click_id_with_no_d1_row_writes_nothing(self) -> None:
        api = FakeApi(
            contacts=[contact("1", easystore_attr_click_id=CLICK_A)],
            clicks=[],
        )
        harness = Harness(api)
        summary = harness.run()

        self.assertEqual(harness.written, [])
        self.assertEqual(summary["contacts_updated"], 0)
        self.assertEqual(summary["click_ids_not_found_in_d1"], 1)
        # Nor is it read back from HubSpot: on a first run most click ids predate
        # the data, and reading a contact this stage cannot write is a request
        # spent on nothing.
        self.assertEqual(
            [url for url, _ in api.calls if url.endswith("/batch/read")],
            [],
        )

    def test_an_already_attributed_contact_is_not_rewritten(self) -> None:
        api = FakeApi(
            contacts=[contact("1", easystore_attr_click_id=CLICK_A)],
            clicks=[click_row(CLICK_A)],
            recorded={"1": CLICK_A},
            schema=[
                {
                    "name": "cc_acquisition_click_id",
                    "type": "string",
                    "fieldType": "text",
                },
                # The property the contact's click id is read from has to exist
                # too, or the read-side search never runs.
                {
                    "name": attribution.DEFAULT_CLICK_ID_PROPERTIES[0],
                    "type": "string",
                    "fieldType": "text",
                },
            ],
        )
        harness = Harness(api)
        summary = harness.run()

        self.assertEqual(harness.written, [])
        self.assertEqual(summary["contacts_already_attributed"], 1)
        self.assertEqual(summary["contacts_updated"], 0)

    def test_a_second_different_click_never_overwrites_the_acquisition(self) -> None:
        api = FakeApi(
            contacts=[contact("1", easystore_attr_click_id=CLICK_B)],
            clicks=[click_row(CLICK_B, source="facebook")],
            recorded={"1": CLICK_A},
            schema=[
                {
                    "name": "cc_acquisition_click_id",
                    "type": "string",
                    "fieldType": "text",
                },
                # The property the contact's click id is read from has to exist
                # too, or the read-side search never runs.
                {
                    "name": attribution.DEFAULT_CLICK_ID_PROPERTIES[0],
                    "type": "string",
                    "fieldType": "text",
                },
            ],
        )
        harness = Harness(api)
        summary = harness.run()

        # How an account was acquired happened once. Reporting the disagreement
        # is the job; picking a winner is not.
        self.assertEqual(harness.written, [])
        self.assertEqual(summary["contacts_with_conflicting_click_id"], 1)
        self.assertEqual(summary["contacts_updated"], 0)

    def test_an_unusable_stored_value_is_counted_and_never_queried(self) -> None:
        api = FakeApi(
            contacts=[
                contact("1", easystore_attr_click_id="Instagram"),
                contact("2", easystore_attr_click_id=CLICK_A),
            ],
            clicks=[click_row(CLICK_A)],
        )
        harness = Harness(api)
        summary = harness.run()

        self.assertEqual(summary["contacts_with_unusable_click_id"], 1)
        self.assertEqual(summary["contacts_with_click_id"], 1)
        for statement in api.d1_statements:
            self.assertNotIn("Instagram", statement)
        self.assertEqual([item["id"] for item in harness.written], ["2"])

    def test_one_click_shared_by_two_contacts_is_reported_and_applied_to_both(self) -> None:
        api = FakeApi(
            contacts=[
                contact("1", easystore_attr_click_id=CLICK_A),
                contact("2", easystore_attr_click_id=CLICK_A),
            ],
            clicks=[click_row(CLICK_A)],
        )
        harness = Harness(api)
        summary = harness.run()

        # A shared device is not an identity conflict: both accounts really did
        # arrive through that click, and the count says the number is not two
        # independent shoppers.
        self.assertEqual(summary["click_ids_shared_by_multiple_contacts"], 1)
        self.assertEqual(summary["click_ids_unique"], 1)
        self.assertEqual(len(harness.written), 2)

    def test_an_automated_click_is_written_but_flagged(self) -> None:
        api = FakeApi(
            contacts=[contact("1", easystore_attr_click_id=CLICK_A)],
            clicks=[click_row(CLICK_A, bot=1, bot_reason="prefetch")],
        )
        harness = Harness(api)
        summary = harness.run()

        self.assertEqual(summary["contacts_whose_click_was_automated"], 1)
        self.assertEqual(
            harness.written[0]["properties"]["cc_acquisition_automated"],
            "prefetch",
        )

    def test_nothing_to_join_creates_no_properties_and_calls_no_cloudflare(self) -> None:
        api = FakeApi(contacts=[])
        harness = Harness(api)
        summary = harness.run()

        # The expected state until the EasyStore attribute exists. It must not
        # provision CRM properties nor touch Cloudflare on the way to saying so.
        self.assertEqual(summary["contacts_with_click_id"], 0)
        self.assertIn("note", summary)
        self.assertEqual(api.created_properties, [])
        self.assertEqual(api.d1_statements, [])
        self.assertEqual(harness.written, [])

    def test_a_portal_that_cannot_store_the_click_id_stops_the_stage(self) -> None:
        api = FakeApi(
            contacts=[contact("1", easystore_attr_click_id=CLICK_A)],
            clicks=[click_row(CLICK_A)],
        )
        # A portal that refuses to create the identity property would let every
        # rerun rewrite the same contacts and lose the acquisition guarantee.
        original_resolve = attribution.resolve_fields
        attribution.resolve_fields = lambda **kwargs: {"source": "cc_acquisition_source"}
        try:
            with self.assertRaises(attribution.SyncError) as raised:
                Harness(api).run()
        finally:
            attribution.resolve_fields = original_resolve
        self.assertIn("acquisition click id", str(raised.exception))


class PortalWithoutClickIdPropertyTests(unittest.TestCase):
    """Production run 32502241646 failed the whole CRM sync on this.

    The click-id property names are a guess at where a storefront put them.
    Filtering on one this portal has never defined fails the search with an
    HTTP 400 that reads like an outage, and because this stage runs before
    Orders and Carts it took everything after it down too.
    """

    def test_a_portal_without_the_property_never_searches_and_does_not_fail(self) -> None:
        api = FakeApi(
            contacts=[contact("1", easystore_attr_click_id=CLICK_A)],
            clicks=[click_row(CLICK_A)],
            schema=[{"name": "email", "type": "string", "fieldType": "text"}],
        )
        summary = Harness(api).run()

        self.assertEqual(summary["click_id_properties_read"], [])
        self.assertIn("no click id property", summary["attribution_status"])
        self.assertEqual(summary["contacts_with_click_id"], 0)
        searches = [url for url, _ in api.calls if url.endswith("/contacts/search")]
        self.assertEqual(searches, [])
        self.assertEqual(api.created_properties, [])
        self.assertEqual(api.d1_statements, [])

    def test_only_the_properties_the_portal_has_are_filtered_on(self) -> None:
        present, absent = attribution.DEFAULT_CLICK_ID_PROPERTIES[:2]
        api = FakeApi(
            contacts=[contact("1", **{present: CLICK_A})],
            clicks=[click_row(CLICK_A)],
            schema=[{"name": present, "type": "string", "fieldType": "text"}],
        )
        summary = Harness(api).run()

        self.assertEqual(summary["click_id_properties_requested"], [present, absent])
        self.assertEqual(summary["click_id_properties_read"], [present])
        self.assertEqual(summary["contacts_with_click_id"], 1)

    def test_a_token_that_cannot_read_the_schema_still_tries(self) -> None:
        # Without the schema the names cannot be checked, and refusing to read
        # would silently stop attributing for a portal that is working fine.
        api = FakeApi(
            contacts=[contact("1", easystore_attr_click_id=CLICK_A)],
            clicks=[click_row(CLICK_A)],
        )
        with mock.patch.object(attribution, "property_schema", return_value=None):
            summary = Harness(api).run()

        self.assertEqual(
            summary["click_id_properties_read"],
            list(attribution.DEFAULT_CLICK_ID_PROPERTIES),
        )
        self.assertEqual(summary["contacts_with_click_id"], 1)


class ConfigurationTests(unittest.TestCase):
    def test_the_default_click_id_property_matches_the_contact_sync_naming(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import easystore_hubspot_sync as customers

        # The Contact sync derives the property name from the EasyStore attribute
        # label, so the default here has to be what an attribute titled
        # "Click ID" actually produces.
        self.assertEqual(
            customers.attribute_property_name("Click ID"),
            attribution.DEFAULT_CLICK_ID_PROPERTIES[0],
        )

    def test_the_d1_database_id_matches_the_worker_configuration(self) -> None:
        config = (
            ROOT / "cloudflare" / "attribution-worker" / "wrangler.jsonc"
        ).read_text(encoding="utf-8")
        # JSONC: the Worker config carries comments, and only the binding matters.
        without_comments = re.sub(r"^\s*//.*$", "", config, flags=re.MULTILINE)
        bindings = json.loads(without_comments)["d1_databases"]

        self.assertEqual(
            [binding["database_id"] for binding in bindings],
            [attribution.D1_DATABASE_ID],
        )
        self.assertEqual(
            [binding["database_name"] for binding in bindings],
            ["cc-attribution"],
        )

    def test_the_columns_read_are_the_columns_the_migrations_create(self) -> None:
        migrations = sorted(
            (ROOT / "cloudflare" / "attribution-worker" / "migrations").glob("*.sql")
        )
        schema = "\n".join(path.read_text(encoding="utf-8") for path in migrations)

        for column in attribution.CLICK_COLUMNS:
            self.assertIn(column, schema, column)

    def test_property_names_can_be_overridden_for_a_differently_named_attribute(
        self,
    ) -> None:
        self.assertEqual(
            attribution._click_id_properties("easystore_attr_setting_7"),
            ("easystore_attr_setting_7",),
        )
        self.assertEqual(
            attribution._click_id_properties("  "),
            attribution.DEFAULT_CLICK_ID_PROPERTIES,
        )

    def test_a_missing_credential_is_named_rather_than_guessed(self) -> None:
        with self.assertRaises(attribution.SyncError) as raised:
            attribution._required("  ", "CLOUDFLARE_ACCOUNT_ID")
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
