#!/usr/bin/env python3
"""Sync EasyStore abandoned checkouts into HubSpot Carts.

An abandoned checkout is a cart a shopper filled and never paid for, so it is
CRM-worthy in its own right: it names a contactable person, the value they were
about to spend, and the link that would let them finish. HubSpot models this with
its native Cart object, keyed here by ``hs_external_cart_id`` holding the
EasyStore checkout ID.

Completed checkouts are deliberately skipped. They already exist as Orders, and
copying them here would double-count revenue.

Two things this stage refuses to guess:

* **Which EasyStore route serves abandoned checkouts.** Every candidate is
  probed for a single record and the outcome of each is reported, so an
  unexpected route is a one-line fix rather than a silent empty sync. Probing is
  discovery, not the sync: a route that 404s, hangs or serves HTML is recorded
  and passed over, never fatal, because a storefront that has no such route must
  not take the run down with it.
* **Whether the portal has a Cart object at all.** Not every HubSpot account
  does. A portal without one is reported and skipped rather than failing the run
  or inventing somewhere else to put the data.

Only Python's standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from itertools import chain
from typing import Any, Callable, Iterator

from easystore_hubspot_orders import (
    HUBSPOT_BASE,
    SyncError,
    _address_derivations,
    _address_fields,
    _billing_address,
    _delivery_address,
    _discount_codes,
    _extract_list,
    _http_json,
    _shop_domain,
    _tags,
    iter_hubspot_objects,
    normalize_mobile,
)
from easystore_hubspot_schema import (
    FieldSpec,
    apply_fields,
    describe_mapping,
    field_values,
    first_present,
    iter_easystore_pages,
    nonempty,
    observed_keys,
    resolve_fields,
)


CART_OBJECT_TYPE = "carts"
HUBSPOT_CARTS_URL = f"{HUBSPOT_BASE}/crm/v3/objects/{CART_OBJECT_TYPE}"
CART_EXTERNAL_ID_PROPERTY = "hs_external_cart_id"
EASYSTORE_PAGE_SIZE = 50

# EasyStore's admin calls these "abandoned checkouts". Every candidate below is
# probed and the first one holding records is used for the whole run; a route
# that answers empty is only settled for once no other route has anything.
CHECKOUT_ROUTES = (
    "checkouts.json",
    "abandoned_checkouts.json",
    "carts.json",
    "abandoned_carts.json",
)

# The collection keys a checkout payload may arrive under.
CHECKOUT_COLLECTIONS = (
    "checkouts",
    "abandoned_checkouts",
    "carts",
    "data",
    "results",
)

# Discovery is throwaway work, so it gets a short leash: one record, one retry
# and a fraction of the normal read timeout. Four dead routes at the default
# 60 seconds and four retries each would spend twenty minutes proving nothing.
CHECKOUT_PROBE_LIMIT = 1
CHECKOUT_PROBE_RETRIES = 1
CHECKOUT_PROBE_TIMEOUT = 20


def _cart_address_fields(prefix: str, native_prefix: str) -> tuple[FieldSpec, ...]:
    """Return one address role's FieldSpecs, phone included.

    The Order stage's address table is reused so both objects read the same
    EasyStore keys. HubSpot's Cart object adds an address phone the Order object
    has no equivalent for, so that one is declared here.
    """

    return (
        *_address_fields(prefix, native_prefix),
        FieldSpec(key=f"{prefix}_phone", native=(f"{native_prefix}_phone",)),
    )


def _cart_address_derivations(
    prefix: str,
    getter: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Callable[[dict[str, Any]], str | None]]:
    return {
        **_address_derivations(prefix, getter),
        f"{prefix}_phone": lambda cart: first_present(
            getter(cart),
            ("phone", "phone_number", "mobile"),
        ),
    }


# Fields copied onto the HubSpot Cart. The native names come from HubSpot's Cart
# object; anything without one lands in a provisioned easystore_* property, the
# same rule the Order stage follows.
CART_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="status",
        sources=("status", "state", "checkout_status", "status_label"),
        native=("hs_external_status",),
        fallback="easystore_cart_status",
        label="EasyStore Checkout Status",
        description="Status EasyStore reports for the abandoned checkout.",
    ),
    FieldSpec(
        key="total_amount",
        sources=("total_price", "total_amount", "grand_total", "total"),
        native=("hs_total_price",),
        fallback="easystore_cart_total_amount",
        label="EasyStore Cart Total",
        description="Total the abandoned checkout would have charged.",
        kind="number",
    ),
    FieldSpec(
        key="subtotal_amount",
        sources=("subtotal_price", "subtotal", "sub_total", "total_line_items_price"),
        native=("hs_subtotal_price", "hs_subtotal"),
        fallback="easystore_cart_subtotal_amount",
        label="EasyStore Cart Subtotal",
        description="Merchandise subtotal of the abandoned checkout.",
        kind="number",
    ),
    FieldSpec(
        key="discount_amount",
        sources=("total_discount", "total_discounts", "discount_amount"),
        native=("hs_cart_discount", "hs_discount_amount"),
        fallback="easystore_cart_discount_amount",
        label="EasyStore Cart Discount",
        description="Discount applied to the abandoned checkout.",
        kind="number",
        absolute=True,
    ),
    FieldSpec(
        key="tax_amount",
        sources=("total_tax", "total_taxes", "tax_total", "tax"),
        native=("hs_tax", "hs_tax_amount"),
        fallback="easystore_cart_tax_amount",
        label="EasyStore Cart Tax",
        description="Tax quoted on the abandoned checkout.",
        kind="number",
    ),
    FieldSpec(
        key="shipping_amount",
        sources=(
            "total_shipping",
            "total_shipping_price",
            "shipping_price",
            "shipping_total",
            "shipping_fee",
        ),
        native=("hs_shipping_cost", "hs_shipping_amount"),
        fallback="easystore_cart_shipping_amount",
        label="EasyStore Cart Shipping",
        description="Shipping quoted on the abandoned checkout.",
        kind="number",
    ),
    FieldSpec(
        key="tags",
        native=("hs_tags",),
        fallback="easystore_cart_tags",
        label="EasyStore Cart Tags",
        description="Comma separated tags on the EasyStore checkout.",
    ),
    FieldSpec(
        key="created_at",
        sources=("created_at", "created_on", "started_at"),
        native=("hs_external_created_date",),
        fallback="easystore_cart_created_at",
        label="EasyStore Cart Started",
        description="When the shopper started the checkout in EasyStore.",
        kind="datetime",
    ),
    FieldSpec(
        key="abandoned_at",
        sources=("abandoned_at", "updated_at", "last_activity_at", "modified_at"),
        native=("hs_external_modified_date",),
        fallback="easystore_cart_abandoned_at",
        label="EasyStore Cart Abandoned",
        description="Last time EasyStore saw activity on the abandoned checkout.",
        kind="datetime",
    ),
    FieldSpec(
        key="recovery_url",
        sources=(
            "abandoned_checkout_url",
            "recovery_url",
            "checkout_url",
            "url",
            "link",
        ),
        native=("hs_cart_url",),
        fallback="easystore_cart_recovery_url",
        label="EasyStore Recovery Link",
        description="Link that lets the shopper resume this checkout.",
    ),
    FieldSpec(
        key="item_count",
        native=(),
        fallback="easystore_cart_item_count",
        label="EasyStore Cart Units",
        description="Number of units left in the abandoned checkout.",
        kind="number",
    ),
    FieldSpec(
        key="items",
        native=(),
        fallback="easystore_cart_items",
        label="EasyStore Cart Contents",
        description="What the shopper left behind, as SKU and quantity.",
    ),
    FieldSpec(
        key="buyer_email",
        native=(),
        fallback="easystore_cart_email",
        label="EasyStore Cart Email",
        description="Email EasyStore captured before the checkout was abandoned.",
    ),
    FieldSpec(
        key="buyer_name",
        native=(),
        fallback="easystore_cart_customer_name",
        label="EasyStore Cart Shopper",
        description="Name EasyStore captured for the abandoned checkout.",
    ),
    FieldSpec(
        key="buyer_phone",
        native=(),
        fallback="easystore_cart_phone",
        label="EasyStore Cart Mobile",
        description="Normalized mobile number captured for the abandoned checkout.",
    ),
    # HubSpot Carts hold both halves of the funnel: sessions still open and
    # sessions that became Orders. ``hs_external_status`` carries EasyStore's own
    # word for it, which differs per store, so the abandoned subset is also
    # written as a plain flag that a HubSpot list or report can filter on.
    FieldSpec(
        key="is_abandoned",
        native=(),
        fallback="easystore_cart_is_abandoned",
        label="EasyStore Cart Abandoned",
        description=(
            "true while the EasyStore checkout is unpaid and unconverted; "
            "false once it has been paid, completed or turned into an order."
        ),
    ),
    # Native-only from here down. HubSpot defines these on every Cart object, so
    # a portal that somehow lacks one gains nothing from a duplicate custom
    # property, and the card that displays them stays authoritative.
    FieldSpec(
        key="token",
        sources=("token", "cart_token", "checkout_token"),
        native=("hs_external_token",),
    ),
    FieldSpec(key="discount_codes", native=("hs_discount_codes",)),
    FieldSpec(
        key="landing_site",
        sources=("landing_site", "landing_page", "landing_site_url"),
        native=("hs_landing_site",),
    ),
    FieldSpec(
        key="referring_site",
        sources=("referring_site", "referrer", "referral_site"),
        native=("hs_referring_site",),
    ),
    # A weight, not a price: HubSpot types this one as text, so the unit
    # EasyStore reports travels with the number instead of being guessed at.
    FieldSpec(
        key="total_weight",
        sources=("total_weight", "weight", "total_weight_grams"),
        native=("hs_total_weight",),
    ),
    *_cart_address_fields("shipping_address", "hs_shipping_address"),
    *_cart_address_fields("billing_address", "hs_billing_address"),
)


def _cart_lines(cart: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("line_items", "items", "cart_items", "checkout_items"):
        lines = cart.get(key)
        if isinstance(lines, dict):
            return [lines]
        if isinstance(lines, list):
            return [line for line in lines if isinstance(line, dict)]
    return []


def _line_quantity(line: dict[str, Any]) -> int:
    try:
        return max(int(line.get("quantity") or 0), 0)
    except (TypeError, ValueError):
        return 0


def _item_count(cart: dict[str, Any]) -> str | None:
    reported = first_present(cart, ("item_count", "total_items", "line_items_count"))
    if reported is not None:
        return reported
    units = sum(_line_quantity(line) for line in _cart_lines(cart))
    return str(units) if units else None


def _items(cart: dict[str, Any]) -> str | None:
    """Return what the shopper left behind, readable at a glance in the CRM."""

    described: list[str] = []
    for line in _cart_lines(cart):
        label = first_present(line, ("title", "name", "product_name", "sku"))
        if label is None:
            continue
        quantity = _line_quantity(line)
        described.append(f"{label} x{quantity}" if quantity else label)
    return "; ".join(described) if described else None


def _buyer_email(cart: dict[str, Any]) -> str | None:
    customer = cart.get("customer")
    if isinstance(customer, dict):
        email = first_present(customer, ("email", "email_address"))
        if email is not None:
            return email
    return first_present(cart, ("email", "customer_email", "contact_email"))


def _person_name(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    whole = first_present(record, ("name", "full_name", "customer_name"))
    if whole is not None:
        return whole
    first = first_present(record, ("first_name", "firstname"))
    last = first_present(record, ("last_name", "lastname"))
    if first and last:
        return f"{first} {last}"
    return first or last


def _buyer_name(cart: dict[str, Any]) -> str | None:
    return (
        _person_name(cart.get("customer"))
        or first_present(cart, ("customer_name", "contact_name"))
        or _person_name(cart.get("billing_address"))
        or _person_name(cart.get("shipping_address"))
    )


def cart_email(cart: dict[str, Any]) -> str | None:
    """Return the shopper email EasyStore recorded on this checkout, if any."""

    return _buyer_email(cart)


def cart_mobile(cart: dict[str, Any], fallback_dial_code: str) -> str | None:
    """Return the shopper's normalized mobile, using the CRM identity rule."""

    candidates: list[tuple[Any, Any]] = []
    customer = cart.get("customer")
    if isinstance(customer, dict):
        candidates.append((customer.get("phone"), customer.get("country_code")))
    for key in ("billing_address", "shipping_address"):
        address = cart.get(key)
        if isinstance(address, dict):
            candidates.append((address.get("phone"), address.get("country_code")))
    candidates.append((cart.get("phone"), cart.get("country_code")))

    for value, country_code in candidates:
        mobile = normalize_mobile(value, country_code, fallback_dial_code)
        if mobile:
            return mobile
    return None


# A checkout in one of these states has stopped being an open cart, whichever
# EasyStore field reports it.
SETTLED_STATUSES = frozenset(
    {
        "completed",
        "complete",
        "paid",
        "converted",
        "order",
        "refunded",
        "voided",
        "cancelled",
        "canceled",
        # Money moved, even if not all of it: these are conversions, not
        # abandoned carts. "pending" is deliberately absent - a pending payment
        # is still an unpaid cart worth recovering.
        "partially_paid",
        "partially_refunded",
        "authorized",
    }
)


def is_abandoned(cart: dict[str, Any]) -> bool:
    """Report whether a checkout is still an open, unpaid cart.

    This is the single abandoned-cart predicate for the CRM. A checkout that
    became an order is already synchronized by the order stage, so counting it as
    an abandoned cart would double-count the revenue; EasyStore reports that
    state through an order reference, a completion timestamp, or one of several
    status fields, so all three are read.
    """

    if nonempty(cart.get("order_id")) is not None:
        return False
    if isinstance(cart.get("order"), dict):
        return False
    if nonempty(cart.get("completed_at")) is not None:
        return False
    for status in (
        first_present(cart, ("financial_status", "payment_status")),
        first_present(cart, ("status", "state", "checkout_status")),
    ):
        if status and status.casefold() in SETTLED_STATUSES:
            return False
    return True


def cart_properties(
    cart: dict[str, Any],
    *,
    external_id: str,
    store_domain: str,
    field_properties: dict[str, str] | None = None,
    fallback_dial_code: str = "65",
) -> dict[str, str]:
    """Map an EasyStore abandoned checkout onto HubSpot Cart properties."""

    name = (
        nonempty(cart.get("name"))
        or nonempty(cart.get("checkout_number"))
        or nonempty(cart.get("token"))
        or f"EasyStore checkout {external_id}"
    )
    properties: dict[str, str] = {
        CART_EXTERNAL_ID_PROPERTY: external_id,
        "hs_cart_name": name,
        "hs_source_store": _shop_domain(store_domain),
    }

    currency = nonempty(cart.get("currency") or cart.get("currency_code"))
    if currency:
        properties["hs_currency_code"] = currency.upper()

    return apply_fields(
        properties,
        cart_field_values(cart, fallback_dial_code),
        field_properties or DEFAULT_CART_FIELD_PROPERTIES,
    )


CART_FIELD_DERIVATIONS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "tags": _tags,
    "discount_codes": _discount_codes,
    "item_count": _item_count,
    "items": _items,
    "buyer_email": _buyer_email,
    "buyer_name": _buyer_name,
    "is_abandoned": lambda cart: "true" if is_abandoned(cart) else "false",
    **_cart_address_derivations("shipping_address", _delivery_address),
    **_cart_address_derivations("billing_address", _billing_address),
}

DEFAULT_CART_FIELD_PROPERTIES: dict[str, str] = {
    field.key: field.native[0] if field.native else field.fallback
    for field in CART_FIELDS
    if field.native or field.fallback
}


def cart_field_values(
    cart: dict[str, Any],
    fallback_dial_code: str = "65",
) -> dict[str, str]:
    """Return every mapped value for a checkout, keyed by field key."""

    derivations = {
        **CART_FIELD_DERIVATIONS,
        "buyer_phone": lambda item: cart_mobile(item, fallback_dial_code),
    }
    return field_values(cart, CART_FIELDS, derivations)


def _describe_probes(probes: dict[str, str]) -> str:
    """Return each candidate route and its outcome, in the order tried."""

    return "; ".join(f"{route}: {reason}" for route, reason in probes.items())


def _probe_reason(error: SyncError) -> str:
    """Return why a candidate route was passed over, short enough to read."""

    return " ".join(str(error).split())[:200]


def iter_easystore_checkouts(
    store_domain: str,
    access_token: str,
) -> tuple[str | None, Iterator[dict[str, Any]], dict[str, str]]:
    """Return the route serving abandoned checkouts, its records, and the probes.

    EasyStore's documented route for these is not reachable from CI, so each
    candidate is probed for one record. Any failure only rules that route out,
    whether it is a 404, the storefront's HTML in place of JSON, or a read that
    never comes back: the reason is recorded and the next candidate is tried. A
    store with no abandoned-checkout route at all therefore reports what it
    tried instead of failing the sync.
    """

    domain = _shop_domain(store_domain)
    headers = {"EasyStore-Access-Token": access_token}
    probes: dict[str, str] = {}
    answered_empty: str | None = None

    for route in CHECKOUT_ROUTES:
        try:
            document = _http_json(
                f"https://{domain}/api/3.0/{route}"
                f"?page=1&limit={CHECKOUT_PROBE_LIMIT}",
                headers=headers,
                retries=CHECKOUT_PROBE_RETRIES,
                timeout=CHECKOUT_PROBE_TIMEOUT,
            )
        except SyncError as error:
            probes[route] = _probe_reason(error)
            continue

        if document is None:
            probes[route] = "no answer"
            continue

        if _extract_list(document, *CHECKOUT_COLLECTIONS):
            probes[route] = "answered with abandoned checkouts"
            return route, _iter_route(domain, access_token, route), probes

        probes[route] = "answered with no records"
        if answered_empty is None:
            answered_empty = route

    return answered_empty, iter(()), probes


def _iter_route(
    domain: str,
    access_token: str,
    route: str,
) -> Iterator[dict[str, Any]]:
    """Yield every checkout the chosen route serves, a page at a time."""


    def fetch(page: int) -> list[dict[str, Any]]:
        document = _http_json(
            f"https://{domain}/api/3.0/{route}?page={page}&limit={EASYSTORE_PAGE_SIZE}",
            headers={"EasyStore-Access-Token": access_token},
        )
        return _extract_list(document, *CHECKOUT_COLLECTIONS)

    yield from iter_easystore_pages(
        fetch,
        page_size=EASYSTORE_PAGE_SIZE,
        what=route,
        error=SyncError,
    )


def hubspot_cart_index(access_token: str) -> dict[str, str]:
    """Return HubSpot cart IDs keyed by their EasyStore checkout ID."""

    by_external_id: dict[str, set[str]] = {}
    for cart in iter_hubspot_objects(
        HUBSPOT_CARTS_URL,
        access_token,
        CART_EXTERNAL_ID_PROPERTY,
    ):
        hubspot_id = nonempty(cart.get("id"))
        properties = cart.get("properties")
        if hubspot_id is None or not isinstance(properties, dict):
            continue
        external_id = nonempty(properties.get(CART_EXTERNAL_ID_PROPERTY))
        if external_id:
            by_external_id.setdefault(external_id, set()).add(hubspot_id)

    duplicates = {key: ids for key, ids in by_external_id.items() if len(ids) > 1}
    if duplicates:
        sample = "; ".join(
            f"{key}: {','.join(sorted(ids))}" for key, ids in list(duplicates.items())[:10]
        )
        raise SyncError(
            "Multiple HubSpot carts carry the same EasyStore checkout ID. "
            f"Resolve the duplicates before syncing. {sample}"
        )
    return {key: next(iter(ids)) for key, ids in by_external_id.items()}


def cart_object_available(access_token: str) -> bool:
    """Report whether this portal exposes the HubSpot Cart object."""

    document = _http_json(
        f"{HUBSPOT_BASE}/crm/v3/properties/{CART_OBJECT_TYPE}",
        headers={"Authorization": f"Bearer {access_token}"},
        allow_statuses={400, 403, 404},
    )
    return isinstance(document, dict) and isinstance(document.get("results"), list)


def _upsert_cart(
    access_token: str,
    existing_id: str | None,
    properties: dict[str, str],
) -> tuple[str, bool]:
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
            raise SyncError("HubSpot created a cart without returning its ID")
        return cart_id, True

    _http_json(
        f"{HUBSPOT_CARTS_URL}/{existing_id}",
        method="PATCH",
        headers=headers,
        payload={"properties": properties},
    )
    return existing_id, False


def _associate_contact(access_token: str, cart_id: str, contact_id: str) -> None:
    """Associate a cart with its shopper using HubSpot's default label.

    The v4 default route avoids hard-coding an association type ID, which is not
    documented for carts and would silently associate the wrong way if guessed.
    """

    _http_json(
        f"{HUBSPOT_BASE}/crm/v4/objects/{CART_OBJECT_TYPE}/{cart_id}"
        f"/associations/default/contacts/{contact_id}",
        method="PUT",
        headers={"Authorization": f"Bearer {access_token}"},
    )


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, Any]:
    """Synchronize EasyStore abandoned checkouts into HubSpot Carts."""

    if not cart_object_available(hubspot_access_token):
        print(
            "WARNING: this HubSpot portal does not expose the Cart object, so "
            "abandoned checkouts were not synchronized. Nothing else is affected.",
            file=sys.stderr,
        )
        return {"hubspot_cart_object": "unavailable"}

    schema_report: dict[str, Any] = {}
    cart_field_properties = resolve_fields(
        http_json=_http_json,
        access_token=hubspot_access_token,
        object_type=CART_OBJECT_TYPE,
        fields=CART_FIELDS,
        error=SyncError,
        report=schema_report,
    )
    print(
        "HubSpot Cart properties in this portal: "
        + ", ".join(schema_report.get("inventory", [])),
        file=sys.stderr,
    )
    print(
        "Cart fields mapped to HubSpot properties: "
        + describe_mapping(cart_field_properties),
        file=sys.stderr,
    )

    route, checkouts, probes = iter_easystore_checkouts(
        store_domain,
        easystore_access_token,
    )
    if route is None:
        print(
            "WARNING: no EasyStore route answered for abandoned checkouts, so "
            "none were synchronized. Nothing else is affected. Routes tried: "
            + _describe_probes(probes),
            file=sys.stderr,
        )
        return {
            "easystore_checkout_route": None,
            "easystore_checkout_route_probes": probes,
        }

    # Nothing to sync is worth knowing before scanning every HubSpot contact and
    # cart for identities no checkout will ask about.
    first_checkout = next(checkouts, None)
    if first_checkout is None:
        print(
            f"WARNING: EasyStore route {route} reports no abandoned checkouts, "
            "so there was nothing to synchronize.",
            file=sys.stderr,
        )
        return {
            "easystore_checkout_route": route,
            "easystore_checkout_route_probes": probes,
            "easystore_checkouts_scanned": 0,
        }
    checkouts = chain([first_checkout], checkouts)

    from easystore_hubspot_orders import hubspot_contact_index

    contacts = hubspot_contact_index(hubspot_access_token, fallback_dial_code)
    existing = hubspot_cart_index(hubspot_access_token)

    scanned = 0
    completed = 0
    created = 0
    updated = 0
    associated = 0
    without_id = 0
    ambiguous_mobile = 0
    field_coverage: dict[str, int] = {field.key: 0 for field in CART_FIELDS}
    checkout_keys: set[str] = set()

    for checkout in checkouts:
        scanned += 1
        observed_keys(checkout_keys, checkout)
        if not is_abandoned(checkout):
            completed += 1
            continue

        external_id = nonempty(checkout.get("id")) or nonempty(checkout.get("token"))
        if external_id is None:
            without_id += 1
            continue

        for key in cart_field_values(checkout, fallback_dial_code):
            field_coverage[key] += 1

        cart_id, was_created = _upsert_cart(
            hubspot_access_token,
            existing.get(external_id),
            cart_properties(
                checkout,
                external_id=external_id,
                store_domain=store_domain,
                field_properties=cart_field_properties,
                fallback_dial_code=fallback_dial_code,
            ),
        )
        existing[external_id] = cart_id
        if was_created:
            created += 1
        else:
            updated += 1

        mobile = cart_mobile(checkout, fallback_dial_code)
        if mobile is None:
            continue
        matching = contacts.by_phone.get(mobile, set())
        if len(matching) == 1:
            _associate_contact(hubspot_access_token, cart_id, next(iter(matching)))
            associated += 1
        elif len(matching) > 1:
            ambiguous_mobile += 1
            print(
                f"WARNING: EasyStore checkout {external_id} mobile {mobile} matches "
                "multiple HubSpot contacts; cart-contact association skipped.",
                file=sys.stderr,
            )

    return {
        "easystore_checkout_route": route,
        "easystore_checkout_route_probes": probes,
        "easystore_checkouts_scanned": scanned,
        "checkouts_skipped_as_completed": completed,
        "checkouts_without_id": without_id,
        "hubspot_carts_created": created,
        "hubspot_carts_updated": updated,
        "cart_contact_associations_ensured": associated,
        "carts_with_ambiguous_contact_mobile": ambiguous_mobile,
        "hubspot_cart_field_properties": dict(sorted(cart_field_properties.items())),
        "easystore_cart_field_coverage": dict(sorted(field_coverage.items())),
        "easystore_checkout_keys_seen": sorted(checkout_keys),
        "hubspot_cart_property_hints": schema_report.get("hints", {}),
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
        summary = sync(
            store_domain=_required(args.store_domain, "EASYSTORE_STORE_DOMAIN"),
            easystore_access_token=_required(
                args.easystore_token,
                "EASYSTORE_ACCESS_TOKEN",
            ),
            hubspot_access_token=_required(
                args.hubspot_token,
                "HUBSPOT_ACCESS_TOKEN",
            ),
            fallback_dial_code=args.fallback_dial_code,
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
