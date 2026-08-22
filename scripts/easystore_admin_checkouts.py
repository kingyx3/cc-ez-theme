#!/usr/bin/env python3
"""Read EasyStore's abandoned checkout list from its admin API.

The public ``/api/3.0/checkouts.json`` route is not the abandoned checkout list
the EasyStore admin shows. It serves every session the storefront ever opened:
production run 32539291543 read 1267 records where the admin lists 15, and only
41 of them carried an email. It also names no customer, so a Cart could only be
matched to a Contact by the email or phone the shopper typed into the form.

The admin route the EasyStore UI itself calls does better on every count:

* it serves the abandoned checkouts and nothing else - ``total_count`` was 15
  against the same store's 1267;
* every record names ``customer_id``, which is the association a store without
  guest checkout should have: an identity EasyStore assigned rather than a value
  typed at checkout;
* it reports ``page_count`` and ``total_count``, so a snapshot is provably
  complete instead of inferred from a ``limit`` that the public route ignores;
* ``is_recovered`` finally distinguishes a converted session from an abandoned
  one. The public payload has no such field, which is why every Cart it produced
  read ``unpaid``.

The two EasyStore API surfaces deliberately use different credentials. Public
``/api/3.0`` requests use ``EASYSTORE_ACCESS_TOKEN``; ``api.easystore.co/admin/v2``
requests use only ``EASYSTORE_ADMIN_TOKEN``. The tokens are never exchanged
between API surfaces.

The admin checkout collection does not include line items, so after the admin
list is read this module reads the public Checkout collection with
``EASYSTORE_ACCESS_TOKEN`` and joins line items onto only the abandoned admin
records whose ``cart_token`` matches. It deliberately does not use the public
Checkout detail route, because that route has rejected tokens returned by the
admin list in production.

When the public collection cannot be read or does not contain a matching token,
the Cart still survives and its existing HubSpot Cart Line Items are preserved.

Only Python's standard library is used.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import easystore_hubspot_carts as cart_mapping
from easystore_hubspot_orders import SyncError, _http_json, _shop_domain
from easystore_hubspot_schema import nonempty


ADMIN_CHECKOUTS_URL = "https://api.easystore.co/admin/v2/store/checkouts"
ADMIN_PAGE_SIZE = 50
ADMIN_SORT = "created_at.desc"
LINE_ITEMS_UNAVAILABLE_KEY = "easystore_line_items_unavailable"
PUBLIC_CHECKOUT_PATH = "/api/3.0/checkouts.json"
PUBLIC_CHECKOUT_LIMIT = 250
PUBLIC_READ_TIMEOUT_SECONDS = 60
PUBLIC_READ_RETRIES = 3

# A backstop, not an expectation: this collection is the abandoned-cart list, so
# 2000 records is already far past anything a store should hold. It exists so a
# server reporting a nonsense page_count cannot spin the job to its timeout.
ADMIN_PAGE_CEILING = 40

# This host answers, unlike the storefront's public route, so patience is not
# the strategy here. A short timeout keeps a dead admin API from delaying the
# fallback to the collection that does answer.
ADMIN_READ_TIMEOUT_SECONDS = 30
ADMIN_READ_RETRIES = 2

# Statuses that mean "this credential is not accepted here", as opposed to a
# transport failure. They rule out one authentication header shape rather than
# the whole route.
UNAUTHORIZED_STATUSES = {401, 403, 404}


class AdminSourceUnavailable(SyncError):
    """Raised when EasyStore's admin checkout list cannot be read at all."""

    def __init__(self, message: str, attempts: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.attempts = tuple(attempts)


@dataclass(frozen=True)
class AdminCheckoutRead:
    """One complete read of the admin abandoned checkout collection."""

    records: tuple[dict[str, Any], ...]
    total_count: int | None
    pages_read: int
    authentication: str
    attempts: tuple[str, ...] = field(default=())

    @property
    def complete(self) -> bool:
        """Report whether the read matched the count EasyStore declared."""

        return self.total_count is None or len(self.records) == self.total_count


def _authentication_schemes(
    access_token: str,
    admin_access_token: str | None,
) -> tuple[tuple[str, dict[str, str]], ...]:
    """Return admin-token header shapes to try.

    ``access_token`` remains in the signature because it is used later for the
    public Checkout collection join, but it is intentionally never put into an
    admin API request header. The admin host only receives
    ``EASYSTORE_ADMIN_TOKEN``.
    """

    del access_token
    token = nonempty(admin_access_token)
    if token is None:
        return ()
    return (
        (
            "admin token as EasyStore-Access-Token",
            {"EasyStore-Access-Token": token},
        ),
        (
            "admin token as Bearer",
            {"Authorization": f"Bearer {token}"},
        ),
    )


def _page_url(page: int, limit: int = ADMIN_PAGE_SIZE) -> str:
    """Return the collection URL for one page, shaped as the admin UI sends it."""

    query = urlencode(
        {
            "page": page,
            "limit": limit,
            "start_date": "",
            "end_date": "",
            "sort": ADMIN_SORT,
        }
    )
    return f"{ADMIN_CHECKOUTS_URL}?{query}"


def _read_page(url: str, headers: dict[str, str]) -> Any:
    """Read one page, returning ``None`` when the credential is not accepted."""

    return _http_json(
        url,
        headers={"Accept": "application/json", **headers},
        retries=ADMIN_READ_RETRIES,
        timeout=ADMIN_READ_TIMEOUT_SECONDS,
        allow_statuses=UNAUTHORIZED_STATUSES,
    )


def _checkouts(document: Any) -> list[dict[str, Any]]:
    """Return the checkout records from an admin response body."""

    if not isinstance(document, dict):
        return []
    data = document.get("data")
    if not isinstance(data, dict):
        return []
    records = data.get("checkouts")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _public_checkouts(document: Any) -> list[dict[str, Any]]:
    """Return Checkout records from the public collection response shapes."""

    if isinstance(document, list):
        return [record for record in document if isinstance(record, dict)]
    if not isinstance(document, dict):
        return []
    for key in ("checkouts", "data", "results"):
        value = document.get(key)
        if isinstance(value, list):
            return [record for record in value if isinstance(record, dict)]
        if isinstance(value, dict):
            nested = value.get("checkouts")
            if isinstance(nested, list):
                return [record for record in nested if isinstance(record, dict)]
    return []


def _public_collection_url(store_domain: str) -> str:
    domain = _shop_domain(store_domain)
    query = urlencode({"page": 1, "limit": PUBLIC_CHECKOUT_LIMIT})
    return f"https://{domain}{PUBLIC_CHECKOUT_PATH}?{query}"


def _join_public_line_items(
    records: list[dict[str, Any]],
    access_token: str,
    attempts: list[str],
) -> list[dict[str, Any]]:
    """Join public Checkout line items to admin abandoned carts by cart_token.

    The admin collection decides membership in the abandoned-cart set. The
    public collection contributes only ``line_items`` to matching tokens, so an
    unrelated public session can never become a HubSpot Cart through this join.
    """

    token = nonempty(access_token)
    store_domain = nonempty(os.getenv("EASYSTORE_STORE_DOMAIN"))
    if token is None or store_domain is None or not records:
        attempts.append(
            "public checkout line join skipped: EASYSTORE_ACCESS_TOKEN or "
            "EASYSTORE_STORE_DOMAIN was unavailable"
        )
        return records

    url = _public_collection_url(store_domain)
    try:
        document = _http_json(
            url,
            headers={"EasyStore-Access-Token": token, "Accept": "application/json"},
            retries=PUBLIC_READ_RETRIES,
            timeout=PUBLIC_READ_TIMEOUT_SECONDS,
        )
    except SyncError as error:
        attempts.append(
            "public checkout line join unavailable: "
            + " ".join(str(error).split())[:200]
        )
        return records

    public_records = _public_checkouts(document)
    by_token: dict[str, list[dict[str, Any]]] = {}
    for public in public_records:
        cart_token = nonempty(public.get("cart_token"))
        if cart_token is not None:
            by_token.setdefault(cart_token, []).append(public)

    joined: list[dict[str, Any]] = []
    matched = 0
    ambiguous = 0
    missing = 0
    for record in records:
        cart_token = nonempty(record.get("cart_token"))
        candidates = by_token.get(cart_token or "", [])
        if len(candidates) != 1:
            if len(candidates) > 1:
                ambiguous += 1
            else:
                missing += 1
            joined.append(record)
            continue

        lines = candidates[0].get("line_items")
        if not isinstance(lines, list):
            missing += 1
            joined.append(record)
            continue

        matched += 1
        joined.append({**record, "line_items": lines})

    attempts.append(
        f"public checkout line join: read {len(public_records)} checkout(s), "
        f"matched {matched} of {len(records)} abandoned cart(s) by cart_token; "
        f"missing={missing}, ambiguous={ambiguous}"
    )
    return joined


def _prefer_easystore_cart_started_property() -> None:
    """Map checkout created_at to the custom EasyStore Cart Started property.

    The default Cart mapping prefers HubSpot's native ``hs_external_created_date``.
    For the authoritative admin checkout source, the store wants ``created_at``
    written to the existing custom ``easystore_cart_created_at`` property whose
    label is "EasyStore Cart Started". The mapping is changed only after the
    admin source has authenticated successfully, so public-fallback runs keep
    their existing native mapping.
    """

    updated = []
    for spec in cart_mapping.CART_FIELDS:
        if spec.key == "created_at":
            updated.append(
                spec._replace(
                    native=(),
                    fallback="easystore_cart_created_at",
                    label="EasyStore Cart Started",
                )
            )
        else:
            updated.append(spec)
    cart_mapping.CART_FIELDS = tuple(updated)


def _params(document: Any) -> dict[str, Any]:
    if isinstance(document, dict) and isinstance(document.get("params"), dict):
        return document["params"]
    return {}


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def read_admin_checkouts(
    access_token: str,
    admin_access_token: str | None = None,
) -> AdminCheckoutRead:
    """Read every abandoned checkout and enrich its lines from the public list."""

    attempts: list[str] = []
    schemes = _authentication_schemes(access_token, admin_access_token)
    if not schemes:
        raise AdminSourceUnavailable(
            "EASYSTORE_ADMIN_TOKEN is required for EasyStore's admin checkout list."
        )

    for label, headers in schemes:
        try:
            first = _read_page(_page_url(1), headers)
        except SyncError as error:
            attempts.append(f"{label}: {' '.join(str(error).split())[:200]}")
            raise AdminSourceUnavailable(
                "EasyStore's admin checkout list did not answer.", tuple(attempts)
            ) from error

        if first is None:
            attempts.append(f"{label}: refused the credential")
            continue

        _prefer_easystore_cart_started_property()
        records = _checkouts(first)
        params = _params(first)
        total_count = _positive_int(params.get("total_count"))
        page_count = _positive_int(params.get("page_count"))
        if not records and not total_count:
            attempts.append(f"{label}: answered with no abandoned checkouts")
            return AdminCheckoutRead(
                records=(),
                total_count=total_count,
                pages_read=1,
                authentication=label,
                attempts=tuple(attempts),
            )

        attempts.append(
            f"{label}: answered {len(records)} of {total_count} checkout(s) "
            f"over {page_count} page(s)"
        )
        collected = list(records)
        seen_pages = {_signature(records)}
        pages_read = 1

        last_page = min(page_count or 1, ADMIN_PAGE_CEILING)
        for page in range(2, last_page + 1):
            document = _read_page(_page_url(page), headers)
            if document is None:
                attempts.append(f"page {page}: refused the credential mid-read")
                break
            page_records = _checkouts(document)
            if not page_records:
                break
            signature = _signature(page_records)
            if signature in seen_pages:
                attempts.append(
                    f"page {page}: repeated records already read, so pagination "
                    "stopped here"
                )
                break
            seen_pages.add(signature)
            collected.extend(page_records)
            pages_read += 1

        collected = _join_public_line_items(collected, access_token, attempts)
        return AdminCheckoutRead(
            records=tuple(collected),
            total_count=total_count,
            pages_read=pages_read,
            authentication=label,
            attempts=tuple(attempts),
        )

    raise AdminSourceUnavailable(
        "EASYSTORE_ADMIN_TOKEN was not accepted by EasyStore's admin checkout list.",
        tuple(attempts),
    )


def _signature(records: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        nonempty(record.get("id")) or nonempty(record.get("cart_token")) or f"row:{index}"
        for index, record in enumerate(records)
    )


def as_checkout(record: dict[str, Any]) -> dict[str, Any]:
    """Return one enriched admin record in the shape the Cart writer reads."""

    customer_id = nonempty(record.get("customer_id"))
    customer: dict[str, Any] = {
        key: record.get(key)
        for key in ("first_name", "last_name", "email", "phone")
        if nonempty(record.get(key)) is not None
    }
    if customer_id is not None:
        customer["id"] = customer_id

    lines = record.get("line_items")
    lines_available = isinstance(lines, list)
    checkout: dict[str, Any] = {
        "id": record.get("id"),
        "cart_token": record.get("cart_token"),
        "created_at": record.get("created_at"),
        "currency_code": record.get("currency"),
        "total_price": record.get("amount"),
        "total_line_items_price": record.get("total_line_items_price"),
        "url": record.get("url"),
        "financial_status": "recovered" if record.get("is_recovered") else "unpaid",
        "line_items": lines if lines_available else [],
    }
    if not lines_available:
        checkout[LINE_ITEMS_UNAVAILABLE_KEY] = True

    for key in (
        "email",
        "phone",
        "landing_site",
        "referring_site",
        "source_name",
        "source_type",
        "channel",
        "client_info",
        "credit_used",
        "credit_earn",
        "is_processed",
        "is_recovered",
    ):
        if record.get(key) is not None:
            checkout[key] = record[key]
    if customer_id is not None:
        checkout["customer_id"] = customer_id
    if customer:
        checkout["customer"] = customer
    return {key: value for key, value in checkout.items() if value is not None}


def as_checkouts(records: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    """Return every admin record the CRM should carry, dropping deleted ones."""

    return tuple(
        as_checkout(record) for record in records if not record.get("is_deleted")
    )


def admin_access_token_from_environment() -> str | None:
    """Return the dedicated admin credential when the store configured one."""

    return nonempty(os.getenv("EASYSTORE_ADMIN_TOKEN"))


def main(argv: list[str] | None = None) -> int:
    """Report what the admin checkout list answers with, and with which credential."""

    admin_access_token = admin_access_token_from_environment()
    if admin_access_token is None:
        print("ERROR: EASYSTORE_ADMIN_TOKEN is required", file=sys.stderr)
        return 1
    access_token = nonempty(os.getenv("EASYSTORE_ACCESS_TOKEN")) or ""

    try:
        read = read_admin_checkouts(access_token, admin_access_token)
    except AdminSourceUnavailable as error:
        print(
            json.dumps(
                {
                    "easystore_admin_checkout_status": "unavailable",
                    "easystore_admin_checkout_error": str(error),
                    "easystore_admin_checkout_attempts": list(error.attempts),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print(
        json.dumps(
            {
                "easystore_admin_checkout_status": "available",
                "easystore_admin_checkout_authentication": read.authentication,
                "easystore_admin_checkouts_read": len(read.records),
                "easystore_admin_checkouts_declared": read.total_count,
                "easystore_admin_checkout_snapshot_complete": read.complete,
                "easystore_admin_checkout_attempts": list(read.attempts),
                "easystore_admin_checkout_keys_seen": sorted(
                    {key for record in read.records for key in record}
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())