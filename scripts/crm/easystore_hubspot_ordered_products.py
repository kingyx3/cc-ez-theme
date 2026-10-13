#!/usr/bin/env python3
"""Sync only EasyStore product variants that have appeared on at least one order.

HubSpot Product records are variant-level in this integration. Before delegating
to the existing product sync, this entrypoint scans the same complete EasyStore
Order lifecycle buckets used by production and keeps only variants whose SKU is
referenced by at least one Order line.

An order can outlive the catalogue variant it originally referenced. When an
ordered SKU no longer exists in the live EasyStore catalogue, production creates
an inactive HubSpot Product from the historical Order-line snapshot so cancelled,
archived and other historical Orders can still retain product-backed Line Items.
The snapshot never invents EasyStore Product creation/update timestamps: those
fields remain absent when the Product record itself is no longer available.

HubSpot's Product ``createdate`` and ``hs_lastmodifieddate`` are CRM system
metadata, not source-system timestamps. Production therefore adds dedicated
``easystore_product_created_at`` and ``easystore_product_modified_at`` datetime
properties and writes the EasyStore parent Product's own creation/update times to
them for every synchronized live-catalogue variant.
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


def ordered_variant_snapshots(
    store_domain: str,
    access_token: str,
) -> tuple[dict[str, dict[str, Any]], int, int]:
    """Return one Order-line snapshot for every SKU referenced by any Order."""

    found: dict[str, dict[str, Any]] = {}
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
            if sku is None:
                continue
            key = sku.casefold()
            candidate = {"sku": sku, "line": dict(line)}
            previous = found.get(key)
            if previous is None:
                found[key] = candidate
                continue

            # Prefer the richer historical snapshot when the first occurrence
            # lacked a title or unit price. Identity remains the case-folded SKU.
            previous_line = previous["line"]
            if (
                orders._line_name(previous_line, previous["sku"]) == previous["sku"]
                and orders._line_name(line, sku) != sku
            ) or (
                orders._line_price(previous_line) is None
                and orders._line_price(line) is not None
            ):
                found[key] = candidate

    return found, orders_scanned, lines_scanned


def ordered_variant_skus(
    store_domain: str,
    access_token: str,
) -> tuple[set[str], int, int]:
    """Return case-folded variant SKUs referenced by at least one EasyStore Order."""

    snapshots, orders_scanned, lines_scanned = ordered_variant_snapshots(
        store_domain,
        access_token,
    )
    return set(snapshots), orders_scanned, lines_scanned


def historical_product_from_order_line(
    sku: str,
    line: dict[str, Any],
) -> dict[str, Any]:
    """Build an inactive Product shape from an Order line without inventing dates."""

    variant: dict[str, Any] = {
        "id": f"order-snapshot:{sku}",
        "sku": sku,
    }
    price = orders._line_price(line)
    if price is not None:
        variant["price"] = price

    return {
        "id": f"order-snapshot:{sku}",
        "title": orders._line_name(line, sku),
        "published": False,
        "variants": [variant],
        "easystore_historical_order_snapshot": True,
    }


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
) -> dict[str, Any]:
    ordered_snapshots, orders_scanned, lines_scanned = ordered_variant_snapshots(
        store_domain,
        easystore_access_token,
    )
    ordered_skus = set(ordered_snapshots)

    base_iter_easystore_products = products.iter_easystore_products
    base_product_variants = products.product_variants
    base_product_fields = products.PRODUCT_FIELDS
    skipped_without_orders = 0
    live_catalogue_skus: set[str] = set()
    historical_order_product_skus: list[str] = []

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
            key = sku.casefold()
            live_catalogue_skus.add(key)
            if key in ordered_skus:
                selected.append(variant)
            else:
                skipped_without_orders += 1
        return selected

    def ordered_easystore_products(
        product_store_domain: str,
        product_access_token: str,
    ):
        # Generator execution alternates with the base sync's variant processing.
        # By the time this source iterator is exhausted, ordered_product_variants
        # has recorded every live catalogue SKU, so only genuinely missing SKUs
        # receive historical fallback Products.
        yield from base_iter_easystore_products(
            product_store_domain,
            product_access_token,
        )

        for key, snapshot in ordered_snapshots.items():
            if key in live_catalogue_skus:
                continue
            sku = snapshot["sku"]
            historical_order_product_skus.append(sku)
            yield historical_product_from_order_line(sku, snapshot["line"])

    products.iter_easystore_products = ordered_easystore_products
    products.product_variants = ordered_product_variants
    products.PRODUCT_FIELDS = (*base_product_fields, *PRODUCT_SOURCE_DATE_FIELDS)
    try:
        summary = products.sync(
            store_domain=store_domain,
            easystore_access_token=easystore_access_token,
            hubspot_access_token=hubspot_access_token,
        )
    finally:
        products.iter_easystore_products = base_iter_easystore_products
        products.product_variants = base_product_variants
        products.PRODUCT_FIELDS = base_product_fields

    result = dict(summary)
    result.update(
        {
            "easystore_orders_scanned_for_product_filter": orders_scanned,
            "easystore_order_lines_scanned_for_product_filter": lines_scanned,
            "ordered_product_skus": len(ordered_skus),
            "easystore_variants_without_orders_skipped": skipped_without_orders,
            "historical_order_products_from_snapshots": len(historical_order_product_skus),
            "historical_order_product_skus": sorted(historical_order_product_skus),
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