#!/usr/bin/env python3
"""Sync EasyStore Checkout sessions into HubSpot Carts.

EasyStore's published Storefront API 3.0 exposes carts through the Checkout
resource:

* GET /api/3.0/checkouts.json
* GET /api/3.0/checkouts/:cart_token.json

``checkout.cart_token`` is the external Cart identity. Checkout line items,
financial status, totals, currency, addresses, contact details and checkout URL
are the Cart source of truth. Orders never create Cart properties or Cart Line
Items; an Order can only be associated after the real Checkout-backed Cart
exists.

The current EasyStore documentation page has an obvious copy/paste defect in the
Checkout list parameter table: it describes product-only filters such as
``collection_ids``, ``skus``, ``visibility`` and ``published_at_*`` and labels
the operation "List products". Production therefore sends only the two generic
pagination parameters that are unambiguous for this endpoint: ``page`` and
``limit``. In particular, it does not send ``sort`` or ``created_at_min``.

The collection is first read with ``limit=1``. This deliberately favors the
smallest possible documented request because the production store previously
timed out on larger / filtered list requests. A complete snapshot is buffered
and any missing line items are hydrated from the documented detail endpoint
before HubSpot is mutated.
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
from easystore_hubspot_schema import nonempty


EASYSTORE_CHECKOUT_COLLECTION_PATH = "/api/3.0/checkouts.json"
EASYSTORE_CHECKOUT_DETAIL_PATH = "/api/3.0/checkouts/{cart_token}.json"
HUBSPOT_CART_COLLECTION_PATH = "/crm/v3/objects/carts"
HUBSPOT_CART_SCHEMA_OBJECT_TYPE = "cart"
HUBSPOT_CART_PROPERTIES_PATH = "/crm/v3/properties/cart"

# Keep the collection request intentionally minimal. The linked EasyStore docs
# clearly contain Product endpoint fields in the Checkout parameter table, so we
# do not rely on those copied filters for production correctness.
CHECKOUT_PAGE_SIZE = 1
CHECKOUT_READ_TIMEOUT_SECONDS = 20
CHECKOUT_READ_RETRIES = 0


@dataclass(frozen=True)
class CheckoutSnapshot:
    records: tuple[dict[str, Any], ...]
    pages_read: int
    details_fetched: int


def _checkout_collection(document: Any) -> list[dict[str, Any]]:
    """Extract a Checkout collection without treating an unknown shape as empty."""

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
    """Extract one Checkout from the documented detail response shapes."""

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


def _collection_url(domain: str, page: int) -> str:
    query = urlencode({"page": page, "limit": CHECKOUT_PAGE_SIZE})
    return f"https://{domain}{EASYSTORE_CHECKOUT_COLLECTION_PATH}?{query}"


def _complete_checkout(
    domain: str,
    access_token: str,
    listed: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Return one Checkout with line_items, hydrating by cart_token if required."""

    if isinstance(listed.get("line_items"), list):
        return listed, False

    cart_token = commerce.checkout_cart_token(listed)
    if cart_token is None:
        # The core synchronizer will count this record and skip it because a
        # HubSpot Cart cannot be safely identified without cart_token.
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
            "Cart synchronization cannot safely continue"
        )
    return merged, True


def read_checkout_snapshot(
    store_domain: str,
    access_token: str,
) -> CheckoutSnapshot:
    """Read the complete Checkout collection using only page + limit.

    Pagination is all-or-nothing. Repeated pages are rejected so an endpoint
    that ignores ``page`` cannot trap the workflow in a loop or expose a partial
    snapshot to HubSpot.
    """

    domain = _shop_domain(store_domain)
    page = 1
    pages_read = 0
    listed_records: list[dict[str, Any]] = []
    seen_page_signatures: set[tuple[str, ...]] = set()

    while True:
        url = _collection_url(domain, page)
        try:
            document = _checkout_get(url, access_token)
        except SyncError as error:
            raise SyncError(
                "EasyStore Checkout collection failed using the minimal documented "
                f"request (page={page}, limit={CHECKOUT_PAGE_SIZE}, no sort/date/"
                f"product filters): {error}"
            ) from error

        records = _checkout_collection(document)
        pages_read += 1
        signature = tuple(
            nonempty(record.get("cart_token"))
            or nonempty(record.get("id"))
            or f"row:{index}"
            for index, record in enumerate(records)
        )
        if records and signature in seen_page_signatures:
            raise SyncError(
                "EasyStore Checkout pagination repeated a page; refusing to sync "
                "an incomplete or looping checkout snapshot"
            )
        if records:
            seen_page_signatures.add(signature)
        listed_records.extend(records)

        if len(records) < CHECKOUT_PAGE_SIZE:
            break
        page += 1

    completed: list[dict[str, Any]] = []
    details_fetched = 0
    for listed in listed_records:
        checkout, fetched = _complete_checkout(domain, access_token, listed)
        completed.append(checkout)
        details_fetched += int(fetched)

    return CheckoutSnapshot(
        records=tuple(completed),
        pages_read=pages_read,
        details_fetched=details_fetched,
    )


def _validate_hubspot_cart_contract() -> None:
    expected = f"{commerce.HUBSPOT_BASE}{HUBSPOT_CART_COLLECTION_PATH}"
    if commerce.HUBSPOT_CARTS_URL != expected:
        raise SyncError(
            f"HubSpot Cart endpoint drift detected: expected {expected}, "
            f"got {commerce.HUBSPOT_CARTS_URL}"
        )


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, Any]:
    """Synchronize all real EasyStore Checkout sessions into HubSpot Carts."""

    _validate_hubspot_cart_contract()
    snapshot = read_checkout_snapshot(store_domain, easystore_access_token)

    # HubSpot Carts represent shopping sessions that may later be purchased or
    # abandoned. The legacy core originally skipped paid/completed checkouts.
    # For this production entrypoint we feed every real Checkout into that same
    # validated Cart/Line Item writer while preserving each Checkout's raw
    # financial_status as hs_external_status.
    original_iterator = commerce.iter_documented_checkouts
    original_is_abandoned = commerce.is_abandoned
    original_schema_type = commerce.CART_SCHEMA_OBJECT_TYPE

    abandoned_or_open = sum(1 for item in snapshot.records if original_is_abandoned(item))
    completed_or_paid = len(snapshot.records) - abandoned_or_open

    commerce.iter_documented_checkouts = lambda _store, _token: iter(snapshot.records)
    commerce.is_abandoned = lambda _checkout: True
    commerce.CART_SCHEMA_OBJECT_TYPE = HUBSPOT_CART_SCHEMA_OBJECT_TYPE
    try:
        summary = commerce.sync(
            store_domain=store_domain,
            easystore_access_token=easystore_access_token,
            hubspot_access_token=hubspot_access_token,
            fallback_dial_code=fallback_dial_code,
        )
    finally:
        commerce.iter_documented_checkouts = original_iterator
        commerce.is_abandoned = original_is_abandoned
        commerce.CART_SCHEMA_OBJECT_TYPE = original_schema_type

    domain = _shop_domain(store_domain)
    summary.update(
        {
            "easystore_checkout_source": "public_api_checkouts",
            "easystore_checkout_collection_endpoint": (
                f"https://{domain}{EASYSTORE_CHECKOUT_COLLECTION_PATH}"
            ),
            "easystore_checkout_detail_endpoint_template": (
                f"https://{domain}/api/3.0/checkouts/:cart_token.json"
            ),
            "easystore_checkout_collection_query": "page,limit only",
            "easystore_checkout_page_size": CHECKOUT_PAGE_SIZE,
            "easystore_checkout_product_style_filters_sent": False,
            "easystore_checkout_pages_read": snapshot.pages_read,
            "easystore_checkout_details_fetched": snapshot.details_fetched,
            "easystore_checkouts_buffered": len(snapshot.records),
            "easystore_checkouts_abandoned_or_open": abandoned_or_open,
            "easystore_checkouts_completed_or_paid": completed_or_paid,
            "easystore_checkout_read_timeout_seconds": CHECKOUT_READ_TIMEOUT_SECONDS,
            "hubspot_cart_collection_endpoint": (
                f"{commerce.HUBSPOT_BASE}{HUBSPOT_CART_COLLECTION_PATH}"
            ),
            "hubspot_cart_properties_endpoint": (
                f"{commerce.HUBSPOT_BASE}{HUBSPOT_CART_PROPERTIES_PATH}"
            ),
            "hubspot_cart_schema_object_type": HUBSPOT_CART_SCHEMA_OBJECT_TYPE,
            "hubspot_cart_source_semantics": (
                "all EasyStore Checkout sessions; unpaid/open is the abandoned subset"
            ),
            "cart_source_is_orders": False,
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
