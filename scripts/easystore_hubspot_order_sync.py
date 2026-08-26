#!/usr/bin/env python3
"""Production Order sync entrypoint with complete EasyStore status coverage.

EasyStore's Orders API exposes terminal orders through status-specific collections.
Production queries every documented lifecycle collection explicitly so cancelled,
archived, and deleted orders cannot disappear from later HubSpot lifecycle runs.

The portal-specific HubSpot mapping stays in ``easystore_hubspot_order_sync_impl``.
This stable entrypoint installs the complete source iterator only while ``main``
runs, so importing the module remains side-effect free for tests and library use.
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


def iter_easystore_orders_all_statuses(
    store_domain: str,
    access_token: str,
) -> Iterator[dict[str, Any]]:
    """Yield every EasyStore Order across all documented status buckets exactly once.

    EasyStore documents ``status`` as an Orders-list filter. Production data has
    shown that relying on the unfiltered collection can omit terminal orders, so
    each lifecycle bucket is paginated explicitly. De-duplication by immutable
    EasyStore order ID protects the sync if the API ever overlaps buckets while an
    order is transitioning between states.
    """

    domain = orders._shop_domain(store_domain)
    seen_order_ids: set[str] = set()

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
            yield order


# Keep the existing portal-specific implementation as the module users receive.
# This preserves its public/private test surface while making the file above the
# stable production entrypoint.
import easystore_hubspot_order_sync_impl as _impl  # noqa: E402


if not hasattr(_impl, "_STATUS_COMPLETE_CORE_MAIN"):
    _impl._STATUS_COMPLETE_CORE_MAIN = _impl.main

_impl.EASYSTORE_SYNC_ORDER_STATUSES = EASYSTORE_SYNC_ORDER_STATUSES
_impl.iter_easystore_orders_all_statuses = iter_easystore_orders_all_statuses


def main(argv: list[str] | None = None) -> int:
    """Run the existing production sync against every EasyStore Order bucket."""

    previous_iterator = orders.iter_easystore_orders
    orders.iter_easystore_orders = iter_easystore_orders_all_statuses
    try:
        return _impl._STATUS_COMPLETE_CORE_MAIN(argv)
    finally:
        orders.iter_easystore_orders = previous_iterator


_impl.main = main

if __name__ == "__main__":
    raise SystemExit(main())

# When imported, preserve backwards compatibility exactly: callers and tests get
# the implementation module object, including mutable runtime state such as the
# resolved HubSpot pipeline IDs.
sys.modules[__name__] = _impl
