#!/usr/bin/env python3
"""Join Cloudflare source clicks to HubSpot contacts.

The `cc-attribution` Worker records one D1 row per tracked /go/* entry and hands
the browser the click id it minted. `theme/snippets/attribution-click-id.liquid`
writes that id into an EasyStore customer attribute during sign-up, and the
Contact sync copies the attribute to HubSpot as ``easystore_attr_click_id``.

This stage closes the loop: it reads the click ids HubSpot already holds, resolves
them against D1, and writes the channel that produced each account onto the
contact. It is the only part of the chain that knows both halves, and it is
deliberately the only part that has to know the Cloudflare account.

What it will not do:

* **Invent a match.** A click id with no D1 row writes nothing and is counted.
* **Trust a shopper-supplied value.** The Worker mints a UUID; anything that is
  not one never reaches a query, because the attribute is filled by a script
  running in a browser and a browser is not a trusted source.
* **Overwrite an acquisition.** How an account was acquired is a fact about a
  moment that has passed. A contact already carrying a different click id is
  reported as a conflict and left exactly as it is.
* **Write HubSpot's own analytics properties.** ``hs_analytics_source`` and its
  relatives belong to HubSpot's tracking code, are enumerated against HubSpot's
  own channel list, and are not this integration's to define. Cloudflare facts
  live in their own property group, so a CRM user can tell which system said so.

The Worker flags link-preview crawlers and browser prefetches rather than
dropping them, and that flag travels here too: a contact whose acquisition click
was automated is still written, with the reason, because a human sign-up behind a
prefetched link is real and the flag is what makes it reviewable.

Only Python's standard library is used, so the scheduled workflow has no runtime
package dependency.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Iterator

from easystore_hubspot_schema import FieldSpec, describe_mapping, resolve_fields
from easystore_hubspot_sync import (
    SyncError,
    _batch_write,
    _http_json,
    chunked,
)


CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4"
HUBSPOT_CONTACTS_URL = "https://api.hubapi.com/crm/v3/objects/contacts"
CONTACT_OBJECT_TYPE = "contacts"

# The D1 database that `cloudflare/attribution-worker/wrangler.jsonc` binds. It
# is a resource identifier rather than a credential, which is why the Worker
# config commits it too; `crm_tests/test_cloudflare_attribution.py` pins the two
# copies together so a database replaced in one place cannot be missed here.
D1_DATABASE_ID = "f7377a40-379a-4713-9126-e05636162c84"
D1_TABLE = "source_clicks"

# Cloudflare facts get their own group. Reusing `easystore_sync` would file a
# click channel under the storefront's name and leave nobody able to tell where
# the value came from.
PROPERTY_GROUP = "cloudflare_attribution"
PROPERTY_GROUP_LABEL = "Cloudflare Attribution"

# The HubSpot contact property the click id arrives in. The Contact sync names an
# attribute property after its EasyStore label, so an attribute titled "Click ID"
# lands in `easystore_attr_click_id`. A store whose attribute-setting titles were
# not reachable syncs answers under the setting id instead, so that shape is
# accepted as well and the first property a contact actually carries is used.
DEFAULT_CLICK_ID_PROPERTIES = ("easystore_attr_click_id", "easystore_attr_clickid")

CLICK_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

HUBSPOT_PAGE_SIZE = 100
# HubSpot's search takes at most five filter groups, and reading "any of these
# properties" needs one group each.
MAX_CLICK_ID_PROPERTIES = 5
# One D1 statement per batch of click ids. SQLite would take far more bound
# parameters than this; the limit keeps a single request small enough to retry
# cheaply when Cloudflare throttles.
D1_BATCH_SIZE = 90

CLICK_ID_FIELD = "click_id"

FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key=CLICK_ID_FIELD,
        fallback="cc_acquisition_click_id",
        label="Acquisition click ID",
        description=(
            "The Cloudflare click this account was created under. Written once "
            "and never changed."
        ),
    ),
    FieldSpec(
        key="source",
        fallback="cc_acquisition_source",
        label="Acquisition source",
        description="The channel of the tracked click that produced this account.",
    ),
    FieldSpec(
        key="medium",
        fallback="cc_acquisition_medium",
        label="Acquisition medium",
        description="The medium of the tracked click that produced this account.",
    ),
    FieldSpec(
        key="campaign",
        fallback="cc_acquisition_campaign",
        label="Acquisition campaign",
        description="The campaign label carried by the tracked click.",
    ),
    FieldSpec(
        key="path",
        fallback="cc_acquisition_entry_path",
        label="Acquisition entry path",
        description="The /go/* entry URL the shopper arrived through.",
    ),
    FieldSpec(
        key="country",
        fallback="cc_acquisition_country",
        label="Acquisition country",
        description="The country Cloudflare reported for the tracked click.",
    ),
    FieldSpec(
        key="clicked_at",
        fallback="cc_acquisition_at",
        label="Acquisition click time",
        description="When the tracked click happened.",
        kind="datetime",
    ),
    FieldSpec(
        key="bot_reason",
        fallback="cc_acquisition_automated",
        label="Acquisition click flagged automated",
        description=(
            "Why the tracked click looked automated - a link-preview crawler or "
            "a browser prefetch - or blank for an ordinary click."
        ),
    ),
)

# The columns the join reads, and the legacy set for a database whose bot
# migration has not been applied yet.
CLICK_COLUMNS = (
    "click_id",
    "source",
    "medium",
    "campaign",
    "path",
    "country",
    "clicked_at",
    "bot",
    "bot_reason",
)
LEGACY_CLICK_COLUMNS = CLICK_COLUMNS[:-2]


def valid_click_id(value: Any) -> str | None:
    """Return a click id in the shape the Worker mints, or ``None``.

    The value reached HubSpot from a form field filled in by a browser, so it is
    shopper-reachable input. Only the Worker's own UUID shape is accepted, and it
    is normalized to lower case because that is how ``crypto.randomUUID`` writes
    one and therefore how D1 stores it.
    """

    if value is None or isinstance(value, (list, tuple, set, dict, bool)):
        return None
    text = str(value).strip().lower()
    return text if CLICK_ID_PATTERN.fullmatch(text) else None


def click_id_of(
    contact: dict[str, Any],
    candidates: tuple[str, ...],
) -> tuple[str | None, bool]:
    """Return a contact's click id and whether it carried an unusable value.

    The second element separates "this contact was never tagged" from "this
    contact carries something that is not a click id", because the first is the
    normal state of a customer who signed up before the chain existed and the
    second is a fault worth counting.
    """

    properties = contact.get("properties")
    if not isinstance(properties, dict):
        return None, False

    for name in candidates:
        raw = properties.get(name)
        if raw is None or not str(raw).strip():
            continue
        click_id = valid_click_id(raw)
        return (click_id, click_id is None)
    return None, False


def iter_hubspot_contacts(
    access_token: str,
    properties: tuple[str, ...],
) -> Iterator[dict[str, Any]]:
    """Yield every contact carrying one of the click-id properties.

    HubSpot's search paging stops at 10,000 records however it is walked, so the
    cursor here is the contact id itself: each page asks for the next ids above
    the last one seen, in ascending order, which has no ceiling. Filtering in
    HubSpot rather than locally also means a portal full of contacts that predate
    this chain costs one empty page instead of a full scan.
    """

    if not properties:
        raise SyncError("No HubSpot contact property was named to read click ids from")
    if len(properties) > MAX_CLICK_ID_PROPERTIES:
        raise SyncError(
            f"At most {MAX_CLICK_ID_PROPERTIES} click-id properties can be read "
            f"in one run; {len(properties)} were given"
        )

    headers = {"Authorization": f"Bearer {access_token}"}
    requested = tuple(dict.fromkeys(properties + ("hs_object_id",)))
    last_id = "0"

    while True:
        # HubSpot treats groups of filters as OR and filters inside a group as
        # AND, so one group per candidate property is "has any of these", each
        # anded with the id cursor.
        filter_groups = [
            {
                "filters": [
                    {"propertyName": name, "operator": "HAS_PROPERTY"},
                    {
                        "propertyName": "hs_object_id",
                        "operator": "GT",
                        "value": last_id,
                    },
                ]
            }
            for name in properties
        ]
        document = _http_json(
            f"{HUBSPOT_CONTACTS_URL}/search",
            method="POST",
            headers=headers,
            payload={
                "filterGroups": filter_groups,
                "properties": list(requested),
                "sorts": [{"propertyName": "hs_object_id", "direction": "ASCENDING"}],
                "limit": HUBSPOT_PAGE_SIZE,
            },
        )
        results = document.get("results") if isinstance(document, dict) else None
        if not isinstance(results, list) or not results:
            return

        highest = last_id
        for contact in results:
            if not isinstance(contact, dict):
                continue
            contact_id = str(contact.get("id") or "").strip()
            if not contact_id:
                continue
            yield contact
            if _as_int(contact_id) > _as_int(highest):
                highest = contact_id

        if highest == last_id:
            # Nothing sortable came back, so another identical request would ask
            # for the same page forever.
            return
        last_id = highest
        if len(results) < HUBSPOT_PAGE_SIZE:
            return


def _as_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def d1_query(
    *,
    account_id: str,
    api_token: str,
    database_id: str,
    sql: str,
    params: list[str],
) -> list[dict[str, Any]]:
    """Run one read against D1 and return its rows."""

    document = _http_json(
        f"{CLOUDFLARE_BASE_URL}/accounts/{account_id}/d1/database/{database_id}/query",
        method="POST",
        headers={"Authorization": f"Bearer {api_token}"},
        payload={"sql": sql, "params": params},
    )
    if not isinstance(document, dict):
        raise SyncError("Cloudflare D1 returned an invalid response")

    if not document.get("success", False):
        errors = document.get("errors")
        detail = json.dumps(errors, ensure_ascii=False) if errors else "no detail"
        raise SyncError(f"Cloudflare D1 query failed: {detail[:1000]}")

    result = document.get("result")
    if not isinstance(result, list):
        raise SyncError("Cloudflare D1 returned no result set")

    rows: list[dict[str, Any]] = []
    for entry in result:
        if not isinstance(entry, dict):
            continue
        for row in entry.get("results") or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def fetch_clicks(
    *,
    account_id: str,
    api_token: str,
    database_id: str,
    click_ids: list[str],
    summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return the D1 row for each click id that has one, keyed by click id."""

    columns = CLICK_COLUMNS
    found: dict[str, dict[str, Any]] = {}
    queries = 0

    for batch in chunked(click_ids, D1_BATCH_SIZE):
        placeholders = ", ".join("?" for _ in batch)
        while True:
            sql = (
                f"SELECT {', '.join(columns)} FROM {D1_TABLE} "
                f"WHERE click_id IN ({placeholders})"
            )
            try:
                rows = d1_query(
                    account_id=account_id,
                    api_token=api_token,
                    database_id=database_id,
                    sql=sql,
                    params=list(batch),
                )
            except SyncError as error:
                # A database still on migration 0001 has no bot columns. Reading
                # what it does have beats failing the stage over a flag.
                if columns is CLICK_COLUMNS and "no such column" in str(error).lower():
                    columns = LEGACY_CLICK_COLUMNS
                    summary["d1_bot_columns_missing"] = True
                    continue
                raise
            break

        queries += 1
        for row in rows:
            click_id = valid_click_id(row.get("click_id"))
            if click_id is not None:
                found[click_id] = row

    summary["d1_queries"] = queries
    return found


def attribution_values(row: dict[str, Any]) -> dict[str, str]:
    """Return the property values one D1 click row contributes."""

    values: dict[str, str] = {}
    for key in ("click_id", "source", "medium", "campaign", "path", "country"):
        text = str(row.get(key) or "").strip()
        if text:
            values[key] = text

    clicked_at = row.get("clicked_at")
    try:
        # D1 holds epoch milliseconds, which is what a HubSpot datetime wants.
        values["clicked_at"] = str(int(clicked_at))
    except (TypeError, ValueError):
        pass

    reason = str(row.get("bot_reason") or "").strip()
    if reason:
        values["bot_reason"] = reason
    return values


def sync(
    *,
    account_id: str,
    api_token: str,
    database_id: str,
    hubspot_access_token: str,
    click_id_properties: tuple[str, ...],
) -> dict[str, Any]:
    """Write the acquisition channel onto every contact that can be resolved."""

    summary: dict[str, Any] = {
        "click_id_properties_read": list(click_id_properties),
        "d1_database_id": database_id,
        "contacts_with_click_id": 0,
        "contacts_with_unusable_click_id": 0,
    }

    contacts: list[tuple[str, str]] = []
    unusable = 0
    for contact in iter_hubspot_contacts(hubspot_access_token, click_id_properties):
        click_id, malformed = click_id_of(contact, click_id_properties)
        if malformed:
            unusable += 1
            continue
        if click_id is None:
            continue
        contacts.append((str(contact["id"]), click_id))

    summary["contacts_with_click_id"] = len(contacts)
    summary["contacts_with_unusable_click_id"] = unusable

    if not contacts:
        # Nothing to join yet. This is the expected state until the EasyStore
        # customer attribute exists and shoppers have signed up through a tracked
        # link, so no properties are provisioned and no Cloudflare call is made.
        summary["note"] = (
            "No HubSpot contact carries a click id yet, so nothing was joined and "
            "no HubSpot properties were created. Confirm the EasyStore customer "
            "attribute exists and that the Contact sync has run since a shopper "
            "registered through a /go/* link."
        )
        return summary

    owners: dict[str, list[str]] = defaultdict(list)
    for contact_id, click_id in contacts:
        owners[click_id].append(contact_id)
    summary["click_ids_unique"] = len(owners)
    summary["click_ids_shared_by_multiple_contacts"] = sum(
        1 for ids in owners.values() if len(ids) > 1
    )

    clicks = fetch_clicks(
        account_id=account_id,
        api_token=api_token,
        database_id=database_id,
        click_ids=sorted(owners),
        summary=summary,
    )
    summary["click_ids_resolved"] = len(clicks)
    summary["click_ids_not_found_in_d1"] = len(owners) - len(clicks)

    report: dict[str, Any] = {}
    properties = resolve_fields(
        http_json=_http_json,
        access_token=hubspot_access_token,
        object_type=CONTACT_OBJECT_TYPE,
        fields=FIELDS,
        error=SyncError,
        report=report,
        group=PROPERTY_GROUP,
        group_label=PROPERTY_GROUP_LABEL,
    )
    summary["hubspot_contact_field_properties"] = {
        field.key: properties[field.key] for field in FIELDS if field.key in properties
    }
    print(
        "Cloudflare attribution properties: "
        f"{describe_mapping(summary['hubspot_contact_field_properties'])}",
        file=sys.stderr,
    )

    click_id_property = properties.get(CLICK_ID_FIELD)
    if click_id_property is None:
        raise SyncError(
            "HubSpot has nowhere to store the acquisition click id, so a rerun "
            "could not tell an already-attributed contact from a new one."
        )

    # Only the contacts a write could touch. On a first run most click ids have
    # no D1 row, and reading back a contact this stage will not write is a
    # HubSpot request spent on nothing.
    resolvable = [
        contact_id for contact_id, click_id in contacts if click_id in clicks
    ]
    existing = _existing_click_ids(
        hubspot_access_token,
        resolvable,
        click_id_property,
    )

    inputs: list[dict[str, Any]] = []
    already_current = 0
    conflicts = 0
    automated = 0
    by_source: Counter[str] = Counter()
    by_campaign: Counter[str] = Counter()

    for contact_id, click_id in contacts:
        row = clicks.get(click_id)
        if row is None:
            continue

        recorded = valid_click_id(existing.get(contact_id))
        if recorded == click_id:
            already_current += 1
            continue
        if recorded is not None:
            # Acquisition happened once. A second click id on the same contact is
            # a question for a person, not something to overwrite silently.
            conflicts += 1
            continue

        values = attribution_values(row)
        payload = {
            properties[key]: value
            for key, value in values.items()
            if key in properties
        }
        if not payload:
            continue

        inputs.append({"id": contact_id, "properties": payload})
        if values.get("bot_reason"):
            automated += 1
        by_source[values.get("source", "unknown")] += 1
        by_campaign[values.get("campaign", "unknown")] += 1

    _batch_write(hubspot_access_token, "update", inputs)

    summary["contacts_updated"] = len(inputs)
    summary["contacts_already_attributed"] = already_current
    summary["contacts_with_conflicting_click_id"] = conflicts
    summary["contacts_whose_click_was_automated"] = automated
    summary["attributed_by_source"] = dict(by_source.most_common())
    summary["attributed_by_campaign"] = dict(by_campaign.most_common())
    if report.get("hints"):
        summary["hubspot_contact_property_hints"] = report["hints"]
    return summary


def _existing_click_ids(
    access_token: str,
    contact_ids: list[str],
    click_id_property: str,
) -> dict[str, str]:
    """Return the acquisition click id HubSpot already holds per contact."""

    headers = {"Authorization": f"Bearer {access_token}"}
    recorded: dict[str, str] = {}

    for batch in chunked(contact_ids, HUBSPOT_PAGE_SIZE):
        document = _http_json(
            f"{HUBSPOT_CONTACTS_URL}/batch/read",
            method="POST",
            headers=headers,
            payload={
                "properties": [click_id_property],
                "inputs": [{"id": contact_id} for contact_id in batch],
            },
        )
        results = document.get("results") if isinstance(document, dict) else None
        for contact in results or []:
            if not isinstance(contact, dict):
                continue
            contact_id = str(contact.get("id") or "").strip()
            props = contact.get("properties")
            if not contact_id or not isinstance(props, dict):
                continue
            value = str(props.get(click_id_property) or "").strip()
            if value:
                recorded[contact_id] = value
    return recorded


def _required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise SyncError(f"{name} is required")


def _click_id_properties(value: str | None) -> tuple[str, ...]:
    if not value or not value.strip():
        return DEFAULT_CLICK_ID_PROPERTIES
    names = tuple(
        dict.fromkeys(part.strip() for part in value.split(",") if part.strip())
    )
    return names or DEFAULT_CLICK_ID_PROPERTIES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", default=os.getenv("CLOUDFLARE_ACCOUNT_ID"))
    parser.add_argument("--api-token", default=os.getenv("CLOUDFLARE_API_TOKEN"))
    parser.add_argument(
        "--database-id",
        default=os.getenv("CLOUDFLARE_D1_DATABASE_ID", D1_DATABASE_ID),
    )
    parser.add_argument("--hubspot-token", default=os.getenv("HUBSPOT_ACCESS_TOKEN"))
    parser.add_argument(
        "--click-id-properties",
        default=os.getenv("ATTRIBUTION_CLICK_ID_PROPERTIES"),
        help=(
            "Comma separated HubSpot contact properties that may carry the click "
            f"id. Defaults to {', '.join(DEFAULT_CLICK_ID_PROPERTIES)}."
        ),
    )
    args = parser.parse_args(argv)

    try:
        summary = sync(
            account_id=_required(args.account_id, "CLOUDFLARE_ACCOUNT_ID"),
            api_token=_required(args.api_token, "CLOUDFLARE_API_TOKEN"),
            database_id=_required(args.database_id, "CLOUDFLARE_D1_DATABASE_ID"),
            hubspot_access_token=_required(args.hubspot_token, "HUBSPOT_ACCESS_TOKEN"),
            click_id_properties=_click_id_properties(args.click_id_properties),
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
