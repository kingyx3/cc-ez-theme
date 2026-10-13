#!/usr/bin/env python3
"""Resolve EasyStore facts onto writable HubSpot properties.

The resolver is deliberately native-first. A declared HubSpot property wins when
it exists, is writable, and has the same storage type. If a declared name is not
present, a custom fallback is avoided when the live portal exposes exactly one
HubSpot-defined property with the same semantic words and storage type. Only
then, when no lossless native destination can be identified, is the deterministic
``easystore_*`` fallback provisioned.

Enumeration properties are never treated as a string destination: forcing a
storefront's free-form text into a closed HubSpot option set is data loss (or a
rejected write), not a native mapping.
"""

from __future__ import annotations

import re
import warnings
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, NamedTuple


HUBSPOT_BASE = "https://api.hubapi.com"
PROPERTY_GROUP = "easystore_sync"
PROPERTY_GROUP_LABEL = "EasyStore Sync"

PROPERTY_FIELD_TYPES = {
    "string": "text",
    "number": "number",
    "date": "date",
    "datetime": "date",
}

_MONEY_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
_COMPACT_DATE_PATTERN = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_GENERIC_TOKENS = {"amount", "at", "of", "the", "value"}
_HINT_LIMIT = 8
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# Conservative equivalents used only while looking for a HubSpot-defined native
# property. Every non-generic word in a field key still has to match, and the
# candidate must be unique and have the exact same HubSpot storage type.
_SEMANTIC_ALIASES: dict[str, tuple[str, ...]] = {
    "cancel": ("cancel",),
    "cancelled": ("cancel",),
    "canceled": ("cancel",),
    "cancellation": ("cancel",),
    "fulfilled": ("fulfill", "fulfil"),
    "fulfillment": ("fulfill", "fulfil"),
    "fulfilment": ("fulfill", "fulfil"),
    "paid": ("paid", "payment"),
    "refund": ("refund",),
    "refunded": ("refund",),
    "buyer": ("buyer", "customer"),
    "codes": ("code", "codes"),
    "tags": ("tag", "tags"),
}


class FieldSpec(NamedTuple):
    """One EasyStore fact and the HubSpot property it should land in."""

    key: str
    sources: tuple[str, ...] = ()
    native: tuple[str, ...] = ()
    fallback: str | None = None
    label: str = ""
    description: str = ""
    kind: str = "string"
    absolute: bool = False
    field_type: str | None = None


def nonempty(value: Any) -> str | None:
    if value is None or isinstance(value, (list, tuple, set, dict)):
        return None
    text = str(value).strip()
    return text or None


def note_text(value: Any) -> str | None:
    if isinstance(value, dict):
        return first_present(value, ("note", "body", "content", "text", "message", "value"))
    if isinstance(value, (list, tuple)):
        notes = [found for found in (note_text(item) for item in value) if found is not None]
        return "\n".join(dict.fromkeys(notes)) if notes else None
    return nonempty(value)


def first_present(record: Any, keys: Iterable[str]) -> str | None:
    if not isinstance(record, dict):
        return None
    for key in keys:
        value = nonempty(record.get(key))
        if value is not None:
            return value
    return None


def money_value(value: Any, *, absolute: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = _MONEY_PATTERN.search(text)
    if match is None:
        return None
    try:
        amount = Decimal(match.group(0))
    except InvalidOperation:
        return None
    if absolute:
        amount = amount.copy_abs()
    return str(amount)


def iso_datetime(value: Any) -> datetime | None:
    text = nonempty(value)
    if text is None:
        return None
    candidate = text[:-1] + "+00:00" if text[-1:] in {"Z", "z"} else text
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def timestamp_value(value: Any) -> str | None:
    text = nonempty(value)
    if text is None:
        return None
    if text.isdigit():
        epoch = int(text)
        return str(epoch * 1000 if len(text) <= 10 else epoch)
    moment = iso_datetime(text)
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return str(int(moment.timestamp() * 1000))


def _utc_midnight(year: int, month: int, day: int) -> str | None:
    try:
        moment = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None
    return str(int(moment.timestamp() * 1000))


def date_value(value: Any) -> str | None:
    text = nonempty(value)
    if text is None:
        return None

    compact = _COMPACT_DATE_PATTERN.match(text)
    if compact is not None:
        year, month, day = (int(part) for part in compact.groups())
        if 1900 <= year <= 2100:
            return _utc_midnight(year, month, day)

    written = iso_datetime(text)
    if written is not None:
        return _utc_midnight(written.year, written.month, written.day)

    stamp = timestamp_value(text)
    if stamp is None:
        return None
    moment = datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc)
    return _utc_midnight(moment.year, moment.month, moment.day)


def field_value(
    record: dict[str, Any],
    field: FieldSpec,
    derivations: dict[str, Callable[[dict[str, Any]], str | None]] | None = None,
) -> str | None:
    derive = (derivations or {}).get(field.key)
    raw = derive(record) if derive is not None else first_present(record, field.sources)
    if raw is None:
        return None
    if field.kind == "number":
        return money_value(raw, absolute=field.absolute)
    if field.kind == "datetime":
        return timestamp_value(raw)
    if field.kind == "date":
        return date_value(raw)
    return raw


def field_values(
    record: dict[str, Any],
    fields: Iterable[FieldSpec],
    derivations: dict[str, Callable[[dict[str, Any]], str | None]] | None = None,
) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in fields:
        value = field_value(record, field, derivations)
        if value is not None:
            values[field.key] = value
    return values


def apply_fields(
    properties: dict[str, str],
    values: dict[str, str],
    field_properties: dict[str, str],
) -> dict[str, str]:
    for key, value in values.items():
        target = field_properties.get(key)
        if target is not None:
            properties[target] = value
    return properties


def writable_property(prop: Any, kind: str) -> bool:
    if not isinstance(prop, dict):
        return False
    if bool(prop.get("calculated")) or bool(prop.get("archived")):
        return False
    metadata = prop.get("modificationMetadata")
    if isinstance(metadata, dict) and bool(metadata.get("readOnlyValue")):
        return False
    return str(prop.get("type") or "") == kind


def select_native(field: FieldSpec, schema: dict[str, dict[str, Any]]) -> str | None:
    for name in field.native:
        if writable_property(schema.get(name), field.kind):
            return name
    return None


def _semantic_groups(field: FieldSpec) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    for token in sorted(field_keywords(field)):
        groups.append(_SEMANTIC_ALIASES.get(token, (token,)))
    return tuple(groups)


def _property_tokens(name: str, prop: dict[str, Any]) -> set[str]:
    text = f"{name} {prop.get('label') or ''}".casefold()
    return set(_TOKEN_PATTERN.findall(text))


def _group_matches(group: tuple[str, ...], tokens: set[str]) -> bool:
    return any(
        token == term or token.startswith(term)
        for term in group
        for token in tokens
    )


def semantic_native_candidates(
    field: FieldSpec,
    schema: dict[str, dict[str, Any]],
) -> list[str]:
    """Return lossless HubSpot-defined properties that semantically fit a field.

    This is intentionally stricter than the diagnostic hint search. A candidate
    must be HubSpot-defined, writable, exactly the same storage type, and match
    every meaningful word in the field key. The caller only uses a candidate
    when exactly one survives, so ambiguity always falls back to a dedicated
    EasyStore property instead of guessing.
    """

    groups = _semantic_groups(field)
    if not groups:
        return []

    candidates: list[str] = []
    for name in sorted(schema):
        prop = schema[name]
        if not bool(prop.get("hubspotDefined")):
            continue
        if not writable_property(prop, field.kind):
            continue
        tokens = _property_tokens(name, prop)
        if all(_group_matches(group, tokens) for group in groups):
            candidates.append(name)
    return candidates


def select_semantic_native(
    field: FieldSpec,
    schema: dict[str, dict[str, Any]],
) -> str | None:
    candidates = semantic_native_candidates(field, schema)
    return candidates[0] if len(candidates) == 1 else None


def describe_property(name: str, prop: dict[str, Any]) -> str:
    kind = str(prop.get("type") or "?")
    notes = []
    if bool(prop.get("calculated")):
        notes.append("calculated")
    metadata = prop.get("modificationMetadata")
    if isinstance(metadata, dict) and bool(metadata.get("readOnlyValue")):
        notes.append("read-only")
    return f"{name}:{kind}" + (f"[{','.join(notes)}]" if notes else "")


def field_keywords(field: FieldSpec) -> set[str]:
    tokens = {token for token in field.key.casefold().split("_") if token}
    return {token for token in tokens if token not in _GENERIC_TOKENS} or tokens


def matching_properties(
    schema: dict[str, dict[str, Any]],
    keywords: Iterable[str],
    *,
    limit: int = _HINT_LIMIT,
) -> list[str]:
    wanted = {keyword.casefold() for keyword in keywords}
    found: list[str] = []
    for name in sorted(schema):
        if name.startswith(PROPERTY_GROUP.split("_")[0] + "_"):
            continue
        prop = schema[name]
        haystack = f"{name} {prop.get('label') or ''}".casefold()
        if any(keyword in haystack for keyword in wanted):
            found.append(describe_property(name, prop))
        if len(found) >= limit:
            break
    return found


def property_schema(
    *,
    http_json: Callable[..., Any],
    access_token: str,
    object_type: str,
    error: type[Exception],
    optional: bool = False,
) -> dict[str, dict[str, Any]] | None:
    document = http_json(
        f"{HUBSPOT_BASE}/crm/v3/properties/{object_type}",
        headers={"Authorization": f"Bearer {access_token}"},
        allow_statuses={403} if optional else None,
    )
    if document is None and optional:
        return None

    results = document.get("results") if isinstance(document, dict) else None
    if not isinstance(results, list):
        raise error(f"HubSpot did not return the {object_type} property schema")

    schema: dict[str, dict[str, Any]] = {}
    for prop in results:
        if not isinstance(prop, dict):
            continue
        name = nonempty(prop.get("name"))
        if name is not None:
            schema[name] = prop
    return schema


def ensure_property_group(
    *,
    http_json: Callable[..., Any],
    access_token: str,
    object_type: str,
    optional: bool = False,
    group: str = PROPERTY_GROUP,
    group_label: str = PROPERTY_GROUP_LABEL,
) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}
    allowed = {404, 403} if optional else {404}
    existing = http_json(
        f"{HUBSPOT_BASE}/crm/v3/properties/{object_type}/groups/{group}",
        headers=headers,
        allow_statuses=allowed,
    )
    if existing is None:
        http_json(
            f"{HUBSPOT_BASE}/crm/v3/properties/{object_type}/groups",
            method="POST",
            headers=headers,
            payload={
                "name": group,
                "label": group_label,
                "displayOrder": -1,
            },
            allow_statuses={403} if optional else None,
        )


def resolve_fields(
    *,
    http_json: Callable[..., Any],
    access_token: str,
    object_type: str,
    fields: Iterable[FieldSpec],
    error: type[Exception],
    optional: bool = False,
    report: dict[str, Any] | None = None,
    group: str = PROPERTY_GROUP,
    group_label: str = PROPERTY_GROUP_LABEL,
) -> dict[str, str]:
    """Map field keys onto lossless native properties, then custom fallbacks."""

    fields = tuple(fields)
    schema = property_schema(
        http_json=http_json,
        access_token=access_token,
        object_type=object_type,
        error=error,
        optional=optional,
    )
    if schema is None:
        return {}

    if report is not None:
        report["inventory"] = [
            describe_property(name, schema[name]) for name in sorted(schema)
        ]
        report["semantic_native"] = {}

    resolved: dict[str, str] = {}
    missing: list[FieldSpec] = []
    unresolved: list[FieldSpec] = []

    for field in fields:
        native = select_native(field, schema)
        # cc_* properties are integration-owned attribution snapshots. They must
        # not be silently redirected into a semantically similar HubSpot-native
        # property such as hs_source_store, whose commerce meaning is different.
        if (
            native is None
            and field.fallback is not None
            and not field.fallback.startswith("cc_")
        ):
            native = select_semantic_native(field, schema)
            if native is not None and report is not None:
                report["semantic_native"][field.key] = native

        if native is not None:
            resolved[field.key] = native
            continue

        unresolved.append(field)
        if field.fallback is None:
            continue

        existing = schema.get(field.fallback)
        if isinstance(existing, dict):
            if not writable_property(existing, field.kind):
                raise error(
                    f"HubSpot {object_type} property {field.fallback!r} exists but "
                    f"cannot accept a writable {field.kind} value. Archive or "
                    "replace it before running the sync."
                )
            resolved[field.key] = field.fallback
            continue

        missing.append(field)

    if missing:
        ensure_property_group(
            http_json=http_json,
            access_token=access_token,
            object_type=object_type,
            optional=optional,
            group=group,
            group_label=group_label,
        )

    if report is not None:
        report["hints"] = {
            field.key: hints
            for field in unresolved
            if (hints := matching_properties(schema, field_keywords(field)))
        }

    for field in missing:
        created = http_json(
            f"{HUBSPOT_BASE}/crm/v3/properties/{object_type}",
            method="POST",
            headers={"Authorization": f"Bearer {access_token}"},
            payload={
                "groupName": group,
                "name": field.fallback,
                "label": field.label,
                "description": field.description,
                "type": field.kind,
                "fieldType": field.field_type or PROPERTY_FIELD_TYPES[field.kind],
                "formField": False,
            },
            allow_statuses={403} if optional else None,
        )
        if created is None and optional:
            continue
        resolved[field.key] = field.fallback

    return resolved


def iter_easystore_pages(
    fetch: Callable[[int], list[dict[str, Any]]],
    *,
    page_size: int,
    what: str,
    error: type[Exception],
) -> Iterable[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    page = 1
    while True:
        records = fetch(page)
        if records:
            signature = tuple(
                nonempty(record.get("id")) or f"row:{index}"
                for index, record in enumerate(records)
            )
            if signature in seen:
                if what == "customers.json":
                    warnings.warn(
                        f"EasyStore {what} repeated page {page}; treating the "
                        "repeat as the end of the customer collection.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    return
                raise error(
                    f"EasyStore {what} served page {page} with records already "
                    f"read, so its page parameter does nothing. Refusing to loop "
                    f"over the same {len(records)} records."
                )
            seen.add(signature)

        yield from records
        if len(records) < page_size:
            return
        page += 1


def observed_keys(seen: set[str], record: Any) -> None:
    if isinstance(record, dict):
        seen.update(str(key) for key in record)


def describe_mapping(field_properties: dict[str, str]) -> str:
    if not field_properties:
        return "none"
    return ", ".join(
        f"{key}={field_properties[key]}" for key in sorted(field_properties)
    )
