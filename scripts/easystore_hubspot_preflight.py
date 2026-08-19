#!/usr/bin/env python3
"""Fail before CRM writes when mobile-number identity is ambiguous.

Customer mobile number is the authoritative Contact identity for this integration.
A duplicate normalized mobile in EasyStore or multiple existing HubSpot Contacts
for an EasyStore mobile therefore makes automatic ownership unsafe. This preflight
performs only reads and fails the workflow before Product, Contact, Order, or Line
Item writes begin.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any

from easystore_hubspot_sync import (
    SyncError,
    _nonempty,
    iter_easystore_customers,
    iter_hubspot_contacts,
    normalize_mobile,
)


def ambiguous_owners(owners: dict[str, set[str]]) -> dict[str, set[str]]:
    """Return identities owned by more than one distinct record."""

    return {identity: ids for identity, ids in owners.items() if len(ids) > 1}


def _sample(duplicates: dict[str, set[str]], limit: int = 10) -> str:
    return "; ".join(
        f"{identity}: {','.join(sorted(ids))}"
        for identity, ids in list(sorted(duplicates.items()))[:limit]
    )


def check_identity(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, int]:
    easystore_owners: dict[str, set[str]] = defaultdict(set)
    easystore_customers = 0
    skipped_without_mobile = 0

    for customer in iter_easystore_customers(store_domain, easystore_access_token):
        easystore_customers += 1
        mobile = normalize_mobile(
            customer.get("phone"),
            customer.get("country_code"),
            fallback_dial_code,
        )
        if mobile is None:
            skipped_without_mobile += 1
            continue
        customer_id = _nonempty(customer.get("id"))
        if customer_id is None:
            raise SyncError(
                f"EasyStore customer with normalized mobile {mobile} has no id"
            )
        easystore_owners[mobile].add(customer_id)

    duplicate_easystore = ambiguous_owners(easystore_owners)
    if duplicate_easystore:
        raise SyncError(
            "EasyStore contains multiple customer records with the same normalized "
            "mobile number. Mobile is the CRM identity key, so no writes were made. "
            + _sample(duplicate_easystore)
        )

    hubspot_owners: dict[str, set[str]] = defaultdict(set)
    hubspot_contacts = 0
    wanted_mobiles = set(easystore_owners)

    for contact in iter_hubspot_contacts(hubspot_access_token):
        hubspot_contacts += 1
        contact_id = _nonempty(contact.get("id"))
        properties = contact.get("properties")
        if contact_id is None or not isinstance(properties, dict):
            continue

        for field in ("mobilephone", "phone"):
            mobile = normalize_mobile(
                properties.get(field),
                fallback_dial_code=fallback_dial_code,
            )
            if mobile in wanted_mobiles:
                hubspot_owners[mobile].add(contact_id)

    duplicate_hubspot = ambiguous_owners(hubspot_owners)
    if duplicate_hubspot:
        raise SyncError(
            "Multiple HubSpot Contacts own an EasyStore normalized mobile number. "
            "No writes were made; reconcile the duplicate Contacts first. "
            + _sample(duplicate_hubspot)
        )

    return {
        "easystore_customers_scanned": easystore_customers,
        "unique_mobile_customers": len(easystore_owners),
        "hubspot_contacts_scanned": hubspot_contacts,
        "skipped_without_mobile": skipped_without_mobile,
        "ambiguous_easystore_mobile_numbers": 0,
        "ambiguous_hubspot_mobile_numbers": 0,
    }


def _required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise SyncError(f"{name} is required")


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
        summary = check_identity(
            store_domain=_required(args.store_domain, "EASYSTORE_STORE_DOMAIN"),
            easystore_access_token=_required(
                args.easystore_token, "EASYSTORE_ACCESS_TOKEN"
            ),
            hubspot_access_token=_required(args.hubspot_token, "HUBSPOT_ACCESS_TOKEN"),
            fallback_dial_code=_required(
                args.fallback_dial_code, "CUSTOMER_SYNC_DEFAULT_DIAL_CODE"
            ),
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
