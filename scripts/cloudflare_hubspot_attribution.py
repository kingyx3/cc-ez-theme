#!/usr/bin/env python3
"""Attribute HubSpot Contacts from Cloudflare customer touch history.

Click UUIDs are transport keys inside Cloudflare only. They are not copied through
an EasyStore customer attribute and are not stored on HubSpot Contacts.

The storefront binds each tracked click to the logged-in EasyStore ``customer.id``
in append-only D1 ``customer_touches`` history. The Customer sync separately writes
the immutable EasyStore customer ID and source creation timestamp to HubSpot. This
stage joins those two trusted facts and chooses the latest human tracked click that
happened before account creation and inside the configured attribution window.

A Contact acquisition is immutable once a real acquisition snapshot exists. A
Contact with no eligible touch may carry ``no_recent_tracked_touch`` and can be
upgraded on a later run if the browser binds the pre-signup touch after registration.

Only Python's standard library is used so the scheduled workflow has no runtime
package dependency.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Iterator
from urllib.parse import urlencode

from easystore_hubspot_schema import (
    FieldSpec,
    describe_mapping,
    nonempty,
    property_schema,
    resolve_fields,
)
from easystore_hubspot_sync import SyncError, _batch_write, _http_json


CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4"
HUBSPOT_CONTACTS_URL = "https://api.hubapi.com/crm/v3/objects/contacts"
CONTACT_OBJECT_TYPE = "contacts"
D1_DATABASE_ID = "f7377a40-379a-4713-9126-e05636162c84"
D1_BATCH_SIZE = 80
HUBSPOT_PAGE_SIZE = 100
DEFAULT_WINDOW_DAYS = 30
MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000
SINGAPORE_TZ = timezone(timedelta(hours=8))

CUSTOMER_ID_PROPERTY = "easystore_customer_id"
CUSTOMER_CREATED_AT_PROPERTY = "easystore_customer_created_at"

PROPERTY_GROUP = "cloudflare_attribution"
PROPERTY_GROUP_LABEL = "Cloudflare Attribution"

FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="source",
        fallback="cc_acquisition_source",
        label="Acquisition source",
        description="Latest tracked marketing source before this EasyStore account was created.",
    ),
    FieldSpec(
        key="medium",
        fallback="cc_acquisition_medium",
        label="Acquisition medium",
        description="Latest tracked marketing medium before this EasyStore account was created.",
    ),
    FieldSpec(
        key="campaign",
        fallback="cc_acquisition_campaign",
        label="Acquisition campaign",
        description="Campaign on the tracked touch that led into account creation.",
    ),
    FieldSpec(
        key="content",
        fallback="cc_acquisition_content",
        label="Acquisition content",
        description="Post, ad or message label on the tracked touch that led into account creation.",
    ),
    FieldSpec(
        key="path",
        fallback="cc_acquisition_entry_path",
        label="Acquisition entry path",
        description="Tracking path used by the selected acquisition touch.",
    ),
    FieldSpec(
        key="country",
        fallback="cc_acquisition_country",
        label="Acquisition country",
        description="Country Cloudflare reported for the selected acquisition touch.",
    ),
    FieldSpec(
        key="clicked_at",
        fallback="cc_acquisition_at",
        label="Acquisition touch time",
        description="When the selected acquisition marketing touch happened.",
        kind="datetime",
    ),
    FieldSpec(
        key="model",
        fallback="cc_acquisition_attribution_model",
        label="Acquisition attribution model",
        description="Attribution rule used to select the Contact acquisition touch.",
    ),
    FieldSpec(
        key="window_days",
        fallback="cc_acquisition_attribution_window_days",
        label="Acquisition attribution window (days)",
        description="Maximum age of an eligible tracked touch before account creation.",
        kind="number",
    ),
    FieldSpec(
        key="status",
        fallback="cc_acquisition_status",
        label="Acquisition attribution status",
        description="Whether a qualifying tracked marketing touch was found for this Contact.",
    ),
)

LOCK_KEYS = ("source", "medium", "campaign", "content", "path", "country", "clicked_at")


def epoch_millis(value: Any) -> int | None:
    """Return a HubSpot/EasyStore timestamp as epoch milliseconds."""

    text = str(value or "").strip()
    if not text:
        return None

    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None:
        return int(number * 1000) if abs(number) < 100_000_000_000 else int(number)

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SINGAPORE_TZ)
    return int(parsed.timestamp() * 1000)


def chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def d1_query(
    *,
    account_id: str,
    api_token: str,
    database_id: str,
    sql: str,
    params: list[Any],
) -> list[dict[str, Any]]:
    document = _http_json(
        f"{CLOUDFLARE_BASE_URL}/accounts/{account_id}/d1/database/{database_id}/query",
        method="POST",
        headers={"Authorization": f"Bearer {api_token}"},
        payload={"sql": sql, "params": params},
    )
    if not isinstance(document, dict) or not document.get("success", False):
        detail = json.dumps(document.get("errors") if isinstance(document, dict) else document)
        raise SyncError(f"Cloudflare D1 acquisition query failed: {detail[:1000]}")

    rows: list[dict[str, Any]] = []
    for result in document.get("result") or []:
        if not isinstance(result, dict):
            continue
        for row in result.get("results") or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def fetch_customer_touches(
    *,
    account_id: str,
    api_token: str,
    database_id: str,
    customer_ids: list[str],
    earliest_signup_at: int,
    latest_signup_at: int,
    window_days: int,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Fetch human click history for candidate customers in bounded D1 batches.

    ``bound_at`` is deliberately not required to precede account creation. A new
    account may bind its already-existing browser touch on the first authenticated
    page after registration. The click itself must still precede account creation.
    """

    by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    lower = earliest_signup_at - window_days * MILLISECONDS_PER_DAY
    queries = 0

    for batch in chunked(sorted(set(customer_ids)), D1_BATCH_SIZE):
        placeholders = ", ".join("?" for _ in batch)
        rows = d1_query(
            account_id=account_id,
            api_token=api_token,
            database_id=database_id,
            sql=f"""
              SELECT
                ct.customer_id,
                ct.bound_at,
                sc.source,
                sc.medium,
                sc.campaign,
                sc.content,
                sc.path,
                sc.country,
                sc.clicked_at
              FROM customer_touches AS ct
              JOIN source_clicks AS sc ON sc.click_id = ct.click_id
              WHERE ct.customer_id IN ({placeholders})
                AND sc.clicked_at >= ?
                AND sc.clicked_at <= ?
                AND COALESCE(sc.bot, 0) = 0
              ORDER BY ct.customer_id, sc.clicked_at, ct.bound_at
            """,
            params=[*batch, lower, latest_signup_at],
        )
        queries += 1
        for row in rows:
            customer_id = nonempty(row.get("customer_id"))
            if customer_id is not None:
                by_customer[customer_id].append(row)

    return dict(by_customer), queries


def latest_touch_before_signup(
    touches: list[dict[str, Any]],
    *,
    signup_at: int,
    window_days: int,
) -> dict[str, Any] | None:
    lower = signup_at - window_days * MILLISECONDS_PER_DAY
    eligible: list[dict[str, Any]] = []
    for touch in touches:
        try:
            clicked_at = int(touch.get("clicked_at"))
            bound_at = int(touch.get("bound_at"))
        except (TypeError, ValueError):
            continue
        if lower <= clicked_at <= signup_at:
            eligible.append(touch)
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda touch: (int(touch["clicked_at"]), int(touch.get("bound_at") or 0)),
    )


def iter_hubspot_contacts(
    access_token: str,
    properties: tuple[str, ...],
) -> Iterator[dict[str, Any]]:
    after: str | None = None
    requested = ",".join(dict.fromkeys(properties))
    headers = {"Authorization": f"Bearer {access_token}"}

    while True:
        params = {
            "limit": str(HUBSPOT_PAGE_SIZE),
            "properties": requested,
            "archived": "false",
        }
        if after is not None:
            params["after"] = after
        document = _http_json(
            f"{HUBSPOT_CONTACTS_URL}?{urlencode(params)}",
            headers=headers,
        )
        results = document.get("results") if isinstance(document, dict) else None
        for contact in results or []:
            if isinstance(contact, dict):
                yield contact

        paging = document.get("paging") if isinstance(document, dict) else None
        next_page = paging.get("next") if isinstance(paging, dict) else None
        next_after = next_page.get("after") if isinstance(next_page, dict) else None
        if next_after is None:
            return
        after = str(next_after)


def acquisition_locked(
    properties: dict[str, Any],
    field_properties: dict[str, str],
) -> bool:
    status_property = field_properties.get("status")
    if status_property and nonempty(properties.get(status_property)) == "attributed":
        return True
    for key in LOCK_KEYS:
        property_name = field_properties.get(key)
        if property_name and nonempty(properties.get(property_name)) is not None:
            return True
    return False


def acquisition_values(
    touch: dict[str, Any] | None,
    *,
    window_days: int,
) -> dict[str, str]:
    values = {
        "model": "last_tracked_touch_before_signup",
        "window_days": str(window_days),
        "status": "attributed" if touch is not None else "no_recent_tracked_touch",
    }
    if touch is None:
        return values

    for key in ("source", "medium", "campaign", "content", "path", "country"):
        value = nonempty(touch.get(key))
        if value is not None:
            values[key] = value
    try:
        values["clicked_at"] = str(int(touch.get("clicked_at")))
    except (TypeError, ValueError):
        pass
    return values


def mapped_properties(
    values: dict[str, str],
    field_properties: dict[str, str],
) -> dict[str, str]:
    return {
        field_properties[key]: value
        for key, value in values.items()
        if key in field_properties
    }


def sync(
    *,
    account_id: str,
    api_token: str,
    database_id: str,
    hubspot_access_token: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    if not 1 <= window_days <= 365:
        raise SyncError("ACQUISITION_ATTRIBUTION_WINDOW_DAYS must be between 1 and 365")

    summary: dict[str, Any] = {
        "attribution_model": "last_tracked_touch_before_signup",
        "attribution_window_days": window_days,
        "d1_database_id": database_id,
        "hubspot_contacts": 0,
        "contacts_missing_easystore_customer_id": 0,
        "contacts_missing_customer_created_at": 0,
        "contacts_with_duplicate_easystore_customer_id": 0,
        "contacts_already_attributed": 0,
        "contacts_with_eligible_touch": 0,
        "contacts_without_recent_tracked_touch": 0,
    }

    schema = property_schema(
        http_json=_http_json,
        access_token=hubspot_access_token,
        object_type=CONTACT_OBJECT_TYPE,
        error=SyncError,
        optional=True,
    )
    if schema is not None:
        missing = [
            name
            for name in (CUSTOMER_ID_PROPERTY, CUSTOMER_CREATED_AT_PROPERTY)
            if name not in schema
        ]
        if missing:
            summary["attribution_status"] = "missing_customer_source_properties"
            summary["missing_hubspot_contact_properties"] = missing
            print(
                "WARNING: Contact acquisition skipped because the Customer sync has "
                "not provisioned: " + ", ".join(missing),
                file=sys.stderr,
            )
            return summary

    schema_report: dict[str, Any] = {}
    field_properties = resolve_fields(
        http_json=_http_json,
        access_token=hubspot_access_token,
        object_type=CONTACT_OBJECT_TYPE,
        fields=FIELDS,
        error=SyncError,
        report=schema_report,
        group=PROPERTY_GROUP,
        group_label=PROPERTY_GROUP_LABEL,
    )
    summary["hubspot_contact_field_properties"] = {
        field.key: field_properties[field.key]
        for field in FIELDS
        if field.key in field_properties
    }
    print(
        "Cloudflare acquisition fields mapped to HubSpot properties: "
        + describe_mapping(summary["hubspot_contact_field_properties"]),
        file=sys.stderr,
    )

    requested = (
        CUSTOMER_ID_PROPERTY,
        CUSTOMER_CREATED_AT_PROPERTY,
        *tuple(field_properties.values()),
    )
    candidates: list[dict[str, Any]] = []
    owners: dict[str, list[str]] = defaultdict(list)

    for contact in iter_hubspot_contacts(hubspot_access_token, requested):
        summary["hubspot_contacts"] += 1
        contact_id = nonempty(contact.get("id"))
        properties = contact.get("properties")
        if contact_id is None or not isinstance(properties, dict):
            continue

        customer_id = nonempty(properties.get(CUSTOMER_ID_PROPERTY))
        if customer_id is None:
            summary["contacts_missing_easystore_customer_id"] += 1
            continue
        owners[customer_id].append(contact_id)

        signup_at = epoch_millis(properties.get(CUSTOMER_CREATED_AT_PROPERTY))
        if signup_at is None:
            summary["contacts_missing_customer_created_at"] += 1
            continue
        if acquisition_locked(properties, field_properties):
            summary["contacts_already_attributed"] += 1
            continue
        candidates.append(
            {
                "contact_id": contact_id,
                "customer_id": customer_id,
                "signup_at": signup_at,
                "properties": properties,
            }
        )

    duplicate_customer_ids = {
        customer_id for customer_id, contact_ids in owners.items() if len(set(contact_ids)) > 1
    }
    if duplicate_customer_ids:
        summary["contacts_with_duplicate_easystore_customer_id"] = sum(
            len(set(owners[customer_id])) for customer_id in duplicate_customer_ids
        )
        candidates = [
            candidate
            for candidate in candidates
            if candidate["customer_id"] not in duplicate_customer_ids
        ]

    touches_by_customer: dict[str, list[dict[str, Any]]] = {}
    d1_queries = 0
    if candidates:
        signup_times = [int(candidate["signup_at"]) for candidate in candidates]
        touches_by_customer, d1_queries = fetch_customer_touches(
            account_id=account_id,
            api_token=api_token,
            database_id=database_id,
            customer_ids=[str(candidate["customer_id"]) for candidate in candidates],
            earliest_signup_at=min(signup_times),
            latest_signup_at=max(signup_times),
            window_days=window_days,
        )
    summary["d1_queries"] = d1_queries
    summary["customers_with_touch_history"] = len(touches_by_customer)

    updates: list[dict[str, Any]] = []
    by_source: Counter[str] = Counter()
    by_campaign: Counter[str] = Counter()

    for candidate in candidates:
        touch = latest_touch_before_signup(
            touches_by_customer.get(str(candidate["customer_id"]), []),
            signup_at=int(candidate["signup_at"]),
            window_days=window_days,
        )
        if touch is None:
            summary["contacts_without_recent_tracked_touch"] += 1
        else:
            summary["contacts_with_eligible_touch"] += 1
            by_source[nonempty(touch.get("source")) or "unknown"] += 1
            by_campaign[nonempty(touch.get("campaign")) or "unknown"] += 1

        desired = mapped_properties(
            acquisition_values(touch, window_days=window_days),
            field_properties,
        )
        existing = candidate["properties"]
        changed = {
            key: value
            for key, value in desired.items()
            if str(existing.get(key) or "") != str(value)
        }
        if changed:
            updates.append({"id": candidate["contact_id"], "properties": changed})

    _batch_write(hubspot_access_token, "update", updates)
    summary["contacts_updated"] = len(updates)
    summary["attributed_by_source"] = dict(by_source.most_common())
    summary["attributed_by_campaign"] = dict(by_campaign.most_common())
    summary["attribution_status"] = "complete"
    if schema_report.get("hints"):
        summary["hubspot_contact_property_hints"] = schema_report["hints"]
    return summary


def _required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise SyncError(f"{name} is required")


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
        "--window-days",
        type=int,
        default=int(os.getenv("ACQUISITION_ATTRIBUTION_WINDOW_DAYS") or DEFAULT_WINDOW_DAYS),
    )
    args = parser.parse_args(argv)

    try:
        summary = sync(
            account_id=_required(args.account_id, "CLOUDFLARE_ACCOUNT_ID"),
            api_token=_required(args.api_token, "CLOUDFLARE_API_TOKEN"),
            database_id=_required(args.database_id, "CLOUDFLARE_D1_DATABASE_ID"),
            hubspot_access_token=_required(args.hubspot_token, "HUBSPOT_ACCESS_TOKEN"),
            window_days=args.window_days,
        )
    except (SyncError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
