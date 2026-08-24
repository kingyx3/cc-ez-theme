#!/usr/bin/env python3
"""Attribute each EasyStore order to its own latest tracked marketing touch.

Customer acquisition and order conversion are deliberately separate facts. The
existing contact attribution job writes the click under which an account was
acquired. This job instead looks at append-only ``customer_touches`` rows in the
Cloudflare D1 database and chooses the latest human marketing click that:

* belongs to the EasyStore customer on the order;
* was bound to that customer before the order was created;
* happened before the order was created; and
* is inside the configured attribution window (30 days by default).

The result is snapshotted onto the HubSpot Order. A later click can therefore
influence a later purchase without rewriting either the Contact acquisition or an
earlier Order. There is intentionally no fallback from an unattributed Order to
the Contact's acquisition source.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import easystore_hubspot_orders as orders
from easystore_hubspot_schema import FieldSpec, describe_mapping, first_present, nonempty, resolve_fields


CLOUDFLARE_BASE_URL = "https://api.cloudflare.com/client/v4"
D1_DATABASE_ID = "f7377a40-379a-4713-9126-e05636162c84"
D1_BATCH_SIZE = 80
HUBSPOT_BATCH_SIZE = 100
DEFAULT_WINDOW_DAYS = 30
MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000
SINGAPORE_TZ = timezone(timedelta(hours=8))

PROPERTY_GROUP = "cloudflare_attribution"
PROPERTY_GROUP_LABEL = "Cloudflare Attribution"
ORDER_OBJECT_TYPE = "order"

FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="source",
        fallback="cc_order_source",
        label="Order source",
        description="Latest tracked marketing source before this order.",
    ),
    FieldSpec(
        key="medium",
        fallback="cc_order_medium",
        label="Order medium",
        description="Latest tracked marketing medium before this order.",
    ),
    FieldSpec(
        key="campaign",
        fallback="cc_order_campaign",
        label="Order campaign",
        description="Latest tracked marketing campaign before this order.",
    ),
    FieldSpec(
        key="content",
        fallback="cc_order_content",
        label="Order content",
        description="Marketing content/post label of the latest tracked touch before this order.",
    ),
    FieldSpec(
        key="click_id",
        fallback="cc_order_click_id",
        label="Order click ID",
        description="Cloudflare click selected as the conversion touch for this order.",
    ),
    FieldSpec(
        key="clicked_at",
        fallback="cc_order_touch_at",
        label="Order marketing touch time",
        description="When the selected marketing touch happened.",
        kind="datetime",
    ),
    FieldSpec(
        key="model",
        fallback="cc_order_attribution_model",
        label="Order attribution model",
        description="Attribution rule used for this order.",
    ),
    FieldSpec(
        key="window_days",
        fallback="cc_order_attribution_window_days",
        label="Order attribution window (days)",
        description="Maximum age of an eligible tracked touch for this order.",
        kind="number",
    ),
    FieldSpec(
        key="status",
        fallback="cc_order_attribution_status",
        label="Order attribution status",
        description="Whether and why a tracked marketing touch was selected for this order.",
    ),
)


def chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def order_customer_id(order: dict[str, Any]) -> str | None:
    direct = nonempty(order.get("customer_id"))
    if direct is not None:
        return direct
    customer = order.get("customer")
    if isinstance(customer, dict):
        return first_present(customer, ("id", "customer_id"))
    return None


def epoch_millis(value: Any) -> int | None:
    """Return an EasyStore timestamp as epoch milliseconds.

    EasyStore normally returns ISO timestamps with an offset. If a legacy shape
    omits the offset, the store's Singapore timezone is used instead of silently
    treating local wall time as UTC.
    """

    text = str(value or "").strip()
    if not text:
        return None

    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None:
        # Seconds are roughly 1e9; milliseconds are roughly 1e12.
        return int(number * 1000) if abs(number) < 100_000_000_000 else int(number)

    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SINGAPORE_TZ)
    return int(parsed.timestamp() * 1000)


def order_created_at(order: dict[str, Any]) -> int | None:
    return epoch_millis(
        first_present(
            order,
            ("created_at", "created_on", "processed_at", "order_date", "date"),
        )
    )


def latest_touch_for_order(
    touches: list[dict[str, Any]],
    *,
    order_at: int,
    window_days: int,
) -> dict[str, Any] | None:
    """Choose the latest eligible touch, never a touch learned after the order."""

    lower = order_at - window_days * MILLISECONDS_PER_DAY
    eligible = []
    for touch in touches:
        try:
            clicked_at = int(touch.get("clicked_at"))
            bound_at = int(touch.get("bound_at"))
        except (TypeError, ValueError):
            continue
        if lower <= clicked_at <= order_at and bound_at <= order_at:
            eligible.append(touch)
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda touch: (int(touch["clicked_at"]), int(touch["bound_at"])),
    )


def d1_query(
    *,
    account_id: str,
    api_token: str,
    database_id: str,
    sql: str,
    params: list[Any],
) -> list[dict[str, Any]]:
    document = orders._http_json(
        f"{CLOUDFLARE_BASE_URL}/accounts/{account_id}/d1/database/{database_id}/query",
        method="POST",
        headers={"Authorization": f"Bearer {api_token}"},
        payload={"sql": sql, "params": params},
    )
    if not isinstance(document, dict) or not document.get("success", False):
        detail = json.dumps(document.get("errors") if isinstance(document, dict) else document)
        raise orders.SyncError(f"Cloudflare D1 order-attribution query failed: {detail[:1000]}")

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
    earliest_order_at: int,
    latest_order_at: int,
    window_days: int,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    queries = 0
    lower = earliest_order_at - window_days * MILLISECONDS_PER_DAY

    for batch in chunked(sorted(set(customer_ids)), D1_BATCH_SIZE):
        placeholders = ", ".join("?" for _ in batch)
        sql = f"""
          SELECT
            ct.customer_id,
            ct.click_id,
            ct.bound_at,
            sc.source,
            sc.medium,
            sc.campaign,
            sc.content,
            sc.clicked_at,
            sc.bot_reason
          FROM customer_touches AS ct
          JOIN source_clicks AS sc ON sc.click_id = ct.click_id
          WHERE ct.customer_id IN ({placeholders})
            AND sc.clicked_at >= ?
            AND sc.clicked_at <= ?
            AND ct.bound_at <= ?
            AND COALESCE(sc.bot, 0) = 0
          ORDER BY ct.customer_id, sc.clicked_at, ct.bound_at
        """
        rows = d1_query(
            account_id=account_id,
            api_token=api_token,
            database_id=database_id,
            sql=sql,
            params=[*batch, lower, latest_order_at, latest_order_at],
        )
        queries += 1
        for row in rows:
            customer_id = nonempty(row.get("customer_id"))
            if customer_id is not None:
                by_customer[customer_id].append(row)

    return dict(by_customer), queries


def hubspot_order_records(
    access_token: str,
    field_properties: dict[str, str],
) -> dict[str, dict[str, Any]]:
    property_names = [orders.ORDER_EXTERNAL_ID_PROPERTY, *field_properties.values()]
    by_external_id: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()

    for record in orders.iter_hubspot_objects(
        orders.HUBSPOT_ORDERS_URL,
        access_token,
        ",".join(dict.fromkeys(property_names)),
    ):
        properties = record.get("properties")
        hubspot_id = nonempty(record.get("id"))
        if hubspot_id is None or not isinstance(properties, dict):
            continue
        external_id = nonempty(properties.get(orders.ORDER_EXTERNAL_ID_PROPERTY))
        if external_id is None:
            continue
        if external_id in by_external_id:
            duplicates.add(external_id)
        by_external_id[external_id] = record

    if duplicates:
        raise orders.SyncError(
            "Multiple HubSpot Orders carry the same EasyStore order ID: "
            + ", ".join(sorted(duplicates)[:10])
        )
    return by_external_id


def touch_values(
    touch: dict[str, Any] | None,
    *,
    window_days: int,
    status: str,
) -> dict[str, str]:
    values = {
        "model": "last_tracked_touch",
        "window_days": str(window_days),
        "status": status,
    }
    if touch is None:
        return values

    for key in ("source", "medium", "campaign", "content", "click_id"):
        value = nonempty(touch.get(key))
        if value is not None:
            values[key] = value
    clicked_at = touch.get("clicked_at")
    try:
        values["clicked_at"] = str(int(clicked_at))
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


def batch_update_orders(access_token: str, inputs: list[dict[str, Any]]) -> int:
    written = 0
    headers = {"Authorization": f"Bearer {access_token}"}
    for start in range(0, len(inputs), HUBSPOT_BATCH_SIZE):
        batch = inputs[start : start + HUBSPOT_BATCH_SIZE]
        orders._http_json(
            f"{orders.HUBSPOT_ORDERS_URL}/batch/update",
            method="POST",
            headers=headers,
            payload={"inputs": batch},
        )
        written += len(batch)
    return written


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    account_id: str,
    api_token: str,
    database_id: str = D1_DATABASE_ID,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    if not 1 <= window_days <= 365:
        raise orders.SyncError("ORDER_ATTRIBUTION_WINDOW_DAYS must be between 1 and 365")

    schema_report: dict[str, Any] = {}
    field_properties = resolve_fields(
        http_json=orders._http_json,
        access_token=hubspot_access_token,
        object_type=ORDER_OBJECT_TYPE,
        fields=FIELDS,
        error=orders.SyncError,
        report=schema_report,
        group=PROPERTY_GROUP,
        group_label=PROPERTY_GROUP_LABEL,
    )

    summary: dict[str, Any] = {
        "attribution_model": "last_tracked_touch",
        "attribution_window_days": window_days,
        "d1_database_id": database_id,
        "hubspot_order_field_properties": {
            field.key: field_properties[field.key]
            for field in FIELDS
            if field.key in field_properties
        },
        "easystore_orders": 0,
        "orders_missing_customer_id": 0,
        "orders_missing_created_at": 0,
        "orders_with_eligible_touch": 0,
        "orders_without_recent_tracked_touch": 0,
        "hubspot_orders_missing": 0,
        "hubspot_orders_with_conflicting_click_id": 0,
        "hubspot_orders_unchanged": 0,
    }
    print(
        "Order attribution fields mapped to HubSpot properties: "
        + describe_mapping(summary["hubspot_order_field_properties"]),
        file=os.sys.stderr,
    )

    source_orders: list[dict[str, Any]] = []
    customer_ids: list[str] = []
    order_times: list[int] = []
    for order in orders.iter_easystore_orders(store_domain, easystore_access_token):
        summary["easystore_orders"] += 1
        external_id = nonempty(order.get("id"))
        if external_id is None:
            continue
        customer_id = order_customer_id(order)
        created_at = order_created_at(order)
        if customer_id is None:
            summary["orders_missing_customer_id"] += 1
        else:
            customer_ids.append(customer_id)
        if created_at is None:
            summary["orders_missing_created_at"] += 1
        else:
            order_times.append(created_at)
        source_orders.append(
            {
                "external_id": external_id,
                "customer_id": customer_id,
                "created_at": created_at,
            }
        )

    touches_by_customer: dict[str, list[dict[str, Any]]] = {}
    d1_queries = 0
    if customer_ids and order_times:
        touches_by_customer, d1_queries = fetch_customer_touches(
            account_id=account_id,
            api_token=api_token,
            database_id=database_id,
            customer_ids=customer_ids,
            earliest_order_at=min(order_times),
            latest_order_at=max(order_times),
            window_days=window_days,
        )
    summary["d1_queries"] = d1_queries
    summary["customers_with_touch_history"] = len(touches_by_customer)

    hubspot_orders = hubspot_order_records(hubspot_access_token, field_properties)
    click_property = field_properties.get("click_id")
    updates: list[dict[str, Any]] = []

    for source in source_orders:
        external_id = source["external_id"]
        record = hubspot_orders.get(external_id)
        if record is None:
            summary["hubspot_orders_missing"] += 1
            continue
        existing = record.get("properties")
        if not isinstance(existing, dict):
            existing = {}

        customer_id = source["customer_id"]
        created_at = source["created_at"]
        touch = None
        if customer_id is None:
            status = "missing_customer_id"
        elif created_at is None:
            status = "missing_order_timestamp"
        else:
            touch = latest_touch_for_order(
                touches_by_customer.get(customer_id, []),
                order_at=created_at,
                window_days=window_days,
            )
            if touch is None:
                status = "no_recent_tracked_touch"
                summary["orders_without_recent_tracked_touch"] += 1
            else:
                status = "attributed"
                summary["orders_with_eligible_touch"] += 1

        current_click = nonempty(existing.get(click_property)) if click_property else None
        desired_click = nonempty(touch.get("click_id")) if touch is not None else None
        if current_click and desired_click and current_click != desired_click:
            summary["hubspot_orders_with_conflicting_click_id"] += 1
            continue
        if current_click and desired_click is None:
            # An Order attribution is a historical snapshot. Never downgrade it
            # merely because a later run cannot find the touch again.
            summary["hubspot_orders_unchanged"] += 1
            continue

        desired = mapped_properties(
            touch_values(touch, window_days=window_days, status=status),
            field_properties,
        )
        changed = {
            key: value
            for key, value in desired.items()
            if str(existing.get(key) or "") != str(value)
        }
        if not changed:
            summary["hubspot_orders_unchanged"] += 1
            continue
        updates.append({"id": str(record["id"]), "properties": changed})

    summary["hubspot_orders_updated"] = batch_update_orders(hubspot_access_token, updates)
    return summary


def required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise orders.SyncError(f"{name} is required")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-domain", default=os.getenv("EASYSTORE_STORE_DOMAIN"))
    parser.add_argument("--easystore-token", default=os.getenv("EASYSTORE_ACCESS_TOKEN"))
    parser.add_argument("--hubspot-token", default=os.getenv("HUBSPOT_ACCESS_TOKEN"))
    parser.add_argument("--account-id", default=os.getenv("CLOUDFLARE_ACCOUNT_ID"))
    parser.add_argument("--api-token", default=os.getenv("CLOUDFLARE_API_TOKEN"))
    parser.add_argument(
        "--database-id",
        default=os.getenv("CLOUDFLARE_D1_DATABASE_ID", D1_DATABASE_ID),
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=int(os.getenv("ORDER_ATTRIBUTION_WINDOW_DAYS") or DEFAULT_WINDOW_DAYS),
    )
    args = parser.parse_args(argv)

    try:
        summary = sync(
            store_domain=required(args.store_domain, "EASYSTORE_STORE_DOMAIN"),
            easystore_access_token=required(args.easystore_token, "EASYSTORE_ACCESS_TOKEN"),
            hubspot_access_token=required(args.hubspot_token, "HUBSPOT_ACCESS_TOKEN"),
            account_id=required(args.account_id, "CLOUDFLARE_ACCOUNT_ID"),
            api_token=required(args.api_token, "CLOUDFLARE_API_TOKEN"),
            database_id=required(args.database_id, "CLOUDFLARE_D1_DATABASE_ID"),
            window_days=args.window_days,
        )
    except (orders.SyncError, ValueError) as error:
        print(f"ERROR: {error}", file=os.sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
