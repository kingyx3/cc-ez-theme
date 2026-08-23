#!/usr/bin/env python3
"""Repair the one safe HubSpot Contact collision this integration can prove.

HubSpot forms deduplicate Contacts by email, not by Phone. That means an EasyStore
Contact created by this integration with only a phone number can later be followed
by a second Contact when the same shopper submits a HubSpot form with an email.
The two records then carry Phone values such as ``+6591735876`` and ``6591735876``
which normalize to the same EasyStore identity.

This module repairs only that exact provenance pattern before identity preflight:

* exactly one EasyStore customer owns the normalized mobile;
* exactly one colliding HubSpot Contact is the EasyStore integration record for
  that customer (matching ``easystore_customer_id`` and the integration source);
* exactly one other colliding Contact was created by a HubSpot form, has no
  EasyStore customer ID, and has an email address;
* the integration Contact already stores the canonical E.164 Phone value.

When every condition holds, the form Contact is merged into the EasyStore Contact.
The EasyStore record is primary so its external identity and canonical Phone win,
while the form record contributes the email/name/activity that caused HubSpot to
create it. Anything less certain is left untouched for the normal fail-closed
preflight to report.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Iterator
from urllib.parse import urlencode

import easystore_hubspot_sync as base


CONTACT_REPAIR_PROPERTIES = (
    "email",
    "phone",
    "mobilephone",
    "easystore_customer_id",
    "hs_object_source_label",
    "hs_object_source_detail_1",
)
INTEGRATION_SOURCE_LABEL = "INTEGRATION"
INTEGRATION_SOURCE_DETAIL = "EasyStore_Integration"
FORM_SOURCE_LABEL = "FORM"


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def iter_hubspot_contacts_for_repair(access_token: str) -> Iterator[dict[str, Any]]:
    """Yield Contacts with provenance needed to prove a safe merge."""

    after: str | None = None
    while True:
        params = {
            "limit": "100",
            "properties": ",".join(CONTACT_REPAIR_PROPERTIES),
            "archived": "false",
        }
        if after is not None:
            params["after"] = after
        document = base._http_json(
            f"{base.HUBSPOT_BASE_URL}?{urlencode(params)}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        results = document.get("results", []) if isinstance(document, dict) else []
        for contact in results:
            if isinstance(contact, dict):
                yield contact

        paging = document.get("paging", {}) if isinstance(document, dict) else {}
        next_page = paging.get("next", {}) if isinstance(paging, dict) else {}
        next_after = next_page.get("after") if isinstance(next_page, dict) else None
        if next_after is None:
            break
        after = str(next_after)


def _properties(contact: dict[str, Any]) -> dict[str, Any]:
    value = contact.get("properties")
    return value if isinstance(value, dict) else {}


def _contact_id(contact: dict[str, Any]) -> str | None:
    return _nonempty(contact.get("id"))


def _normalized_phone(contact: dict[str, Any], fallback_dial_code: str) -> str | None:
    return base.normalize_mobile(
        _properties(contact).get("phone"),
        fallback_dial_code=fallback_dial_code,
    )


def _is_integration_primary(
    contact: dict[str, Any],
    *,
    customer_id: str,
    normalized_phone: str,
) -> bool:
    props = _properties(contact)
    return (
        _nonempty(props.get("easystore_customer_id")) == customer_id
        and _nonempty(props.get("hs_object_source_label")) == INTEGRATION_SOURCE_LABEL
        and _nonempty(props.get("hs_object_source_detail_1")) == INTEGRATION_SOURCE_DETAIL
        and _nonempty(props.get("phone")) == normalized_phone
    )


def _is_form_secondary(contact: dict[str, Any]) -> bool:
    props = _properties(contact)
    return (
        _nonempty(props.get("hs_object_source_label")) == FORM_SOURCE_LABEL
        and _nonempty(props.get("easystore_customer_id")) is None
        and _nonempty(props.get("email")) is not None
    )


def safe_form_merge_pair(
    *,
    customer_id: str,
    normalized_phone: str,
    contacts: Iterable[dict[str, Any]],
) -> tuple[str, str] | None:
    """Return ``(primary, secondary)`` only for the proven form-duplicate shape."""

    owners = list(contacts)
    if len(owners) != 2:
        return None

    primaries = [
        contact
        for contact in owners
        if _is_integration_primary(
            contact,
            customer_id=customer_id,
            normalized_phone=normalized_phone,
        )
    ]
    secondaries = [contact for contact in owners if _is_form_secondary(contact)]
    if len(primaries) != 1 or len(secondaries) != 1:
        return None
    if primaries[0] is secondaries[0]:
        return None

    primary_id = _contact_id(primaries[0])
    secondary_id = _contact_id(secondaries[0])
    if primary_id is None or secondary_id is None or primary_id == secondary_id:
        return None
    return primary_id, secondary_id


def repair_form_duplicates(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, int]:
    """Merge only form-created duplicates whose EasyStore owner is provable."""

    easystore_owners: dict[str, set[str]] = defaultdict(set)
    for customer in base.iter_easystore_customers(store_domain, easystore_access_token):
        mobile = base.customer_mobile(customer, fallback_dial_code)
        customer_id = _nonempty(customer.get("id"))
        if mobile is not None and customer_id is not None:
            easystore_owners[mobile].add(customer_id)

    hubspot_by_phone: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for contact in iter_hubspot_contacts_for_repair(hubspot_access_token):
        mobile = _normalized_phone(contact, fallback_dial_code)
        if mobile is not None and mobile in easystore_owners:
            hubspot_by_phone[mobile].append(contact)

    collisions = 0
    repaired = 0
    left_for_preflight = 0
    for mobile, contacts in sorted(hubspot_by_phone.items()):
        if len(contacts) <= 1:
            continue
        collisions += 1
        source_ids = easystore_owners.get(mobile, set())
        if len(source_ids) != 1:
            left_for_preflight += 1
            continue

        pair = safe_form_merge_pair(
            customer_id=next(iter(source_ids)),
            normalized_phone=mobile,
            contacts=contacts,
        )
        if pair is None:
            left_for_preflight += 1
            continue

        primary_id, secondary_id = pair
        base._http_json(
            f"{base.HUBSPOT_BASE_URL}/merge",
            method="POST",
            headers={"Authorization": f"Bearer {hubspot_access_token}"},
            payload={
                "primaryObjectId": primary_id,
                "objectIdToMerge": secondary_id,
            },
        )
        repaired += 1
        print(
            f"Repaired HubSpot form duplicate for {mobile}: merged Contact "
            f"{secondary_id} into EasyStore Contact {primary_id}.",
        )

    return {
        "hubspot_normalized_phone_collisions_seen": collisions,
        "hubspot_form_duplicates_merged": repaired,
        "hubspot_phone_collisions_left_for_preflight": left_for_preflight,
    }
