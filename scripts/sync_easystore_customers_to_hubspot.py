#!/usr/bin/env python3
"""Sync EasyStore customer data to HubSpot contacts.

Two source modes are supported:
- api: read customers from EasyStore's authenticated Admin API.
- csv: read a customer export locally, requiring no EasyStore app or API token.

The CSV mode is intentionally manual. A fully unattended sync still requires an
EasyStore access token issued through EasyStore app authorization (or an
existing valid token obtained that way).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

EASYSTORE_PAGE_SIZE = 100
HUBSPOT_BATCH_SIZE = 100
MAX_RETRIES = 5
HUBSPOT_UPSERT_URL = "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert"


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def normalize_shop(value: str) -> str:
    parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
        raise RuntimeError("EASYSTORE_SHOP must be an HTTPS shop hostname without a path")
    return parsed.hostname


def request_json(
    url: str,
    *,
    headers: dict[str, str],
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[Any, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response), response.headers
        except urllib.error.HTTPError as error:
            retryable = error.code == 429 or 500 <= error.code < 600
            if not retryable or attempt == MAX_RETRIES - 1:
                detail = error.read().decode("utf-8", errors="replace")[:1000]
                raise RuntimeError(f"{method} {url} failed ({error.code}): {detail}") from error
            retry_after = error.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            time.sleep(delay)
        except urllib.error.URLError as error:
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(f"{method} {url} failed: {error.reason}") from error
            time.sleep(2**attempt)
    raise AssertionError("retry loop exhausted")


def customer_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("customers", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise RuntimeError("Unexpected EasyStore customers response shape")


def easystore_headers(token: str) -> dict[str, str]:
    return {"Accept": "application/json", "EasyStore-Access-Token": token}


def probe_easystore(shop: str, token: str) -> None:
    query = urllib.parse.urlencode({"limit": 1, "page": 1})
    url = f"https://{shop}/api/3.0/customers.json?{query}"
    payload, _ = request_json(url, headers=easystore_headers(token))
    customer_list(payload)


def get_easystore_customers(shop: str, token: str) -> list[dict[str, Any]]:
    customers: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"limit": EASYSTORE_PAGE_SIZE, "page": page})
        url = f"https://{shop}/api/3.0/customers.json?{query}"
        payload, _ = request_json(url, headers=easystore_headers(token))
        batch = customer_list(payload)
        customers.extend(batch)
        if len(batch) < EASYSTORE_PAGE_SIZE:
            break
        page += 1
    return customers


def normalized_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def get_csv_value(row: dict[str, str], *names: str) -> str:
    values = {normalized_key(key): (value or "").strip() for key, value in row.items()}
    for name in names:
        value = values.get(normalized_key(name), "")
        if value:
            return value
    return ""


def get_csv_customers(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"CSV file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise RuntimeError("CSV file has no header row")
        return [
            {
                "email": get_csv_value(row, "Email", "Email Address"),
                "first_name": get_csv_value(row, "First Name", "Firstname"),
                "last_name": get_csv_value(row, "Last Name", "Lastname"),
                "phone": get_csv_value(row, "Phone", "Mobile"),
            }
            for row in reader
        ]


def first_value(customer: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = customer.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def to_hubspot_input(customer: dict[str, Any]) -> dict[str, Any] | None:
    email = first_value(customer, "email").lower()
    if not email:
        return None
    properties = {
        key: value
        for key, value in {
            "email": email,
            "firstname": first_value(customer, "first_name", "firstname"),
            "lastname": first_value(customer, "last_name", "lastname"),
            "phone": first_value(customer, "phone", "mobile"),
        }.items()
        if value
    }
    return {"id": email, "idProperty": "email", "properties": properties}


def chunks(values: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def probe_hubspot(token: str) -> None:
    request_json(
        "https://api.hubapi.com/crm/v3/objects/contacts?limit=1",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
    )


def sync_to_hubspot(
    customers: list[dict[str, Any]], token: str, *, dry_run: bool = False
) -> tuple[int, int]:
    inputs = [item for customer in customers if (item := to_hubspot_input(customer))]
    skipped = len(customers) - len(inputs)
    if dry_run:
        return len(inputs), skipped
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    for batch in chunks(inputs, HUBSPOT_BATCH_SIZE):
        request_json(HUBSPOT_UPSERT_URL, headers=headers, method="POST", payload={"inputs": batch})
    return len(inputs), skipped


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--source", choices=("api", "csv"), default="api")
    result.add_argument("--csv", type=Path, help="EasyStore customer CSV export")
    result.add_argument("--probe", action="store_true", help="Validate credentials only")
    result.add_argument("--dry-run", action="store_true", help="Read and map customers without writing HubSpot")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        hubspot_token = required_env("HUBSPOT_ACCESS_TOKEN")
        if args.probe:
            probe_hubspot(hubspot_token)
            if args.source == "api":
                probe_easystore(
                    normalize_shop(required_env("EASYSTORE_SHOP")),
                    required_env("EASYSTORE_ACCESS_TOKEN"),
                )
            print("Credential probe succeeded.")
            return 0

        if args.source == "api":
            customers = get_easystore_customers(
                normalize_shop(required_env("EASYSTORE_SHOP")),
                required_env("EASYSTORE_ACCESS_TOKEN"),
            )
        else:
            if args.csv is None:
                raise RuntimeError("--csv is required when --source=csv")
            customers = get_csv_customers(args.csv)

        synced, skipped = sync_to_hubspot(customers, hubspot_token, dry_run=args.dry_run)
        action = "would upsert" if args.dry_run else "upserted"
        print(f"Read {len(customers)} customers; {action} {synced}; skipped {skipped} without email.")
        return 0
    except Exception as error:
        print(f"Sync failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
