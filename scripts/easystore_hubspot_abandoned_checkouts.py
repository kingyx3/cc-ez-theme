#!/usr/bin/env python3
"""Sync EasyStore abandoned checkouts into HubSpot Carts.

EasyStore's public API exposes the cart/checkout data used by the Admin
"Abandoned checkouts" screen through the Checkout resource:

* GET /api/3.0/checkouts.json
* GET /api/3.0/checkouts/:cart_token.json

There is no separate abandoned_checkouts.json endpoint in EasyStore's published
Public API. This entrypoint therefore reads recent Checkout records, keeps only
incomplete/unpaid checkouts, and passes those real EasyStore records to the
strict HubSpot Cart synchronizer.

The checkout source is authoritative. Orders are not used to manufacture Cart
properties or Cart Line Items. A complete recent checkout snapshot is buffered
before any HubSpot Cart mutation; if EasyStore cannot provide that snapshot the
Cart stage fails visibly instead of reporting a successful empty sync.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

# EasyStore's merchant UI retains abandoned checkouts for 90 days. Constrain the
# Public API read to the same useful recovery window instead of asking the
# checkout endpoint to scan the store's entire history.
ABANDONED_CHECKOUT_WINDOW_DAYS = 90

# The live store timed out when 50 checkout records were requested at once.
# Start small and, only when a collection request itself times out/fails, restart
# the whole snapshot with an even smaller page. This never exposes a partial
# checkout set to HubSpot.
CHECKOUT_PAGE_SIZE_CANDIDATES = (10, 5, 1)
CHECKOUT_READ_TIMEOUT_SECONDS = 15
CHECKOUT_READ_RETRIES = 0
CHECKOUT_SORT = "id.desc"


class CheckoutCollectionReadError(SyncError):
    """Raised only for a failed Checkout collection page read."""


@dataclass(frozen=True)
class CheckoutSnapshot:
    records: tuple[dict[str, Any], ...]
    pages_read: int
    details_fetched: int
    listed_count: int
    page_size: int
    created_at_min: str


def checkout_window_start(now: datetime | None = None) -> str:
    """Return EasyStore's documented timestamp format for the 90-day window."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current.astimezone(timezone.utc) - timedelta(
        days=ABANDONED_CHECKOUT_WINDOW_DAYS
    )
    return cutoff.strftime("%Y-%m-%d %H:%M:%S")


def _checkout_collection(document: Any) -> list[dict[str, Any]]:
    """Extract a checkout list without turning an unknown response into empty."""

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


def _read_collection(
    domain: str,
    access_token: str,
    *,
    page_size: int,
    created_at_min: str,
) -> tuple[list[dict[str, Any]], int]:
    page = 1
    pages_read = 0
    listed: list[dict[str, Any]] = []

    while True:
        query = urlencode(
            {
                "page": page,
                "limit": page_size,
                "sort": CHECKOUT_SORT,
                "created_at_min": created_at_min,
            }
        )
        url = f"https://{domain}{EASYSTORE_CHECKOUT_COLLECTION_PATH}?{query}"
        try:
            document = _checkout_get(url, access_token)
        except SyncError as error:
            raise CheckoutCollectionReadError(str(error)) from error

        records = _checkout_collection(document)
        pages_read += 1
        listed.extend(records)
        if len(records) < page_size:
            return listed, pages_read
        page += 1


def _complete_abandoned_checkout(
    domain: str,
    access_token: str,
    listed: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Hydrate one abandoned checkout when the list record omits line_items."""

    if isinstance(listed.get("line_items"), list):
        return listed, False

    cart_token = commerce.checkout_cart_token(listed)
    if cart_token is None:
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


def _snapshot_with_page_size(
    store_domain: str,
    access_token: str,
    *,
    page_size: int,
    created_at_min: str,
) -> CheckoutSnapshot:
    domain = _shop_domain(store_domain)
    listed, pages_read = _read_collection(
        domain,
        access_token,
        page_size=page_size,
        created_at_min=created_at_min,
    )

    abandoned: list[dict[str, Any]] = []
    details_fetched = 0
    for record in listed:
        # The Checkout resource exposes financial_status. Skip records that are
        # already visibly paid/completed before spending a detail request.
        if not commerce.is_abandoned(record):
            continue
        checkout, fetched = _complete_abandoned_checkout(
            domain,
            access_token,
            record,
        )
        details_fetched += int(fetched)
        # Detail can reveal completion state that the list record omitted.
        if commerce.is_abandoned(checkout):
            abandoned.append(checkout)

    return CheckoutSnapshot(
        records=tuple(abandoned),
        pages_read=pages_read,
        details_fetched=details_fetched,
        listed_count=len(listed),
        page_size=page_size,
        created_at_min=created_at_min,
    )


def read_abandoned_checkout_snapshot(
    store_domain: str,
    access_token: str,
    *,
    now: datetime | None = None,
) -> CheckoutSnapshot:
    """Read a complete recent abandoned-checkout snapshot from EasyStore.

    Collection timeouts retry by restarting from page one with a smaller page
    size. Detail failures are not hidden: a checkout whose contents cannot be
    read makes the Cart stage fail before any HubSpot Cart write.
    """

    created_at_min = checkout_window_start(now)
    collection_errors: list[str] = []
    for page_size in CHECKOUT_PAGE_SIZE_CANDIDATES:
        try:
            return _snapshot_with_page_size(
                store_domain,
                access_token,
                page_size=page_size,
                created_at_min=created_at_min,
            )
        except CheckoutCollectionReadError as error:
            message = " ".join(str(error).split())[:300]
            collection_errors.append(f"limit={page_size}: {message}")
            print(
                "WARNING: EasyStore checkout collection read failed with "
                f"limit={page_size}; restarting with a smaller page. {message}",
                file=sys.stderr,
            )

    raise SyncError(
        "EasyStore abandoned-checkout API could not be read with any safe page "
        "size. " + " | ".join(collection_errors)
    )


def _install_hubspot_cart_contract() -> None:
    commerce.CART_SCHEMA_OBJECT_TYPE = HUBSPOT_CART_SCHEMA_OBJECT_TYPE


def _validate_hubspot_cart_contract() -> None:
    _install_hubspot_cart_contract()
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
    """Synchronize only real EasyStore abandoned Checkout records to Carts."""

    _validate_hubspot_cart_contract()
    snapshot = read_abandoned_checkout_snapshot(
        store_domain,
        easystore_access_token,
    )

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

    domain = _shop_domain(store_domain)
    summary.update(
        {
            "easystore_abandoned_checkout_source": "checkouts",
            "easystore_checkout_collection_endpoint": (
                f"https://{domain}{EASYSTORE_CHECKOUT_COLLECTION_PATH}"
            ),
            "easystore_checkout_detail_endpoint_template": (
                f"https://{domain}/api/3.0/checkouts/:cart_token.json"
            ),
            "easystore_checkout_window_days": ABANDONED_CHECKOUT_WINDOW_DAYS,
            "easystore_checkout_created_at_min": snapshot.created_at_min,
            "easystore_checkout_sort": CHECKOUT_SORT,
            "easystore_checkout_page_size_used": snapshot.page_size,
            "easystore_checkout_page_size_candidates": list(
                CHECKOUT_PAGE_SIZE_CANDIDATES
            ),
            "easystore_checkout_pages_read": snapshot.pages_read,
            "easystore_checkout_details_fetched": snapshot.details_fetched,
            "easystore_checkouts_listed": snapshot.listed_count,
            "easystore_abandoned_checkouts_buffered": len(snapshot.records),
            "easystore_checkout_read_timeout_seconds": (
                CHECKOUT_READ_TIMEOUT_SECONDS
            ),
            "hubspot_cart_collection_endpoint": (
                f"{commerce.HUBSPOT_BASE}{HUBSPOT_CART_COLLECTION_PATH}"
            ),
            "hubspot_cart_properties_endpoint": (
                f"{commerce.HUBSPOT_BASE}{HUBSPOT_CART_PROPERTIES_PATH}"
            ),
            "hubspot_cart_schema_object_type": HUBSPOT_CART_SCHEMA_OBJECT_TYPE,
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
