#!/usr/bin/env python3
"""Production Order sync entrypoint with portal-specific HubSpot mappings."""

from __future__ import annotations

from typing import Any

import easystore_hubspot_orders as orders
from easystore_hubspot_contact_identity import hubspot_contact_index
from easystore_hubspot_schema import FieldSpec, first_present, nonempty


HUBSPOT_EXTERNAL_ORDER_STATUS = "hs_external_order_status"
HUBSPOT_EXTERNAL_ORDER_MODIFIED_DATE = "hs_external_modified_date"
HUBSPOT_SHIPPING_ADDRESS_NAME = "hs_shipping_address_name"

ORDER_MODIFIED_SOURCES = (
    "updated_at",
    "modified_at",
    "updated_on",
    "modified_on",
    "last_modified_at",
)
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
CANCELLED_STATUS_KEYS = {"cancelled", "canceled", "deleted"}
FALSEY_CANCELLATION_KEYS = {"", "0", "false", "nil", "null", "none"}
_BASE_COMPLETE_ORDER = orders.complete_order


def _status_key(value: Any) -> str:
    text = nonempty(value)
    if text is None:
        return ""
    return "_".join(text.casefold().replace("-", " ").split())


def _positive_cancellation_flag(value: Any) -> bool:
    """Accept EasyStore's boolean/integer/string cancellation flag shapes."""

    return _status_key(value) in {"1", "true", "yes"}


def _cancellation_status(
    order: dict[str, Any],
    order_state: str | None,
    payment_state: str | None,
    fulfillment_state: str | None,
) -> str | None:
    """Return EasyStore's cancellation label when any known signal cancels it.

    The storefront receives several EasyStore order shapes. Depending on the
    route, cancellation can be a status label, an integer/boolean flag, or a
    timestamp. Treat only positive signals as cancellation so missing/false
    fields never invent a cancelled state.
    """

    for state in (order_state, payment_state, fulfillment_state):
        if _status_key(state) in CANCELLED_STATUS_KEYS:
            return state

    for key in ("is_cancelled", "cancelled", "canceled"):
        if _positive_cancellation_flag(order.get(key)):
            return "cancelled"

    for key in ("cancelled_at", "canceled_at", "cancellation_date"):
        value = nonempty(order.get(key))
        if value is not None and _status_key(value) not in FALSEY_CANCELLATION_KEYS:
            return "cancelled"

    return None


def easystore_order_status(order: dict[str, Any]) -> str | None:
    """Return one actionable EasyStore state for HubSpot's native Status field.

    EasyStore exposes order, payment and fulfilment state separately. HubSpot's
    ``hs_external_order_status`` is one source-system status, so the production
    sync rolls those source facts up without inventing HubSpot-only states:

    * any explicit cancellation signal wins, including flags/timestamps;
    * refunded/partially-refunded payment state wins next;
    * fulfilled/partially-fulfilled/restocked wins over paid;
    * otherwise payment state wins, then the raw EasyStore order state.

    Cancellation is intentionally first: EasyStore can refund an order as part of
    cancelling it, but HubSpot Status should still say Cancelled when the order is
    explicitly cancelled. Payment and fulfilment remain synchronized separately
    to ``hs_payment_status`` and ``hs_fulfillment_status``.
    """

    order_state = first_present(order, ORDER_STATUS_SOURCES)
    payment_state = first_present(order, PAYMENT_STATUS_SOURCES)
    fulfillment_state = first_present(order, FULFILLMENT_STATUS_SOURCES)

    cancellation = _cancellation_status(
        order,
        order_state,
        payment_state,
        fulfillment_state,
    )
    if cancellation is not None:
        return cancellation

    payment_key = _status_key(payment_state)
    fulfillment_key = _status_key(fulfillment_state)

    if "refund" in payment_key:
        return payment_state

    if fulfillment_key and fulfillment_key not in {"unfulfilled", "pending"}:
        return fulfillment_state

    if payment_state is not None:
        return payment_state
    return order_state or fulfillment_state


def complete_order_with_modified_date(
    store_domain: str,
    access_token: str,
    order: dict[str, Any],
    *,
    commerce_fields: bool = True,
) -> dict[str, Any]:
    """Ensure production has EasyStore's source modification timestamp.

    EasyStore list records can be thinner than order detail. The generic order
    completion path already fetches detail when commerce data is incomplete; this
    wrapper additionally fetches detail when the production Order sync has no
    modification timestamp to write to HubSpot's native Modified Date field.
    Reconciliation opts out because it only needs line items.
    """

    source_needs_modified_detail = (
        commerce_fields and first_present(order, ORDER_MODIFIED_SOURCES) is None
    )
    completed = _BASE_COMPLETE_ORDER(
        store_domain,
        access_token,
        order,
        commerce_fields=commerce_fields,
    )
    if not source_needs_modified_detail:
        return completed
    if first_present(completed, ORDER_MODIFIED_SOURCES) is not None:
        return completed

    # If the generic completion path already needed detail, a second fetch cannot
    # reveal more. Otherwise force one detail read by removing line_items from a
    # copy; complete_order treats that shape as thin without changing the source.
    if orders.order_needs_detail(order):
        return completed
    detail_required = dict(order)
    detail_required.pop("line_items", None)
    return _BASE_COMPLETE_ORDER(
        store_domain,
        access_token,
        detail_required,
        commerce_fields=True,
    )


def configure_production_order_mapping() -> None:
    """Install the portal's authoritative native Order mappings in one pass."""

    configured = []
    found_modified_date = False
    for field in orders.ORDER_FIELDS:
        if field.key == "modified_at":
            found_modified_date = True
            field = field._replace(
                sources=ORDER_MODIFIED_SOURCES,
                native=(HUBSPOT_EXTERNAL_ORDER_MODIFIED_DATE,),
                fallback=None,
                label="EasyStore Order Modified",
                description=(
                    "Most recent source-system modification timestamp reported "
                    "by EasyStore for this order."
                ),
                kind="datetime",
            )
        elif field.key == "order_status":
            field = field._replace(
                native=(HUBSPOT_EXTERNAL_ORDER_STATUS,),
                description=(
                    "Actionable EasyStore order state rolled up from payment, "
                    "fulfilment and terminal order status for HubSpot Status."
                ),
            )
        elif field.key == "shipping_recipient":
            field = field._replace(
                native=(HUBSPOT_SHIPPING_ADDRESS_NAME,),
                fallback=None,
                description=(
                    "Name EasyStore records on the delivery address, written "
                    "to HubSpot Shipping Address Customer Name."
                ),
            )
        configured.append(field)

    if not found_modified_date:
        configured.append(
            FieldSpec(
                key="modified_at",
                sources=ORDER_MODIFIED_SOURCES,
                native=(HUBSPOT_EXTERNAL_ORDER_MODIFIED_DATE,),
                fallback=None,
                label="EasyStore Order Modified",
                description=(
                    "Most recent source-system modification timestamp reported "
                    "by EasyStore for this order."
                ),
                kind="datetime",
            )
        )

    orders.ORDER_FIELDS = tuple(configured)
    orders.ORDER_FIELD_DERIVATIONS["order_status"] = easystore_order_status
    orders.DEFAULT_ORDER_FIELD_PROPERTIES = {
        field.key: field.native[0] if field.native else field.fallback
        for field in orders.ORDER_FIELDS
        if field.native or field.fallback
    }


def main(argv: list[str] | None = None) -> int:
    # Keep the generic mapping implementation in easystore_hubspot_orders, but
    # inject the same authoritative Contact identity used by preflight/customer
    # sync plus the portal's actual native Order fields.
    orders.hubspot_contact_index = hubspot_contact_index
    orders.complete_order = complete_order_with_modified_date
    configure_production_order_mapping()
    return orders.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())