#!/usr/bin/env python3
"""Reconcile product-backed HubSpot Order line items to EasyStore.

The main order sync creates and updates the desired product-backed line items.
This final reconciliation stage archives product-backed HubSpot line items whose
SKU is no longer present on the corresponding EasyStore order (for example after
an order edit or a quantity being removed). Standalone/manual line items without
``hs_product_id`` are deliberately left untouched.

All EasyStore orders and product references are validated before any archive is
performed so a partial upstream read cannot erase CRM data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from easystore_hubspot_orders import (
    HUBSPOT_LINE_ITEMS_URL,
    SyncError,
    _existing_order_line_items,
    _http_json,
    complete_order,
    desired_lines,
    hubspot_order_index,
    hubspot_product_index,
    iter_easystore_orders,
    nonempty,
)


def stale_product_backed_line_ids(
    existing: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, str]],
) -> list[str]:
    """Return stale product-backed line item IDs, preserving manual standalone lines."""

    stale: list[str] = []
    for sku_key, line in existing.items():
        if sku_key in desired:
            continue
        line_id = nonempty(line.get("id"))
        properties = line.get("properties")
        if line_id is None or not isinstance(properties, dict):
            raise SyncError("HubSpot returned an unusable associated line item")
        if nonempty(properties.get("hs_product_id")) is None:
            continue
        stale.append(line_id)
    return stale


def reconcile(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
) -> dict[str, int]:
    product_by_sku = hubspot_product_index(hubspot_access_token)
    hubspot_orders = hubspot_order_index(hubspot_access_token)

    archive_plan: list[tuple[str, str]] = []
    orders_scanned = 0
    orders_with_stale_lines = 0

    # Build the complete plan before deleting anything. If EasyStore returns an
    # incomplete/ambiguous order or a Product is missing, desired_lines raises
    # and this stage leaves HubSpot unchanged.
    for listed in iter_easystore_orders(store_domain, easystore_access_token):
        orders_scanned += 1
        order = complete_order(store_domain, easystore_access_token, listed)
        external_id = nonempty(order.get("id"))
        if external_id is None:
            raise SyncError("EasyStore returned an order without an id")

        hubspot_order_id = hubspot_orders.get(external_id)
        if hubspot_order_id is None:
            raise SyncError(
                f"EasyStore order {external_id} is missing from HubSpot after the order sync"
            )

        desired = desired_lines(order, product_by_sku)
        existing = _existing_order_line_items(
            hubspot_access_token,
            hubspot_order_id,
        )
        stale_ids = stale_product_backed_line_ids(existing, desired)
        if stale_ids:
            orders_with_stale_lines += 1
        archive_plan.extend((hubspot_order_id, line_id) for line_id in stale_ids)

    headers = {"Authorization": f"Bearer {hubspot_access_token}"}
    for hubspot_order_id, line_id in archive_plan:
        _http_json(
            f"{HUBSPOT_LINE_ITEMS_URL}/{line_id}",
            method="DELETE",
            headers=headers,
        )
        print(
            f"Archived stale product-backed line item {line_id} from HubSpot order {hubspot_order_id}",
            file=sys.stderr,
        )

    return {
        "easystore_orders_scanned": orders_scanned,
        "orders_with_stale_product_lines": orders_with_stale_lines,
        "stale_product_backed_line_items_archived": len(archive_plan),
    }


def _required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise SyncError(f"{name} is required")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-domain", default=os.getenv("EASYSTORE_STORE_DOMAIN"))
    parser.add_argument("--easystore-token", default=os.getenv("EASYSTORE_ACCESS_TOKEN"))
    parser.add_argument("--hubspot-token", default=os.getenv("HUBSPOT_ACCESS_TOKEN"))
    args = parser.parse_args(argv)

    try:
        summary = reconcile(
            store_domain=_required(args.store_domain, "EASYSTORE_STORE_DOMAIN"),
            easystore_access_token=_required(
                args.easystore_token, "EASYSTORE_ACCESS_TOKEN"
            ),
            hubspot_access_token=_required(args.hubspot_token, "HUBSPOT_ACCESS_TOKEN"),
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
