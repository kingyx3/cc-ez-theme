#!/usr/bin/env python3
"""Sync Cloudflare attribution and native ad click identifiers to HubSpot Contacts.

The Worker UUID remains an internal transport key inside Cloudflare. It is never
copied through EasyStore and is never stored on a HubSpot Contact.

The storefront binds each tracked Worker click to the logged-in EasyStore
``customer.id`` in append-only D1 ``customer_touches`` history. This stage uses
that history for two independent jobs:

* Contact acquisition: choose the latest human tracked touch before account
  creation inside the configured attribution window. Once attributed, this
  marketing snapshot is immutable.
* Advertising identity: choose the latest bound vendor click identifier for each
  supported ad network and copy it into HubSpot's native conversion-compatible
  Contact property when that property is writable. These values are rolling and
  are not locked by the Contact acquisition snapshot.

Google ``gbraid`` and ``wbraid`` are preserved in D1 and forwarded to the
storefront but are not written into ``hs_google_click_id`` because that native
property represents GCLID specifically.

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

# The click-ID destinations intentionally have no custom fallback: a custom
# property cannot substitute for HubSpot's native conversion matching fields.
AD_CLICK_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="google_click_id",
        native=("hs_google_click_id",),
        label="Google Click ID",
        description="Latest bound Google Ads GCLID.",
    ),
    FieldSpec(
        key="facebook_click_id",
        native=("hs_facebook_click_id",),
        label="Facebook Click ID",
        description="Latest bound Meta/Facebook FBCLID.",
    ),
    FieldSpec(
        key="tiktok_click_id",
        native=("hs_tiktok_click_id",),
        label="TikTok click id",
        description="Latest bound TikTok TTCLID.",
    ),
    FieldSpec(
        key="linkedin_click_id",
        native=("hs_linkedin_click_id",),
        label="LinkedIn click id",
        description="Latest bound LinkedIn li_fat_id.",
    ),
)

# Companion timestamps make our API writes monotonic and stop an older D1 touch
# from overwriting a newer value on a retry. They also let us preserve a native
# HubSpot value whose origin/timestamp is unknown instead of guessing.
AD_CLICK_TIMESTAMP_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="google_click_at",
        fallback="cc_google_click_at",
        label="Google click time",
        description="Cloudflare click time for the GCLID last written by this integration.",
        kind="datetime",
    ),
    FieldSpec(
        key="facebook_click_at",
        fallback="cc_facebook_click_at",
        label="Facebook click time",
        description="Cloudflare click time for the FBCLID last written by this integration.",
        kind="datetime",
    ),
    FieldSpec(
        key="tiktok_click_at",
        fallback="cc_tiktok_click_at",
        label="TikTok click time",
        description="Cloudflare click time for the TTCLID last written by this integration.",
        kind="datetime",
    ),
    FieldSpec(
        key="linkedin_click_at",
        fallback="cc_linkedin_click_at",
        label="LinkedIn click time",
        description="Cloudflare click time for the li_fat_id last written by this integration.",
        kind="datetime",
    ),
)

AD_CLICK_SYNC_FIELDS = AD_CLICK_FIELDS + AD_CLICK_TIMESTAMP_FIELDS
AD_CLICK_PARAMETER_FIELDS: dict[str, tuple[str, str]] = {
    "gclid": ("google_click_id", "google_click_at"),
    "fbclid": ("facebook_click_id", "facebook_click_at"),
    "ttclid": ("tiktok_click_id", "tiktok_click_at"),
    "li_fat_id": ("linkedin_click_id", "linkedin_click_at"),
}

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
    """Fetch human click history for acquisition candidates in bounded batches.

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


def fetch_customer_ad_clicks(
    *,
    account_id: str,
    api_token: str,
    database_id: str,
    customer_ids: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Fetch only the newest supported vendor click ID per customer/parameter."""

    by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    queries = 0

    for batch in chunked(sorted(set(customer_ids)), D1_BATCH_SIZE):
        placeholders = ", ".join("?" for _ in batch)
        rows = d1_query(
            account_id=account_id,
            api_token=api_token,
            database_id=database_id,
            sql=f"""
              WITH ranked AS (
                SELECT
                  ct.customer_id,
                  ct.bound_at,
                  sci.parameter,
                  sci.identifier,
                  sc.clicked_at,
                  ROW_NUMBER() OVER (
                    PARTITION BY ct.customer_id, sci.parameter
                    ORDER BY sc.clicked_at DESC, ct.bound_at DESC
                  ) AS row_number
                FROM customer_touches AS ct
                JOIN source_clicks AS sc ON sc.click_id = ct.click_id
                JOIN source_click_identifiers AS sci ON sci.click_id = sc.click_id
                WHERE ct.customer_id IN ({placeholders})
                  AND sci.parameter IN ('gclid', 'fbclid', 'ttclid', 'li_fat_id')
                  AND COALESCE(sc.bot, 0) = 0
              )
              SELECT customer_id, bound_at, parameter, identifier, clicked_at
              FROM ranked
              WHERE row_number = 1
              ORDER BY customer_id, parameter
            """,
            params=[*batch],
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


def latest_ad_clicks(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return the newest D1 row for every HubSpot-supported vendor parameter."""

    latest: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
    for row in rows:
        parameter = str(row.get("parameter") or "")
        if parameter not in AD_CLICK_PARAMETER_FIELDS:
            continue
        identifier = row.get("identifier")
        if identifier is None or str(identifier) == "":
            continue
        try:
            clicked_at = int(row.get("clicked_at"))
            bound_at = int(row.get("bound_at"))
        except (TypeError, ValueError):
            continue
        rank = (clicked_at, bound_at)
        current = latest.get(parameter)
        if current is None or rank > current[0]:
            latest[parameter] = (rank, row)
    return {parameter: value[1] for parameter, value in latest.items()}


def ad_click_property_changes(
    rows: list[dict[str, Any]],
    *,
    existing: dict[str, Any],
    field_properties: dict[str, str],
) -> tuple[dict[str, str], list[str], list[str]]:
    """Build monotonic native click-ID updates.

    If HubSpot already carries a different native click ID and this integration
    has no companion timestamp for it, preserve the native value rather than
    guessing that the D1 value is newer.
    """

    changes: dict[str, str] = {}
    updated_parameters: list[str] = []
    preserved_parameters: list[str] = []

    for parameter, row in latest_ad_clicks(rows).items():
        id_key, at_key = AD_CLICK_PARAMETER_FIELDS[parameter]
        id_property = field_properties.get(id_key)
        at_property = field_properties.get(at_key)
        if id_property is None or at_property is None:
            continue

        identifier = str(row["identifier"])
        try:
            clicked_at = int(row["clicked_at"])
        except (TypeError, ValueError):
            continue

        current_raw = existing.get(id_property)
        current_id = None if current_raw is None or str(current_raw) == "" else str(current_raw)
        current_at = epoch_millis(existing.get(at_property))

        if current_at is None:
            if current_id is None:
                changes[id_property] = identifier
                changes[at_property] = str(clicked_at)
                updated_parameters.append(parameter)
            elif current_id == identifier:
                changes[at_property] = str(clicked_at)
                updated_parameters.append(parameter)
            else:
                preserved_parameters.append(parameter)
            continue

        if clicked_at > current_at:
            changes[id_property] = identifier
            changes[at_property] = str(clicked_at)
            updated_parameters.append(parameter)
        elif clicked_at == current_at and current_id is None:
            changes[id_property] = identifier
            updated_parameters.append(parameter)

    return changes, updated_parameters, preserved_parameters


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
        "contacts_with_native_ad_click_updates": 0,
        "native_ad_click_ids_updated_by_parameter": {},
        "native_ad_click_ids_preserved_without_timestamp": {},
    }

    schema = property_schema(
        http_json=_http_json,
        access_token=hubspot_access_token,
        object_type=CONTACT_OBJECT_TYPE,
        error=SyncError,
        optional=True,
    )
    if schema is not None and CUSTOMER_ID_PROPERTY not in schema:
        summary["attribution_status"] = "missing_customer_source_properties"
        summary["missing_hubspot_contact_properties"] = [CUSTOMER_ID_PROPERTY]
        print(
            "WARNING: Cloudflare Contact sync skipped because the Customer sync has "
            f"not provisioned: {CUSTOMER_ID_PROPERTY}",
            file=sys.stderr,
        )
        return summary

    acquisition_enabled = schema is None or CUSTOMER_CREATED_AT_PROPERTY in schema
    if not acquisition_enabled:
        summary["acquisition_status"] = "missing_customer_created_at_property"
        summary["missing_hubspot_contact_properties"] = [CUSTOMER_CREATED_AT_PROPERTY]
        print(
            "WARNING: Contact acquisition skipped because the Customer sync has "
            f"not provisioned: {CUSTOMER_CREATED_AT_PROPERTY}. Native ad click ID "
            "sync will still run.",
            file=sys.stderr,
        )

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

    ad_schema_report: dict[str, Any] = {}
    ad_field_properties = resolve_fields(
        http_json=_http_json,
        access_token=hubspot_access_token,
        object_type=CONTACT_OBJECT_TYPE,
        fields=AD_CLICK_SYNC_FIELDS,
        error=SyncError,
        report=ad_schema_report,
        group=PROPERTY_GROUP,
        group_label=PROPERTY_GROUP_LABEL,
    )
    summary["hubspot_ad_click_field_properties"] = {
        field.key: ad_field_properties[field.key]
        for field in AD_CLICK_SYNC_FIELDS
        if field.key in ad_field_properties
    }
    missing_native = [
        field.native[0]
        for field in AD_CLICK_FIELDS
        if field.key not in ad_field_properties and field.native
    ]
    if missing_native:
        summary["unwritable_or_missing_native_ad_click_properties"] = missing_native
        print(
            "WARNING: HubSpot did not expose writable native ad click properties: "
            + ", ".join(missing_native),
            file=sys.stderr,
        )
    print(
        "Native ad click fields mapped to HubSpot properties: "
        + describe_mapping(summary["hubspot_ad_click_field_properties"]),
        file=sys.stderr,
    )

    requested = (
        CUSTOMER_ID_PROPERTY,
        CUSTOMER_CREATED_AT_PROPERTY,
        *tuple(field_properties.values()),
        *tuple(ad_field_properties.values()),
    )
    contacts: list[dict[str, Any]] = []
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

        signup_at = (
            epoch_millis(properties.get(CUSTOMER_CREATED_AT_PROPERTY))
            if acquisition_enabled
            else None
        )
        if acquisition_enabled and signup_at is None:
            summary["contacts_missing_customer_created_at"] += 1

        contacts.append(
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
    unique_contacts = [
        contact
        for contact in contacts
        if contact["customer_id"] not in duplicate_customer_ids
    ]

    acquisition_candidates: list[dict[str, Any]] = []
    if acquisition_enabled:
        for contact in unique_contacts:
            if contact["signup_at"] is None:
                continue
            if acquisition_locked(contact["properties"], field_properties):
                summary["contacts_already_attributed"] += 1
                continue
            acquisition_candidates.append(contact)

    touches_by_customer: dict[str, list[dict[str, Any]]] = {}
    d1_queries = 0
    if acquisition_candidates:
        signup_times = [int(candidate["signup_at"]) for candidate in acquisition_candidates]
        touches_by_customer, d1_queries = fetch_customer_touches(
            account_id=account_id,
            api_token=api_token,
            database_id=database_id,
            customer_ids=[str(candidate["customer_id"]) for candidate in acquisition_candidates],
            earliest_signup_at=min(signup_times),
            latest_signup_at=max(signup_times),
            window_days=window_days,
        )
    summary["d1_queries"] = d1_queries
    summary["customers_with_touch_history"] = len(touches_by_customer)

    ad_clicks_by_customer: dict[str, list[dict[str, Any]]] = {}
    ad_d1_queries = 0
    if unique_contacts and any(
        field.key in ad_field_properties for field in AD_CLICK_FIELDS
    ):
        ad_clicks_by_customer, ad_d1_queries = fetch_customer_ad_clicks(
            account_id=account_id,
            api_token=api_token,
            database_id=database_id,
            customer_ids=[str(contact["customer_id"]) for contact in unique_contacts],
        )
    summary["d1_ad_click_queries"] = ad_d1_queries
    summary["customers_with_ad_click_history"] = len(ad_clicks_by_customer)

    updates_by_contact: dict[str, dict[str, str]] = defaultdict(dict)
    by_source: Counter[str] = Counter()
    by_campaign: Counter[str] = Counter()

    for candidate in acquisition_candidates:
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
        updates_by_contact[candidate["contact_id"]].update(changed)

    updated_parameters: Counter[str] = Counter()
    preserved_parameters: Counter[str] = Counter()
    for contact in unique_contacts:
        changes, updated, preserved = ad_click_property_changes(
            ad_clicks_by_customer.get(str(contact["customer_id"]), []),
            existing=contact["properties"],
            field_properties=ad_field_properties,
        )
        if changes:
            summary["contacts_with_native_ad_click_updates"] += 1
            updates_by_contact[contact["contact_id"]].update(changes)
        updated_parameters.update(updated)
        preserved_parameters.update(preserved)

    updates = [
        {"id": contact_id, "properties": properties}
        for contact_id, properties in updates_by_contact.items()
        if properties
    ]
    _batch_write(hubspot_access_token, "update", updates)
    summary["contacts_updated"] = len(updates)
    summary["native_ad_click_ids_updated_by_parameter"] = dict(
        updated_parameters.most_common()
    )
    summary["native_ad_click_ids_preserved_without_timestamp"] = dict(
        preserved_parameters.most_common()
    )
    summary["attributed_by_source"] = dict(by_source.most_common())
    summary["attributed_by_campaign"] = dict(by_campaign.most_common())
    summary["attribution_status"] = (
        "complete" if acquisition_enabled else "native_ad_click_sync_complete"
    )
    hints = dict(schema_report.get("hints") or {})
    hints.update(ad_schema_report.get("hints") or {})
    if hints:
        summary["hubspot_contact_property_hints"] = hints
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
