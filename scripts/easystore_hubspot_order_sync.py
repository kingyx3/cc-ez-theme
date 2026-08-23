#!/usr/bin/env python3
"""Production Order sync entrypoint with portal-specific HubSpot mappings."""

from __future__ import annotations

from typing import Any

import easystore_hubspot_orders as orders
from easystore_hubspot_contact_identity import hubspot_contact_index
from easystore_hubspot_schema import first_present, nonempty


HUBSPOT_EXTERNAL_ORDER_STATUS = "hs_external_order_status"
HUBSPOT_SHIPPING_ADDRESS_NAME = "hs_shipping_address_name"

ORDER_STATUS_SOURCES = (
    "status_label",
    "order_status_label",
    "status",
    "order_status",
    "state_label",
    "state",
    "order_state",
)
PAYMENT_STATUS_SOURCES = (
    "payment_status_label",
    "financial_status_label",
    "payment_status",
    "financial_status",
)
FULFILLMENT_STATUS_SOURCES = (
    "fulfillment_status_label",
    "fulfillment_status",
    "shipment_status",
    "shipping_status",
)


def _status_key(value: Any) -> str:
    text = nonempty(value)
    if text is None:
        return ""
    return "_".join(text.casefold().replace("-", " ").split())


def easystore_order_status(order: dict[str, Any]) -> str | None:
    """Return one actionable EasyStore state for HubSpot's native Status field.

    EasyStore exposes order, payment and fulfilment state separately. HubSpot's
    ``hs_external_order_status`` is one source-system status, so the production
    sync rolls those source facts up without inventing HubSpot-only states:

    * refunded/partially-refunded payment state wins;
    * cancellation/deletion wins next;
    * fulfilled/partially-fulfilled/restocked wins over paid;
    * otherwise payment state wins, then the raw EasyStore order state.

    The original EasyStore label/value is returned so casing and wording remain
    source-authentic. Payment and fulfilment are still synchronized separately to
    ``hs_payment_status`` and ``hs_fulfillment_status``.
    """

    order_state = first_present(order, ORDER_STATUS_SOURCES)
    payment_state = first_present(order, PAYMENT_STATUS_SOURCES)
    fulfillment_state = first_present(order, FULFILLMENT_STATUS_SOURCES)

    payment_key = _status_key(payment_state)
    order_key = _status_key(order_state)
    fulfillment_key = _status_key(fulfillment_state)

    if "refund" in payment_key:
        return payment_state

    if order_key in {"cancelled", "canceled", "deleted"}:
        return order_state
    if order_state is None and order.get("is_cancelled") is True:
        return "cancelled"

    if fulfillment_key and fulfillment_key not in {"unfulfilled", "pending"}:
        return fulfillment_state

    if payment_state is not None:
        return payment_state
    return order_state or fulfillment_state


def _refresh_default_order_field_properties() -> None:
    orders.DEFAULT_ORDER_FIELD_PROPERTIES = {
        field.key: field.native[0] if field.native else field.fallback
        for field in orders.ORDER_FIELDS
        if field.native or field.fallback
    }


def configure_order_status_mapping() -> None:
    """Point the generic Order mapper at HubSpot's actual native Status field."""

    configured = []
    for field in orders.ORDER_FIELDS:
        if field.key == "order_status":
            configured.append(
                field._replace(
                    native=(HUBSPOT_EXTERNAL_ORDER_STATUS,),
                    description=(
                        "Actionable EasyStore order state rolled up from payment, "
                        "fulfilment and terminal order status for HubSpot Status."
                    ),
                )
            )
        else:
            configured.append(field)

    orders.ORDER_FIELDS = tuple(configured)
    orders.ORDER_FIELD_DERIVATIONS["order_status"] = easystore_order_status
    _refresh_default_order_field_properties()


def configure_shipping_recipient_mapping() -> None:
    """Write EasyStore's delivery recipient into HubSpot's native address name."""

    configured = []
    for field in orders.ORDER_FIELDS:
        if field.key == "shipping_recipient":
            configured.append(
                field._replace(
                    native=(HUBSPOT_SHIPPING_ADDRESS_NAME,),
                    fallback=None,
                    description=(
                        "Name EasyStore records on the delivery address, written "
                        "to HubSpot Shipping Address Customer Name."
                    ),
                )
            )
        else:
            configured.append(field)

    orders.ORDER_FIELDS = tuple(configured)
    _refresh_default_order_field_properties()


def main(argv: list[str] | None = None) -> int:
    # Keep the generic mapping implementation in easystore_hubspot_orders, but
    # inject the same authoritative Contact identity used by preflight/customer
    # sync plus the portal's actual native Order fields.
    orders.hubspot_contact_index = hubspot_contact_index
    configure_order_status_mapping()
    configure_shipping_recipient_mapping()
    return orders.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
