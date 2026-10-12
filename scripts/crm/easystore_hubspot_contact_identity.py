#!/usr/bin/env python3
"""Build HubSpot Contact indexes using native ``phone`` as CRM identity.

The CRM still mirrors EasyStore's normalized number to HubSpot ``mobilephone`` for
operator convenience, but ``mobilephone`` is not a second identity namespace.
HubSpot's native Phone field already enforces the store's intended deduplication
semantics, so Order/Cart associations must use that same field as preflight and
the Customer stage.
"""

from __future__ import annotations

from collections import defaultdict

import easystore_hubspot_orders as orders


def hubspot_contact_index(
    access_token: str,
    fallback_dial_code: str,
) -> orders.ContactIndex:
    """Return Contact indexes with only HubSpot ``phone`` used as phone identity."""

    by_phone: dict[str, set[str]] = defaultdict(set)
    by_email: dict[str, set[str]] = defaultdict(set)
    by_customer_id: dict[str, set[str]] = defaultdict(set)
    lifecycle_by_id: dict[str, str] = {}

    for contact in orders.iter_hubspot_objects(
        orders.HUBSPOT_CONTACTS_URL,
        access_token,
        "phone,email,"
        f"{orders.CONTACT_EASYSTORE_ID_PROPERTY},{orders.CONTACT_LIFECYCLE_PROPERTY}",
    ):
        contact_id = orders.nonempty(contact.get("id"))
        properties = contact.get("properties")
        if contact_id is None or not isinstance(properties, dict):
            continue

        mobile = orders.normalize_mobile(
            properties.get("phone"),
            fallback_dial_code=fallback_dial_code,
        )
        if mobile:
            by_phone[mobile].add(contact_id)

        email = orders.nonempty(properties.get("email"))
        if email:
            by_email[email.casefold()].add(contact_id)

        easystore_id = orders.nonempty(
            properties.get(orders.CONTACT_EASYSTORE_ID_PROPERTY)
        )
        if easystore_id:
            by_customer_id[easystore_id].add(contact_id)

        stage = orders.nonempty(properties.get(orders.CONTACT_LIFECYCLE_PROPERTY))
        if stage is not None:
            lifecycle_by_id[contact_id] = stage

    return orders.ContactIndex(
        by_phone=by_phone,
        lifecycle_by_id=lifecycle_by_id,
        by_email=by_email,
        by_easystore_customer_id=by_customer_id,
    )
