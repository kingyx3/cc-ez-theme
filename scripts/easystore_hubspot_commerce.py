#!/usr/bin/env python3
"""Sync EasyStore carts, cart Line Items, contacts, and Cart→Order links.

Customer notes do not belong in this stage. EasyStore has separate Customer and
Order note fields, so Contacts are handled by ``easystore_hubspot_customer_sync``
and Orders keep their own ``note``/``remark`` mapping in the Order stage.

This stage is intentionally cart-only:

* EasyStore ``checkout.cart_token`` is the HubSpot Cart external identity.
* Product-backed HubSpot Line Items are created and associated to the Cart.
* stale synchronized Cart Line Items are reconciled.
* ``order.cart_token`` associates the resulting HubSpot Order back to the Cart.
* the shopper is associated by the same normalized-mobile identity used by the
  Contact and Order stages.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Iterator, Sequence
from urllib.parse import quote, urlencode

import easystore_hubspot_carts as cart_mapping
from easystore_hubspot_orders import (
    HUBSPOT_BASE,
    HUBSPOT_LINE_ITEMS_URL,
    SyncError,
    _extract_list,
    _http_json,
    _shop_domain,
    desired_lines,
    hubspot_contact_index,
    hubspot_order_index,
    hubspot_product_index,
    iter_easystore_orders,
    iter_hubspot_objects,
    resolve_line_item_fields,
)
from easystore_hubspot_schema import (
    describe_mapping,
    iter_easystore_pages,
    nonempty,
    observed_keys,
    resolve_fields,
)


CART_SCHEMA_OBJECT_TYPE = cart_mapping.CART_OBJECT_TYPE
HUBSPOT_CARTS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/carts"
CART_EXTERNAL_ID_PROPERTY = cart_mapping.CART_EXTERNAL_ID_PROPERTY
EASYSTORE_PAGE_SIZE = 50
CART_CONTACT_ASSOCIATION_TYPE_ID = 586
CART_LINE_ITEM_ASSOCIATION_TYPE_ID = 590
CART_ORDER_ASSOCIATION_TYPE_ID = 592


def checkout_cart_token(checkout: dict[str, Any]) -> str | None:
    """Return EasyStore's unique cart identity and nothing else."""

    return nonempty(checkout.get("cart_token"))


def checkout_status(checkout: dict[str, Any]) -> str | None:
    """Return the status EasyStore documents for checkout/payment state."""

    return nonempty(
        checkout.get("financial_status")
        or checkout.get("status")
        or checkout.get("state")
        or checkout.get("checkout_status")
    )


def is_abandoned(checkout: dict[str, Any]) -> bool:
    """Return whether a checkout still belongs in the open/abandoned cart funnel.

    The predicate itself lives with the Cart mapping so this stage and the Cart
    property it writes can never disagree about which sessions are abandoned.
    """

    return cart_mapping.is_abandoned(checkout)


def iter_documented_checkouts(
    store_domain: str,
    access_token: str,
) -> Iterator[dict[str, Any]]:
    """Yield checkouts only from EasyStore's documented ``checkouts.json`` route."""

    domain = _shop_domain(store_domain)

    def fetch(page: int) -> list[dict[str, Any]]:
        query = urlencode({"page": page, "limit": EASYSTORE_PAGE_SIZE})
        document = _http_json(
            f"https://{domain}/api/3.0/checkouts.json?{query}",
            headers={"EasyStore-Access-Token": access_token},
        )
        return _extract_list(document, "checkouts", "data", "results")

    yield from iter_easystore_pages(
        fetch,
        page_size=EASYSTORE_PAGE_SIZE,
        what="checkouts.json",
        error=SyncError,
    )


def complete_checkout(
    store_domain: str,
    access_token: str,
    checkout: dict[str, Any],
) -> dict[str, Any]:
    """Fetch checkout detail by ``cart_token`` when the list record lacks lines."""

    if isinstance(checkout.get("line_items"), list):
        return checkout
    cart_token = checkout_cart_token(checkout)
    if cart_token is None:
        return checkout

    domain = _shop_domain(store_domain)
    document = _http_json(
        f"https://{domain}/api/3.0/checkouts/{quote(cart_token, safe='')}.json",
        headers={"EasyStore-Access-Token": access_token},
    )
    if not isinstance(document, dict):
        return checkout
    candidate = document.get("checkout")
    if isinstance(candidate, dict):
        return candidate
    candidate = document.get("data")
    if isinstance(candidate, dict):
        nested = candidate.get("checkout")
        return nested if isinstance(nested, dict) else candidate
    return document or checkout


def iter_orders_for_cart_links(
    store_domain: str,
    access_token: str,
) -> Iterator[dict[str, Any]]:
    """Yield orders carrying the ``cart_token`` used to bridge Cart→Order."""

    domain = _shop_domain(store_domain)
    headers = {"EasyStore-Access-Token": access_token}
    for listed in iter_easystore_orders(store_domain, access_token):
        if nonempty(listed.get("cart_token")) is not None:
            yield listed
            continue

        order_id = nonempty(listed.get("id"))
        if order_id is None:
            yield listed
            continue
        document = _http_json(
            f"https://{domain}/api/3.0/orders/{quote(order_id, safe='')}.json",
            headers=headers,
        )
        if not isinstance(document, dict):
            yield listed
            continue
        candidate = document.get("order")
        if isinstance(candidate, dict):
            yield candidate
            continue
        candidate = document.get("data")
        if isinstance(candidate, dict):
            nested = candidate.get("order")
            yield nested if isinstance(nested, dict) else candidate
            continue
        yield document or listed


def cart_object_available(
    access_token: str,
    object_type: str | None = None,
) -> bool:
    """Return whether this HubSpot portal exposes the Cart object."""

    document = _http_json(
        f"{HUBSPOT_BASE}/crm/v3/properties/{object_type or CART_SCHEMA_OBJECT_TYPE}",
        headers={"Authorization": f"Bearer {access_token}"},
        allow_statuses={400, 403, 404},
    )
    return isinstance(document, dict) and isinstance(document.get("results"), list)


def hubspot_cart_index(access_token: str) -> dict[str, str]:
    """Return HubSpot Cart IDs keyed by ``hs_external_cart_id``."""

    by_external_id: dict[str, set[str]] = {}
    for cart in iter_hubspot_objects(
        HUBSPOT_CARTS_URL,
        access_token,
        CART_EXTERNAL_ID_PROPERTY,
    ):
        cart_id = nonempty(cart.get("id"))
        properties = cart.get("properties")
        if cart_id is None or not isinstance(properties, dict):
            continue
        external_id = nonempty(properties.get(CART_EXTERNAL_ID_PROPERTY))
        if external_id:
            by_external_id.setdefault(external_id, set()).add(cart_id)

    duplicates = {key: ids for key, ids in by_external_id.items() if len(ids) > 1}
    if duplicates:
        sample = "; ".join(
            f"{key}: {','.join(sorted(ids))}" for key, ids in list(duplicates.items())[:10]
        )
        raise SyncError(
            "Multiple HubSpot Carts carry the same external cart ID. "
            f"Resolve the duplicates before syncing. {sample}"
        )
    return {key: next(iter(ids)) for key, ids in by_external_id.items()}


def cart_properties(
    checkout: dict[str, Any],
    *,
    cart_token: str,
    store_domain: str,
    field_properties: dict[str, str],
    fallback_dial_code: str,
) -> dict[str, str]:
    """Map a checkout onto Cart properties, including ``financial_status``."""

    properties = cart_mapping.cart_properties(
        checkout,
        external_id=cart_token,
        store_domain=store_domain,
        field_properties=field_properties,
        fallback_dial_code=fallback_dial_code,
    )
    status = checkout_status(checkout)
    status_property = field_properties.get("status")
    if status is not None and status_property:
        properties[status_property] = status
    return properties


def upsert_cart(
    access_token: str,
    existing_id: str | None,
    properties: dict[str, str],
) -> tuple[str, bool]:
    """Create or update one HubSpot Cart."""

    headers = {"Authorization": f"Bearer {access_token}"}
    if existing_id is None:
        response = _http_json(
            HUBSPOT_CARTS_URL,
            method="POST",
            headers=headers,
            payload={"properties": properties},
        )
        cart_id = nonempty(response.get("id")) if isinstance(response, dict) else None
        if cart_id is None:
            raise SyncError("HubSpot created a Cart without returning its ID")
        return cart_id, True

    _http_json(
        f"{HUBSPOT_CARTS_URL}/{existing_id}",
        method="PATCH",
        headers=headers,
        payload={"properties": properties},
    )
    return existing_id, False


def associate_cart(
    access_token: str,
    cart_id: str,
    object_type: str,
    object_id: str,
    association_type_id: int,
) -> None:
    """Associate a HubSpot Cart to one CRM object with a defined type ID."""

    _http_json(
        f"{HUBSPOT_CARTS_URL}/{cart_id}/associations/"
        f"{object_type}/{object_id}/{association_type_id}",
        method="PUT",
        headers={"Authorization": f"Bearer {access_token}"},
    )


def existing_cart_line_items(
    access_token: str,
    cart_id: str,
) -> dict[str, dict[str, Any]]:
    """Return this Cart's associated Line Items keyed by normalized SKU."""

    headers = {"Authorization": f"Bearer {access_token}"}
    associations = _http_json(
        f"{HUBSPOT_CARTS_URL}/{cart_id}/associations/line_items",
        headers=headers,
    )
    results = associations.get("results", []) if isinstance(associations, dict) else []

    by_sku: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        line_id = nonempty(result.get("id"))
        if line_id is None:
            continue
        line = _http_json(
            f"{HUBSPOT_LINE_ITEMS_URL}/{line_id}?"
            + urlencode(
                {
                    "properties": (
                        "hs_sku,hs_product_id,name,quantity,price,"
                        "hs_line_item_currency_code"
                    )
                }
            ),
            headers=headers,
        )
        properties = line.get("properties") if isinstance(line, dict) else None
        if not isinstance(properties, dict):
            continue
        sku = nonempty(properties.get("hs_sku"))
        if sku is None:
            continue
        key = sku.casefold()
        if key in by_sku:
            raise SyncError(
                f"HubSpot Cart {cart_id} has multiple Line Items for SKU {sku!r}."
            )
        by_sku[key] = line
    return by_sku


def sync_cart_line_items(
    *,
    access_token: str,
    cart_id: str,
    desired: dict[str, dict[str, str]],
    remove_stale: bool = True,
) -> tuple[int, int, int]:
    """Upsert and reconcile product-backed Line Items for one HubSpot Cart.

    ``remove_stale`` is turned off for a Cart whose source Checkout had a line
    this sync could not map to a HubSpot Product. Once a line is missing from
    ``desired`` for that reason, "gone from the Checkout" and "product retired
    from the catalogue" look identical, and deleting on that guess would throw
    away a Cart line the shopper really had.
    """

    existing = existing_cart_line_items(access_token, cart_id)
    headers = {"Authorization": f"Bearer {access_token}"}
    created = updated = removed = 0

    for key, properties in desired.items():
        current = existing.get(key)
        if current is None:
            response = _http_json(
                HUBSPOT_LINE_ITEMS_URL,
                method="POST",
                headers=headers,
                payload={"properties": properties},
            )
            line_id = nonempty(response.get("id")) if isinstance(response, dict) else None
            if line_id is None:
                raise SyncError(
                    f"HubSpot created Cart Line Item {properties.get('hs_sku')!r} "
                    "without returning its ID"
                )
            associate_cart(
                access_token,
                cart_id,
                "line_items",
                line_id,
                CART_LINE_ITEM_ASSOCIATION_TYPE_ID,
            )
            created += 1
            continue

        line_id = nonempty(current.get("id"))
        current_properties = current.get("properties")
        if line_id is None or not isinstance(current_properties, dict):
            raise SyncError(f"HubSpot Cart {cart_id} returned an unusable Line Item")

        wanted_product_id = properties["hs_product_id"]
        current_product_id = nonempty(current_properties.get("hs_product_id"))
        if current_product_id and current_product_id != wanted_product_id:
            _http_json(
                f"{HUBSPOT_LINE_ITEMS_URL}/{line_id}",
                method="DELETE",
                headers=headers,
            )
            response = _http_json(
                HUBSPOT_LINE_ITEMS_URL,
                method="POST",
                headers=headers,
                payload={"properties": properties},
            )
            new_id = nonempty(response.get("id")) if isinstance(response, dict) else None
            if new_id is None:
                raise SyncError(
                    f"HubSpot recreated Cart Line Item {properties.get('hs_sku')!r} "
                    "without returning its ID"
                )
            associate_cart(
                access_token,
                cart_id,
                "line_items",
                new_id,
                CART_LINE_ITEM_ASSOCIATION_TYPE_ID,
            )
            created += 1
            continue

        _http_json(
            f"{HUBSPOT_LINE_ITEMS_URL}/{line_id}",
            method="PATCH",
            headers=headers,
            payload={
                "properties": {
                    name: value
                    for name, value in properties.items()
                    if name != "hs_product_id"
                }
            },
        )
        updated += 1

    stale_candidates = existing.items() if remove_stale else ()
    for key, current in stale_candidates:
        if key in desired:
            continue
        line_id = nonempty(current.get("id"))
        properties = current.get("properties")
        if (
            line_id is None
            or not isinstance(properties, dict)
            or nonempty(properties.get("hs_product_id")) is None
        ):
            continue
        _http_json(
            f"{HUBSPOT_LINE_ITEMS_URL}/{line_id}",
            method="DELETE",
            headers=headers,
        )
        removed += 1

    return created, updated, removed


def link_carts_to_orders(
    *,
    orders: list[dict[str, Any]],
    hubspot_access_token: str,
    carts_by_token: dict[str, str],
    hubspot_orders: dict[str, str],
) -> int:
    """Associate each HubSpot Cart with the Order sharing its EasyStore cart token."""

    linked = 0
    for order in orders:
        cart_token = nonempty(order.get("cart_token"))
        order_external_id = nonempty(order.get("id"))
        if cart_token is None or order_external_id is None:
            continue
        cart_id = carts_by_token.get(cart_token)
        order_id = hubspot_orders.get(order_external_id)
        if cart_id is None or order_id is None:
            continue
        associate_cart(
            hubspot_access_token,
            cart_id,
            "order",
            order_id,
            CART_ORDER_ASSOCIATION_TYPE_ID,
        )
        linked += 1
    return linked


def _legacy_cart_owner(
    checkout: dict[str, Any],
    existing: dict[str, str],
) -> str | None:
    """Return one legacy Cart to migrate, failing if old IDs point to two Carts."""

    candidates = {
        existing[legacy]
        for legacy in (
            nonempty(checkout.get("id")),
            nonempty(checkout.get("token")),
        )
        if legacy is not None and legacy in existing
    }
    if len(candidates) > 1:
        raise SyncError(
            "EasyStore checkout legacy ID and token point to different HubSpot "
            "Carts; resolve the duplicate carts before migrating to cart_token."
        )
    return next(iter(candidates), None)


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
    checkouts: Sequence[dict[str, Any]] | None = None,
    include_completed: bool = False,
    cart_schema_object_type: str | None = None,
) -> dict[str, Any]:
    """Perform the corrected EasyStore Checkout → HubSpot Cart sync.

    ``checkouts`` accepts a snapshot the caller has already read and hydrated, so
    the production entrypoint can prove the source data is complete before any
    HubSpot Cart is touched. Left out, the documented collection is read here.

    ``include_completed`` keeps paid and converted Checkouts as Carts, which is
    what HubSpot's Cart object models: a shopping session, abandoned or not. With
    it off, only the abandoned subset becomes a Cart.

    ``cart_schema_object_type`` overrides the object type used for the Cart
    property schema, because HubSpot's schema API is singular (``cart``) while
    its object API is plural (``carts``).
    """

    schema_object_type = cart_schema_object_type or CART_SCHEMA_OBJECT_TYPE

    if not cart_object_available(hubspot_access_token, schema_object_type):
        print(
            "WARNING: this HubSpot portal does not expose the Cart object, so "
            "checkout synchronization was skipped.",
            file=sys.stderr,
        )
        return {"hubspot_cart_object": "unavailable"}

    orders = list(iter_orders_for_cart_links(store_domain, easystore_access_token))
    listed_checkouts = (
        list(checkouts)
        if checkouts is not None
        else list(iter_documented_checkouts(store_domain, easystore_access_token))
    )

    schema_report: dict[str, Any] = {}
    cart_field_properties = resolve_fields(
        http_json=_http_json,
        access_token=hubspot_access_token,
        object_type=schema_object_type,
        fields=cart_mapping.CART_FIELDS,
        error=SyncError,
        report=schema_report,
    )
    line_item_field_properties = resolve_line_item_fields(hubspot_access_token)
    print(
        "Cart fields mapped to HubSpot properties: "
        + describe_mapping(cart_field_properties),
        file=sys.stderr,
    )
    print(
        "Cart Line Item fields mapped to HubSpot properties: "
        + describe_mapping(line_item_field_properties),
        file=sys.stderr,
    )

    product_by_sku = hubspot_product_index(hubspot_access_token)
    contacts = hubspot_contact_index(hubspot_access_token, fallback_dial_code)

    validated: list[tuple[dict[str, Any], str, dict[str, dict[str, str]], bool]] = []
    scanned = completed = without_cart_token = 0
    abandoned_carts = converted_carts = 0
    carts_with_unmatched_lines = unmatched_line_count = 0
    unmatched_skus: set[str] = set()
    checkout_keys: set[str] = set()
    line_keys: set[str] = set()
    field_coverage = {field.key: 0 for field in cart_mapping.CART_FIELDS}

    # Validate all checkout product references before mutating Carts/Line Items.
    for listed in listed_checkouts:
        scanned += 1
        checkout = complete_checkout(store_domain, easystore_access_token, listed)
        observed_keys(checkout_keys, checkout)
        lines = checkout.get("line_items")
        if isinstance(lines, list):
            for line in lines:
                observed_keys(line_keys, line)

        if is_abandoned(checkout):
            abandoned_carts += 1
        else:
            converted_carts += 1
            if not include_completed:
                completed += 1
                continue

        cart_token = checkout_cart_token(checkout)
        if cart_token is None:
            without_cart_token += 1
            continue

        values = cart_mapping.cart_field_values(checkout, fallback_dial_code)
        if checkout_status(checkout) is not None:
            values.setdefault("status", checkout_status(checkout) or "")
        for key in values:
            if key in field_coverage:
                field_coverage[key] += 1

        unmatched: list[str] = []
        desired = desired_lines(
            checkout,
            product_by_sku,
            line_item_field_properties,
            record="checkout",
            unmatched_lines=unmatched,
        )
        if unmatched:
            carts_with_unmatched_lines += 1
            unmatched_line_count += len(unmatched)
            unmatched_skus.update(unmatched)
        validated.append((checkout, cart_token, desired, bool(unmatched)))

    existing = hubspot_cart_index(hubspot_access_token)
    hubspot_orders = hubspot_order_index(hubspot_access_token)
    created = updated = migrated = 0
    contact_links = ambiguous_mobile = 0
    line_created = line_updated = line_removed = 0

    for checkout, cart_token, desired, had_unmatched in validated:
        existing_id = existing.get(cart_token)
        if existing_id is None:
            existing_id = _legacy_cart_owner(checkout, existing)
            if existing_id is not None:
                migrated += 1

        cart_id, was_created = upsert_cart(
            hubspot_access_token,
            existing_id,
            cart_properties(
                checkout,
                cart_token=cart_token,
                store_domain=store_domain,
                field_properties=cart_field_properties,
                fallback_dial_code=fallback_dial_code,
            ),
        )
        existing[cart_token] = cart_id
        if was_created:
            created += 1
        else:
            updated += 1

        c, u, r = sync_cart_line_items(
            access_token=hubspot_access_token,
            cart_id=cart_id,
            desired=desired,
            remove_stale=not had_unmatched,
        )
        line_created += c
        line_updated += u
        line_removed += r

        mobile = cart_mapping.cart_mobile(checkout, fallback_dial_code)
        if mobile is None:
            continue
        matching = contacts.by_phone.get(mobile, set())
        if len(matching) == 1:
            associate_cart(
                hubspot_access_token,
                cart_id,
                "contact",
                next(iter(matching)),
                CART_CONTACT_ASSOCIATION_TYPE_ID,
            )
            contact_links += 1
        elif len(matching) > 1:
            ambiguous_mobile += 1
            print(
                f"WARNING: EasyStore cart {cart_token} mobile {mobile} matches "
                "multiple HubSpot contacts; Cart→Contact association skipped.",
                file=sys.stderr,
            )

    order_links = link_carts_to_orders(
        orders=orders,
        hubspot_access_token=hubspot_access_token,
        carts_by_token=existing,
        hubspot_orders=hubspot_orders,
    )

    return {
        "easystore_checkout_route": "checkouts.json",
        "easystore_checkouts_scanned": scanned,
        "easystore_checkouts_abandoned": abandoned_carts,
        "easystore_checkouts_converted": converted_carts,
        "checkouts_skipped_as_completed": completed,
        "completed_checkouts_kept_as_carts": include_completed,
        "checkouts_without_cart_token": without_cart_token,
        "easystore_orders_scanned_for_cart_links": len(orders),
        "hubspot_carts_created": created,
        "hubspot_carts_updated": updated,
        "hubspot_carts_migrated_to_cart_token": migrated,
        "hubspot_cart_line_items_created": line_created,
        "hubspot_cart_line_items_updated": line_updated,
        "stale_product_backed_cart_line_items_removed": line_removed,
        "cart_contact_associations_ensured": contact_links,
        "cart_order_associations_ensured": order_links,
        "carts_with_ambiguous_contact_mobile": ambiguous_mobile,
        "cart_lines_without_a_hubspot_product": unmatched_line_count,
        "carts_with_lines_without_a_hubspot_product": carts_with_unmatched_lines,
        "cart_line_skus_without_a_hubspot_product": sorted(unmatched_skus)[:25],
        "hubspot_cart_schema_object_type": schema_object_type,
        "hubspot_cart_abandoned_property": cart_field_properties.get("is_abandoned"),
        "hubspot_cart_field_properties": dict(sorted(cart_field_properties.items())),
        "easystore_cart_field_coverage": dict(sorted(field_coverage.items())),
        "easystore_checkout_keys_seen": sorted(checkout_keys),
        "easystore_checkout_line_item_keys_seen": sorted(line_keys),
        "hubspot_cart_property_hints": schema_report.get("hints", {}),
    }


def required(value: str | None, name: str) -> str:
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
        summary = sync(
            store_domain=required(args.store_domain, "EASYSTORE_STORE_DOMAIN"),
            easystore_access_token=required(
                args.easystore_token,
                "EASYSTORE_ACCESS_TOKEN",
            ),
            hubspot_access_token=required(
                args.hubspot_token,
                "HUBSPOT_ACCESS_TOKEN",
            ),
            fallback_dial_code=required(
                args.fallback_dial_code,
                "CUSTOMER_SYNC_DEFAULT_DIAL_CODE",
            ),
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
