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

Alongside identity, shipping and tracking, each order carries its commerce state:
creation timestamp, payment status, fulfilment status, total amount, discount
amount and discount codes. A buyer resolved to a single HubSpot Contact is also
promoted to the ``customer`` lifecycle stage, because an order proves a purchase.

HubSpot's native Order schema differs between portals, so the commerce fields are
resolved against the live schema and fall back to provisioned ``easystore_*``
properties when the portal has no writable native property of the right shape.

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
from typing import Any, Callable, Iterator, NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from easystore_hubspot_schema import (
    FieldSpec,
    PROPERTY_GROUP,
    apply_fields,
    describe_mapping,
    ensure_property_group,
    field_values,
    first_present,
    nonempty,
    observed_keys,
    resolve_fields,
)


EASYSTORE_PAGE_SIZE = 50
HUBSPOT_PAGE_SIZE = 100
HUBSPOT_BASE = "https://api.hubapi.com"
HUBSPOT_ORDERS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/order"
HUBSPOT_LINE_ITEMS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/line_items"
HUBSPOT_PRODUCTS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/products"
HUBSPOT_CONTACTS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/contacts"
ORDER_CONTACT_ASSOCIATION_TYPE_ID = 507
ORDER_LINE_ITEM_ASSOCIATION_TYPE_ID = 513
ORDER_OBJECT_TYPE = "order"
LINE_ITEM_OBJECT_TYPE = "line_items"
ORDER_EXTERNAL_ID_PROPERTY = "easystore_order_id"
CONTACT_LIFECYCLE_PROPERTY = "lifecyclestage"
LIFECYCLE_CUSTOMER = "customer"

# HubSpot refuses to move a contact backwards through the default lifecycle
# pipeline, so a stage is only written when it is a genuine step forward. A stage
# outside this ordering belongs to a custom pipeline and is never overwritten.
LIFECYCLE_STAGE_RANKS = {
    "subscriber": 1,
    "lead": 2,
    "marketingqualifiedlead": 3,
    "salesqualifiedlead": 4,
    "opportunity": 5,
    "customer": 6,
    "evangelist": 7,
}

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

# HubSpot field types used when provisioning an easystore_* order property.
class SyncError(RuntimeError):
    """Raised when an API or identity invariant prevents a safe order sync."""


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def lifecycle_stage_write(current: Any, target: str) -> str | None:
    """Return the lifecycle stage to write, or ``None`` to leave HubSpot alone.

    A contact keeps the furthest stage it has already reached, and a stage from a
    custom pipeline is never overwritten by this sync.
    """

    existing = nonempty(current)
    if existing is None:
        return target

    current_rank = LIFECYCLE_STAGE_RANKS.get(existing.casefold())
    if current_rank is None:
        return None
    if current_rank >= LIFECYCLE_STAGE_RANKS[target]:
        return None
    return target


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
    if len(set(digits)) == 1:
        # Placeholders such as 0000000 are not a recorded mobile number.
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
    *,
    commerce_fields: bool = True,
) -> dict[str, Any]:
    """Return a complete order, fetching the detail when list data is thin.

    ``commerce_fields`` is what the order stage needs: addresses and totals as
    well as line items. The reconciliation stage only reads line items, so it
    opts out and keeps its request count unchanged.
    """

    thin = order_needs_detail(order) if commerce_fields else not isinstance(
        order.get("line_items"), list
    )
    if not thin:
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
    ensure_property_group(
        http_json=_http_json,
        access_token=access_token,
        object_type=ORDER_OBJECT_TYPE,
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


class ContactIndex(NamedTuple):
    """HubSpot contacts indexed for order association and lifecycle promotion."""

    by_phone: dict[str, set[str]]
    lifecycle_by_id: dict[str, str]


def hubspot_contact_index(
    access_token: str,
    fallback_dial_code: str,
) -> ContactIndex:
    by_phone: dict[str, set[str]] = defaultdict(set)
    lifecycle_by_id: dict[str, str] = {}
    for contact in iter_hubspot_objects(
        HUBSPOT_CONTACTS_URL,
        access_token,
        f"phone,mobilephone,{CONTACT_LIFECYCLE_PROPERTY}",
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
        stage = nonempty(properties.get(CONTACT_LIFECYCLE_PROPERTY))
        if stage is not None:
            lifecycle_by_id[contact_id] = stage
    return ContactIndex(by_phone=by_phone, lifecycle_by_id=lifecycle_by_id)


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


ADDRESS_KEYS = ("shipping_address", "billing_address", "address")


def _usable_address(address: Any) -> bool:
    """Report whether an address says where to deliver, not just which country.

    EasyStore's order list returns a stub address carrying only a country, which
    is present enough to look like an address and useless for delivery.
    """

    if not isinstance(address, dict):
        return False
    return (
        first_present(address, ("address1", "address_1", "street", "line1")) is not None
        or first_present(address, ("city", "town")) is not None
    )


def _order_address(order: dict[str, Any]) -> dict[str, Any]:
    """Return the address to ship to, falling back to the billing address.

    A stub is never preferred over a real address: the first candidate that says
    where to deliver wins, and only if none does is a stub returned so its country
    still reaches the CRM.
    """

    for key in ADDRESS_KEYS:
        value = order.get(key)
        if _usable_address(value):
            return value
    for key in ADDRESS_KEYS:
        value = order.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _billing_address(order: dict[str, Any]) -> dict[str, Any]:
    value = order.get("billing_address")
    return value if isinstance(value, dict) else {}


def _address_street(address: dict[str, Any]) -> str | None:
    """Return the street lines of an address as one multi-line value."""

    address1 = first_present(address, ("address1", "address_1", "street", "line1"))
    address2 = first_present(address, ("address2", "address_2", "unit", "line2"))
    if address1 and address2:
        return f"{address1}\n{address2}"
    return address1 or address2


def _fulfillments(order: dict[str, Any]) -> list[dict[str, Any]]:
    fulfillments = order.get("fulfillments")
    if isinstance(fulfillments, dict):
        fulfillments = [fulfillments]
    if not isinstance(fulfillments, list):
        fulfillment = order.get("fulfillment")
        fulfillments = [fulfillment] if isinstance(fulfillment, dict) else []
    return [item for item in fulfillments if isinstance(item, dict)]


def _tracking(order: dict[str, Any]) -> tuple[str | None, str | None]:
    numbers: list[str] = []
    urls: list[str] = []
    for fulfillment in _fulfillments(order):
        number = first_present(fulfillment, ("tracking_number", "tracking_no"))
        url = first_present(fulfillment, ("tracking_url", "tracking_status_url"))
        if number and number not in numbers:
            numbers.append(number)
        if url and url not in urls:
            urls.append(url)
    return (
        ", ".join(numbers) if numbers else None,
        urls[0] if urls else None,
    )


def _tracking_number(order: dict[str, Any]) -> str | None:
    return _tracking(order)[0]


def _tracking_url(order: dict[str, Any]) -> str | None:
    return _tracking(order)[1]


def _from_collection(
    order: dict[str, Any],
    keys: tuple[str, ...],
    labels: tuple[str, ...],
) -> str | None:
    """Read a value out of whichever nested record or list EasyStore used.

    EasyStore reports several facts either as a scalar, as a single nested object,
    or as a list of them (shipping lines, payments, fulfilments), so all three
    shapes are searched before giving up.
    """

    for key in keys:
        value = order.get(key)
        if isinstance(value, dict):
            found = first_present(value, labels)
            if found is not None:
                return found
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    found = first_present(item, labels)
                    if found is not None:
                        return found
                else:
                    found = nonempty(item)
                    if found is not None:
                        return found
    return None


def _shipping_method(order: dict[str, Any]) -> str | None:
    """Return the chosen delivery method, however EasyStore reports it."""

    direct = first_present(
        order,
        (
            "shipping_method",
            "shipping_method_name",
            "shipping_method_title",
            "shipping_title",
            "shipment_method",
            "delivery_method",
            "delivery_option",
            "courier",
        ),
    )
    if direct is not None:
        return direct

    return _from_collection(
        order,
        ("shipping_lines", "shipping_line", "shipment", "shipments", "shipping"),
        ("title", "name", "method", "code", "courier", "provider"),
    )


def _payment_method(order: dict[str, Any]) -> str | None:
    """Return how the order was paid for, however EasyStore reports it."""

    direct = first_present(
        order,
        (
            "payment_method",
            "payment_method_name",
            "payment_method_title",
            "payment_gateway",
            "gateway",
            "payment_type",
            "payment_name",
        ),
    )
    if direct is not None:
        return direct

    return _from_collection(
        order,
        ("payment", "payments", "transactions", "payment_details"),
        ("method", "name", "title", "gateway", "type", "provider"),
    )


def _discount_codes(order: dict[str, Any]) -> str | None:
    """Return the order's discount codes as one comma separated value."""

    entries = order.get("discount_codes")
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        entries = []

    codes: list[str] = []
    for entry in entries:
        if isinstance(entry, dict):
            code = first_present(entry, ("code", "discount_code", "title"))
        else:
            code = nonempty(entry)
        if code is not None and code not in codes:
            codes.append(code)

    for key in ("discount_code", "coupon_code", "voucher_code"):
        code = nonempty(order.get(key))
        if code is not None and code not in codes:
            codes.append(code)

    return ", ".join(codes) if codes else None


def _order_note(order: dict[str, Any]) -> str | None:
    return first_present(order, ("note", "notes", "customer_note", "remark"))


def _tags(record: dict[str, Any], key: str = "tags") -> str | None:
    """Return a record's tags as one comma separated value."""

    tags = record.get(key)
    if isinstance(tags, str):
        candidates: list[Any] = tags.split(",")
    elif isinstance(tags, list):
        candidates = list(tags)
    else:
        candidates = []

    collected: list[str] = []
    for candidate in candidates:
        tag = (
            first_present(candidate, ("name", "title", "tag"))
            if isinstance(candidate, dict)
            else nonempty(candidate)
        )
        if tag is not None and tag not in collected:
            collected.append(tag)
    return ", ".join(collected) if collected else None


def _person_name(record: Any) -> str | None:
    """Return a person's full name from whichever fields a record carries."""

    if not isinstance(record, dict):
        return None
    whole = first_present(record, ("name", "full_name", "customer_name"))
    if whole is not None:
        return whole
    first = first_present(record, ("first_name", "firstname", "given_name"))
    last = first_present(record, ("last_name", "lastname", "family_name"))
    if first and last:
        return f"{first} {last}"
    return first or last


def _buyer_email(order: dict[str, Any]) -> str | None:
    """Return the buyer's email, wherever the order records it."""

    customer = order.get("customer")
    if isinstance(customer, dict):
        email = first_present(customer, ("email", "email_address"))
        if email is not None:
            return email

    email = first_present(order, ("email", "customer_email", "contact_email"))
    if email is not None:
        return email

    for key in ("billing_address", "shipping_address"):
        email = first_present(order.get(key), ("email",))
        if email is not None:
            return email
    return None


def _buyer_name(order: dict[str, Any]) -> str | None:
    # Never read the order's own ``name``: that is the order number, not a person.
    return (
        _person_name(order.get("customer"))
        or first_present(order, ("customer_name", "contact_name", "buyer_name"))
        or _person_name(order.get("billing_address"))
        or _person_name(_order_address(order))
    )


def _shipping_recipient(order: dict[str, Any]) -> str | None:
    return _person_name(_order_address(order))


def _shipping_phone(order: dict[str, Any]) -> str | None:
    """Return the delivery contact number as EasyStore recorded it."""

    return first_present(_order_address(order), ("phone", "phone_number", "mobile"))


def _item_count(order: dict[str, Any]) -> str | None:
    """Return how many units the order covers, counted from its line items."""

    reported = first_present(order, ("item_count", "total_items", "line_items_count"))
    if reported is not None:
        return reported

    lines = order.get("line_items")
    if not isinstance(lines, list) or not lines:
        return None

    units = 0
    for line in lines:
        if not isinstance(line, dict):
            continue
        try:
            units += int(line.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
    return str(units) if units else None


# The address components EasyStore may use for each HubSpot address field. Both
# the shipping and billing sets are built from this one table.
ADDRESS_COMPONENTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("city", "city", ("city", "town")),
    ("state", "state", ("province", "state", "province_code", "state_code")),
    (
        "postal_code",
        "postal_code",
        ("zip", "postal_code", "postcode", "post_code"),
    ),
    ("country", "country", ("country", "country_name", "country_code")),
)


def _address_fields(
    prefix: str,
    native_prefix: str,
) -> tuple[FieldSpec, ...]:
    """Return the native-only address FieldSpecs for one address role."""

    fields = [
        FieldSpec(
            key=f"{prefix}_street",
            native=(f"{native_prefix}_street",),
        )
    ]
    fields.extend(
        FieldSpec(key=f"{prefix}_{suffix}", native=(f"{native_prefix}_{native}",))
        for suffix, native, _sources in ADDRESS_COMPONENTS
    )
    return tuple(fields)


def _address_derivations(
    prefix: str,
    getter: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Callable[[dict[str, Any]], str | None]]:
    derivations: dict[str, Callable[[dict[str, Any]], str | None]] = {
        f"{prefix}_street": lambda order: _address_street(getter(order)),
    }
    for suffix, _native, sources in ADDRESS_COMPONENTS:
        derivations[f"{prefix}_{suffix}"] = (
            lambda order, sources=sources: first_present(getter(order), sources)
        )
    return derivations


# Everything the sync copies from an EasyStore order onto its HubSpot Order,
# beyond identity, name, currency and source store. Commerce facts declare an
# easystore_* fallback so the value always lands; shipping details are
# native-only, because a portal without the matching HubSpot field gains nothing
# from a duplicate custom property.
ORDER_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="created_at",
        sources=("created_at", "created_on", "processed_at", "order_date", "date"),
        native=("hs_order_date",),
        fallback="easystore_order_created_at",
        label="EasyStore Order Created",
        description="Timestamp at which the order was created in EasyStore.",
        kind="datetime",
    ),
    FieldSpec(
        key="payment_status",
        sources=(
            "payment_status_label",
            "payment_status",
            "financial_status_label",
            "financial_status",
        ),
        native=("hs_payment_status",),
        fallback="easystore_payment_status",
        label="EasyStore Payment Status",
        description="Payment status reported by EasyStore for this order.",
    ),
    FieldSpec(
        key="fulfillment_status",
        sources=(
            "fulfillment_status_label",
            "fulfillment_status",
            "shipment_status",
            "shipping_status",
        ),
        native=("hs_fulfillment_status",),
        fallback="easystore_fulfillment_status",
        label="EasyStore Fulfilment Status",
        description="Shipping/fulfilment status reported by EasyStore for this order.",
    ),
    FieldSpec(
        key="total_amount",
        sources=("total_price", "total_amount", "grand_total", "total"),
        native=("hs_total_price",),
        fallback="easystore_total_amount",
        label="EasyStore Order Total",
        description="Total amount charged for the order, in the order currency.",
        kind="number",
    ),
    FieldSpec(
        key="subtotal_amount",
        sources=(
            "subtotal_price",
            "subtotal",
            "sub_total",
            "total_line_items_price",
        ),
        native=("hs_subtotal_price", "hs_subtotal"),
        fallback="easystore_subtotal_amount",
        label="EasyStore Order Subtotal",
        description="Merchandise subtotal before tax, shipping and discounts.",
        kind="number",
    ),
    FieldSpec(
        key="tax_amount",
        sources=("total_tax", "total_taxes", "tax_total", "tax_amount", "tax"),
        native=("hs_tax", "hs_tax_amount", "hs_total_tax"),
        fallback="easystore_tax_amount",
        label="EasyStore Order Tax",
        description="Total tax charged on the order, in the order currency.",
        kind="number",
    ),
    FieldSpec(
        key="shipping_amount",
        sources=(
            "total_shipping",
            "total_shipping_price",
            "shipping_price",
            "shipping_total",
            "shipping_fee",
            "shipping_amount",
            "shipping_cost",
        ),
        native=(
            "hs_shipping_cost",
            "hs_shipping_amount",
            "hs_shipping_price",
            "hs_total_shipping",
        ),
        fallback="easystore_shipping_amount",
        label="EasyStore Shipping Charge",
        description="Shipping charged on the order, in the order currency.",
        kind="number",
    ),
    FieldSpec(
        key="discount_amount",
        sources=(
            "total_discount",
            "total_discounts",
            "discount_amount",
            "discount_total",
        ),
        native=(
            "hs_order_discount_amount",
            "hs_discount_amount",
            "hs_total_discount",
            "hs_total_discount_amount",
            "hs_discount_total",
            "hs_order_discount",
            "hs_discount",
        ),
        fallback="easystore_discount_amount",
        label="EasyStore Order Discount",
        description="Total discount applied to the order, in the order currency.",
        kind="number",
        absolute=True,
    ),
    FieldSpec(
        key="refund_amount",
        sources=(
            "total_refunded",
            "refunded_amount",
            "refund_amount",
            "total_refund",
        ),
        native=(),
        fallback="easystore_refund_amount",
        label="EasyStore Order Refunded",
        description="Amount refunded on the order, in the order currency.",
        kind="number",
        absolute=True,
    ),
    FieldSpec(
        key="discount_codes",
        native=(),
        fallback="easystore_discount_codes",
        label="EasyStore Discount Codes",
        description="Comma separated discount codes applied to the EasyStore order.",
    ),
    FieldSpec(
        key="payment_method",
        native=("hs_payment_method",),
        fallback="easystore_payment_method",
        label="EasyStore Payment Method",
        description="How the order was paid for, as reported by EasyStore.",
    ),
    FieldSpec(
        key="order_status",
        sources=(
            "status",
            "order_status",
            "order_status_label",
            "status_label",
            "state",
            "order_state",
            "state_label",
        ),
        native=("hs_order_status",),
        fallback="easystore_order_status",
        label="EasyStore Order Status",
        description="Overall order state in EasyStore, e.g. open, closed or cancelled.",
    ),
    FieldSpec(
        key="paid_at",
        sources=("paid_at", "payment_date", "paid_on"),
        native=(),
        fallback="easystore_order_paid_at",
        label="EasyStore Order Paid",
        description="Timestamp at which EasyStore recorded payment for the order.",
        kind="datetime",
    ),
    FieldSpec(
        key="fulfilled_at",
        sources=("fulfilled_at", "shipped_at", "fulfillment_date"),
        native=(),
        fallback="easystore_order_fulfilled_at",
        label="EasyStore Order Fulfilled",
        description="Timestamp at which the order was fulfilled in EasyStore.",
        kind="datetime",
    ),
    FieldSpec(
        key="cancelled_at",
        sources=("cancelled_at", "canceled_at", "cancellation_date"),
        native=(),
        fallback="easystore_order_cancelled_at",
        label="EasyStore Order Cancelled",
        description="Timestamp at which the order was cancelled in EasyStore.",
        kind="datetime",
    ),
    FieldSpec(
        key="cancel_reason",
        sources=("cancel_reason", "cancellation_reason", "cancelled_reason"),
        native=(),
        fallback="easystore_order_cancel_reason",
        label="EasyStore Cancellation Reason",
        description="Reason EasyStore recorded for cancelling the order.",
    ),
    FieldSpec(
        key="channel",
        sources=("source_name", "sales_channel", "channel", "source"),
        native=(),
        fallback="easystore_order_channel",
        label="EasyStore Order Channel",
        description="Sales channel the order came through, as reported by EasyStore.",
    ),
    FieldSpec(
        key="item_count",
        native=(),
        fallback="easystore_order_item_count",
        label="EasyStore Order Units",
        description="Number of units the EasyStore order covers.",
        kind="number",
    ),
    FieldSpec(
        key="tags",
        native=(),
        fallback="easystore_order_tags",
        label="EasyStore Order Tags",
        description="Comma separated tags on the EasyStore order.",
    ),
    FieldSpec(
        key="buyer_email",
        native=(),
        fallback="easystore_order_email",
        label="EasyStore Buyer Email",
        description=(
            "Email EasyStore recorded for the buyer. Kept on the order so a guest "
            "order that matches no Contact is still traceable."
        ),
    ),
    FieldSpec(
        key="buyer_name",
        native=(),
        fallback="easystore_order_customer_name",
        label="EasyStore Buyer Name",
        description="Name EasyStore recorded for the buyer of this order.",
    ),
    FieldSpec(
        key="buyer_phone",
        native=(),
        fallback="easystore_order_phone",
        label="EasyStore Buyer Mobile",
        description="Normalized mobile number EasyStore recorded for the buyer.",
    ),
    FieldSpec(
        key="shipping_recipient",
        native=(),
        fallback="easystore_shipping_recipient",
        label="EasyStore Shipping Recipient",
        description="Name the order is being delivered to.",
    ),
    FieldSpec(
        key="shipping_phone",
        native=(),
        fallback="easystore_shipping_phone",
        label="EasyStore Shipping Phone",
        description="Contact number recorded on the delivery address.",
    ),
    FieldSpec(
        key="note",
        native=(),
        fallback="easystore_order_note",
        label="EasyStore Order Note",
        description="Note the shopper or staff left on the EasyStore order.",
    ),
    FieldSpec(key="shipping_method", native=("hs_shipping_method",)),
    FieldSpec(key="tracking_number", native=("hs_shipping_tracking_number",)),
    FieldSpec(key="tracking_url", native=("hs_shipping_status_url",)),
    *_address_fields("shipping_address", "hs_shipping_address"),
    *_address_fields("billing_address", "hs_billing_address"),
)

ORDER_FIELD_DERIVATIONS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "discount_codes": _discount_codes,
    "note": _order_note,
    "tags": _tags,
    "item_count": _item_count,
    "buyer_email": _buyer_email,
    "buyer_name": _buyer_name,
    "shipping_recipient": _shipping_recipient,
    "shipping_phone": _shipping_phone,
    "shipping_method": _shipping_method,
    "payment_method": _payment_method,
    "tracking_number": _tracking_number,
    "tracking_url": _tracking_url,
    **_address_derivations("shipping_address", _order_address),
    **_address_derivations("billing_address", _billing_address),
}

# Property names used when the live HubSpot schema has not been resolved, e.g.
# in unit tests. Production runs always resolve against the portal schema.
DEFAULT_ORDER_FIELD_PROPERTIES: dict[str, str] = {
    field.key: field.native[0] if field.native else field.fallback
    for field in ORDER_FIELDS
    if field.native or field.fallback
}

# The order-list endpoint returns a thinner record than the order endpoint. The
# sources that decide whether a listed order still needs its detail fetched.
DETAIL_MONEY_SOURCES: tuple[str, ...] = next(
    field.sources for field in ORDER_FIELDS if field.key == "total_amount"
)


def order_field_values(
    order: dict[str, Any],
    fallback_dial_code: str = "65",
) -> dict[str, str]:
    """Return every mapped value for an order, keyed by field key."""

    derivations = {
        **ORDER_FIELD_DERIVATIONS,
        # The buyer's mobile is normalized with the same rule that resolves the
        # order's Contact, so both sides of a match read identically.
        "buyer_phone": lambda item: _order_customer_phone(item, fallback_dial_code),
    }
    return field_values(order, ORDER_FIELDS, derivations)


def order_needs_detail(order: dict[str, Any]) -> bool:
    """Report whether a listed order is too thin to map completely.

    EasyStore's order list omits fields the order endpoint returns. Line items
    were the first symptom; addresses and totals are the same story, so the
    detail is fetched whenever any of the three is missing rather than only when
    line items are.

    The list's address is the subtle case: it arrives as a stub carrying only a
    country, so an order needs its detail whenever no address states a street or
    a city.
    """

    if not isinstance(order.get("line_items"), list):
        return True
    # A country-only stub is not a delivery address, so it does not count as one.
    if not _usable_address(_order_address(order)):
        return True
    return first_present(order, DETAIL_MONEY_SOURCES) is None


def order_properties(
    order: dict[str, Any],
    *,
    external_id: str,
    store_domain: str,
    field_properties: dict[str, str] | None = None,
    fallback_dial_code: str = "65",
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

    return apply_fields(
        properties,
        order_field_values(order, fallback_dial_code),
        field_properties or DEFAULT_ORDER_FIELD_PROPERTIES,
    )


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


# Per-line money and variant detail, on top of name, SKU, product, quantity,
# price and currency. All native-only: HubSpot's own Line Item properties are the
# ones its order editor reads.
LINE_ITEM_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="discount",
        sources=("total_discount", "discount", "discount_amount"),
        native=("discount",),
        kind="number",
        absolute=True,
    ),
    FieldSpec(
        key="tax",
        sources=("total_tax", "tax", "tax_amount"),
        native=("tax",),
        kind="number",
        absolute=True,
    ),
    FieldSpec(
        key="variant",
        sources=("variant_title", "variant_name", "option_title", "options_label"),
        native=("description",),
    ),
)


def resolve_line_item_fields(access_token: str) -> dict[str, str]:
    """Map per-line detail onto native HubSpot Line Item properties.

    Reading the line item schema needs ``crm.schemas.line_items.read``. Line
    items themselves sync without it, so a token that cannot read the schema logs
    the skipped fields and carries on.
    """

    resolved = resolve_fields(
        http_json=_http_json,
        access_token=access_token,
        object_type=LINE_ITEM_OBJECT_TYPE,
        fields=LINE_ITEM_FIELDS,
        error=SyncError,
        optional=True,
    )
    if len(resolved) < len(LINE_ITEM_FIELDS):
        missing = sorted(
            field.key for field in LINE_ITEM_FIELDS if field.key not in resolved
        )
        print(
            "WARNING: line item fields not synchronized because HubSpot did not "
            "provide a writable property (add crm.schemas.line_items.read to the "
            "token to enable them): " + ", ".join(missing),
            file=sys.stderr,
        )
    return resolved


def desired_lines(
    order: dict[str, Any],
    product_by_sku: dict[str, str],
    field_properties: dict[str, str] | None = None,
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
        if field_properties:
            apply_fields(
                properties,
                field_values(line, LINE_ITEM_FIELDS),
                field_properties,
            )
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
) -> dict[str, Any]:
    ensure_order_identity_property(hubspot_access_token)
    schema_report: dict[str, Any] = {}
    order_field_properties = resolve_fields(
        http_json=_http_json,
        access_token=hubspot_access_token,
        object_type=ORDER_OBJECT_TYPE,
        fields=ORDER_FIELDS,
        error=SyncError,
        report=schema_report,
    )
    print(
        "HubSpot Order properties in this portal: "
        + ", ".join(schema_report.get("inventory", [])),
        file=sys.stderr,
    )
    line_item_field_properties = resolve_line_item_fields(hubspot_access_token)
    print(
        "Order fields mapped to HubSpot properties: "
        + describe_mapping(order_field_properties),
        file=sys.stderr,
    )
    print(
        "Line item fields mapped to HubSpot properties: "
        + describe_mapping(line_item_field_properties),
        file=sys.stderr,
    )
    unmapped = sorted(
        field.key for field in ORDER_FIELDS if field.key not in order_field_properties
    )
    if unmapped:
        print(
            "WARNING: this HubSpot portal has no property for: "
            + ", ".join(unmapped),
            file=sys.stderr,
        )

    product_by_sku = hubspot_product_index(hubspot_access_token)
    contacts = hubspot_contact_index(
        hubspot_access_token,
        fallback_dial_code,
    )
    existing_orders = hubspot_order_index(hubspot_access_token)

    orders: list[tuple[dict[str, Any], str, dict[str, dict[str, str]]]] = []
    easystore_orders = 0
    easystore_lines = 0
    orders_fetched_in_detail = 0
    # How many orders actually carried each field. A zero here means EasyStore
    # did not report that fact, not that HubSpot rejected it.
    field_coverage: dict[str, int] = {field.key: 0 for field in ORDER_FIELDS}
    # Which keys EasyStore actually sends, so a zero above can be traced to the
    # real field name instead of guessed at. Names only, never values.
    order_keys: set[str] = set()
    address_keys: set[str] = set()
    line_keys: set[str] = set()

    # Validate every order and product reference before making order/line writes.
    for listed in iter_easystore_orders(store_domain, easystore_access_token):
        easystore_orders += 1
        if order_needs_detail(listed):
            orders_fetched_in_detail += 1
        order = complete_order(store_domain, easystore_access_token, listed)
        external_id = nonempty(order.get("id"))
        if external_id is None:
            raise SyncError("EasyStore returned an order without an id")
        for key in order_field_values(order, fallback_dial_code):
            field_coverage[key] += 1
        observed_keys(order_keys, order)
        observed_keys(address_keys, _order_address(order))
        observed_keys(address_keys, _billing_address(order))
        for line in order.get("line_items") or ():
            observed_keys(line_keys, line)
        desired = desired_lines(order, product_by_sku, line_item_field_properties)
        easystore_lines += sum(int(line["quantity"]) for line in desired.values())
        orders.append((order, external_id, desired))

    created_orders = 0
    updated_orders = 0
    created_lines = 0
    updated_lines = 0
    contact_associations = 0
    orders_without_mobile = 0
    ambiguous_contact_mobile = 0
    promoted_to_customer: set[str] = set()

    for order, external_id, desired in orders:
        hubspot_order_id, created = _upsert_hubspot_order(
            hubspot_access_token,
            existing_orders.get(external_id),
            order_properties(
                order,
                external_id=external_id,
                store_domain=store_domain,
                field_properties=order_field_properties,
                fallback_dial_code=fallback_dial_code,
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
            matching_contacts = contacts.by_phone.get(mobile, set())
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

                # The order itself is the proof of purchase, so its buyer becomes
                # a customer regardless of the stage the contact sync assigned.
                stage = lifecycle_stage_write(
                    contacts.lifecycle_by_id.get(contact_id),
                    LIFECYCLE_CUSTOMER,
                )
                if stage is not None:
                    _http_json(
                        f"{HUBSPOT_CONTACTS_URL}/{contact_id}",
                        method="PATCH",
                        headers={"Authorization": f"Bearer {hubspot_access_token}"},
                        payload={"properties": {CONTACT_LIFECYCLE_PROPERTY: stage}},
                    )
                    contacts.lifecycle_by_id[contact_id] = stage
                    promoted_to_customer.add(contact_id)
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

    custom_order_fields = sum(
        1
        for field in ORDER_FIELDS
        if field.fallback is not None
        and order_field_properties.get(field.key) == field.fallback
    )

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
        "commerce_fields_on_easystore_properties": custom_order_fields,
        "contacts_promoted_to_customer": len(promoted_to_customer),
        "orders_fetched_in_detail": orders_fetched_in_detail,
        "easystore_order_keys_seen": sorted(order_keys),
        "easystore_order_address_keys_seen": sorted(address_keys),
        "easystore_line_item_keys_seen": sorted(line_keys),
        "hubspot_order_property_hints": schema_report.get("hints", {}),
        "hubspot_order_field_properties": dict(sorted(order_field_properties.items())),
        "hubspot_line_item_field_properties": dict(
            sorted(line_item_field_properties.items())
        ),
        "easystore_order_field_coverage": dict(sorted(field_coverage.items())),
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
