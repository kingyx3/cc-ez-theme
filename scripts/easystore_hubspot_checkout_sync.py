#!/usr/bin/env python3
"""Production Checkout/Cart sync entrypoint with primary-Phone Contact identity.

Cart records remain associated to their Contact for history. When the checkout
has become an EasyStore Order, the existing Cart→Order linker is also the point
where the Cart stops being abandoned: the same HubSpot Cart is retained, its
``easystore_cart_is_abandoned`` flag is set to ``false``, and no Contact→Cart
association is removed.
"""

from __future__ import annotations

import sys
from typing import Any

import easystore_hubspot_checkouts as checkouts
import easystore_hubspot_commerce as commerce
import easystore_hubspot_orders as orders
from easystore_hubspot_contact_identity import hubspot_contact_index


_BASE_LINK_CARTS_TO_ORDERS = commerce.link_carts_to_orders


def link_carts_to_orders_and_reconcile(
    *,
    orders: list[dict[str, Any]],
    hubspot_access_token: str,
    carts_by_token: dict[str, str],
    hubspot_orders: dict[str, str],
) -> int:
    """Link converted Carts to Orders and clear their abandoned state.

    A Cart remains a historical shopping-session record after payment, so the
    Contact association is intentionally untouched. Only Carts for which both the
    EasyStore cart token and the synchronized HubSpot Order resolve are changed.
    """

    linked = _BASE_LINK_CARTS_TO_ORDERS(
        orders=orders,
        hubspot_access_token=hubspot_access_token,
        carts_by_token=carts_by_token,
        hubspot_orders=hubspot_orders,
    )

    reconciled_cart_ids: set[str] = set()
    for order in orders:
        cart_token = commerce.nonempty(order.get("cart_token"))
        order_external_id = commerce.nonempty(order.get("id"))
        if cart_token is None or order_external_id is None:
            continue
        cart_id = carts_by_token.get(cart_token)
        order_id = hubspot_orders.get(order_external_id)
        if cart_id is None or order_id is None or cart_id in reconciled_cart_ids:
            continue

        commerce._http_json(
            f"{commerce.HUBSPOT_CARTS_URL}/{cart_id}",
            method="PATCH",
            headers={"Authorization": f"Bearer {hubspot_access_token}"},
            payload={
                "properties": {
                    "easystore_cart_is_abandoned": "false",
                }
            },
        )
        reconciled_cart_ids.add(cart_id)

    if reconciled_cart_ids:
        print(
            "Reconciled "
            f"{len(reconciled_cart_ids)} converted HubSpot Cart(s) to "
            "easystore_cart_is_abandoned=false after Cart→Order linking.",
            file=sys.stderr,
        )
    return linked


def main(argv: list[str] | None = None) -> int:
    # commerce imported the low-level Contact index by name, so patch both module
    # globals before the checkout entrypoint starts resolving Cart associations.
    orders.hubspot_contact_index = hubspot_contact_index
    commerce.hubspot_contact_index = hubspot_contact_index
    commerce.link_carts_to_orders = link_carts_to_orders_and_reconcile
    return checkouts.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
