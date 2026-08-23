#!/usr/bin/env python3
"""Production Checkout/Cart sync with native HubSpot Cart lifecycle status.

HubSpot exposes one native Cart lifecycle field in this portal:
``hs_external_status`` (label: Status). It is the authoritative human-readable
state of the shopping session, so the production sync writes the normalized CRM
states ``Abandoned`` and ``Recovered`` there instead of leaking EasyStore's raw
``unpaid`` value into the HubSpot card.

Cart records remain associated to their Contact for history. When the checkout
has become an EasyStore Order, the existing Cart→Order linker is also the point
where the Cart becomes recovered: the same HubSpot Cart is retained, native
``hs_external_status`` is set to ``Recovered``, the EasyStore-specific abandoned
flag is cleared as supplemental source data, and no Contact→Cart association is
removed.
"""

from __future__ import annotations

import sys
from typing import Any

import easystore_hubspot_checkouts as checkouts
import easystore_hubspot_commerce as commerce
import easystore_hubspot_orders as orders
from easystore_hubspot_contact_identity import hubspot_contact_index


NATIVE_CART_STATUS_PROPERTY = "hs_external_status"
ABANDONED_STATUS = "Abandoned"
RECOVERED_STATUS = "Recovered"

_BASE_CART_PROPERTIES = commerce.cart_properties
_BASE_LINK_CARTS_TO_ORDERS = commerce.link_carts_to_orders


def semantic_cart_status(checkout: dict[str, Any]) -> str:
    """Return the normalized HubSpot Cart lifecycle state for one checkout."""

    return ABANDONED_STATUS if commerce.is_abandoned(checkout) else RECOVERED_STATUS


def cart_properties_with_native_status(
    checkout: dict[str, Any],
    *,
    cart_token: str,
    store_domain: str,
    field_properties: dict[str, str],
    fallback_dial_code: str,
) -> dict[str, str]:
    """Map a checkout and make HubSpot's native Status lifecycle-authoritative.

    The low-level mapper retains EasyStore-specific source fields for diagnostics,
    including ``easystore_cart_is_abandoned``. When the portal resolves the
    standard Cart Status field, however, its value is normalized to the CRM
    lifecycle a person actually needs to see: Abandoned or Recovered.
    """

    properties = _BASE_CART_PROPERTIES(
        checkout,
        cart_token=cart_token,
        store_domain=store_domain,
        field_properties=field_properties,
        fallback_dial_code=fallback_dial_code,
    )
    if field_properties.get("status") == NATIVE_CART_STATUS_PROPERTY:
        properties[NATIVE_CART_STATUS_PROPERTY] = semantic_cart_status(checkout)
    return properties


def link_carts_to_orders_and_reconcile(
    *,
    orders: list[dict[str, Any]],
    hubspot_access_token: str,
    carts_by_token: dict[str, str],
    hubspot_orders: dict[str, str],
) -> int:
    """Link converted Carts to Orders and mark native Status as Recovered.

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
                    NATIVE_CART_STATUS_PROPERTY: RECOVERED_STATUS,
                    "easystore_cart_is_abandoned": "false",
                }
            },
        )
        reconciled_cart_ids.add(cart_id)

    if reconciled_cart_ids:
        print(
            "Reconciled "
            f"{len(reconciled_cart_ids)} converted HubSpot Cart(s) to native "
            f"{NATIVE_CART_STATUS_PROPERTY}={RECOVERED_STATUS} after Cart→Order linking.",
            file=sys.stderr,
        )
    return linked


def main(argv: list[str] | None = None) -> int:
    # commerce imported these helpers by name, so patch its module globals before
    # the checkout entrypoint starts mapping Carts or resolving associations.
    orders.hubspot_contact_index = hubspot_contact_index
    commerce.hubspot_contact_index = hubspot_contact_index
    commerce.cart_properties = cart_properties_with_native_status
    commerce.link_carts_to_orders = link_carts_to_orders_and_reconcile
    return checkouts.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
