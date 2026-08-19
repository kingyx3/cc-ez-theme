#!/usr/bin/env python3
"""Sync EasyStore orders into HubSpot Orders with product-backed Line Items.

The sync assumes the product and customer stages run first:

* EasyStore variants are already present as HubSpot Products keyed by ``hs_sku``.
* EasyStore customers are already present as HubSpot Contacts keyed by normalized
  mobile number.

Each EasyStore order is identified in HubSpot by a custom unique
``easystore_order_id`` property that this script creates on first run. Each
distinct product SKU within an order becomes one HubSpot Line Item backed by the
matching HubSpot Product via ``hs_product_id``. Existing order line items are
matched by SKU so scheduled reruns update rather than duplicate them.

Only Python's standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


EASYSTORE_PAGE_SIZE = 50
HUBSPOT_PAGE_SIZE = 100
HUBSPOT_BASE = "https://api.hubapi.com"
HUBSPOT_ORDERS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/order"
HUBSPOT_LINE_ITEMS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/line_items"
HUBSPOT_PRODUCTS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/products"
HUBSPOT_CONTACTS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/contacts"
ORDER_CONTACT_ASSOCIATION_TYPE_ID = 507
ORDER_LINE_ITEM_ASSOCIATION_TYPE_ID = 513
ORDER_EXTERNAL_ID_PROPERTY = "easystore_order_id"
PROPERTY_GROUP = "easystore_sync"
PHONE_MIN_DIGITS = 7
PHONE_MAX_DIGITS = 15

COUNTRY_DIAL_CODES = {
    "AU": "61",
    "CA": "1",
    "CN": "86",
    "GB": "44",
    "HK": "852",
    "ID": "62",
    "IN": "91",
    "JP": "81",
    "KR": "82",
    "MY": "60",
    "NZ": "64",
    "PH": "63",
    "SG": "65",
    "TH": "66",
    "TW": "886",
    "US": "1",
    "VN": "84",
}


class SyncError(RuntimeError):
    """Raised when an API or identity invariant prevents a safe order sync."""


def nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_mobile(
    value: Any,
    country_code: Any = None,
    fallback_dial_code: str = "65",
) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    digits = _digits(raw)
    if not digits:
        return None

    if raw.startswith("+"):
        international = digits
    elif raw.startswith("00"):
        international = digits[2:]
    else:
        iso = str(country_code or "").strip().upper()
        dial_code = COUNTRY_DIAL_CODES.get(iso) or _digits(fallback_dial_code)
        if not dial_code:
            return None
        if digits.startswith(dial_code):
            international = digits
        else:
            local = digits[1:] if digits.startswith("0") else digits
            international = dial_code + local

    if not (PHONE_MIN_DIGITS <= len(international) <= PHONE_MAX_DIGITS):
        return None
    if international.startswith("0"):
        return None
    return f"+{international}"


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
        "User-Agent": "cc-ez-theme-order-sync/1.0",
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


def _shop_domain(value: str) -> str:
    return (
        value.strip()
        .removeprefix("https://")
        .removeprefix("http://")
        .rstrip("/")
    )


def iter_easystore_orders(
    store_domain: str,
    access_token: str,
) -> Iterator[dict[str, Any]]:
    domain = _shop_domain(store_domain)
    page = 1
    while True:
        query = urlencode(
            {
                "page": page,
                "limit": EASYSTORE_PAGE_SIZE,
                "sort": "id.asc",
            }
        )
        document = _http_json(
            f"https://{domain}/api/3.0/orders.json?{query}",
            headers={"EasyStore-Access-Token": access_token},
        )
        orders = _extract_list(document, "orders", "data", "results")
        for order in orders:
            yield order
        if len(orders) < EASYSTORE_PAGE_SIZE:
            break
        page += 1


def complete_order(
    store_domain: str,
    access_token: str,
    order: dict[str, Any],
) -> dict[str, Any]:
    """Return an order carrying line_items, fetching detail when list data is thin."""

    if isinstance(order.get("line_items"), list):
        return order

    order_id = nonempty(order.get("id"))
    if order_id is None:
        return order

    domain = _shop_domain(store_domain)
    document = _http_json(
        f"https://{domain}/api/3.0/orders/{order_id}.json",
        headers={"EasyStore-Access-Token": access_token},
    )
    if isinstance(document, dict):
        candidate = document.get("order")
        if isinstance(candidate, dict):
            return candidate
        candidate = document.get("data")
        if isinstance(candidate, dict):
            nested = candidate.get("order")
            return nested if isinstance(nested, dict) else candidate
        return document
    return order


def iter_hubspot_objects(
    url: str,
    access_token: str,
    properties: str,
) -> Iterator[dict[str, Any]]:
    after: str | None = None
    while True:
        params = {
            "limit": str(HUBSPOT_PAGE_SIZE),
            "properties": properties,
            "archived": "false",
        }
        if after is not None:
            params["after"] = after
        document = _http_json(
            f"{url}?{urlencode(params)}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        results = document.get("results", []) if isinstance(document, dict) else []
        for record in results:
            if isinstance(record, dict):
                yield record

        paging = document.get("paging", {}) if isinstance(document, dict) else {}
        nxt = paging.get("next", {}) if isinstance(paging, dict) else {}
        next_after = nxt.get("after") if isinstance(nxt, dict) else None
        if next_after is None:
            break
        after = str(next_after)


def ensure_order_identity_property(access_token: str) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}
    group_url = f"{HUBSPOT_BASE}/crm/v3/properties/order/groups/{PROPERTY_GROUP}"
    group = _http_json(group_url, headers=headers, allow_statuses={404})
    if group is None:
        _http_json(
            f"{HUBSPOT_BASE}/crm/v3/properties/order/groups",
            method="POST",
            headers=headers,
            payload={
                "name": PROPERTY_GROUP,
                "label": "EasyStore Sync",
                "displayOrder": -1,
            },
        )

    property_url = (
        f"{HUBSPOT_BASE}/crm/v3/properties/order/{ORDER_EXTERNAL_ID_PROPERTY}"
    )
    prop = _http_json(property_url, headers=headers, allow_statuses={404})
    if prop is None:
        _http_json(
            f"{HUBSPOT_BASE}/crm/v3/properties/order",
            method="POST",
            headers=headers,
            payload={
                "groupName": PROPERTY_GROUP,
                "name": ORDER_EXTERNAL_ID_PROPERTY,
                "label": "EasyStore Order ID",
                "description": "Immutable EasyStore order ID used for CRM synchronization.",
                "hasUniqueValue": True,
                "type": "string",
                "fieldType": "text",
                "formField": False,
            },
        )
        return

    if not bool(prop.get("hasUniqueValue")):
        raise SyncError(
            f"HubSpot property {ORDER_EXTERNAL_ID_PROPERTY!r} exists but is not unique. "
            "Archive/replace it as a unique property before running the order sync."
        )


def hubspot_product_index(access_token: str) -> dict[str, str]:
    by_sku: dict[str, set[str]] = defaultdict(set)
    for product in iter_hubspot_objects(
        HUBSPOT_PRODUCTS_URL,
        access_token,
        "hs_sku",
    ):
        product_id = nonempty(product.get("id"))
        properties = product.get("properties")
        if product_id is None or not isinstance(properties, dict):
            continue
        sku = nonempty(properties.get("hs_sku"))
        if sku:
            by_sku[sku.casefold()].add(product_id)

    ambiguous = {sku: ids for sku, ids in by_sku.items() if len(ids) > 1}
    if ambiguous:
        sample = "; ".join(
            f"{sku}: {','.join(sorted(ids))}"
            for sku, ids in list(ambiguous.items())[:10]
        )
        raise SyncError(
            "HubSpot product SKU identity is ambiguous; product-backed order "
            f"line items cannot be resolved safely. {sample}"
        )
    return {sku: next(iter(ids)) for sku, ids in by_sku.items()}


def hubspot_contact_phone_index(
    access_token: str,
    fallback_dial_code: str,
) -> dict[str, set[str]]:
    by_phone: dict[str, set[str]] = defaultdict(set)
    for contact in iter_hubspot_objects(
        HUBSPOT_CONTACTS_URL,
        access_token,
        "phone,mobilephone",
    ):
        contact_id = nonempty(contact.get("id"))
        properties = contact.get("properties")
        if contact_id is None or not isinstance(properties, dict):
            continue
        for field in ("mobilephone", "phone"):
            mobile = normalize_mobile(
                properties.get(field),
                fallback_dial_code=fallback_dial_code,
            )
            if mobile:
                by_phone[mobile].add(contact_id)
    return by_phone


def hubspot_order_index(access_token: str) -> dict[str, str]:
    by_external_id: dict[str, set[str]] = defaultdict(set)
    for order in iter_hubspot_objects(
        HUBSPOT_ORDERS_URL,
        access_token,
        ORDER_EXTERNAL_ID_PROPERTY,
    ):
        hubspot_id = nonempty(order.get("id"))
        properties = order.get("properties")
        if hubspot_id is None or not isinstance(properties, dict):
            continue
        external_id = nonempty(properties.get(ORDER_EXTERNAL_ID_PROPERTY))
        if external_id:
            by_external_id[external_id].add(hubspot_id)

    duplicates = {
        external_id: ids
        for external_id, ids in by_external_id.items()
        if len(ids) > 1
    }
    if duplicates:
        sample = "; ".join(
            f"{external_id}: {','.join(sorted(ids))}"
            for external_id, ids in list(duplicates.items())[:10]
        )
        raise SyncError(
            "Multiple HubSpot orders carry the same EasyStore order ID. "
            f"Resolve the duplicates before syncing. {sample}"
        )

    return {
        external_id: next(iter(ids))
        for external_id, ids in by_external_id.items()
    }


def _order_address(order: dict[str, Any]) -> dict[str, Any]:
    for key in ("shipping_address", "billing_address"):
        value = order.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _tracking(order: dict[str, Any]) -> tuple[str | None, str | None]:
    fulfillments = order.get("fulfillments")
    if isinstance(fulfillments, dict):
        fulfillments = [fulfillments]
    if not isinstance(fulfillments, list):
        fulfillment = order.get("fulfillment")
        fulfillments = [fulfillment] if isinstance(fulfillment, dict) else []

    numbers: list[str] = []
    urls: list[str] = []
    for fulfillment in fulfillments:
        if not isinstance(fulfillment, dict):
            continue
        number = nonempty(
            fulfillment.get("tracking_number")
            or fulfillment.get("tracking_no")
        )
        url = nonempty(
            fulfillment.get("tracking_url")
            or fulfillment.get("tracking_status_url")
        )
        if number and number not in numbers:
            numbers.append(number)
        if url and url not in urls:
            urls.append(url)
    return (
        ", ".join(numbers) if numbers else None,
        urls[0] if urls else None,
    )


def order_properties(
    order: dict[str, Any],
    *,
    external_id: str,
    store_domain: str,
) -> dict[str, str]:
    name = (
        nonempty(order.get("name"))
        or nonempty(order.get("order_number"))
        or nonempty(order.get("ref_number"))
        or f"EasyStore order {external_id}"
    )

    properties: dict[str, str] = {
        ORDER_EXTERNAL_ID_PROPERTY: external_id,
        "hs_order_name": name,
        "hs_source_store": _shop_domain(store_domain),
    }

    currency = nonempty(order.get("currency") or order.get("currency_code"))
    if currency:
        properties["hs_currency_code"] = currency.upper()

    fulfillment = nonempty(
        order.get("fulfillment_status_label")
        or order.get("fulfillment_status")
    )
    if fulfillment:
        properties["hs_fulfillment_status"] = fulfillment

    address = _order_address(order)
    address1 = nonempty(address.get("address1"))
    address2 = nonempty(address.get("address2"))
    if address1 and address2:
        properties["hs_shipping_address_street"] = f"{address1}\n{address2}"
    elif address1 or address2:
        properties["hs_shipping_address_street"] = address1 or address2 or ""

    city = nonempty(address.get("city"))
    if city:
        properties["hs_shipping_address_city"] = city
    postal = nonempty(address.get("zip") or address.get("postal_code"))
    if postal:
        properties["hs_shipping_address_postal_code"] = postal

    tracking_number, tracking_url = _tracking(order)
    if tracking_number:
        properties["hs_shipping_tracking_number"] = tracking_number
    if tracking_url:
        properties["hs_shipping_status_url"] = tracking_url
    return properties


def _order_customer_phone(
    order: dict[str, Any],
    fallback_dial_code: str,
) -> str | None:
    candidates: list[tuple[Any, Any]] = []

    customer = order.get("customer")
    if isinstance(customer, dict):
        candidates.append(
            (
                customer.get("phone"),
                customer.get("country_code"),
            )
        )

    for key in ("billing_address", "shipping_address"):
        address = order.get(key)
        if isinstance(address, dict):
            candidates.append(
                (
                    address.get("phone"),
                    address.get("country_code"),
                )
            )

    candidates.append(
        (
            order.get("phone"),
            order.get("country_code"),
        )
    )

    for value, country_code in candidates:
        normalized = normalize_mobile(
            value,
            country_code,
            fallback_dial_code,
        )
        if normalized:
            return normalized
    return None


def _line_sku(line: dict[str, Any]) -> str | None:
    sku = nonempty(line.get("sku"))
    if sku:
        return sku

    variant = line.get("variant")
    product = line.get("product")
    variant_id = nonempty(
        line.get("variant_id")
        or (variant.get("id") if isinstance(variant, dict) else None)
    )
    product_id = nonempty(
        line.get("product_id")
        or (product.get("id") if isinstance(product, dict) else None)
    )
    if product_id and variant_id:
        return f"ES-{product_id}-{variant_id}"
    return None


def _line_name(line: dict[str, Any], sku: str) -> str:
    return (
        nonempty(line.get("title"))
        or nonempty(line.get("name"))
        or nonempty(line.get("product_name"))
        or sku
    )


def _line_quantity(line: dict[str, Any]) -> int:
    raw = line.get("quantity")
    try:
        quantity = int(raw)
    except (TypeError, ValueError):
        raise SyncError(f"EasyStore line item has invalid quantity {raw!r}") from None
    if quantity < 0:
        raise SyncError(f"EasyStore line item has negative quantity {quantity}")
    return quantity


def _line_price(line: dict[str, Any]) -> str | None:
    for key in ("price", "final_price", "unit_price"):
        value = nonempty(line.get(key))
        if value is not None:
            return value
    return None


def desired_lines(
    order: dict[str, Any],
    product_by_sku: dict[str, str],
) -> dict[str, dict[str, str]]:
    lines = order.get("line_items")
    if not isinstance(lines, list):
        lines = []

    currency = nonempty(order.get("currency") or order.get("currency_code"))
    grouped: dict[str, dict[str, str]] = {}
    for line in lines:
        if not isinstance(line, dict):
            continue

        sku = _line_sku(line)
        if sku is None:
            raise SyncError(
                f"EasyStore order {order.get('id')} contains a line item without "
                "SKU or product/variant IDs, so it cannot be product-backed."
            )

        product_id = product_by_sku.get(sku.casefold())
        if product_id is None:
            raise SyncError(
                f"EasyStore order {order.get('id')} line SKU {sku!r} has no matching "
                "HubSpot Product. Product sync must complete successfully first."
            )

        quantity = _line_quantity(line)
        if quantity == 0:
            continue

        key = sku.casefold()
        price = _line_price(line)
        if key in grouped:
            existing = grouped[key]
            if price is not None and existing.get("price") not in (None, price):
                raise SyncError(
                    f"EasyStore order {order.get('id')} repeats SKU {sku!r} with "
                    "different unit prices; refusing to merge ambiguous lines."
                )
            existing["quantity"] = str(int(existing["quantity"]) + quantity)
            continue

        properties: dict[str, str] = {
            "name": _line_name(line, sku),
            "hs_sku": sku,
            "hs_product_id": product_id,
            "quantity": str(quantity),
        }
        if price is not None:
            properties["price"] = price
        if currency:
            properties["hs_line_item_currency_code"] = currency.upper()
        grouped[key] = properties
    return grouped


def _existing_order_line_items(
    access_token: str,
    hubspot_order_id: str,
) -> dict[str, dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    associations = _http_json(
        f"{HUBSPOT_ORDERS_URL}/{hubspot_order_id}/associations/line_items",
        headers=headers,
    )
    results = associations.get("results", []) if isinstance(associations, dict) else []

    by_sku: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        line_id = nonempty(result.get("id"))
        if line_id is None:
            continue
        line = _http_json(
            f"{HUBSPOT_LINE_ITEMS_URL}/{line_id}?"
            + urlencode(
                {
                    "properties": (
                        "hs_sku,hs_product_id,name,quantity,price,"
                        "hs_line_item_currency_code"
                    )
                }
            ),
            headers=headers,
        )
        properties = line.get("properties")
        if not isinstance(properties, dict):
            continue
        sku = nonempty(properties.get("hs_sku"))
        if sku is None:
            continue
        key = sku.casefold()
        if key in by_sku:
            raise SyncError(
                f"HubSpot order {hubspot_order_id} has multiple line items for "
                f"SKU {sku!r}; cannot safely choose one to update."
            )
        by_sku[key] = line
    return by_sku


def _upsert_hubspot_order(
    access_token: str,
    existing_id: str | None,
    properties: dict[str, str],
) -> tuple[str, bool]:
    headers = {"Authorization": f"Bearer {access_token}"}
    if existing_id is None:
        response = _http_json(
            HUBSPOT_ORDERS_URL,
            method="POST",
            headers=headers,
            payload={"properties": properties},
        )
        hubspot_id = nonempty(response.get("id")) if isinstance(response, dict) else None
        if hubspot_id is None:
            raise SyncError("HubSpot created an order without returning its ID")
        return hubspot_id, True

    _http_json(
        f"{HUBSPOT_ORDERS_URL}/{existing_id}",
        method="PATCH",
        headers=headers,
        payload={"properties": properties},
    )
    return existing_id, False


def _associate_order(
    access_token: str,
    hubspot_order_id: str,
    object_type: str,
    object_id: str,
    association_type_id: int,
) -> None:
    _http_json(
        (
            f"{HUBSPOT_ORDERS_URL}/{hubspot_order_id}/associations/"
            f"{object_type}/{object_id}/{association_type_id}"
        ),
        method="PUT",
        headers={"Authorization": f"Bearer {access_token}"},
    )


def sync_line_items(
    *,
    access_token: str,
    hubspot_order_id: str,
    desired: dict[str, dict[str, str]],
) -> tuple[int, int]:
    existing = _existing_order_line_items(access_token, hubspot_order_id)
    headers = {"Authorization": f"Bearer {access_token}"}
    created = 0
    updated = 0

    for key, properties in desired.items():
        current = existing.get(key)
        if current is None:
            response = _http_json(
                HUBSPOT_LINE_ITEMS_URL,
                method="POST",
                headers=headers,
                payload={"properties": properties},
            )
            line_id = nonempty(response.get("id")) if isinstance(response, dict) else None
            if line_id is None:
                raise SyncError(
                    f"HubSpot created line item {properties.get('hs_sku')!r} "
                    "without returning its ID"
                )
            _associate_order(
                access_token,
                hubspot_order_id,
                "line_items",
                line_id,
                ORDER_LINE_ITEM_ASSOCIATION_TYPE_ID,
            )
            created += 1
            continue

        line_id = nonempty(current.get("id"))
        current_properties = current.get("properties")
        if line_id is None or not isinstance(current_properties, dict):
            raise SyncError(
                f"HubSpot order {hubspot_order_id} returned an unusable line item"
            )

        wanted_product_id = properties["hs_product_id"]
        current_product_id = nonempty(current_properties.get("hs_product_id"))
        if current_product_id and current_product_id != wanted_product_id:
            _http_json(
                f"{HUBSPOT_LINE_ITEMS_URL}/{line_id}",
                method="DELETE",
                headers=headers,
            )
            response = _http_json(
                HUBSPOT_LINE_ITEMS_URL,
                method="POST",
                headers=headers,
                payload={"properties": properties},
            )
            new_id = nonempty(response.get("id")) if isinstance(response, dict) else None
            if new_id is None:
                raise SyncError(
                    f"HubSpot recreated line item {properties.get('hs_sku')!r} "
                    "without returning its ID"
                )
            _associate_order(
                access_token,
                hubspot_order_id,
                "line_items",
                new_id,
                ORDER_LINE_ITEM_ASSOCIATION_TYPE_ID,
            )
            created += 1
            continue

        update_properties = {
            key_name: value
            for key_name, value in properties.items()
            if key_name != "hs_product_id"
        }
        _http_json(
            f"{HUBSPOT_LINE_ITEMS_URL}/{line_id}",
            method="PATCH",
            headers=headers,
            payload={"properties": update_properties},
        )
        updated += 1

    return created, updated


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, int]:
    ensure_order_identity_property(hubspot_access_token)

    product_by_sku = hubspot_product_index(hubspot_access_token)
    contacts_by_phone = hubspot_contact_phone_index(
        hubspot_access_token,
        fallback_dial_code,
    )
    existing_orders = hubspot_order_index(hubspot_access_token)

    orders: list[tuple[dict[str, Any], str, dict[str, dict[str, str]]]] = []
    easystore_orders = 0
    easystore_lines = 0

    # Validate every order and product reference before making order/line writes.
    for listed in iter_easystore_orders(store_domain, easystore_access_token):
        easystore_orders += 1
        order = complete_order(store_domain, easystore_access_token, listed)
        external_id = nonempty(order.get("id"))
        if external_id is None:
            raise SyncError("EasyStore returned an order without an id")
        desired = desired_lines(order, product_by_sku)
        easystore_lines += sum(int(line["quantity"]) for line in desired.values())
        orders.append((order, external_id, desired))

    created_orders = 0
    updated_orders = 0
    created_lines = 0
    updated_lines = 0
    contact_associations = 0
    orders_without_mobile = 0
    ambiguous_contact_mobile = 0

    for order, external_id, desired in orders:
        hubspot_order_id, created = _upsert_hubspot_order(
            hubspot_access_token,
            existing_orders.get(external_id),
            order_properties(
                order,
                external_id=external_id,
                store_domain=store_domain,
            ),
        )
        existing_orders[external_id] = hubspot_order_id
        if created:
            created_orders += 1
        else:
            updated_orders += 1

        mobile = _order_customer_phone(order, fallback_dial_code)
        if mobile is None:
            orders_without_mobile += 1
        else:
            matching_contacts = contacts_by_phone.get(mobile, set())
            if len(matching_contacts) == 1:
                contact_id = next(iter(matching_contacts))
                _associate_order(
                    hubspot_access_token,
                    hubspot_order_id,
                    "contact",
                    contact_id,
                    ORDER_CONTACT_ASSOCIATION_TYPE_ID,
                )
                contact_associations += 1
            elif len(matching_contacts) > 1:
                ambiguous_contact_mobile += 1
                print(
                    f"WARNING: EasyStore order {external_id} mobile {mobile} "
                    "matches multiple HubSpot contacts; order-contact association skipped.",
                    file=sys.stderr,
                )

        line_created, line_updated = sync_line_items(
            access_token=hubspot_access_token,
            hubspot_order_id=hubspot_order_id,
            desired=desired,
        )
        created_lines += line_created
        updated_lines += line_updated

    return {
        "easystore_orders": easystore_orders,
        "easystore_line_item_units": easystore_lines,
        "hubspot_orders_created": created_orders,
        "hubspot_orders_updated": updated_orders,
        "hubspot_line_items_created": created_lines,
        "hubspot_line_items_updated": updated_lines,
        "order_contact_associations_ensured": contact_associations,
        "orders_without_usable_mobile": orders_without_mobile,
        "orders_with_ambiguous_contact_mobile": ambiguous_contact_mobile,
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
    parser.add_argument(
        "--fallback-dial-code",
        default=os.getenv("CUSTOMER_SYNC_DEFAULT_DIAL_CODE", "65"),
    )
    args = parser.parse_args(argv)

    try:
        summary = sync(
            store_domain=_required(args.store_domain, "EASYSTORE_STORE_DOMAIN"),
            easystore_access_token=_required(
                args.easystore_token,
                "EASYSTORE_ACCESS_TOKEN",
            ),
            hubspot_access_token=_required(
                args.hubspot_token,
                "HUBSPOT_ACCESS_TOKEN",
            ),
            fallback_dial_code=args.fallback_dial_code,
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
