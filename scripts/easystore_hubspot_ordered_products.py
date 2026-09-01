#!/usr/bin/env python3
"""Sync only EasyStore product variants that have appeared on at least one order.

HubSpot Product records are variant-level in this integration. Before delegating
to the existing product sync, this entrypoint scans the same complete EasyStore
Order lifecycle buckets used by production and keeps only variants whose SKU is
referenced by at least one Order line.

HubSpot's Product ``createdate`` and ``hs_lastmodifieddate`` are CRM system
metadata, not source-system timestamps. Production therefore adds dedicated
``easystore_product_created_at`` and ``easystore_product_modified_at`` datetime
properties and writes the EasyStore parent Product's own creation/update times to
them for every synchronized variant.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import easystore_hubspot_order_sync as order_sync
import easystore_hubspot_orders as orders
import easystore_hubspot_products as products


PRODUCT_SOURCE_DATE_FIELDS: tuple[products.FieldSpec, ...] = (
    products.FieldSpec(
        key="source_created_at",
        sources=("created_at", "created_on"),
        fallback="easystore_product_created_at",
        label="EasyStore Created Date",
        description="Date and time the product record was created in EasyStore.",
        kind="datetime",
    ),
    products.FieldSpec(
        key="source_modified_at",
        sources=("updated_at", "modified_at", "updated_on", "modified_on"),
        fallback="easystore_product_modified_at",
        label="EasyStore Modified Date",
        description="Date and time the product record was last modified in EasyStore.",
        kind="datetime",
    ),
)


def ordered_variant_skus(
    store_domain: str,
    access_token: str,
) -> tuple[set[str], int, int]:
    """Return case-folded variant SKUs referenced by at least one EasyStore Order."""

    found: set[str] = set()
    orders_scanned = 0
    lines_scanned = 0

    for source_order in order_sync.iter_easystore_orders_all_statuses(
        store_domain,
        access_token,
    ):
        order = orders.complete_order(
            store_domain,
            access_token,
            source_order,
            commerce_fields=False,
        )
        order_id = orders.nonempty(order.get("id")) or orders.nonempty(source_order.get("id"))
        lines = order.get("line_items")
        if not isinstance(lines, list):
            raise products.SyncError(
                "EasyStore order "
                f"{order_id or '(unknown)'} did not provide line_items while building "
                "the ordered-product filter."
            )

        orders_scanned += 1
        for line in lines:
            if not isinstance(line, dict):
                continue
            lines_scanned += 1
            sku = orders._line_sku(line)
            if sku is not None:
                found.add(sku.casefold())

    return found, orders_scanned, lines_scanned


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
) -> dict[str, Any]:
    ordered_skus, orders_scanned, lines_scanned = ordered_variant_skus(
        store_domain,
        easystore_access_token,
    )

    base_product_variants = products.product_variants
    base_product_fields = products.PRODUCT_FIELDS
    skipped_without_orders = 0

    def ordered_product_variants(
        variant_store_domain: str,
        variant_access_token: str,
        product: dict[str, Any],
    ) -> list[dict[str, Any]]:
        nonlocal skipped_without_orders

        variants = base_product_variants(
            variant_store_domain,
            variant_access_token,
            product,
        )
        product_id = products.nonempty(product.get("id"))
        if product_id is None:
            skipped_without_orders += len(variants)
            return []

        selected: list[dict[str, Any]] = []
        for variant in variants:
            sku, _synthetic = products.variant_sku(product_id, variant)
            if sku.casefold() in ordered_skus:
                selected.append(variant)
            else:
                skipped_without_orders += 1
        return selected

    products.product_variants = ordered_product_variants
    products.PRODUCT_FIELDS = (*base_product_fields, *PRODUCT_SOURCE_DATE_FIELDS)
    try:
        summary = products.sync(
            store_domain=store_domain,
            easystore_access_token=easystore_access_token,
            hubspot_access_token=hubspot_access_token,
        )
    finally:
        products.product_variants = base_product_variants
        products.PRODUCT_FIELDS = base_product_fields

    result = dict(summary)
    result.update(
        {
            "easystore_orders_scanned_for_product_filter": orders_scanned,
            "easystore_order_lines_scanned_for_product_filter": lines_scanned,
            "ordered_product_skus": len(ordered_skus),
            "easystore_variants_without_orders_skipped": skipped_without_orders,
        }
    )
    return result


def _required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise products.SyncError(f"{name} is required")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-domain", default=os.getenv("EASYSTORE_STORE_DOMAIN"))
    parser.add_argument("--easystore-token", default=os.getenv("EASYSTORE_ACCESS_TOKEN"))
    parser.add_argument("--hubspot-token", default=os.getenv("HUBSPOT_ACCESS_TOKEN"))
    args = parser.parse_args(argv)

    try:
        summary = sync(
            store_domain=_required(args.store_domain, "EASYSTORE_STORE_DOMAIN"),
            easystore_access_token=_required(args.easystore_token, "EASYSTORE_ACCESS_TOKEN"),
            hubspot_access_token=_required(args.hubspot_token, "HUBSPOT_ACCESS_TOKEN"),
        )
    except (products.SyncError, orders.SyncError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())