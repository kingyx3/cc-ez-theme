#!/usr/bin/env python3
"""Repair proven form duplicates, then fail before CRM writes if identity is unsafe.

Customer mobile number is the authoritative Contact identity for this integration.
HubSpot's native ``phone`` property is the authoritative CRM identity field;
``mobilephone`` may mirror the same value but never participates in deduplication.

HubSpot forms deduplicate Contacts by email rather than by Phone. If this
integration first creates a phone-only EasyStore Contact, a later HubSpot form can
therefore create a second Contact for the same shopper. Before the read-only
identity check below, the preflight repairs only that exact, provenance-proven
pattern by merging the form Contact into the EasyStore integration Contact. Any
other collision remains fail-closed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Iterable

from easystore_hubspot_contact_repair import repair_form_duplicates
from easystore_hubspot_orders import (
    HUBSPOT_BASE,
    HUBSPOT_LINE_ITEMS_URL,
    HUBSPOT_ORDERS_URL,
    HUBSPOT_PRODUCTS_URL,
    SyncError as OrderSyncError,
    _http_json,
    iter_easystore_orders,
    iter_hubspot_objects,
)
from easystore_hubspot_products import (
    SyncError as ProductSyncError,
    iter_easystore_products,
)
from easystore_hubspot_sync import (
    SyncError,
    _nonempty,
    customer_mobile,
    iter_easystore_customers,
    iter_hubspot_contacts,
    normalize_mobile,
)


PREFLIGHT_ERRORS = (SyncError, OrderSyncError, ProductSyncError)


def ambiguous_owners(owners: dict[str, set[str]]) -> dict[str, set[str]]:
    """Return identities owned by more than one distinct record."""

    return {identity: ids for identity, ids in owners.items() if len(ids) > 1}


def _sample(duplicates: dict[str, set[str]], limit: int = 10) -> str:
    return "; ".join(
        f"{identity}: {','.join(sorted(ids))}"
        for identity, ids in list(sorted(duplicates.items()))[:limit]
    )


def _probe(iterator: Iterable[Any]) -> None:
    """Execute the iterator's first API page without requiring any records."""

    next(iter(iterator), None)


def check_api_access(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
) -> None:
    """Verify every read-side route/scope used later before mutations begin."""

    # EasyStore: trigger the first page for all three required Public API scopes.
    _probe(iter_easystore_products(store_domain, easystore_access_token))
    _probe(iter_easystore_orders(store_domain, easystore_access_token))

    # HubSpot: prove that the Product, Order and Line Item object routes/scopes
    # are readable. Contacts are scanned fully by check_identity immediately
    # afterwards, so a separate Contact probe would only duplicate a request.
    _probe(
        iter_hubspot_objects(
            HUBSPOT_PRODUCTS_URL,
            hubspot_access_token,
            "hs_sku",
        )
    )
    _probe(
        iter_hubspot_objects(
            HUBSPOT_ORDERS_URL,
            hubspot_access_token,
            "hs_order_name",
        )
    )
    _probe(
        iter_hubspot_objects(
            HUBSPOT_LINE_ITEMS_URL,
            hubspot_access_token,
            "hs_sku,hs_product_id",
        )
    )

    # The order stage may create its unique EasyStore ID property and the
    # easystore_* commerce properties on first run, and it resolves every
    # commerce field against the live Order property schema. These reads
    # validate both schema routes and crm.schemas.orders.read before
    # Product/Contact mutations. The write scope is exercised only if a property
    # actually needs to be created.
    schema_headers = {"Authorization": f"Bearer {hubspot_access_token}"}
    _http_json(
        f"{HUBSPOT_BASE}/crm/v3/properties/order/groups",
        headers=schema_headers,
    )
    _http_json(
        f"{HUBSPOT_BASE}/crm/v3/properties/order",
        headers=schema_headers,
    )


def check_identity(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, Any]:
    check_api_access(
        store_domain=store_domain,
        easystore_access_token=easystore_access_token,
        hubspot_access_token=hubspot_access_token,
    )

    repair_summary = repair_form_duplicates(
        store_domain=store_domain,
        easystore_access_token=easystore_access_token,
        hubspot_access_token=hubspot_access_token,
        fallback_dial_code=fallback_dial_code,
    )

    easystore_owners: dict[str, set[str]] = defaultdict(set)
    easystore_customers = 0
    skipped_without_mobile = 0

    for customer in iter_easystore_customers(store_domain, easystore_access_token):
        easystore_customers += 1
        # Same contact filter as the customer sync: customers with no mobile
        # number recorded never reach HubSpot, so they cannot collide either.
        mobile = customer_mobile(customer, fallback_dial_code)
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

    # Re-scan after any merge. HubSpot can return a new object ID for the merged
    # record, so using a pre-merge identity index here would be unsafe.
    for contact in iter_hubspot_contacts(hubspot_access_token):
        hubspot_contacts += 1
        contact_id = _nonempty(contact.get("id"))
        properties = contact.get("properties")
        if contact_id is None or not isinstance(properties, dict):
            continue

        # HubSpot's primary Phone number is the authoritative CRM identity. A
        # secondary mobilephone value can legitimately repeat another Contact's
        # Phone and therefore must not manufacture a duplicate-identity failure.
        mobile = normalize_mobile(
            properties.get("phone"),
            fallback_dial_code=fallback_dial_code,
        )
        if mobile in wanted_mobiles:
            hubspot_owners[mobile].add(contact_id)

    duplicate_hubspot = ambiguous_owners(hubspot_owners)
    if duplicate_hubspot:
        raise SyncError(
            "Multiple HubSpot Contacts still own an EasyStore normalized mobile "
            "number after the safe form-duplicate repair pass. No further guess "
            "was made. "
            + _sample(duplicate_hubspot)
        )

    return {
        "api_surfaces_readable": 1,
        "easystore_customers_scanned": easystore_customers,
        "unique_mobile_customers": len(easystore_owners),
        "hubspot_contacts_scanned": hubspot_contacts,
        "hubspot_contact_identity_property": "phone",
        "skipped_without_mobile": skipped_without_mobile,
        "ambiguous_easystore_mobile_numbers": 0,
        "ambiguous_hubspot_mobile_numbers": 0,
        **repair_summary,
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
    except PREFLIGHT_ERRORS as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
