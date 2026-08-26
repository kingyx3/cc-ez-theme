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


def source_status_for_order(order: dict[str, Any]) -> str | None:
    """Return the EasyStore list-bucket status recorded for this Order."""

    order_id = orders.nonempty(order.get("id"))
    return _ORDER_SOURCE_STATUS_BY_ID.get(order_id) if order_id is not None else None


def is_terminal_source_order(order: dict[str, Any]) -> bool:
    """Whether this Order came from a terminal EasyStore lifecycle bucket."""

    return source_status_for_order(order) in TERMINAL_ORDER_STATUSES


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

        def fetch(page: int, source_status: str = source_status) -> list[dict[str, Any]]:
            query = urlencode(
                {
                    "page": page,
                    "limit": orders.EASYSTORE_PAGE_SIZE,
                    "sort": "id.asc",
                    "status": source_status,
                }
            )
            document = orders._http_json(
                f"https://{domain}/api/3.0/orders.json?{query}",
                headers={"EasyStore-Access-Token": access_token},
            )
            return orders._extract_list(document, "orders", "data", "results")

        for order in orders.iter_easystore_pages(
            fetch,
            page_size=orders.EASYSTORE_PAGE_SIZE,
            what=f"orders.json?status={source_status}",
            error=orders.SyncError,
        ):
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
