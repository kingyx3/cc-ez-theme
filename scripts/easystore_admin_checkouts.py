#!/usr/bin/env python3
"""Read EasyStore's real abandoned checkout list from its admin API.

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

What it does not carry is line items, so those are hydrated per ``cart_token``
from the documented detail route - a bounded cost at this collection size.

Authentication is the open question this module is written to answer rather than
assume. The route was observed from an authenticated admin session, so it may
not accept the app access token the public API uses. Each candidate scheme is
tried in turn and the outcome of each is reported; a route that will not
authenticate is not fatal, it simply leaves the public collection in place.

Only Python's standard library is used.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from easystore_hubspot_orders import SyncError, _http_json
from easystore_hubspot_schema import nonempty


ADMIN_CHECKOUTS_URL = "https://api.easystore.co/admin/v2/store/checkouts"
ADMIN_PAGE_SIZE = 50
ADMIN_SORT = "created_at.desc"

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
# transport failure. They rule out one authentication scheme rather than the
# whole route.
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
    """Return each credential and header shape to try, in order.

    A dedicated admin token is tried first when one is configured, because a
    store that needed one has said so explicitly.
    """

    schemes: list[tuple[str, dict[str, str]]] = []
    for label, token in (("admin token", admin_access_token), ("app token", access_token)):
        if not token:
            continue
        schemes.append((f"{label} as EasyStore-Access-Token", {"EasyStore-Access-Token": token}))
        schemes.append((f"{label} as Bearer", {"Authorization": f"Bearer {token}"}))
    return tuple(schemes)


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
    """Read every abandoned checkout the admin collection serves.

    Raises :class:`AdminSourceUnavailable` naming each credential tried when
    none of them is accepted, which the caller treats as "use the public
    collection" rather than as a failure.
    """

    attempts: list[str] = []
    schemes = _authentication_schemes(access_token, admin_access_token)
    if not schemes:
        raise AdminSourceUnavailable(
            "No EasyStore credential was available for the admin checkout list."
        )

    for label, headers in schemes:
        try:
            first = _read_page(_page_url(1), headers)
        except SyncError as error:
            # A transport failure is about the route, not the credential, so it
            # ends the read rather than moving on to another header shape.
            attempts.append(f"{label}: {' '.join(str(error).split())[:200]}")
            raise AdminSourceUnavailable(
                "EasyStore's admin checkout list did not answer.", tuple(attempts)
            ) from error

        if first is None:
            attempts.append(f"{label}: refused the credential")
            continue

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
                # The public route does exactly this. Stop rather than rewrite
                # the same records for as long as the job is allowed to run.
                attempts.append(
                    f"page {page}: repeated records already read, so pagination "
                    "stopped here"
                )
                break
            seen_pages.add(signature)
            collected.extend(page_records)
            pages_read += 1

        return AdminCheckoutRead(
            records=tuple(collected),
            total_count=total_count,
            pages_read=pages_read,
            authentication=label,
            attempts=tuple(attempts),
        )

    raise AdminSourceUnavailable(
        "No credential was accepted by EasyStore's admin checkout list.",
        tuple(attempts),
    )


def _signature(records: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        nonempty(record.get("id")) or nonempty(record.get("cart_token")) or f"row:{index}"
        for index, record in enumerate(records)
    )


def as_checkout(record: dict[str, Any]) -> dict[str, Any]:
    """Return one admin record in the shape the Cart writer already reads.

    Only renaming and shaping happens here: ``amount`` is the total, ``currency``
    is the currency code, and the shopper's own fields are gathered under
    ``customer`` because that is where the Cart mapping looks for a name. The
    payment state is expressed as ``financial_status`` so the one abandoned-cart
    predicate keeps deciding what is abandoned, rather than this module deciding
    it a second way.
    """

    customer_id = nonempty(record.get("customer_id"))
    customer: dict[str, Any] = {
        key: record.get(key)
        for key in ("first_name", "last_name", "email", "phone")
        if nonempty(record.get(key)) is not None
    }
    if customer_id is not None:
        customer["id"] = customer_id

    checkout: dict[str, Any] = {
        "id": record.get("id"),
        "cart_token": record.get("cart_token"),
        "created_at": record.get("created_at"),
        "currency_code": record.get("currency"),
        "total_price": record.get("amount"),
        "total_line_items_price": record.get("total_line_items_price"),
        "url": record.get("url"),
        "financial_status": "recovered" if record.get("is_recovered") else "unpaid",
    }
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

    return nonempty(os.getenv("EASYSTORE_ADMIN_ACCESS_TOKEN"))


def main(argv: list[str] | None = None) -> int:
    """Report what the admin checkout list answers with, and with which credential."""

    access_token = nonempty(os.getenv("EASYSTORE_ACCESS_TOKEN"))
    if access_token is None:
        print("ERROR: EASYSTORE_ACCESS_TOKEN is required", file=sys.stderr)
        return 1

    try:
        read = read_admin_checkouts(access_token, admin_access_token_from_environment())
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
