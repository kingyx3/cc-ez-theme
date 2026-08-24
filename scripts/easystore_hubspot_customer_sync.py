#!/usr/bin/env python3
"""Run the EasyStore customer sync with authoritative source semantics.

EasyStore exposes two different concepts that must not be mixed:

* ``Customer.note`` / ``Customer.note2`` belong to the Customer object.
* ``Order.note`` / ``Order.remark`` belong to the Order object.

The regular Customer endpoint is the primary source. Some EasyStore API
responses omit ``note``/``note2`` from that standalone customer shape even though
the documented Customer object included by the Orders API contains them. When
that happens, this production entrypoint enriches the customer by customer ID
from the nested Customer object only. The Order API is therefore only a transport
for a Customer object in this fallback path; top-level Order note fields are never
read when populating a HubSpot Contact.

HubSpot's native ``phone`` property is the authoritative Contact identity.
``mobilephone`` still receives the normalized EasyStore number as a convenience
mirror, but it is hidden from the base sync's identity index so a secondary mobile
value on another Contact cannot create a false duplicate.

HubSpot's Contact ``createdate`` and ``lastmodifieddate`` are CRM system metadata:
they describe when the HubSpot record was created or changed, not when the
EasyStore customer was created or changed. Contacts do not expose writable native
external-created/external-modified properties, so production writes the EasyStore
source timestamps to explicit ``easystore_customer_created_at`` and
``easystore_customer_modified_at`` properties instead. The legacy
``easystore_customer_since`` destination is no longer written.

HubSpot portals do not expose ``date_of_birth`` consistently: some type it as a
CRM date while this portal exposes the native property as a writable string. The
shared schema resolver deliberately requires exact storage types, so this
entrypoint adapts only that known native property. A real EasyStore birth date is
serialized as ``YYYY-MM-DD`` into native ``date_of_birth`` when HubSpot exposes it
as a string, and the legacy ``easystore_customer_birthday`` fallback is not
written on those runs. The shared resolver stays strict for every other field.

The old machine-only EasyStore ``Click ID`` customer attribute is retired. It is
filtered out of merchant-defined attributes here so it is neither provisioned nor
written to HubSpot. Cloudflare attribution now joins D1 ``customer_touches`` to
the existing ``easystore_customer_id`` and source creation timestamp instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from functools import lru_cache
from typing import Any, Iterable, Iterator
from urllib.parse import quote, urlencode

import easystore_hubspot_sync as base
from easystore_hubspot_orders import _extract_list, _http_json, _shop_domain
from easystore_hubspot_schema import (
    FieldSpec,
    iter_easystore_pages,
    nonempty,
    note_text,
)

CUSTOMER_NOTE_SOURCES = ("note", "note2")
EASYSTORE_ORDER_PAGE_SIZE = 50
NATIVE_DATE_OF_BIRTH_PROPERTY = "date_of_birth"
NATIVE_DATE_OF_BIRTH_SCHEMA_URL = (
    "https://api.hubapi.com/crm/v3/properties/contacts/date_of_birth"
)
LEGACY_CUSTOMER_SINCE_KEY = "customer_since"
RETIRED_CLICK_ID_ATTRIBUTE_TITLES = frozenset(
    {
        "click id",
        "clickid",
        "cb_click_id",
        "source click id",
        "attribution click id",
    }
)
CONTACT_SOURCE_DATE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="source_created_at",
        sources=("created_at", "created_on", "registered_at"),
        fallback="easystore_customer_created_at",
        label="EasyStore Created Date",
        description="Date and time the customer record was created in EasyStore.",
        kind="datetime",
    ),
    FieldSpec(
        key="source_modified_at",
        sources=("updated_at", "modified_at", "updated_on", "modified_on"),
        fallback="easystore_customer_modified_at",
        label="EasyStore Modified Date",
        description="Date and time the customer record was last modified in EasyStore.",
        kind="datetime",
    ),
)
_BASE_COMPLETE_CUSTOMER = base.complete_customer
_BASE_ITER_HUBSPOT_CONTACTS = base.iter_hubspot_contacts
_BASE_RESOLVE_CONTACT_FIELDS = base.resolve_contact_fields
_BASE_CUSTOMER_PROPERTIES = base.customer_properties
_BASE_CUSTOMER_ATTRIBUTES = base.customer_attributes
_FALLBACK_CUSTOMER_IDS_USED: set[str] = set()
_NATIVE_DOB_STRING = False


def customer_note(customer: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in CUSTOMER_NOTE_SOURCES:
        value = note_text(customer.get(key))
        if value is not None and value not in parts:
            parts.append(value)
    return "\n".join(parts) if parts else None


def customer_needs_detail(customer: dict[str, Any]) -> bool:
    has_birthday = any(key in customer for key in base.BIRTHDAY_SOURCES)
    has_attributes = any(key in customer for key in base.CUSTOM_ATTRIBUTE_SOURCES)
    return not (has_birthday and has_attributes)


def _customer_object(document: Any) -> dict[str, Any] | None:
    if not isinstance(document, dict):
        return None
    customer = document.get("customer")
    return customer if isinstance(customer, dict) else None


def _complete_order_customer(
    store_domain: str,
    access_token: str,
    listed: dict[str, Any],
) -> dict[str, Any] | None:
    customer = _customer_object(listed)
    if customer is not None:
        return customer

    order_id = nonempty(listed.get("id"))
    if order_id is None:
        return None

    domain = _shop_domain(store_domain)
    document = _http_json(
        f"https://{domain}/api/3.0/orders/{quote(order_id, safe='')}.json?fields=customer",
        headers={"EasyStore-Access-Token": access_token},
    )
    if not isinstance(document, dict):
        return None

    order = document.get("order")
    if isinstance(order, dict):
        return _customer_object(order)
    data = document.get("data")
    if isinstance(data, dict):
        nested = data.get("order")
        if isinstance(nested, dict):
            return _customer_object(nested)
        return _customer_object(data)
    return _customer_object(document)


@lru_cache(maxsize=4)
def customer_note_fallback_index(
    store_domain: str,
    access_token: str,
) -> dict[str, dict[str, Any]]:
    domain = _shop_domain(store_domain)
    indexed: dict[str, dict[str, Any]] = {}

    def fetch(page: int) -> list[dict[str, Any]]:
        query = urlencode(
            {
                "page": page,
                "limit": EASYSTORE_ORDER_PAGE_SIZE,
                "sort": "processed_at.desc",
                "fields": "customer",
            }
        )
        document = _http_json(
            f"https://{domain}/api/3.0/orders.json?{query}",
            headers={"EasyStore-Access-Token": access_token},
        )
        return _extract_list(document, "orders", "data", "results")

    for listed in iter_easystore_pages(
        fetch,
        page_size=EASYSTORE_ORDER_PAGE_SIZE,
        what="orders.json",
        error=base.SyncError,
    ):
        customer = _complete_order_customer(store_domain, access_token, listed)
        if customer is None:
            continue
        customer_id = nonempty(customer.get("id"))
        if customer_id is None or customer_id in indexed:
            continue
        if not any(key in customer for key in CUSTOMER_NOTE_SOURCES):
            continue
        indexed[customer_id] = customer

    return indexed


def complete_customer(
    store_domain: str,
    access_token: str,
    listed: dict[str, Any],
) -> dict[str, Any]:
    completed = _BASE_COMPLETE_CUSTOMER(store_domain, access_token, listed)
    merged = dict(listed)
    if isinstance(completed, dict):
        merged.update(completed)

    if any(key in merged for key in CUSTOMER_NOTE_SOURCES):
        return merged

    customer_id = nonempty(merged.get("id"))
    if customer_id is None:
        return merged

    fallback = customer_note_fallback_index(store_domain, access_token).get(customer_id)
    if fallback is None:
        return merged

    copied = False
    for key in CUSTOMER_NOTE_SOURCES:
        if key in fallback:
            merged[key] = fallback[key]
            copied = True
    if copied:
        _FALLBACK_CUSTOMER_IDS_USED.add(customer_id)
    return merged


def iter_hubspot_contacts_by_primary_phone(
    access_token: str,
) -> Iterator[dict[str, Any]]:
    """Yield Contacts with ``mobilephone`` excluded from identity matching."""

    for contact in _BASE_ITER_HUBSPOT_CONTACTS(access_token):
        properties = contact.get("properties")
        if not isinstance(properties, dict) or "mobilephone" not in properties:
            yield contact
            continue
        primary_only = dict(contact)
        primary_properties = dict(properties)
        primary_properties.pop("mobilephone", None)
        primary_only["properties"] = primary_properties
        yield primary_only


def _normalized_attribute_title(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def customer_attributes_without_click_id(
    customer: dict[str, Any],
    attribute_titles: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return merchant attributes except the retired machine-only Click ID."""

    return {
        label: answer
        for label, answer in _BASE_CUSTOMER_ATTRIBUTES(customer, attribute_titles).items()
        if _normalized_attribute_title(label) not in RETIRED_CLICK_ID_ATTRIBUTE_TITLES
    }


def native_date_of_birth_storage_type(access_token: str) -> str | None:
    """Return the writable native DOB storage type this portal exposes."""

    document = base._http_json(
        NATIVE_DATE_OF_BIRTH_SCHEMA_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        allow_statuses={403, 404},
    )
    if not isinstance(document, dict):
        return None
    if document.get("archived") or document.get("calculated"):
        return None
    metadata = document.get("modificationMetadata")
    if isinstance(metadata, dict) and metadata.get("readOnlyValue"):
        return None
    storage_type = str(document.get("type") or "")
    return storage_type if storage_type in {"date", "string"} else None


def _install_contact_source_date_fields() -> None:
    existing = {field.key for field in base.CONTACT_FIELDS}
    additions = tuple(
        field for field in CONTACT_SOURCE_DATE_FIELDS if field.key not in existing
    )
    if additions:
        base.CONTACT_FIELDS = base.CONTACT_FIELDS + additions


def resolve_contact_fields(
    access_token: str,
    attribute_labels: Iterable[str] = (),
    report: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Prefer explicit EasyStore source timestamps and ordinary merchant fields."""

    adapted = dict(
        _BASE_RESOLVE_CONTACT_FIELDS(
            access_token,
            attribute_labels,
            report,
        )
    )
    adapted.pop(LEGACY_CUSTOMER_SINCE_KEY, None)
    if _NATIVE_DOB_STRING:
        adapted.pop("birthday", None)
    return adapted


def customer_properties(
    customer: dict[str, Any],
    mobile: str,
    field_properties: dict[str, str] | None = None,
    attribute_titles: dict[str, str] | None = None,
) -> dict[str, str]:
    properties = _BASE_CUSTOMER_PROPERTIES(
        customer,
        mobile,
        field_properties,
        attribute_titles,
    )
    if _NATIVE_DOB_STRING:
        birth_date = base.customer_birthday(customer)
        if birth_date is not None:
            properties[NATIVE_DATE_OF_BIRTH_PROPERTY] = birth_date
    return properties


def _install_refinements(native_dob_type: str | None = None) -> None:
    global _NATIVE_DOB_STRING
    _NATIVE_DOB_STRING = native_dob_type == "string"
    _install_contact_source_date_fields()
    base.NOTE_SOURCES = CUSTOMER_NOTE_SOURCES
    base.customer_note = customer_note
    base.customer_needs_detail = customer_needs_detail
    base.complete_customer = complete_customer
    base.iter_hubspot_contacts = iter_hubspot_contacts_by_primary_phone
    base.customer_attributes = customer_attributes_without_click_id
    base.resolve_contact_fields = resolve_contact_fields
    base.customer_properties = customer_properties
    base.CONTACT_FIELD_DERIVATIONS["note"] = customer_note


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, Any]:
    _FALLBACK_CUSTOMER_IDS_USED.clear()
    customer_note_fallback_index.cache_clear()
    native_dob_type = native_date_of_birth_storage_type(hubspot_access_token)
    _install_refinements(native_dob_type)
    summary = base.sync(
        store_domain=store_domain,
        easystore_access_token=easystore_access_token,
        hubspot_access_token=hubspot_access_token,
        fallback_dial_code=fallback_dial_code,
    )
    summary["hubspot_contact_identity_property"] = "phone"
    summary["easystore_customer_note_fields"] = list(CUSTOMER_NOTE_SOURCES)
    summary["customer_notes_enriched_from_nested_customer_object"] = len(
        _FALLBACK_CUSTOMER_IDS_USED
    )
    summary["hubspot_native_date_of_birth_storage_type"] = native_dob_type
    summary["easystore_contact_source_created_property"] = "easystore_customer_created_at"
    summary["easystore_contact_source_modified_property"] = "easystore_customer_modified_at"
    summary["retired_customer_attributes_not_synced"] = sorted(
        RETIRED_CLICK_ID_ATTRIBUTE_TITLES
    )
    if native_dob_type == "string":
        mapping = dict(summary.get("hubspot_contact_field_properties") or {})
        mapping["birthday"] = NATIVE_DATE_OF_BIRTH_PROPERTY
        summary["hubspot_contact_field_properties"] = dict(sorted(mapping.items()))
    return summary


def _required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise base.SyncError(f"{name} is required")


def main(argv: list[str] | None = None) -> int:
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
        summary = sync(
            store_domain=_required(args.store_domain, "EASYSTORE_STORE_DOMAIN"),
            easystore_access_token=_required(args.easystore_token, "EASYSTORE_ACCESS_TOKEN"),
            hubspot_access_token=_required(args.hubspot_token, "HUBSPOT_ACCESS_TOKEN"),
            fallback_dial_code=_required(
                args.fallback_dial_code,
                "CUSTOMER_SYNC_DEFAULT_DIAL_CODE",
            ),
        )
    except base.SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if summary.get("ambiguous_hubspot_mobile_numbers") else 0


if __name__ == "__main__":
    raise SystemExit(main())
