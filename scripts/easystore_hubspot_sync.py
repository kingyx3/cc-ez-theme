#!/usr/bin/env python3
"""Sync EasyStore customers into HubSpot contacts using normalized mobile numbers.

The normalized mobile number is the identity key. Existing HubSpot contacts are
indexed by both ``mobilephone`` and ``phone`` after applying the same
normalization rules used for EasyStore. A unique match is updated; no match is
created; ambiguous HubSpot matches are left untouched and make the run fail.

Customers with no mobile number recorded are filtered out before any write:
blank, unusable and placeholder values (``0000000`` and friends) all count as
"not recorded", so they are never created or updated as HubSpot contacts.

Having an EasyStore account makes a contact a ``lead``. The order sync promotes
buyers to ``customer`` afterwards, and neither stage is ever written backwards.

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
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from easystore_hubspot_schema import (
    FieldSpec,
    apply_fields,
    date_value,
    describe_mapping,
    field_values,
    first_present,
    observed_keys,
    resolve_fields,
)


HUBSPOT_BASE_URL = "https://api.hubapi.com/crm/v3/objects/contacts"
BATCH_SIZE = 100
EASYSTORE_PAGE_SIZE = 50
PHONE_MIN_DIGITS = 7
PHONE_MAX_DIGITS = 15
LIFECYCLE_PROPERTY = "lifecyclestage"
LIFECYCLE_LEAD = "lead"

# HubSpot refuses to move a contact backwards through the default lifecycle
# pipeline, so a stage is only written when it is a genuine step forward. A stage
# outside this ordering belongs to a custom pipeline and is never overwritten.
# Having an EasyStore account makes a contact a lead; the order sync promotes
# buyers to "customer" afterwards, and that promotion is never undone here.
LIFECYCLE_STAGE_RANKS = {
    "subscriber": 1,
    "lead": 2,
    "marketingqualifiedlead": 3,
    "salesqualifiedlead": 4,
    "opportunity": 5,
    "customer": 6,
    "evangelist": 7,
}

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


CONTACT_OBJECT_TYPE = "contacts"

# EasyStore customer facts that HubSpot's standard contact properties have no
# home for. HubSpot's own equivalents (total_revenue, num_associated_deals) are
# calculated from HubSpot records rather than writable, so these are provisioned
# in the easystore_sync group. The stage is optional: a token without the
# contact schema scopes simply syncs the standard properties.
CONTACT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="customer_id",
        sources=("id", "customer_id"),
        fallback="easystore_customer_id",
        label="EasyStore Customer ID",
        description="Immutable EasyStore customer ID for cross-referencing the store.",
    ),
    FieldSpec(
        key="customer_since",
        sources=("created_at", "created_on", "registered_at"),
        fallback="easystore_customer_since",
        label="EasyStore Customer Since",
        description="Timestamp at which the customer account was created in EasyStore.",
        kind="datetime",
    ),
    FieldSpec(
        key="orders_count",
        sources=("orders_count", "order_count", "total_orders"),
        fallback="easystore_orders_count",
        label="EasyStore Orders",
        description="Number of orders the customer has placed in EasyStore.",
        kind="number",
    ),
    FieldSpec(
        key="total_spent",
        sources=("total_spent", "total_spend", "lifetime_spend"),
        fallback="easystore_total_spent",
        label="EasyStore Total Spent",
        description="Lifetime amount the customer has spent in EasyStore.",
        kind="number",
    ),
    FieldSpec(
        key="last_order_at",
        sources=("last_order_at", "last_order_date", "latest_order_at"),
        fallback="easystore_last_order_at",
        label="EasyStore Last Order",
        description="Timestamp of the customer's most recent EasyStore order.",
        kind="datetime",
    ),
    FieldSpec(
        key="birthday",
        # Read through customer_birthday, which refuses a date that cannot be a
        # birthday and moves on to the next source.
        native=("date_of_birth",),
        fallback="easystore_customer_birthday",
        label="EasyStore Birthday",
        description="Birthday the customer gave EasyStore.",
        kind="date",
    ),
    FieldSpec(
        key="birthday_day",
        # The day and month, which EasyStore reports reliably even when the year
        # it sends is only the next occurrence.
        fallback="easystore_birthday_day",
        label="EasyStore Birthday (day and month)",
        description=(
            "The customer's birthday as MM-DD. EasyStore reports a birthday as "
            "its next occurrence, so the day and month are the trustworthy part."
        ),
    ),
    FieldSpec(
        key="next_birthday",
        fallback="easystore_next_birthday",
        label="EasyStore Next Birthday",
        description="When the customer's birthday next falls.",
        kind="date",
    ),
    FieldSpec(
        key="gender",
        sources=("gender", "sex"),
        native=("gender",),
        fallback="easystore_customer_gender",
        label="EasyStore Gender",
        description="Gender the customer gave EasyStore.",
    ),
    FieldSpec(
        key="tags",
        fallback="easystore_customer_tags",
        label="EasyStore Customer Tags",
        description="Comma separated tags on the EasyStore customer record.",
    ),
    FieldSpec(
        key="note",
        sources=("note", "notes", "remark"),
        fallback="easystore_customer_note",
        label="EasyStore Customer Note",
        description="Note staff left on the EasyStore customer record.",
    ),
)


# Where EasyStore reports the customer attributes a merchant defines themselves,
# e.g. "How did you find us?". Each one becomes its own HubSpot property.
CUSTOM_ATTRIBUTE_SOURCES = (
    "custom_fields",
    "customer_attributes",
    "attributes",
    "note_attributes",
    "metafields",
    "fields",
)
ATTRIBUTE_PROPERTY_PREFIX = "easystore_attr_"
ATTRIBUTE_KEY_PREFIX = "attribute:"
# A storefront can accumulate a long tail of one-off attributes. Provisioning a
# HubSpot property for each without limit would clutter the CRM, so the sync
# takes the first attributes in alphabetical order and names the rest in the log.
ATTRIBUTE_LIMIT = 25
# HubSpot rejects an internal property name longer than 100 characters.
PROPERTY_NAME_LIMIT = 100


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
    if len(set(digits)) == 1:
        # Placeholders such as 0000000 are not a recorded mobile number.
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


def customer_mobile(
    customer: dict[str, Any],
    fallback_dial_code: str = "65",
) -> str | None:
    """Return an EasyStore customer's CRM mobile identity, or ``None``.

    This is the single definition of the contact filter: a customer with no
    usable recorded mobile number is left out of the CRM entirely, because
    mobile is the identity key and such a record can neither be matched to an
    existing HubSpot Contact nor safely created as a new one.
    """

    return normalize_mobile(
        customer.get("phone"),
        customer.get("country_code"),
        fallback_dial_code,
    )


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def lifecycle_stage_write(current: Any, target: str = LIFECYCLE_LEAD) -> str | None:
    """Return the lifecycle stage to write, or ``None`` to leave HubSpot alone.

    A contact keeps the furthest stage it has already reached, so a buyer already
    marked ``customer`` is not demoted back to ``lead`` by a later contact sync,
    and a stage from a custom pipeline is never overwritten.
    """

    existing = _nonempty(current)
    if existing is None:
        return target

    current_rank = LIFECYCLE_STAGE_RANKS.get(existing.casefold())
    if current_rank is None:
        return None
    if current_rank >= LIFECYCLE_STAGE_RANKS[target]:
        return None
    return target


BIRTHDAY_SOURCES = ("birthday", "birth_date", "date_of_birth", "dob")
# The property this sync provisions for a date of birth. It owns that property,
# which is what lets it clear a value an earlier run got wrong.
BIRTHDAY_FALLBACK_PROPERTY = next(
    field.fallback for field in CONTACT_FIELDS if field.key == "birthday"
)


def _utc_today_ms() -> int:
    """Return UTC midnight today, in epoch milliseconds."""

    today = datetime.now(timezone.utc)
    return int(
        datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp()
        * 1000
    )


def _birthday_dates(customer: dict[str, Any]) -> list[tuple[str, date]]:
    """Return each birthday-ish source that parses, as a calendar date."""

    found: list[tuple[str, date]] = []
    for key in BIRTHDAY_SOURCES:
        stamp = date_value(customer.get(key))
        if stamp is None:
            continue
        found.append(
            (key, datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc).date())
        )
    return found


def is_date_of_birth(value: date, today: date | None = None) -> bool:
    """Report whether a date can be a date of birth rather than an occurrence.

    EasyStore reports a customer's birthday as its **next occurrence**, so the
    year says when the birthday next falls, not when the customer was born. Such
    a value is always within the coming twelve months, which is exactly what this
    rules out: a real date of birth is at least a year old, and nobody with a
    storefront account was born this week.
    """

    today = today or datetime.now(timezone.utc).date()
    return value < date(today.year - 1, today.month, today.day)


def customer_birthday(customer: dict[str, Any]) -> str | None:
    """Return a real date of birth, if any source carries one.

    A next-occurrence value is not written here. Inventing a birth year from it
    would put wrong personal data in the CRM, and the day and month it does carry
    are kept by :func:`customer_birthday_day` instead.
    """

    today = datetime.now(timezone.utc).date()
    for _key, value in _birthday_dates(customer):
        if is_date_of_birth(value, today):
            return value.isoformat()
    return None


def customer_birthday_day(customer: dict[str, Any]) -> str | None:
    """Return the day and month of the customer's birthday, as ``MM-DD``.

    This is the part EasyStore actually knows and the part a birthday campaign
    needs. It is the same whether the store reported a date of birth or the next
    occurrence, so it is the one birthday value that is always trustworthy.
    """

    for _key, value in _birthday_dates(customer):
        return f"{value.month:02d}-{value.day:02d}"
    return None


def _next_occurrence(value: date, today: date) -> date:
    """Return the next time a day and month comes round, today included."""

    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, value.month, value.day)
        except ValueError:
            # 29 February in a common year: mark it on the 28th.
            candidate = date(year, value.month, value.day - 1)
        if candidate >= today:
            return candidate
    return today


def customer_next_birthday(customer: dict[str, Any]) -> str | None:
    """Return when the customer's birthday next falls.

    A next-occurrence value from EasyStore is kept as it is, because that is
    exactly what it means. A real date of birth is projected forward to its next
    occurrence, so campaigns can target one property whichever way the store
    reports birthdays.
    """

    today = datetime.now(timezone.utc).date()
    for _key, value in _birthday_dates(customer):
        if not is_date_of_birth(value, today):
            return value.isoformat()
        return _next_occurrence(value, today).isoformat()
    return None


def _mask(text: str) -> str:
    """Return a value's shape with its content removed."""

    return re.sub(r"[0-9]", "#", re.sub(r"[A-Za-z]", "a", text))


def birthday_diagnostics(customer: dict[str, Any]) -> tuple[list[str], list[str], int]:
    """Return the shape and year of each birthday source, and future-date count.

    Reported so a wrong birthday can be diagnosed without putting anyone's date
    of birth in a build log: shapes are masked (``####-##-##``) and years are an
    aggregate distribution.
    """

    shapes: list[str] = []
    years: list[str] = []
    future = 0
    today = _utc_today_ms()

    for key in BIRTHDAY_SOURCES:
        raw = _nonempty(customer.get(key))
        if raw is None:
            continue
        shapes.append(f"{key}={_mask(raw)}")
        stamp = date_value(raw)
        if stamp is None:
            years.append(f"{key}=unparsed")
            continue
        moment = datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc)
        years.append(f"{key}={moment.year}")
        if int(stamp) > today:
            future += 1
    return shapes, years, future


def _customer_tags(customer: dict[str, Any]) -> str | None:
    """Return the customer's tags as one comma separated value."""

    tags = customer.get("tags")
    if isinstance(tags, str):
        candidates: list[Any] = tags.split(",")
    elif isinstance(tags, list):
        candidates = list(tags)
    else:
        candidates = []

    collected: list[str] = []
    for candidate in candidates:
        tag = (
            first_present(candidate, ("name", "title", "tag"))
            if isinstance(candidate, dict)
            else _nonempty(candidate)
        )
        if tag is not None and tag not in collected:
            collected.append(tag)
    return ", ".join(collected) if collected else None


CONTACT_FIELD_DERIVATIONS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "tags": _customer_tags,
    "birthday": customer_birthday,
    "birthday_day": customer_birthday_day,
    "next_birthday": customer_next_birthday,
}


def _attribute_value(value: Any) -> str | None:
    """Return one attribute answer as text, however EasyStore shaped it."""

    if isinstance(value, dict):
        return first_present(value, ("value", "label", "name", "answer"))
    if isinstance(value, list):
        answers = [
            answer
            for answer in (_attribute_value(item) for item in value)
            if answer is not None
        ]
        return ", ".join(dict.fromkeys(answers)) if answers else None
    if isinstance(value, bool):
        return "true" if value else "false"
    return _nonempty(value)


def customer_attributes(customer: dict[str, Any]) -> dict[str, str]:
    """Return the merchant-defined attributes on a customer, keyed by label.

    EasyStore reports these either as a mapping of label to answer or as a list
    of records carrying a label and a value, so both shapes are read.
    """

    collected: dict[str, str] = {}
    for source in CUSTOM_ATTRIBUTE_SOURCES:
        raw = customer.get(source)
        entries: list[tuple[Any, Any]] = []
        if isinstance(raw, dict):
            entries = list(raw.items())
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    label = first_present(
                        item,
                        ("label", "name", "key", "title", "question"),
                    )
                    if label is not None:
                        entries.append((label, item.get("value", item.get("answer"))))
                    continue
                # A bare list is a set of answers rather than labelled fields.
                entries.append((source, item))

        for label, value in entries:
            label_text = _nonempty(label)
            answer = _attribute_value(value)
            if label_text is None or answer is None:
                continue
            collected.setdefault(label_text, answer)
    return collected


def attribute_property_name(label: str) -> str | None:
    """Return the HubSpot property name for an attribute label, or ``None``."""

    slug = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")
    if not slug:
        return None
    return (ATTRIBUTE_PROPERTY_PREFIX + slug)[:PROPERTY_NAME_LIMIT]


def attribute_fields(labels: Iterable[str]) -> tuple[tuple[FieldSpec, ...], list[str]]:
    """Return a FieldSpec per attribute label, plus the labels left out.

    Labels are taken in alphabetical order so a run is deterministic, and two
    labels that would share one property name keep the first.
    """

    fields: list[FieldSpec] = []
    skipped: list[str] = []
    claimed: set[str] = set()

    for label in sorted(set(labels)):
        name = attribute_property_name(label)
        if name is None or name in claimed or len(fields) >= ATTRIBUTE_LIMIT:
            skipped.append(label)
            continue
        claimed.add(name)
        fields.append(
            FieldSpec(
                key=f"{ATTRIBUTE_KEY_PREFIX}{label}",
                fallback=name,
                label=f"EasyStore: {label}",
                description=f"EasyStore customer attribute {label!r}.",
            )
        )
    return tuple(fields), skipped


def customer_field_values(customer: dict[str, Any]) -> dict[str, str]:
    """Return the extra EasyStore customer facts, keyed by field key.

    Merchant-defined attributes are keyed by their label. Only the ones that
    resolved to a HubSpot property are written, so an unmapped attribute is
    simply ignored by :func:`apply_fields`.
    """

    values = field_values(customer, CONTACT_FIELDS, CONTACT_FIELD_DERIVATIONS)
    for label, answer in customer_attributes(customer).items():
        values[f"{ATTRIBUTE_KEY_PREFIX}{label}"] = answer
    return values


def resolve_contact_fields(
    access_token: str,
    attribute_labels: Iterable[str] = (),
    report: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Map the extra customer facts and attributes onto HubSpot properties.

    Provisioning contact properties needs the HubSpot contact schema scopes. They
    are not required to synchronize a contact's standard properties, so a token
    without them logs a warning and the extras are skipped.
    """

    discovered, skipped = attribute_fields(attribute_labels)
    if skipped:
        print(
            f"WARNING: {len(skipped)} EasyStore customer attributes were not "
            "synchronized (attribute limit or duplicate property name): "
            + ", ".join(skipped),
            file=sys.stderr,
        )

    fields = CONTACT_FIELDS + discovered
    resolved = resolve_fields(
        http_json=_http_json,
        access_token=access_token,
        object_type=CONTACT_OBJECT_TYPE,
        fields=fields,
        error=SyncError,
        optional=True,
        report=report,
    )
    if len(resolved) < len(fields):
        missing = sorted(field.key for field in fields if field.key not in resolved)
        print(
            "WARNING: EasyStore customer fields not synchronized because HubSpot "
            "did not provide a writable property (add crm.schemas.contacts.read "
            "and crm.schemas.contacts.write to the token to enable them): "
            + ", ".join(missing),
            file=sys.stderr,
        )
    return resolved


def customer_properties(
    customer: dict[str, Any],
    mobile: str,
    field_properties: dict[str, str] | None = None,
) -> dict[str, str]:
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

    if field_properties:
        apply_fields(properties, customer_field_values(customer), field_properties)

    return properties


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: Any = None,
    retries: int = 4,
    allow_statuses: set[int] | None = None,
) -> Any:
    """Issue an HTTP request and decode JSON, retrying throttling/server errors.

    ``allow_statuses`` turns the listed HTTP statuses into a ``None`` result
    instead of an error, which lets optional schema work degrade quietly.
    """

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
            if allow_statuses and error.code in allow_statuses:
                error.read()
                return None

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
            "properties": f"email,phone,mobilephone,{LIFECYCLE_PROPERTY}",
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
) -> dict[str, Any]:
    """Perform one complete EasyStore -> HubSpot customer sync."""

    hubspot_phone_ids: dict[str, set[str]] = defaultdict(set)
    hubspot_email_ids: dict[str, set[str]] = defaultdict(set)
    hubspot_lifecycle: dict[str, str] = {}
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

        stage = _nonempty(properties.get(LIFECYCLE_PROPERTY))
        if stage is not None:
            hubspot_lifecycle[contact_id] = stage

    easystore_by_phone: dict[str, dict[str, Any]] = {}
    customer_keys: set[str] = set()
    address_keys: set[str] = set()
    # A birthday that came out wrong is diagnosed from these: the shape of the
    # value EasyStore sent, with its digits masked, and the year it parses to.
    birthday_shapes: Counter[str] = Counter()
    birthday_years: Counter[str] = Counter()
    birthdays_in_future = 0
    easystore_total = 0
    skipped_without_phone = 0
    duplicate_easystore_phones = 0

    for customer in iter_easystore_customers(store_domain, easystore_access_token):
        easystore_total += 1
        # Names only, never values: enough to trace a zero in the coverage block
        # back to the real EasyStore field name.
        observed_keys(customer_keys, customer)
        observed_keys(address_keys, customer.get("primary_address"))
        shapes, years, future = birthday_diagnostics(customer)
        birthday_shapes.update(shapes)
        birthday_years.update(years)
        birthdays_in_future += future
        normalized = customer_mobile(customer, fallback_dial_code)
        if normalized is None:
            # Filtered out: no mobile number recorded, so no CRM identity.
            skipped_without_phone += 1
            continue
        if normalized in easystore_by_phone:
            duplicate_easystore_phones += 1
        easystore_by_phone[normalized] = choose_customer(
            easystore_by_phone.get(normalized),
            customer,
        )

    # Which merchant-defined attributes exist is a property of the data, not of
    # this script, so the HubSpot properties are resolved once the customers that
    # will actually be written are known.
    attribute_labels = {
        label
        for customer in easystore_by_phone.values()
        for label in customer_attributes(customer)
    }
    schema_report: dict[str, Any] = {}
    contact_field_properties = resolve_contact_fields(
        hubspot_access_token,
        attribute_labels,
        schema_report,
    )
    print(
        "EasyStore customer fields mapped to HubSpot properties: "
        + describe_mapping(contact_field_properties),
        file=sys.stderr,
    )

    creates: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    ambiguous_hubspot_phones = 0
    email_conflicts = 0
    lifecycle_assignments = 0
    birthdays_cleared = 0
    # How many synchronized customers actually carried each extra fact. A zero
    # means EasyStore did not report it, not that HubSpot rejected it.
    field_coverage: dict[str, int] = {field.key: 0 for field in CONTACT_FIELDS}

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

        properties = customer_properties(customer, mobile, contact_field_properties)
        for key in customer_field_values(customer):
            field_coverage[key] = field_coverage.get(key, 0) + 1
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

        # An EasyStore account is a lead. Contacts that already sit further along
        # the pipeline, e.g. buyers promoted to "customer" by the order sync,
        # keep the stage they reached.
        stage = lifecycle_stage_write(
            hubspot_lifecycle.get(target_id) if target_id is not None else None,
            LIFECYCLE_LEAD,
        )
        if stage is not None:
            properties[LIFECYCLE_PROPERTY] = stage
            lifecycle_assignments += 1

        birthday_property = contact_field_properties.get("birthday")
        if (
            target_id is not None
            and birthday_property == BIRTHDAY_FALLBACK_PROPERTY
            and birthday_property not in properties
        ):
            # This sync provisioned easystore_customer_birthday and owns it.
            # Earlier runs wrote EasyStore's next-occurrence date into it, so
            # clearing it when no date of birth is reported repairs those
            # contacts rather than leaving a birthday in 2027 behind. A portal
            # whose native date_of_birth was resolved instead is never cleared:
            # that property belongs to the portal, not to this sync.
            properties[birthday_property] = ""
            birthdays_cleared += 1

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
        "lifecycle_stage_leads_assigned": lifecycle_assignments,
        "hubspot_contact_field_properties": dict(
            sorted(contact_field_properties.items())
        ),
        "easystore_customer_attributes_found": len(attribute_labels),
        "easystore_birthday_shapes": dict(sorted(birthday_shapes.items())),
        "easystore_birthday_years": dict(sorted(birthday_years.items())),
        "birthdays_in_future_ignored": birthdays_in_future,
        "birthday_property_cleared": birthdays_cleared,
        "easystore_customer_keys_seen": sorted(customer_keys),
        "easystore_customer_address_keys_seen": sorted(address_keys),
        "hubspot_contact_property_hints": schema_report.get("hints", {}),
        "easystore_customer_field_coverage": dict(sorted(field_coverage.items())),
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
