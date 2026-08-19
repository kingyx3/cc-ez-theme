#!/usr/bin/env python3
"""Sync EasyStore customers into HubSpot contacts using normalized mobile numbers.

The normalized mobile number is the identity key. Existing HubSpot contacts are
indexed by both ``mobilephone`` and ``phone`` after applying the same
normalization rules used for EasyStore. A unique match is updated; no match is
created; ambiguous HubSpot matches are left untouched and make the run fail.

Only Python's standard library is used so the scheduled workflow has no runtime
package dependency.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from typing import Any, Iterable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


HUBSPOT_BASE_URL = "https://api.hubapi.com/crm/v3/objects/contacts"
BATCH_SIZE = 100
EASYSTORE_PAGE_SIZE = 50
PHONE_MIN_DIGITS = 7
PHONE_MAX_DIGITS = 15

# Enough coverage for the store's common APAC customer base plus the markets
# most often seen in the CRM. International numbers that already carry a
# country code do not depend on this table.
COUNTRY_DIAL_CODES = {
    "AU": "61",
    "CA": "1",
    "CN": "86",
    "GB": "44",
    "HK": "852",
    "ID": "62",
    "IN": "91",
    "JP": "81",
    "KR": "82",
    "MY": "60",
    "NZ": "64",
    "PH": "63",
    "SG": "65",
    "TH": "66",
    "TW": "886",
    "US": "1",
    "VN": "84",
}


class SyncError(RuntimeError):
    """Raised when a remote API or identity invariant prevents a safe sync."""


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_mobile(
    value: Any,
    country_code: Any = None,
    fallback_dial_code: str = "65",
) -> str | None:
    """Return a conservative E.164-style number or ``None`` when unusable.

    EasyStore commonly returns phone numbers without a leading ``+``. If the
    customer's ISO country is known, its calling code is applied. Otherwise the
    workflow's configured fallback calling code is used (Singapore, ``65``, by
    default). Numbers beginning with ``+`` or ``00`` are treated as already
    international.
    """

    raw = str(value or "").strip()
    if not raw:
        return None

    digits = _digits(raw)
    if not digits:
        return None

    if raw.startswith("+"):
        international = digits
    elif raw.startswith("00"):
        international = digits[2:]
    else:
        iso = str(country_code or "").strip().upper()
        dial_code = COUNTRY_DIAL_CODES.get(iso) or _digits(fallback_dial_code)
        if not dial_code:
            return None

        # EasyStore often stores international values without the plus sign,
        # e.g. 6011... for a Malaysian customer. Do not prepend the calling code
        # a second time when it is already present.
        if digits.startswith(dial_code):
            international = digits
        else:
            local = digits[1:] if digits.startswith("0") else digits
            international = dial_code + local

    if not (PHONE_MIN_DIGITS <= len(international) <= PHONE_MAX_DIGITS):
        return None
    if international.startswith("0"):
        return None
    return f"+{international}"


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def customer_properties(customer: dict[str, Any], mobile: str) -> dict[str, str]:
    """Map an EasyStore customer onto HubSpot's standard contact properties."""

    properties: dict[str, str] = {
        "phone": mobile,
        "mobilephone": mobile,
    }

    direct = {
        "first_name": "firstname",
        "last_name": "lastname",
        "email": "email",
    }
    for source, target in direct.items():
        value = _nonempty(customer.get(source))
        if value is not None:
            properties[target] = value

    address = customer.get("primary_address")
    if not isinstance(address, dict):
        address = {}

    address1 = _nonempty(address.get("address1"))
    address2 = _nonempty(address.get("address2"))
    if address1 and address2:
        properties["address"] = f"{address1}\n{address2}"
    elif address1 or address2:
        properties["address"] = address1 or address2 or ""

    mapped_address = {
        "city": "city",
        "province": "state",
        "zip": "zip",
        "country": "country",
        "company": "company",
    }
    for source, target in mapped_address.items():
        value = _nonempty(address.get(source))
        if value is not None:
            properties[target] = value

    if "country" not in properties:
        country = _nonempty(customer.get("country"))
        if country is not None:
            properties["country"] = country

    return properties


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: Any = None,
    retries: int = 4,
) -> Any:
    """Issue an HTTP request and decode JSON, retrying throttling/server errors."""

    body = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "cc-ez-theme-customer-sync/1.0",
    }
    if headers:
        request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    for attempt in range(retries + 1):
        request = Request(url, data=body, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            raw_error = error.read().decode("utf-8", errors="replace")
            retryable = error.code == 429 or 500 <= error.code < 600
            if retryable and attempt < retries:
                retry_after = error.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 2**attempt
                except ValueError:
                    delay = 2**attempt
                time.sleep(min(max(delay, 1.0), 30.0))
                continue
            raise SyncError(
                f"{method} {url} failed with HTTP {error.code}: {raw_error[:1000]}"
            ) from error
        except (URLError, TimeoutError) as error:
            if attempt < retries:
                time.sleep(min(2**attempt, 30))
                continue
            raise SyncError(f"{method} {url} failed: {error}") from error
        except json.JSONDecodeError as error:
            raise SyncError(f"{method} {url} returned invalid JSON") from error

    raise AssertionError("unreachable")


def _extract_easystore_customers(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, list):
        return [item for item in document if isinstance(item, dict)]
    if not isinstance(document, dict):
        return []

    for key in ("customers", "data", "results"):
        value = document.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = value.get("customers")
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def iter_easystore_customers(
    store_domain: str,
    access_token: str,
) -> Iterator[dict[str, Any]]:
    """Yield every EasyStore customer through the documented API pagination."""

    domain = store_domain.strip().removeprefix("https://").removeprefix("http://")
    domain = domain.rstrip("/")
    page = 1

    while True:
        query = urlencode(
            {
                "page": page,
                "limit": EASYSTORE_PAGE_SIZE,
                "sort": "id.asc",
            }
        )
        url = f"https://{domain}/api/3.0/customers.json?{query}"
        document = _http_json(
            url,
            headers={"EasyStore-Access-Token": access_token},
        )
        customers = _extract_easystore_customers(document)
        for customer in customers:
            yield customer

        if len(customers) < EASYSTORE_PAGE_SIZE:
            break
        page += 1


def iter_hubspot_contacts(access_token: str) -> Iterator[dict[str, Any]]:
    """Yield HubSpot contacts with the fields needed to build identity indexes."""

    after: str | None = None
    while True:
        params = {
            "limit": "100",
            "properties": "email,phone,mobilephone",
            "archived": "false",
        }
        if after is not None:
            params["after"] = after
        document = _http_json(
            f"{HUBSPOT_BASE_URL}?{urlencode(params)}",
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


def choose_customer(
    current: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Choose the most recent EasyStore record when a phone is duplicated."""

    if current is None:
        return candidate

    def rank(customer: dict[str, Any]) -> tuple[str, int]:
        updated = str(customer.get("updated_at") or customer.get("created_at") or "")
        try:
            identifier = int(customer.get("id") or 0)
        except (TypeError, ValueError):
            identifier = 0
        return updated, identifier

    return candidate if rank(candidate) >= rank(current) else current


def chunked(items: list[Any], size: int = BATCH_SIZE) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def assert_batch_success(
    document: Any,
    *,
    action: str,
    expected_count: int,
) -> None:
    """Reject HubSpot batch responses that contain partial or pending failures."""

    if not isinstance(document, dict):
        raise SyncError(f"HubSpot contact batch {action} returned an invalid response")

    errors = document.get("errors")
    try:
        num_errors = int(document.get("numErrors") or 0)
    except (TypeError, ValueError):
        num_errors = 1

    if num_errors or (isinstance(errors, list) and errors):
        detail = json.dumps(errors[:3], ensure_ascii=False) if isinstance(errors, list) else repr(errors)
        raise SyncError(
            f"HubSpot contact batch {action} reported {num_errors or 'one or more'} "
            f"item errors: {detail[:1500]}"
        )

    status = str(document.get("status") or "").upper()
    if status and status != "COMPLETE":
        raise SyncError(
            f"HubSpot contact batch {action} did not complete synchronously: {status}"
        )

    results = document.get("results")
    if not isinstance(results, list) or len(results) != expected_count:
        actual = len(results) if isinstance(results, list) else "missing"
        raise SyncError(
            f"HubSpot contact batch {action} returned {actual} results for "
            f"{expected_count} inputs"
        )


def _batch_write(
    access_token: str,
    action: str,
    inputs: list[dict[str, Any]],
) -> None:
    if not inputs:
        return
    headers = {"Authorization": f"Bearer {access_token}"}
    for batch_number, batch in enumerate(chunked(inputs), start=1):
        traced: list[dict[str, Any]] = []
        for item_number, item in enumerate(batch, start=1):
            traced_item = dict(item)
            traced_item["objectWriteTraceId"] = (
                f"contacts-{action}-{batch_number}-{item_number}"
            )
            traced.append(traced_item)

        response = _http_json(
            f"{HUBSPOT_BASE_URL}/batch/{action}",
            method="POST",
            headers=headers,
            payload={"inputs": traced},
        )
        assert_batch_success(
            response,
            action=action,
            expected_count=len(traced),
        )


def sync(
    *,
    store_domain: str,
    easystore_access_token: str,
    hubspot_access_token: str,
    fallback_dial_code: str,
) -> dict[str, int]:
    """Perform one complete EasyStore -> HubSpot customer sync."""

    hubspot_phone_ids: dict[str, set[str]] = defaultdict(set)
    hubspot_email_ids: dict[str, set[str]] = defaultdict(set)
    hubspot_contacts = 0

    for contact in iter_hubspot_contacts(hubspot_access_token):
        hubspot_contacts += 1
        contact_id = _nonempty(contact.get("id"))
        properties = contact.get("properties")
        if contact_id is None or not isinstance(properties, dict):
            continue

        for field in ("mobilephone", "phone"):
            normalized = normalize_mobile(
                properties.get(field),
                fallback_dial_code=fallback_dial_code,
            )
            if normalized:
                hubspot_phone_ids[normalized].add(contact_id)

        email = _nonempty(properties.get("email"))
        if email:
            hubspot_email_ids[email.casefold()].add(contact_id)

    easystore_by_phone: dict[str, dict[str, Any]] = {}
    easystore_total = 0
    skipped_without_phone = 0
    duplicate_easystore_phones = 0

    for customer in iter_easystore_customers(store_domain, easystore_access_token):
        easystore_total += 1
        normalized = normalize_mobile(
            customer.get("phone"),
            customer.get("country_code"),
            fallback_dial_code,
        )
        if normalized is None:
            skipped_without_phone += 1
            continue
        if normalized in easystore_by_phone:
            duplicate_easystore_phones += 1
        easystore_by_phone[normalized] = choose_customer(
            easystore_by_phone.get(normalized),
            customer,
        )

    creates: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    ambiguous_hubspot_phones = 0
    email_conflicts = 0

    for mobile, customer in easystore_by_phone.items():
        matching_ids = hubspot_phone_ids.get(mobile, set())
        if len(matching_ids) > 1:
            ambiguous_hubspot_phones += 1
            print(
                f"ERROR: {mobile} matches multiple HubSpot contacts: "
                + ", ".join(sorted(matching_ids)),
                file=sys.stderr,
            )
            continue

        properties = customer_properties(customer, mobile)
        email = properties.get("email")
        target_id = next(iter(matching_ids), None)

        # Email remains data, never identity. If HubSpot already owns that email
        # on a different contact, leave it unchanged so a phone-based sync does
        # not accidentally merge or fail on HubSpot's email uniqueness rule.
        if email:
            email_ids = hubspot_email_ids.get(email.casefold(), set())
            if email_ids and (target_id is None or email_ids != {target_id}):
                email_conflicts += 1
                properties.pop("email", None)
                print(
                    f"WARNING: not writing email {email!r} for {mobile}; "
                    "it belongs to a different HubSpot contact.",
                    file=sys.stderr,
                )

        if target_id is None:
            creates.append({"properties": properties})
        else:
            updates.append({"id": target_id, "properties": properties})

    _batch_write(hubspot_access_token, "update", updates)
    _batch_write(hubspot_access_token, "create", creates)

    summary = {
        "easystore_customers": easystore_total,
        "unique_mobile_customers": len(easystore_by_phone),
        "hubspot_contacts_scanned": hubspot_contacts,
        "updated": len(updates),
        "created": len(creates),
        "skipped_without_mobile": skipped_without_phone,
        "duplicate_easystore_mobile_records": duplicate_easystore_phones,
        "ambiguous_hubspot_mobile_numbers": ambiguous_hubspot_phones,
        "email_conflicts_omitted": email_conflicts,
    }
    return summary


def _required(value: str | None, name: str) -> str:
    if value and value.strip():
        return value.strip()
    raise SyncError(f"{name} is required")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store-domain",
        default=os.getenv("EASYSTORE_STORE_DOMAIN"),
        help="EasyStore shop domain, e.g. cardboardcollective.easy.co",
    )
    parser.add_argument(
        "--easystore-token",
        default=os.getenv("EASYSTORE_ACCESS_TOKEN"),
        help="EasyStore Public API token with read_customers scope",
    )
    parser.add_argument(
        "--hubspot-token",
        default=os.getenv("HUBSPOT_ACCESS_TOKEN"),
        help="HubSpot token with crm.objects.contacts.read/write",
    )
    parser.add_argument(
        "--fallback-dial-code",
        default=os.getenv("CUSTOMER_SYNC_DEFAULT_DIAL_CODE", "65"),
        help="Calling code used when EasyStore has no usable customer country code",
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
            fallback_dial_code=_required(
                args.fallback_dial_code,
                "CUSTOMER_SYNC_DEFAULT_DIAL_CODE",
            ),
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, sort_keys=True))

    # Ambiguous CRM phone ownership is unsafe to resolve automatically. Other
    # skips are data-quality warnings and should not stop future scheduled runs.
    return 1 if summary["ambiguous_hubspot_mobile_numbers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
