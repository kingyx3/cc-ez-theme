#!/usr/bin/env python3
"""Sync EasyStore product variants into HubSpot's Product library.

Each EasyStore variant becomes one HubSpot Product. HubSpot products have one SKU
and one unit price, so variant-level records preserve the exact SKU/price used by
order line items. The EasyStore SKU is the HubSpot ``hs_sku`` identity when
present. Variants without a SKU receive a deterministic ``ES-<product>-<variant>``
SKU so reruns remain idempotent.

Only Python's standard library is used.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from collections import defaultdict
from typing import Any, Iterable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HUBSPOT_PRODUCTS_URL = "https://api.hubapi.com/crm/v3/objects/products"
EASYSTORE_PAGE_SIZE = 50
BATCH_SIZE = 100


class SyncError(RuntimeError):
    """Raised when a remote API or identity invariant prevents a safe sync."""


def nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: Any = None,
    retries: int = 4,
) -> Any:
    body = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "cc-ez-theme-product-sync/1.0",
    }
    if headers:
        request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    for attempt in range(retries + 1):
        request = Request(url, data=body, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            retryable = error.code == 429 or 500 <= error.code < 600
            if retryable and attempt < retries:
                retry_after = error.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 2**attempt
                except ValueError:
                    delay = 2**attempt
                time.sleep(min(max(delay, 1.0), 30.0))
                continue
            raise SyncError(
                f"{method} {url} failed with HTTP {error.code}: {detail[:1000]}"
            ) from error
        except (URLError, TimeoutError) as error:
            if attempt < retries:
                time.sleep(min(2**attempt, 30))
                continue
            raise SyncError(f"{method} {url} failed: {error}") from error
        except json.JSONDecodeError as error:
            raise SyncError(f"{method} {url} returned invalid JSON") from error
    raise AssertionError("unreachable")


def _extract_list(document: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    if not isinstance(document, dict):
        return []
    for key in keys:
        value = document.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for nested_key in keys:
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
    return []


def iter_easystore_products(store_domain: str, access_token: str) -> Iterator[dict[str, Any]]:
    domain = store_domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    page = 1
    while True:
        query = urlencode({"page": page, "limit": EASYSTORE_PAGE_SIZE, "sort": "id.asc"})
        document = _http_json(
            f"https://{domain}/api/3.0/products.json?{query}",
            headers={"EasyStore-Access-Token": access_token},
        )
        products = _extract_list(document, "products", "data", "results")
        for product in products:
            yield product
        if len(products) < EASYSTORE_PAGE_SIZE:
            break
        page += 1


def product_variants(
    store_domain: str,
    access_token: str,
    product: dict[str, Any],
) -> list[dict[str, Any]]:
    embedded = product.get("variants")
    if isinstance(embedded, list) and embedded:
        return [item for item in embedded if isinstance(item, dict)]

    product_id = nonempty(product.get("id"))
    if product_id is None:
        return []
    domain = store_domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    document = _http_json(
        f"https://{domain}/api/3.0/products/{product_id}/variants.json",
        headers={"EasyStore-Access-Token": access_token},
    )
    return _extract_list(document, "variants", "data", "results")


def iter_hubspot_products(access_token: str) -> Iterator[dict[str, Any]]:
    after: str | None = None
    while True:
        params = {
            "limit": "100",
            "properties": "hs_sku,name,price,description,hs_cost_of_goods_sold",
            "archived": "false",
        }
        if after is not None:
            params["after"] = after
        document = _http_json(
            f"{HUBSPOT_PRODUCTS_URL}?{urlencode(params)}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        results = document.get("results", []) if isinstance(document, dict) else []
        for product in results:
            if isinstance(product, dict):
                yield product
        paging = document.get("paging", {}) if isinstance(document, dict) else {}
        nxt = paging.get("next", {}) if isinstance(paging, dict) else {}
        next_after = nxt.get("after") if isinstance(nxt, dict) else None
        if next_after is None:
            break
        after = str(next_after)


def _plain_description(product: dict[str, Any]) -> str | None:
    text = nonempty(product.get("description"))
    if text is None:
        text = nonempty(product.get("body_html"))
    if text is None:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return " ".join(text.split()) or None


def variant_sku(product_id: str, variant: dict[str, Any]) -> tuple[str, bool]:
    sku = nonempty(variant.get("sku"))
    if sku:
        return sku, False
    variant_id = nonempty(variant.get("id"))
    if variant_id is None:
        raise SyncError(f"EasyStore product {product_id} contains a variant without id or SKU")
    return f"ES-{product_id}-{variant_id}", True


def variant_properties(
    product: dict[str, Any],
    variant: dict[str, Any],
    sku: str,
) -> dict[str, str]:
    title = nonempty(product.get("title")) or nonempty(product.get("name")) or f"EasyStore product {product.get('id')}"
    variant_name = nonempty(variant.get("name")) or nonempty(variant.get("title"))
    if variant_name and variant_name.casefold() not in {"default", "default title"}:
        name = f"{title} — {variant_name}"
    else:
        name = title

    props: dict[str, str] = {"name": name, "hs_sku": sku}
    price = nonempty(variant.get("price")) or nonempty(product.get("price"))
    if price is not None:
        props["price"] = price
    description = _plain_description(product)
    if description is not None:
        props["description"] = description
    cost = nonempty(variant.get("cost_price"))
    if cost is not None:
        props["hs_cost_of_goods_sold"] = cost
    return props


def chunked(items: list[Any], size: int = BATCH_SIZE) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _batch_write(access_token: str, action: str, inputs: list[dict[str, Any]]) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}
    for batch in chunked(inputs):
        _http_json(
            f"{HUBSPOT_PRODUCTS_URL}/batch/{action}",
            method="POST",
            headers=headers,
            payload={"inputs": batch},
        )


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
) -> dict[str, int]:
    hubspot_by_sku: dict[str, set[str]] = defaultdict(set)
    hubspot_total = 0
    for product in iter_hubspot_products(hubspot_access_token):
        hubspot_total += 1
        product_id = nonempty(product.get("id"))
        properties = product.get("properties")
        if product_id is None or not isinstance(properties, dict):
            continue
        sku = nonempty(properties.get("hs_sku"))
        if sku:
            hubspot_by_sku[sku.casefold()].add(product_id)

    easystore_by_sku: dict[str, tuple[dict[str, Any], dict[str, Any], str]] = {}
    easystore_products = 0
    easystore_variants = 0
    synthetic_skus = 0
    duplicate_easystore_skus = 0

    for product in iter_easystore_products(store_domain, easystore_access_token):
        easystore_products += 1
        product_id = nonempty(product.get("id"))
        if product_id is None:
            continue
        for variant in product_variants(store_domain, easystore_access_token, product):
            easystore_variants += 1
            sku, synthetic = variant_sku(product_id, variant)
            if synthetic:
                synthetic_skus += 1
            key = sku.casefold()
            if key in easystore_by_sku:
                duplicate_easystore_skus += 1
                previous = easystore_by_sku[key]
                print(
                    f"ERROR: EasyStore SKU {sku!r} is used by more than one variant "
                    f"({previous[1].get('id')} and {variant.get('id')}).",
                    file=sys.stderr,
                )
                continue
            easystore_by_sku[key] = (product, variant, sku)

    creates: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    ambiguous_hubspot_skus = 0

    for key, (product, variant, sku) in easystore_by_sku.items():
        matching = hubspot_by_sku.get(key, set())
        if len(matching) > 1:
            ambiguous_hubspot_skus += 1
            print(
                f"ERROR: HubSpot SKU {sku!r} matches multiple products: " + ", ".join(sorted(matching)),
                file=sys.stderr,
            )
            continue
        properties = variant_properties(product, variant, sku)
        target_id = next(iter(matching), None)
        if target_id is None:
            creates.append({"properties": properties})
        else:
            updates.append({"id": target_id, "properties": properties})

    if duplicate_easystore_skus or ambiguous_hubspot_skus:
        raise SyncError(
            "Product sync stopped because SKU identity is ambiguous; fix duplicate SKUs before writing HubSpot products."
        )

    _batch_write(hubspot_access_token, "update", updates)
    _batch_write(hubspot_access_token, "create", creates)

    return {
        "easystore_products": easystore_products,
        "easystore_variants": easystore_variants,
        "hubspot_products_scanned": hubspot_total,
        "updated": len(updates),
        "created": len(creates),
        "synthetic_skus_for_blank_easystore_skus": synthetic_skus,
        "duplicate_easystore_skus": duplicate_easystore_skus,
        "ambiguous_hubspot_skus": ambiguous_hubspot_skus,
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
        summary = sync(
            store_domain=_required(args.store_domain, "EASYSTORE_STORE_DOMAIN"),
            easystore_access_token=_required(args.easystore_token, "EASYSTORE_ACCESS_TOKEN"),
            hubspot_access_token=_required(args.hubspot_token, "HUBSPOT_ACCESS_TOKEN"),
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
