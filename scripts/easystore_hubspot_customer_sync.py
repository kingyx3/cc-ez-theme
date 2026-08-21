#!/usr/bin/env python3
"""Run the EasyStore customer sync with authoritative customer-note semantics.

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
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from functools import lru_cache
from typing import Any
from urllib.parse import quote, urlencode

import easystore_hubspot_sync as base
from easystore_hubspot_orders import _extract_list, _http_json, _shop_domain
from easystore_hubspot_schema import (
    iter_easystore_pages,
    nonempty,
    note_text,
)

CUSTOMER_NOTE_SOURCES = ("note", "note2")
EASYSTORE_ORDER_PAGE_SIZE = 50
_BASE_COMPLETE_CUSTOMER = base.complete_customer
_FALLBACK_CUSTOMER_IDS_USED: set[str] = set()


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


def _install_refinements() -> None:
    base.NOTE_SOURCES = CUSTOMER_NOTE_SOURCES
    base.customer_note = customer_note
    base.customer_needs_detail = customer_needs_detail
    base.complete_customer = complete_customer
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
    _install_refinements()
    summary = base.sync(
        store_domain=store_domain,
        easystore_access_token=easystore_access_token,
        hubspot_access_token=hubspot_access_token,
        fallback_dial_code=fallback_dial_code,
    )
    summary["easystore_customer_note_fields"] = list(CUSTOMER_NOTE_SOURCES)
    summary["customer_notes_enriched_from_nested_customer_object"] = len(
        _FALLBACK_CUSTOMER_IDS_USED
    )
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
