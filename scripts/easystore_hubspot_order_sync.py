#!/usr/bin/env python3
"""Production Order sync entrypoint with portal-specific HubSpot mappings.

The storefront does not permit guest checkout. EasyStore customer ID is therefore
also the strongest Order -> Contact association key: it is assigned by EasyStore,
survives phone/email edits, and is already synchronized onto HubSpot Contacts as
``easystore_customer_id``.

The generic order sync keeps its conservative mobile association for backwards
compatibility. This production entrypoint follows it with an idempotent
customer-ID association pass so every registered checkout can be joined to the
same Contact that carries Cloudflare/HubSpot acquisition data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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
CANCELLED_STATUS_KEYS = {"cancelled", "canceled", "deleted"}
FALSEY_CANCELLATION_KEYS = {"", "0", "false", "nil", "null", "none"}


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


def easystore_order_customer_id(order: dict[str, Any]) -> str | None:
    """Return the registered EasyStore customer ID carried by an order."""

    direct = nonempty(order.get("customer_id"))
    if direct is not None:
        return direct

    customer = order.get("customer")
    if isinstance(customer, dict):
        return first_present(customer, ("id", "customer_id"))
    return None


def ensure_registered_customer_order_associations(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, int]:
    """Associate orders to Contacts by EasyStore customer ID.

    Guest checkout is disabled in the storefront UI, so a real checkout belongs
    to a registered EasyStore customer. The customer sync writes that immutable
    EasyStore ID onto the HubSpot Contact. This pass uses that trusted key first,
    independently of whether the shopper later changed phone/email details.

    The generic order sync already associated any unique mobile match. Repeating
    the same HubSpot association with PUT is idempotent, so this pass safely
    upgrades mobile-based matches and fills orders whose mobile was missing or
    changed.
    """

    contacts = hubspot_contact_index(hubspot_access_token, fallback_dial_code)
    hubspot_orders = orders.hubspot_order_index(hubspot_access_token)

    with_customer_id = 0
    without_customer_id = 0
    associations_ensured = 0
    unmatched_customer_id = 0
    ambiguous_customer_id = 0
    missing_hubspot_order = 0

    for listed in orders.iter_easystore_orders(store_domain, easystore_access_token):
        # The list payload normally carries the customer reference. Only pay for
        # an order-detail request when it does not; the primary sync has already
        # done the expensive commerce hydration once in this run.
        order = listed
        customer_id = easystore_order_customer_id(order)
        if customer_id is None:
            order = orders.complete_order(
                store_domain,
                easystore_access_token,
                listed,
            )
            customer_id = easystore_order_customer_id(order)

        external_id = nonempty(order.get("id"))
        if external_id is None:
            # The primary order sync rejects this before this pass can run.
            continue

        if customer_id is None:
            without_customer_id += 1
            continue

        with_customer_id += 1
        hubspot_order_id = hubspot_orders.get(external_id)
        if hubspot_order_id is None:
            missing_hubspot_order += 1
            continue

        matching_contacts = contacts.by_easystore_customer_id.get(customer_id, set())
        if len(matching_contacts) == 1:
            contact_id = next(iter(matching_contacts))
            orders._associate_order(
                hubspot_access_token,
                hubspot_order_id,
                "contact",
                contact_id,
                orders.ORDER_CONTACT_ASSOCIATION_TYPE_ID,
            )
            associations_ensured += 1
        elif len(matching_contacts) > 1:
            ambiguous_customer_id += 1
        else:
            unmatched_customer_id += 1

    if without_customer_id:
        print(
            "WARNING: storefront checkout requires a registered customer, but "
            f"{without_customer_id} EasyStore orders exposed no customer ID; "
            "those orders keep the generic mobile association only.",
            file=sys.stderr,
        )
    if unmatched_customer_id or ambiguous_customer_id:
        print(
            "WARNING: some registered EasyStore order customer IDs could not be "
            "resolved to exactly one HubSpot Contact: "
            f"unmatched={unmatched_customer_id}, ambiguous={ambiguous_customer_id}.",
            file=sys.stderr,
        )

    return {
        "orders_with_easystore_customer_id": with_customer_id,
        "orders_without_easystore_customer_id": without_customer_id,
        "order_customer_id_associations_ensured": associations_ensured,
        "orders_with_unmatched_easystore_customer_id": unmatched_customer_id,
        "orders_with_ambiguous_easystore_customer_id": ambiguous_customer_id,
        "orders_missing_hubspot_order_for_customer_id_join": missing_hubspot_order,
    }


def main(argv: list[str] | None = None) -> int:
    # Keep the generic mapping implementation in easystore_hubspot_orders, but
    # inject the same authoritative Contact identity used by preflight/customer
    # sync plus the portal's actual native Order fields.
    orders.hubspot_contact_index = hubspot_contact_index
    configure_order_status_mapping()
    configure_shipping_recipient_mapping()

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
        store_domain = orders._required(args.store_domain, "EASYSTORE_STORE_DOMAIN")
        easystore_token = orders._required(
            args.easystore_token,
            "EASYSTORE_ACCESS_TOKEN",
        )
        hubspot_token = orders._required(args.hubspot_token, "HUBSPOT_ACCESS_TOKEN")

        summary = orders.sync(
            store_domain=store_domain,
            easystore_access_token=easystore_token,
            hubspot_access_token=hubspot_token,
            fallback_dial_code=args.fallback_dial_code,
        )
        summary.update(
            ensure_registered_customer_order_associations(
                store_domain=store_domain,
                easystore_access_token=easystore_token,
                hubspot_access_token=hubspot_token,
                fallback_dial_code=args.fallback_dial_code,
            )
        )
    except orders.SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
