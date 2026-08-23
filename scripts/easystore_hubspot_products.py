#!/usr/bin/env python3
"""Sync EasyStore product variants into HubSpot's Product library.

Each EasyStore variant becomes one HubSpot Product. Product publication state is
also synchronized onto HubSpot's native Product Status/active property when the
live schema exposes a lossless Active/Inactive mapping: an EasyStore product with
no ``published_at`` value is inactive, and a published product is active.
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
from typing import Any, Callable, Iterable, Iterator, NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from easystore_hubspot_schema import (
    FieldSpec,
    apply_fields,
    describe_mapping,
    field_values,
    first_present,
    iter_easystore_pages,
    nonempty,
    observed_keys,
    property_schema,
    resolve_fields,
    writable_property,
)

HUBSPOT_PRODUCTS_URL = "https://api.hubapi.com/crm/v3/objects/products"
PRODUCT_OBJECT_TYPE = "products"
EASYSTORE_PAGE_SIZE = 50
EASYSTORE_PRODUCT_VISIBILITIES = ("published", "unpublished")
BATCH_SIZE = 100

PRODUCT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(key="url", native=("hs_url",)),
    FieldSpec(key="image", native=("hs_images",)),
    FieldSpec(
        key="product_type",
        sources=("product_type", "type", "category_name", "category_title"),
        native=("hs_product_type",),
    ),
)


class ProductStatusMapping(NamedTuple):
    property_name: str
    active_value: str
    inactive_value: str


class SyncError(RuntimeError):
    """Raised when a remote API or identity invariant prevents a safe sync."""


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: Any = None,
    retries: int = 4,
    allow_statuses: set[int] | None = None,
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
            if allow_statuses and error.code in allow_statuses:
                error.read()
                return None
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

    # EasyStore documents visibility as two separate Product-list filters rather
    # than an "all" value. Read both complete, disjoint snapshots so an
    # unpublished product cannot disappear from the source and leave a stale
    # Active Product behind in HubSpot.
    for visibility in EASYSTORE_PRODUCT_VISIBILITIES:
        def fetch(page: int, *, _visibility: str = visibility) -> list[dict[str, Any]]:
            query = urlencode(
                {
                    "page": page,
                    "limit": EASYSTORE_PAGE_SIZE,
                    "sort": "id.asc",
                    "visibility": _visibility,
                }
            )
            document = _http_json(
                f"https://{domain}/api/3.0/products.json?{query}",
                headers={"EasyStore-Access-Token": access_token},
            )
            return _extract_list(document, "products", "data", "results")

        for product in iter_easystore_pages(
            fetch,
            page_size=EASYSTORE_PAGE_SIZE,
            what=f"products.json visibility={visibility}",
            error=SyncError,
        ):
            # The visibility filter itself is an explicit publication signal.
            # Some list payloads may omit published_at, so preserve that signal
            # without overriding a publication field EasyStore did return.
            if not any(
                key in product for key in ("is_published", "published", "published_at")
            ):
                product = dict(product)
                product["published"] = visibility == "published"
            yield product


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
    text = nonempty(product.get("description")) or nonempty(product.get("body_html"))
    if text is None:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split()) or None


def variant_sku(product_id: str, variant: dict[str, Any]) -> tuple[str, bool]:
    sku = nonempty(variant.get("sku"))
    if sku:
        return sku, False
    variant_id = nonempty(variant.get("id"))
    if variant_id is None:
        raise SyncError(f"EasyStore product {product_id} contains a variant without id or SKU")
    return f"ES-{product_id}-{variant_id}", True


def _product_url(product: dict[str, Any], store_domain: str | None = None) -> str | None:
    direct = first_present(product, ("url", "permalink", "online_store_url", "link"))
    if direct is not None:
        return direct if direct.startswith("http") else None
    handle = first_present(product, ("handle", "slug", "seo_url"))
    if handle is None or not store_domain:
        return None
    domain = store_domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    return f"https://{domain}/products/{handle.strip('/')}" if domain else None


def _product_image(product: dict[str, Any]) -> str | None:
    image = product.get("image")
    if isinstance(image, dict):
        found = first_present(image, ("src", "url", "image_url"))
        if found is not None:
            return found
    images = product.get("images")
    if isinstance(images, dict):
        images = [images]
    if isinstance(images, list):
        for candidate in images:
            found = (
                first_present(candidate, ("src", "url", "image_url"))
                if isinstance(candidate, dict)
                else nonempty(candidate)
            )
            if found is not None:
                return found
    return first_present(product, ("image_url", "featured_image", "thumbnail"))


def _product_type(product: dict[str, Any]) -> str | None:
    direct = first_present(
        product,
        ("product_type", "type", "category_name", "category_title"),
    )
    if direct is not None:
        return direct
    for key in ("category", "categories", "collection", "collections"):
        value = product.get(key)
        if isinstance(value, dict):
            found = first_present(value, ("name", "title", "label"))
            if found is not None:
                return found
        elif isinstance(value, list):
            for item in value:
                found = (
                    first_present(item, ("name", "title", "label"))
                    if isinstance(item, dict)
                    else nonempty(item)
                )
                if found is not None:
                    return found
    return None


def product_field_values(
    product: dict[str, Any],
    store_domain: str | None = None,
) -> dict[str, str]:
    derivations: dict[str, Callable[[dict[str, Any]], str | None]] = {
        "url": lambda item: _product_url(item, store_domain),
        "image": _product_image,
        "product_type": _product_type,
    }
    return field_values(product, PRODUCT_FIELDS, derivations)


def resolve_product_fields(
    access_token: str,
    report: dict[str, Any] | None = None,
) -> dict[str, str]:
    resolved = resolve_fields(
        http_json=_http_json,
        access_token=access_token,
        object_type=PRODUCT_OBJECT_TYPE,
        fields=PRODUCT_FIELDS,
        error=SyncError,
        optional=True,
        report=report,
    )
    if len(resolved) < len(PRODUCT_FIELDS):
        missing = sorted(field.key for field in PRODUCT_FIELDS if field.key not in resolved)
        print(
            "WARNING: catalogue fields not synchronized because HubSpot did not "
            "provide a writable property (add crm.schemas.products.read to the "
            "token to enable them): " + ", ".join(missing),
            file=sys.stderr,
        )
    return resolved


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = nonempty(value)
    if text is None:
        return None
    folded = text.casefold()
    if folded in {"true", "1", "yes", "published", "active"}:
        return True
    if folded in {"false", "0", "no", "unpublished", "inactive"}:
        return False
    return None


def easystore_product_published(product: dict[str, Any]) -> bool | None:
    """Return EasyStore publication state without confusing it with inventory.

    EasyStore's documented Product payload carries ``published_at``. Null/blank
    means unpublished and a timestamp means published. Explicit boolean-style
    publication fields are accepted when a portal supplies them. If none of
    these fields exists the sync leaves HubSpot status untouched instead of
    inventing a state from availability or stock.
    """

    for key in ("is_published", "published"):
        if key in product:
            parsed = _boolish(product.get(key))
            if parsed is not None:
                return parsed
    if "published_at" in product:
        return nonempty(product.get("published_at")) is not None
    return None


def _status_option_values(prop: dict[str, Any]) -> tuple[str, str] | None:
    options = prop.get("options")
    if not isinstance(options, list):
        return None
    active: str | None = None
    inactive: str | None = None
    for option in options:
        if not isinstance(option, dict):
            continue
        value = nonempty(option.get("value"))
        if value is None:
            continue
        labels = {
            text.casefold()
            for text in (
                nonempty(option.get("label")),
                value,
            )
            if text is not None
        }
        if "active" in labels:
            active = value
        if "inactive" in labels:
            inactive = value
    if active is None or inactive is None:
        return None
    return active, inactive


def _status_tokens(name: str, prop: dict[str, Any]) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", f"{name} {prop.get('label') or ''}".casefold()))


def resolve_product_status_mapping(access_token: str) -> ProductStatusMapping | None:
    """Resolve HubSpot's native Active/Inactive product property losslessly."""

    schema = property_schema(
        http_json=_http_json,
        access_token=access_token,
        object_type=PRODUCT_OBJECT_TYPE,
        error=SyncError,
        optional=True,
    )
    if schema is None:
        return None

    # Prefer the known native names, but read the portal's actual option values.
    for name in ("hs_product_status", "hs_active"):
        prop = schema.get(name)
        if not isinstance(prop, dict):
            continue
        if writable_property(prop, "enumeration"):
            values = _status_option_values(prop)
            if values is not None:
                return ProductStatusMapping(name, values[0], values[1])
        if name == "hs_active" and writable_property(prop, "bool"):
            return ProductStatusMapping(name, "true", "false")

    # Portals can expose a different internal name. Only accept one unambiguous
    # HubSpot-defined property whose semantics and option set say Product Status.
    enum_candidates: list[ProductStatusMapping] = []
    bool_candidates: list[ProductStatusMapping] = []
    for name, prop in schema.items():
        if not bool(prop.get("hubspotDefined")):
            continue
        tokens = _status_tokens(name, prop)
        if writable_property(prop, "enumeration") and "status" in tokens:
            values = _status_option_values(prop)
            if values is not None and ("product" in tokens or name.startswith("hs_product")):
                enum_candidates.append(ProductStatusMapping(name, values[0], values[1]))
        if writable_property(prop, "bool") and "active" in tokens and "product" in tokens:
            bool_candidates.append(ProductStatusMapping(name, "true", "false"))

    candidates = enum_candidates or bool_candidates
    return candidates[0] if len(candidates) == 1 else None


def variant_properties(
    product: dict[str, Any],
    variant: dict[str, Any],
    sku: str,
    field_properties: dict[str, str] | None = None,
    store_domain: str | None = None,
    status_mapping: ProductStatusMapping | None = None,
) -> dict[str, str]:
    title = (
        nonempty(product.get("title"))
        or nonempty(product.get("name"))
        or f"EasyStore product {product.get('id')}"
    )
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

    if field_properties:
        apply_fields(props, product_field_values(product, store_domain), field_properties)

    published = easystore_product_published(product)
    if status_mapping is not None and published is not None:
        props[status_mapping.property_name] = (
            status_mapping.active_value if published else status_mapping.inactive_value
        )
    return props


def chunked(items: list[Any], size: int = BATCH_SIZE) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def assert_batch_success(
    document: Any,
    *,
    action: str,
    expected_count: int,
) -> None:
    if not isinstance(document, dict):
        raise SyncError(f"HubSpot product batch {action} returned an invalid response")

    errors = document.get("errors")
    try:
        num_errors = int(document.get("numErrors") or 0)
    except (TypeError, ValueError):
        num_errors = 1
    if num_errors or (isinstance(errors, list) and errors):
        detail = json.dumps(errors[:3], ensure_ascii=False) if isinstance(errors, list) else repr(errors)
        raise SyncError(
            f"HubSpot product batch {action} reported {num_errors or 'one or more'} "
            f"item errors: {detail[:1500]}"
        )

    status = str(document.get("status") or "").upper()
    if status and status != "COMPLETE":
        raise SyncError(f"HubSpot product batch {action} did not complete synchronously: {status}")

    results = document.get("results")
    if not isinstance(results, list) or len(results) != expected_count:
        actual = len(results) if isinstance(results, list) else "missing"
        raise SyncError(
            f"HubSpot product batch {action} returned {actual} results for {expected_count} inputs"
        )


def _batch_write(access_token: str, action: str, inputs: list[dict[str, Any]]) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}
    for batch_number, batch in enumerate(chunked(inputs), start=1):
        traced: list[dict[str, Any]] = []
        for item_number, item in enumerate(batch, start=1):
            traced_item = dict(item)
            traced_item["objectWriteTraceId"] = f"products-{action}-{batch_number}-{item_number}"
            traced.append(traced_item)

        response = _http_json(
            f"{HUBSPOT_PRODUCTS_URL}/batch/{action}",
            method="POST",
            headers=headers,
            payload={"inputs": traced},
        )
        assert_batch_success(response, action=action, expected_count=len(traced))


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
) -> dict[str, Any]:
    schema_report: dict[str, Any] = {}
    product_field_properties = resolve_product_fields(hubspot_access_token, schema_report)
    status_mapping = resolve_product_status_mapping(hubspot_access_token)
    print(
        "Catalogue fields mapped to HubSpot properties: " + describe_mapping(product_field_properties),
        file=sys.stderr,
    )
    if status_mapping is None:
        print(
            "WARNING: HubSpot native Product Status could not be resolved losslessly; "
            "publication status will be left unchanged. crm.schemas.products.read is "
            "required to inspect the native status options.",
            file=sys.stderr,
        )
    else:
        print(
            f"EasyStore publication mapped to HubSpot {status_mapping.property_name} "
            f"({status_mapping.active_value!r}/{status_mapping.inactive_value!r}).",
            file=sys.stderr,
        )

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
    product_keys: set[str] = set()
    variant_keys: set[str] = set()
    easystore_products = 0
    easystore_variants = 0
    synthetic_skus = 0
    duplicate_easystore_skus = 0
    published_products = 0
    unpublished_products = 0
    publication_unknown_products = 0

    for product in iter_easystore_products(store_domain, easystore_access_token):
        easystore_products += 1
        observed_keys(product_keys, product)
        publication = easystore_product_published(product)
        if publication is True:
            published_products += 1
        elif publication is False:
            unpublished_products += 1
        else:
            publication_unknown_products += 1

        product_id = nonempty(product.get("id"))
        if product_id is None:
            continue
        for variant in product_variants(store_domain, easystore_access_token, product):
            easystore_variants += 1
            observed_keys(variant_keys, variant)
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
    active_variants = 0
    inactive_variants = 0
    status_unknown_variants = 0
    field_coverage: dict[str, int] = {field.key: 0 for field in PRODUCT_FIELDS}

    for key, (product, variant, sku) in easystore_by_sku.items():
        matching = hubspot_by_sku.get(key, set())
        if len(matching) > 1:
            ambiguous_hubspot_skus += 1
            print(
                f"ERROR: HubSpot SKU {sku!r} matches multiple products: " + ", ".join(sorted(matching)),
                file=sys.stderr,
            )
            continue

        publication = easystore_product_published(product)
        if publication is True:
            active_variants += 1
        elif publication is False:
            inactive_variants += 1
        else:
            status_unknown_variants += 1

        properties = variant_properties(
            product,
            variant,
            sku,
            product_field_properties,
            store_domain,
            status_mapping,
        )
        for field_key in product_field_values(product, store_domain):
            field_coverage[field_key] += 1
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
        "easystore_published_products": published_products,
        "easystore_unpublished_products": unpublished_products,
        "easystore_publication_unknown_products": publication_unknown_products,
        "hubspot_products_scanned": hubspot_total,
        "updated": len(updates),
        "created": len(creates),
        "hubspot_product_status_property": status_mapping.property_name if status_mapping else None,
        "hubspot_variants_marked_active": active_variants if status_mapping else 0,
        "hubspot_variants_marked_inactive": inactive_variants if status_mapping else 0,
        "hubspot_variants_publication_unknown": status_unknown_variants,
        "synthetic_skus_for_blank_easystore_skus": synthetic_skus,
        "duplicate_easystore_skus": duplicate_easystore_skus,
        "ambiguous_hubspot_skus": ambiguous_hubspot_skus,
        "hubspot_catalogue_field_properties": dict(sorted(product_field_properties.items())),
        "easystore_catalogue_field_coverage": dict(sorted(field_coverage.items())),
        "easystore_product_keys_seen": sorted(product_keys),
        "easystore_variant_keys_seen": sorted(variant_keys),
        "hubspot_product_property_hints": schema_report.get("hints", {}),
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
