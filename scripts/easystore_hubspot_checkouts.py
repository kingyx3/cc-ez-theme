#!/usr/bin/env python3
"""Sync EasyStore Checkout sessions into HubSpot Carts and abandoned Carts.

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

Every Checkout session becomes a HubSpot Cart. The unpaid, unconverted subset is
the abandoned-cart funnel and is flagged as such on the Cart itself; paid and
converted sessions stay Carts with their EasyStore status and can be associated
to the Order they became.

Reading the collection is retried with backoff, and the page size falls back from
the documented maximum to the smallest possible request, because this store has
served read timeouts on this endpoint. A complete snapshot is buffered and any
missing line items are hydrated from the documented detail endpoint before
HubSpot is mutated.

If EasyStore cannot serve the Checkout collection at all, that is an outage in
one upstream endpoint, not a broken CRM sync: Cart and Cart Line Item writes are
skipped, existing Cart→Order links are still refreshed from ``order.cart_token``,
the run is annotated with a warning naming the exact failed request, and the
summary reports ``easystore_checkout_status: unavailable``. Pass
``--require-checkouts`` (or set ``EASYSTORE_CHECKOUTS_REQUIRED=1``) to make that
outage fail the step instead. Everything else still fails loudly: an unknown
response shape, a detail response without line items, a duplicate Cart identity,
a bad product reference, or any HubSpot write error.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
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
#
# The page sizes are tried in order. EasyStore documents 50 as the maximum, which
# needs the fewest requests; 1 is the smallest request the endpoint can be asked
# for, and is what a store that times out on anything larger can still answer.
# Only a transport-level failure moves on to the next size, and each size starts
# again from page 1, so a snapshot is never stitched together from two of them.
CHECKOUT_PAGE_SIZES = (50, 1)
CHECKOUT_READ_TIMEOUT_SECONDS = 30
CHECKOUT_READ_RETRIES = 1


class CheckoutSourceUnavailable(SyncError):
    """EasyStore could not serve the Checkout collection or a required detail.

    This is deliberately narrow: it means a request never came back, was rate
    limited past its retries, or failed with a server error. A response that
    arrived and broke the data contract is a plain :class:`SyncError`, because
    reading it wrong would corrupt HubSpot Carts.
    """


@dataclass(frozen=True)
class CheckoutSnapshot:
    records: tuple[dict[str, Any], ...]
    pages_read: int
    details_fetched: int
    page_size: int = CHECKOUT_PAGE_SIZES[0]
    attempts: tuple[str, ...] = ()


def _short(error: BaseException) -> str:
    return " ".join(str(error).split())[:300]


def _is_source_outage(error: SyncError) -> bool:
    """Return whether a failed request means "EasyStore did not answer".

    ``_http_json`` chains the underlying urllib failure, so the cause says which
    kind of failure this was: a timeout or a refused connection is an outage, and
    so is a 429 or a 5xx that survived the retries. A 4xx is a request or
    credential problem this sync must not paper over.
    """

    cause = error.__cause__
    if isinstance(cause, HTTPError):
        return cause.code == 429 or 500 <= cause.code < 600
    return isinstance(cause, (URLError, TimeoutError))


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


def _checkout_get(url: str, access_token: str, *, what: str) -> Any:
    """Read one documented Checkout URL, naming an outage as such."""

    try:
        return _http_json(
            url,
            headers={"EasyStore-Access-Token": access_token},
            retries=CHECKOUT_READ_RETRIES,
            timeout=CHECKOUT_READ_TIMEOUT_SECONDS,
        )
    except SyncError as error:
        if _is_source_outage(error):
            raise CheckoutSourceUnavailable(
                f"{what} did not answer after {CHECKOUT_READ_RETRIES + 1} "
                f"attempts of {CHECKOUT_READ_TIMEOUT_SECONDS}s: {_short(error)}"
            ) from error
        raise


def _collection_url(domain: str, page: int, page_size: int) -> str:
    query = urlencode({"page": page, "limit": page_size})
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
        _checkout_get(
            f"https://{domain}{path}",
            access_token,
            what=f"EasyStore checkout {cart_token} detail",
        ),
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


def _read_collection(
    domain: str,
    access_token: str,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    """Read every Checkout page at one page size, all or nothing.

    Pagination is all-or-nothing. Repeated pages are rejected so an endpoint
    that ignores ``page`` cannot trap the workflow in a loop or expose a partial
    snapshot to HubSpot.
    """

    page = 1
    pages_read = 0
    listed_records: list[dict[str, Any]] = []
    seen_page_signatures: set[tuple[str, ...]] = set()

    while True:
        document = _checkout_get(
            _collection_url(domain, page, page_size),
            access_token,
            what=(
                "EasyStore Checkout collection using the minimal documented "
                f"request (page={page}, limit={page_size}, no sort/date/product "
                "filters)"
            ),
        )

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

        if len(records) < page_size:
            return listed_records, pages_read
        page += 1


def read_checkout_snapshot(
    store_domain: str,
    access_token: str,
) -> CheckoutSnapshot:
    """Read and hydrate the complete Checkout collection before HubSpot is touched.

    Each documented page size is tried in turn; a size that never answers is
    recorded and the next one starts over from page 1. When none of them answer,
    :class:`CheckoutSourceUnavailable` names every request that was tried.
    """

    domain = _shop_domain(store_domain)
    attempts: list[str] = []

    for page_size in CHECKOUT_PAGE_SIZES:
        try:
            listed_records, pages_read = _read_collection(
                domain,
                access_token,
                page_size,
            )
        except CheckoutSourceUnavailable as error:
            attempts.append(f"limit={page_size}: {_short(error)}")
            continue

        attempts.append(f"limit={page_size}: answered {len(listed_records)} checkouts")
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
            page_size=page_size,
            attempts=tuple(attempts),
        )

    raise CheckoutSourceUnavailable(
        "EasyStore served no Checkout collection for any documented page size. "
        + "; ".join(attempts)
    )


def _validate_hubspot_cart_contract() -> None:
    expected = f"{commerce.HUBSPOT_BASE}{HUBSPOT_CART_COLLECTION_PATH}"
    if commerce.HUBSPOT_CARTS_URL != expected:
        raise SyncError(
            f"HubSpot Cart endpoint drift detected: expected {expected}, "
            f"got {commerce.HUBSPOT_CARTS_URL}"
        )


def _endpoint_summary(store_domain: str) -> dict[str, Any]:
    domain = _shop_domain(store_domain)
    return {
        "easystore_checkout_source": "public_api_checkouts",
        "easystore_checkout_collection_endpoint": (
            f"https://{domain}{EASYSTORE_CHECKOUT_COLLECTION_PATH}"
        ),
        "easystore_checkout_detail_endpoint_template": (
            f"https://{domain}/api/3.0/checkouts/:cart_token.json"
        ),
        "easystore_checkout_collection_query": "page,limit only",
        "easystore_checkout_page_sizes_tried_in_order": list(CHECKOUT_PAGE_SIZES),
        "easystore_checkout_product_style_filters_sent": False,
        "easystore_checkout_read_timeout_seconds": CHECKOUT_READ_TIMEOUT_SECONDS,
        "easystore_checkout_read_retries": CHECKOUT_READ_RETRIES,
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


def link_existing_carts_to_orders(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
) -> dict[str, Any]:
    """Keep Cart→Order conversion links current without any Checkout read.

    An outage in the Checkout endpoint does not invalidate what HubSpot already
    holds: Carts synchronized by an earlier run can still be attached to the
    Orders they became, because that link comes from ``order.cart_token``.
    """

    if not commerce.cart_object_available(
        hubspot_access_token,
        HUBSPOT_CART_SCHEMA_OBJECT_TYPE,
    ):
        return {
            "hubspot_cart_object": "unavailable",
            "easystore_orders_scanned_for_cart_links": 0,
            "cart_order_associations_ensured": 0,
        }

    orders = list(
        commerce.iter_orders_for_cart_links(store_domain, easystore_access_token)
    )
    carts = commerce.hubspot_cart_index(hubspot_access_token)
    linked = commerce.link_carts_to_orders(
        orders=orders,
        hubspot_access_token=hubspot_access_token,
        carts_by_token=carts,
        hubspot_orders=commerce.hubspot_order_index(hubspot_access_token),
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
    require_checkouts: bool = False,
) -> dict[str, Any]:
    """Synchronize all real EasyStore Checkout sessions into HubSpot Carts."""

    _validate_hubspot_cart_contract()
    summary = _endpoint_summary(store_domain)

    try:
        snapshot = read_checkout_snapshot(store_domain, easystore_access_token)
    except CheckoutSourceUnavailable as error:
        if require_checkouts:
            raise
        reason = _short(error)
        print(
            "::warning title=EasyStore Checkout API unavailable::"
            "HubSpot Cart and Cart Line Item writes were skipped this run. "
            "Cart->Order links were still refreshed from order.cart_token. "
            + reason,
            file=sys.stderr,
        )
        summary.update(
            link_existing_carts_to_orders(
                store_domain=store_domain,
                easystore_access_token=easystore_access_token,
                hubspot_access_token=hubspot_access_token,
            )
        )
        summary.update(
            {
                "easystore_checkout_status": "unavailable",
                "easystore_checkout_error": reason,
                "easystore_checkouts_scanned": 0,
                "easystore_checkout_pages_read": 0,
                "easystore_checkout_details_fetched": 0,
                "easystore_checkouts_buffered": 0,
                "hubspot_cart_upserts_skipped": True,
                "hubspot_cart_line_item_sync_skipped": True,
            }
        )
        return summary

    # HubSpot Carts represent shopping sessions that may later be purchased or
    # abandoned, so every real Checkout is fed to the Cart writer with its own
    # financial_status preserved as hs_external_status. The abandoned subset is
    # counted here and flagged on each Cart by the shared cart mapping.
    abandoned = sum(1 for item in snapshot.records if commerce.is_abandoned(item))

    summary.update(
        commerce.sync(
            store_domain=store_domain,
            easystore_access_token=easystore_access_token,
            hubspot_access_token=hubspot_access_token,
            fallback_dial_code=fallback_dial_code,
            checkouts=snapshot.records,
            include_completed=True,
            cart_schema_object_type=HUBSPOT_CART_SCHEMA_OBJECT_TYPE,
        )
    )
    summary.update(
        {
            "easystore_checkout_status": "available",
            "easystore_checkout_collection_attempts": list(snapshot.attempts),
            "easystore_checkout_page_size_used": snapshot.page_size,
            "easystore_checkout_pages_read": snapshot.pages_read,
            "easystore_checkout_details_fetched": snapshot.details_fetched,
            "easystore_checkouts_buffered": len(snapshot.records),
            "easystore_checkouts_abandoned_or_open": abandoned,
            "easystore_checkouts_completed_or_paid": len(snapshot.records) - abandoned,
            "hubspot_cart_upserts_skipped": False,
            "hubspot_cart_line_item_sync_skipped": False,
        }
    )
    return summary


def _required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise SyncError(f"{name} is required")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-domain", default=os.getenv("EASYSTORE_STORE_DOMAIN"))
    parser.add_argument("--easystore-token", default=os.getenv("EASYSTORE_ACCESS_TOKEN"))
    parser.add_argument("--hubspot-token", default=os.getenv("HUBSPOT_ACCESS_TOKEN"))
    parser.add_argument(
        "--fallback-dial-code",
        default=os.getenv("CUSTOMER_SYNC_DEFAULT_DIAL_CODE", "65"),
    )
    parser.add_argument(
        "--require-checkouts",
        action="store_true",
        default=_truthy(os.getenv("EASYSTORE_CHECKOUTS_REQUIRED")),
        help=(
            "Fail instead of degrading when EasyStore cannot serve the Checkout "
            "collection. Use this once the endpoint is known to be reliable."
        ),
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
            require_checkouts=args.require_checkouts,
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
