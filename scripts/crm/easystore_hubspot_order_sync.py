#!/usr/bin/env python3
"""Production Order sync entrypoint with complete EasyStore status coverage.

EasyStore's Orders API exposes terminal orders through status-specific collections.
Production queries every documented lifecycle collection explicitly so cancelled,
archived, and deleted orders cannot disappear from later HubSpot lifecycle runs.

Historical terminal orders can legitimately reference variants that have since
been removed from the live catalogue. Current/open orders still require every
line to resolve to a HubSpot Product; terminal orders keep syncing when a retired
SKU no longer has a current Product, with that line reported and skipped.

The portal-specific HubSpot mapping stays in ``easystore_hubspot_order_sync_impl``.
This stable entrypoint installs the production source iterator and terminal-order
line policy only while ``main`` runs, so importing the module remains side-effect
free for tests and library use.
"""

from __future__ import annotations

import sys
from typing import Any, Iterator
from urllib.parse import urlencode

import easystore_hubspot_orders as orders


# EasyStore documents four Order-list lifecycle buckets. Query all of them so
# production reconciliation has complete source visibility, including records
# that EasyStore marks deleted.
EASYSTORE_SYNC_ORDER_STATUSES = ("open", "cancelled", "archived", "deleted")
TERMINAL_ORDER_STATUSES = frozenset({"cancelled", "archived", "deleted"})

# The list endpoint status filter is the authoritative lifecycle bucket even when
# a later detail response omits the same fact. Keep it keyed by immutable Order ID
# for the duration of one process/run.
_ORDER_SOURCE_STATUS_BY_ID: dict[str, str] = {}
_BASE_DESIRED_LINES = orders.desired_lines

# Mirrors the largest first-tier limit already proven against EasyStore's equally
# untrustworthy checkouts.json pagination (docs/EASYSTORE_CHECKOUT_CART_SYNC.md).
_LARGE_ORDER_PAGE_LIMIT = 250


def source_status_for_order(order: dict[str, Any]) -> str | None:
    """Return the EasyStore list-bucket status recorded for this Order."""

    order_id = orders.nonempty(order.get("id"))
    return _ORDER_SOURCE_STATUS_BY_ID.get(order_id) if order_id is not None else None


def is_terminal_source_order(order: dict[str, Any]) -> bool:
    """Whether this Order came from a terminal EasyStore lifecycle bucket."""

    return source_status_for_order(order) in TERMINAL_ORDER_STATUSES


def _fetch_order_status_bucket(
    domain: str,
    access_token: str,
    source_status: str,
) -> Iterator[dict[str, Any]]:
    """Yield every Order in one EasyStore status bucket.

    ``orders.json`` has started exhibiting the same untrustworthy ``page``
    parameter already documented for ``checkouts.json``
    (docs/EASYSTORE_CHECKOUT_CART_SYNC.md): a later page can repeat records an
    earlier page already served instead of advancing. ``iter_easystore_pages``
    refuses to loop on that rather than risk an infinite fetch. Before failing
    the run, one larger-``limit`` request is tried: an answer shorter than
    that limit proves it is the whole bucket, the same proof the Checkout
    stage relies on. An answer that is still saturated at the larger limit
    cannot prove completeness, so the original page-repeat error is raised
    instead of risking a silently incomplete Order sync.
    """

    def fetch(page: int, *, limit: int = orders.EASYSTORE_PAGE_SIZE) -> list[dict[str, Any]]:
        query = urlencode(
            {
                "page": page,
                "limit": limit,
                "sort": "id.asc",
                "status": source_status,
            }
        )
        document = orders._http_json(
            f"https://{domain}/api/3.0/orders.json?{query}",
            headers={"EasyStore-Access-Token": access_token},
        )
        return orders._extract_list(document, "orders", "data", "results")

    try:
        yield from orders.iter_easystore_pages(
            fetch,
            page_size=orders.EASYSTORE_PAGE_SIZE,
            what=f"orders.json?status={source_status}",
            error=orders.SyncError,
        )
        return
    except orders.SyncError as error:
        if "page parameter does nothing" not in str(error):
            raise

    records = fetch(1, limit=_LARGE_ORDER_PAGE_LIMIT)
    if len(records) >= _LARGE_ORDER_PAGE_LIMIT:
        raise orders.SyncError(
            f"EasyStore orders.json?status={source_status} repeats pages at "
            f"limit={orders.EASYSTORE_PAGE_SIZE} and is still saturated at "
            f"limit={_LARGE_ORDER_PAGE_LIMIT}, so a complete snapshot cannot be "
            "proven. Refusing to sync a possibly-incomplete Order bucket."
        )

    print(
        f"WARNING: EasyStore orders.json?status={source_status} repeated a page "
        f"at limit={orders.EASYSTORE_PAGE_SIZE}; recovered the complete bucket "
        f"with one limit={_LARGE_ORDER_PAGE_LIMIT} request ({len(records)} "
        "orders).",
        file=sys.stderr,
    )
    yield from records


def iter_easystore_orders_all_statuses(
    store_domain: str,
    access_token: str,
) -> Iterator[dict[str, Any]]:
    """Yield every EasyStore Order across all documented status buckets exactly once.

    EasyStore documents ``status`` as an Orders-list filter. Production data has
    shown that relying on the unfiltered collection can omit terminal orders, so
    each lifecycle bucket is paginated explicitly. De-duplication by immutable
    EasyStore order ID protects the sync if the API ever overlaps buckets while an
    order is transitioning between states. The first bucket wins; since ``open``
    is queried first, an overlapping current Order retains the stricter policy.
    """

    domain = orders._shop_domain(store_domain)
    seen_order_ids: set[str] = set()
    _ORDER_SOURCE_STATUS_BY_ID.clear()

    for source_status in EASYSTORE_SYNC_ORDER_STATUSES:
        for order in _fetch_order_status_bucket(domain, access_token, source_status):
            order_id = orders.nonempty(order.get("id"))
            if order_id is not None:
                if order_id in seen_order_ids:
                    continue
                seen_order_ids.add(order_id)
                _ORDER_SOURCE_STATUS_BY_ID[order_id] = source_status
            yield order


def desired_lines_with_terminal_product_tolerance(
    order: dict[str, Any],
    product_by_sku: dict[str, str],
    field_properties: dict[str, str] | None = None,
    *,
    record: str = "order",
    unmatched_lines: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Keep current Orders strict while tolerating retired SKUs on terminal history.

    A missing Product on an ``open`` Order still raises exactly as the generic
    commerce invariant requires. Cancelled, archived and deleted Orders are
    historical snapshots; their variants may no longer exist in the current
    EasyStore catalogue and therefore cannot be recreated by the Product stage.
    Those unmatched historical lines are skipped rather than blocking every
    later Order in the run.
    """

    if not is_terminal_source_order(order):
        return _BASE_DESIRED_LINES(
            order,
            product_by_sku,
            field_properties,
            record=record,
            unmatched_lines=unmatched_lines,
        )

    skipped = unmatched_lines if unmatched_lines is not None else []
    desired = _BASE_DESIRED_LINES(
        order,
        product_by_sku,
        field_properties,
        record=record,
        unmatched_lines=skipped,
    )
    if skipped and unmatched_lines is None:
        external_id = orders.nonempty(order.get("id")) or "(unknown)"
        print(
            "WARNING: terminal EasyStore order "
            f"{external_id} ({source_status_for_order(order)}) references retired "
            "or unavailable Product line(s): "
            + ", ".join(skipped)
            + ". The Order will sync and those historical lines will be skipped.",
            file=sys.stderr,
        )
    return desired


# Keep the existing portal-specific implementation as the module users receive.
# This preserves its public/private test surface while making the file above the
# stable production entrypoint.
import easystore_hubspot_order_sync_impl as _impl  # noqa: E402


if not hasattr(_impl, "_STATUS_COMPLETE_CORE_MAIN"):
    _impl._STATUS_COMPLETE_CORE_MAIN = _impl.main

_impl.EASYSTORE_SYNC_ORDER_STATUSES = EASYSTORE_SYNC_ORDER_STATUSES
_impl.TERMINAL_ORDER_STATUSES = TERMINAL_ORDER_STATUSES
_impl._ORDER_SOURCE_STATUS_BY_ID = _ORDER_SOURCE_STATUS_BY_ID
_impl.source_status_for_order = source_status_for_order
_impl.is_terminal_source_order = is_terminal_source_order
_impl.iter_easystore_orders_all_statuses = iter_easystore_orders_all_statuses
_impl._fetch_order_status_bucket = _fetch_order_status_bucket
_impl._LARGE_ORDER_PAGE_LIMIT = _LARGE_ORDER_PAGE_LIMIT
_impl.desired_lines_with_terminal_product_tolerance = (
    desired_lines_with_terminal_product_tolerance
)


def main(argv: list[str] | None = None) -> int:
    """Run the existing production sync against every EasyStore Order bucket."""

    previous_iterator = orders.iter_easystore_orders
    previous_desired_lines = orders.desired_lines
    _ORDER_SOURCE_STATUS_BY_ID.clear()
    orders.iter_easystore_orders = iter_easystore_orders_all_statuses
    orders.desired_lines = desired_lines_with_terminal_product_tolerance
    try:
        return _impl._STATUS_COMPLETE_CORE_MAIN(argv)
    finally:
        orders.iter_easystore_orders = previous_iterator
        orders.desired_lines = previous_desired_lines
        _ORDER_SOURCE_STATUS_BY_ID.clear()


_impl.main = main

if __name__ == "__main__":
    raise SystemExit(main())

# When imported, preserve backwards compatibility exactly: callers and tests get
# the implementation module object, including mutable runtime state such as the
# resolved HubSpot pipeline IDs.
sys.modules[__name__] = _impl
