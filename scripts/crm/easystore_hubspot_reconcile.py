#!/usr/bin/env python3
"""Reconcile product-backed HubSpot Order line items to EasyStore.

The main order sync creates and updates the desired product-backed line items.
This final reconciliation stage archives product-backed HubSpot line items whose
SKU is no longer present on the corresponding EasyStore order (for example after
an order edit or a quantity being removed). Standalone/manual line items without
``hs_product_id`` are deliberately left untouched.

Production scans the same open, cancelled, archived and deleted EasyStore Order
buckets as the main Order stage. Terminal historical Orders may reference retired
variants that no longer have an active HubSpot Product; those source SKUs are
preserved during reconciliation instead of being mistaken for removed lines.

All EasyStore orders and product references are validated before any archive is
performed so a partial upstream read cannot erase CRM data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import easystore_hubspot_order_sync as production_orders
from easystore_hubspot_orders import (
    HUBSPOT_LINE_ITEMS_URL,
    SyncError,
    _existing_order_line_items,
    _http_json,
    complete_order,
    desired_lines,
    hubspot_order_index,
    hubspot_product_index,
    nonempty,
)


def stale_product_backed_line_ids(
    existing: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, str]],
    *,
    preserve_skus: set[str] | None = None,
) -> list[str]:
    """Return stale product-backed line IDs while preserving known historical SKUs."""

    preserved = preserve_skus or set()
    stale: list[str] = []
    for sku_key, line in existing.items():
        if sku_key in desired or sku_key in preserved:
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
    terminal_unmatched_product_lines = 0

    # Build the complete plan before deleting anything. Current/open Orders remain
    # strict: if one references a missing Product, desired_lines raises and this
    # stage leaves HubSpot unchanged. Terminal history can legitimately outlive a
    # catalogue variant, so those unmatched SKUs are preserved instead.
    for listed in production_orders.iter_easystore_orders_all_statuses(
        store_domain,
        easystore_access_token,
    ):
        orders_scanned += 1
        # Only line items matter here, so skip the detail fetch that the order
        # stage needs for addresses and totals.
        order = complete_order(
            store_domain,
            easystore_access_token,
            listed,
            commerce_fields=False,
        )
        external_id = nonempty(order.get("id"))
        if external_id is None:
            raise SyncError("EasyStore returned an order without an id")

        hubspot_order_id = hubspot_orders.get(external_id)
        if hubspot_order_id is None:
            raise SyncError(
                f"EasyStore order {external_id} is missing from HubSpot after the order sync"
            )

        unmatched_lines: list[str] = []
        if production_orders.is_terminal_source_order(order):
            desired = desired_lines(
                order,
                product_by_sku,
                unmatched_lines=unmatched_lines,
            )
        else:
            desired = desired_lines(order, product_by_sku)

        # A terminal source line with a retired Product is still present on the
        # EasyStore Order. If HubSpot already has that historical product-backed
        # line, do not archive it simply because the current Product index no
        # longer contains the SKU.
        preserve_skus = {
            sku.casefold()
            for sku in unmatched_lines
            if not sku.startswith("<")
        }
        if unmatched_lines:
            terminal_unmatched_product_lines += len(unmatched_lines)
            print(
                "WARNING: terminal EasyStore order "
                f"{external_id} ({production_orders.source_status_for_order(order)}) "
                "references retired or unavailable Product line(s): "
                + ", ".join(unmatched_lines)
                + ". Existing matching historical HubSpot lines will be preserved.",
                file=sys.stderr,
            )

        existing = _existing_order_line_items(
            hubspot_access_token,
            hubspot_order_id,
        )
        stale_ids = stale_product_backed_line_ids(
            existing,
            desired,
            preserve_skus=preserve_skus,
        )
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
        "terminal_order_lines_without_active_hubspot_product": (
            terminal_unmatched_product_lines
        ),
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
