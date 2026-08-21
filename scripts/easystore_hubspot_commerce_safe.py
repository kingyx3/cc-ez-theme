#!/usr/bin/env python3
"""Run the EasyStore Checkout -> HubSpot Cart sync with outage isolation.

EasyStore calls the cart-facing Public API resource ``Checkouts``:

* ``GET /api/3.0/checkouts.json`` lists checkout/cart sessions.
* ``GET /api/3.0/checkouts/:cart_token.json`` retrieves one checkout.
* ``checkout.cart_token`` is the cart identity retained as ``order.cart_token``.

HubSpot calls the corresponding CRM object ``Carts``. Its object API is plural
(``/crm/v3/objects/carts``), while the properties/schema API uses the singular
object type (``/crm/v3/properties/cart``). This wrapper keeps those contracts
explicit and validates a complete EasyStore checkout snapshot before allowing
Cart or Cart Line Item reconciliation.

If the EasyStore checkout API is unavailable, Products, Customers and Orders
remain successful. Existing HubSpot Carts can still be associated to newly
synced Orders through ``order.cart_token``; Cart and Cart Line Item upserts are
skipped until a complete checkout snapshot is available.

Only EasyStore checkout reads degrade. HubSpot write errors, duplicate identity
conflicts, bad product references and other data-integrity failures still raise.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import sys
from typing import Any
from urllib.parse import quote, urlencode

import easystore_hubspot_commerce as commerce
from easystore_hubspot_orders import SyncError, _http_json, _shop_domain


EASYSTORE_CHECKOUT_COLLECTION_PATH = "/api/3.0/checkouts.json"
EASYSTORE_CHECKOUT_DETAIL_PATH = "/api/3.0/checkouts/{cart_token}.json"
HUBSPOT_CART_COLLECTION_PATH = "/crm/v3/objects/carts"
HUBSPOT_CART_SCHEMA_OBJECT_TYPE = "cart"
HUBSPOT_CART_PROPERTIES_PATH = "/crm/v3/properties/cart"

# EasyStore documents 50 as the maximum list-page size. Using it minimizes the
# number of calls to the currently fragile checkout endpoint.
CHECKOUT_PAGE_SIZE = 50
CHECKOUT_READ_TIMEOUT_SECONDS = 15
CHECKOUT_READ_RETRIES = 0


@dataclass(frozen=True)
class CheckoutSnapshot:
    records: tuple[dict[str, Any], ...]
    pages_read: int
    details_fetched: int


def _short_reason(error: SyncError) -> str:
    return " ".join(str(error).split())[:300]


def _checkout_collection(document: Any) -> list[dict[str, Any]]:
    """Extract a checkout list, rejecting an unrecognized response shape."""

    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    if not isinstance(document, dict):
        raise SyncError("EasyStore checkouts.json returned a non-object response")

    for key in ("checkouts", "data", "results"):
        value = document.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = value.get("checkouts")
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]

    raise SyncError(
        "EasyStore checkouts.json returned JSON without a checkout collection"
    )


def _checkout_detail(document: Any, cart_token: str) -> dict[str, Any]:
    """Extract one checkout from the documented detail response shapes."""

    if not isinstance(document, dict):
        raise SyncError(
            f"EasyStore checkout {cart_token} detail returned a non-object response"
        )

    candidate = document.get("checkout")
    if isinstance(candidate, dict):
        return candidate

    data = document.get("data")
    if isinstance(data, dict):
        nested = data.get("checkout")
        return nested if isinstance(nested, dict) else data

    # Some EasyStore endpoints return the resource object directly.
    if "cart_token" in document or "line_items" in document:
        return document

    raise SyncError(
        f"EasyStore checkout {cart_token} detail returned an unknown JSON shape"
    )


def _checkout_get(url: str, access_token: str) -> Any:
    return _http_json(
        url,
        headers={"EasyStore-Access-Token": access_token},
        retries=CHECKOUT_READ_RETRIES,
        timeout=CHECKOUT_READ_TIMEOUT_SECONDS,
    )


def _complete_snapshot_checkout(
    domain: str,
    access_token: str,
    listed: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Return a checkout with line items, fetching detail by cart_token if needed."""

    if isinstance(listed.get("line_items"), list):
        return listed, False

    cart_token = commerce.checkout_cart_token(listed)
    if cart_token is None:
        # The strict commerce stage will count and skip this record. There is no
        # safe detail identity to fetch, so do not invent one from checkout.id.
        return listed, False

    path = EASYSTORE_CHECKOUT_DETAIL_PATH.format(
        cart_token=quote(cart_token, safe="")
    )
    detail = _checkout_detail(
        _checkout_get(f"https://{domain}{path}", access_token),
        cart_token,
    )

    merged = dict(listed)
    merged.update(detail)
    if not isinstance(merged.get("line_items"), list):
        raise SyncError(
            f"EasyStore checkout {cart_token} detail omitted line_items; "
            "Cart reconciliation cannot safely continue"
        )
    return merged, True


def read_checkout_snapshot(
    store_domain: str,
    access_token: str,
) -> CheckoutSnapshot:
    """Read and fully hydrate the checkout collection before exposing records.

    This is deliberately all-or-nothing. If page N or one required checkout
    detail fails, no partial record set reaches the Cart reconciler.
    """

    domain = _shop_domain(store_domain)
    page = 1
    pages_read = 0
    listed_records: list[dict[str, Any]] = []

    while True:
        query = urlencode({"page": page, "limit": CHECKOUT_PAGE_SIZE})
        document = _checkout_get(
            f"https://{domain}{EASYSTORE_CHECKOUT_COLLECTION_PATH}?{query}",
            access_token,
        )
        records = _checkout_collection(document)
        pages_read += 1
        listed_records.extend(records)
        if len(records) < CHECKOUT_PAGE_SIZE:
            break
        page += 1

    complete: list[dict[str, Any]] = []
    details_fetched = 0
    for listed in listed_records:
        checkout, fetched = _complete_snapshot_checkout(
            domain,
            access_token,
            listed,
        )
        complete.append(checkout)
        details_fetched += int(fetched)

    return CheckoutSnapshot(
        records=tuple(complete),
        pages_read=pages_read,
        details_fetched=details_fetched,
    )


def _install_hubspot_cart_contract() -> None:
    """Use HubSpot's singular schema object type with its plural object endpoint."""

    commerce.CART_SCHEMA_OBJECT_TYPE = HUBSPOT_CART_SCHEMA_OBJECT_TYPE


def _endpoint_summary(store_domain: str) -> dict[str, Any]:
    domain = _shop_domain(store_domain)
    return {
        "easystore_checkout_collection_endpoint": (
            f"https://{domain}{EASYSTORE_CHECKOUT_COLLECTION_PATH}"
        ),
        "easystore_checkout_detail_endpoint_template": (
            f"https://{domain}/api/3.0/checkouts/:cart_token.json"
        ),
        "easystore_checkout_page_size": CHECKOUT_PAGE_SIZE,
        "easystore_checkout_read_timeout_seconds": CHECKOUT_READ_TIMEOUT_SECONDS,
        "easystore_checkout_read_retries": CHECKOUT_READ_RETRIES,
        "hubspot_cart_collection_endpoint": (
            f"{commerce.HUBSPOT_BASE}{HUBSPOT_CART_COLLECTION_PATH}"
        ),
        "hubspot_cart_properties_endpoint": (
            f"{commerce.HUBSPOT_BASE}{HUBSPOT_CART_PROPERTIES_PATH}"
        ),
        "hubspot_cart_schema_object_type": HUBSPOT_CART_SCHEMA_OBJECT_TYPE,
    }


def _validate_hubspot_cart_endpoint() -> None:
    _install_hubspot_cart_contract()
    expected = f"{commerce.HUBSPOT_BASE}{HUBSPOT_CART_COLLECTION_PATH}"
    if commerce.HUBSPOT_CARTS_URL != expected:
        raise SyncError(
            "HubSpot Cart endpoint drift detected: expected "
            f"{expected}, got {commerce.HUBSPOT_CARTS_URL}"
        )
    if commerce.CART_SCHEMA_OBJECT_TYPE != HUBSPOT_CART_SCHEMA_OBJECT_TYPE:
        raise SyncError(
            "HubSpot Cart schema object type drift detected: expected "
            f"{HUBSPOT_CART_SCHEMA_OBJECT_TYPE}, got {commerce.CART_SCHEMA_OBJECT_TYPE}"
        )


def link_existing_carts_to_orders(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
) -> dict[str, Any]:
    """Keep Cart->Order conversion links current without checkout reads."""

    if not commerce.cart_object_available(hubspot_access_token):
        return {
            "hubspot_cart_object": "unavailable",
            "easystore_orders_scanned_for_cart_links": 0,
            "cart_order_associations_ensured": 0,
        }

    orders = list(
        commerce.iter_orders_for_cart_links(store_domain, easystore_access_token)
    )
    carts = commerce.hubspot_cart_index(hubspot_access_token)
    hubspot_orders = commerce.hubspot_order_index(hubspot_access_token)
    linked = commerce.link_carts_to_orders(
        orders=orders,
        hubspot_access_token=hubspot_access_token,
        carts_by_token=carts,
        hubspot_orders=hubspot_orders,
    )
    return {
        "easystore_orders_scanned_for_cart_links": len(orders),
        "cart_order_associations_ensured": linked,
    }


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, Any]:
    """Run strict Cart sync only after a complete EasyStore checkout snapshot."""

    _validate_hubspot_cart_endpoint()
    endpoint_summary = _endpoint_summary(store_domain)

    try:
        snapshot = read_checkout_snapshot(store_domain, easystore_access_token)
    except SyncError as error:
        reason = _short_reason(error)
        print(
            "WARNING: EasyStore checkout API is unavailable or incomplete; Cart "
            "and Cart Line Item upserts were skipped. Existing Cart->Order links "
            "will still be refreshed from EasyStore Orders. Reason: " + reason,
            file=sys.stderr,
        )
        summary = link_existing_carts_to_orders(
            store_domain=store_domain,
            easystore_access_token=easystore_access_token,
            hubspot_access_token=hubspot_access_token,
        )
        summary.update(endpoint_summary)
        summary.update(
            {
                "easystore_checkout_status": "unavailable",
                "easystore_checkout_error": reason,
                "easystore_checkouts_scanned": 0,
                "easystore_checkout_pages_read": 0,
                "easystore_checkout_details_fetched": 0,
                "hubspot_cart_upserts_skipped": True,
                "hubspot_cart_line_item_sync_skipped": True,
            }
        )
        return summary

    original = commerce.iter_documented_checkouts
    commerce.iter_documented_checkouts = lambda _store, _token: iter(snapshot.records)
    try:
        summary = commerce.sync(
            store_domain=store_domain,
            easystore_access_token=easystore_access_token,
            hubspot_access_token=hubspot_access_token,
            fallback_dial_code=fallback_dial_code,
        )
    finally:
        commerce.iter_documented_checkouts = original

    summary.update(endpoint_summary)
    summary.update(
        {
            "easystore_checkout_status": "available",
            "easystore_checkout_pages_read": snapshot.pages_read,
            "easystore_checkout_details_fetched": snapshot.details_fetched,
            "easystore_checkouts_buffered": len(snapshot.records),
            "hubspot_cart_upserts_skipped": False,
            "hubspot_cart_line_item_sync_skipped": False,
        }
    )
    return summary


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
            fallback_dial_code=_required(
                args.fallback_dial_code,
                "CUSTOMER_SYNC_DEFAULT_DIAL_CODE",
            ),
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
