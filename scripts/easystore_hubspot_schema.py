#!/usr/bin/env python3
"""Resolve EasyStore facts onto writable HubSpot properties.

HubSpot's native schema is not identical between portals: a property can be
absent, calculated from other records, read-only, or defined as an enumeration
that rejects the free-form labels a storefront reports. Guessing a property name
either fails the write or silently drops the value, so every field a sync stage
wants to fill is declared as a :class:`FieldSpec` and resolved against the live
schema before any write:

* the first native property that exists, is writable and has the expected type
  wins;
* otherwise a deterministic ``easystore_*`` property is provisioned in the
  ``easystore_sync`` group, so the value still lands somewhere;
* a field declared without a fallback is native-only and is skipped when the
  portal has no suitable property, rather than adding CRM clutter.

The module holds no HTTP client of its own. Each stage passes its own
``_http_json`` and its own error class, so requests keep that stage's user agent,
retry policy and error reporting.

Only Python's standard library is used.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, NamedTuple


HUBSPOT_BASE = "https://api.hubapi.com"
PROPERTY_GROUP = "easystore_sync"
PROPERTY_GROUP_LABEL = "EasyStore Sync"

# HubSpot property type -> the field type used when provisioning one.
PROPERTY_FIELD_TYPES = {
    "string": "text",
    "number": "number",
    "date": "date",
    "datetime": "date",
}

_MONEY_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
# A compact ISO 8601 calendar date, e.g. 19930420. Read as an epoch it would come
# out as a day in 1970, so it is recognised before the epoch heuristic.
_COMPACT_DATE_PATTERN = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

# Tokens that describe every field rather than any one of them, so they make
# useless search keywords when looking for a portal's property by name.
_GENERIC_TOKENS = {"amount", "at", "of", "the", "value"}
# How many candidate property names to report per unresolved field.
_HINT_LIMIT = 8


class FieldSpec(NamedTuple):
    """One EasyStore fact and the HubSpot property it should land in.

    ``sources`` are the record keys to read, most preferred first; a field whose
    value needs assembling instead supplies a derivation callable. ``native``
    lists the HubSpot properties to prefer. ``fallback`` is the ``easystore_*``
    property to provision when no native property fits, or ``None`` for a
    native-only field that is simply skipped in a portal without one.
    """

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
    """Return a scalar value as trimmed text, or ``None``.

    A list or a mapping is never text: ``str([])`` is ``"[]"`` and a list of note
    records stringifies to a Python repr, either of which would land in the CRM
    as garbage. A field whose value arrives as a container needs a derivation
    that knows its shape, so one is reported absent here rather than mangled.
    """

    if value is None or isinstance(value, (list, tuple, set, dict)):
        return None
    text = str(value).strip()
    return text or None


def note_text(value: Any) -> str | None:
    """Return free text however a storefront wrapped it.

    A note arrives as a string, as a record holding the words, or as a list of
    note records with their own timestamps. All three are read, and several notes
    are joined in the order given.
    """

    if isinstance(value, dict):
        return first_present(value, ("note", "body", "content", "text", "message", "value"))
    if isinstance(value, (list, tuple)):
        notes = [
            found
            for found in (note_text(item) for item in value)
            if found is not None
        ]
        return "\n".join(dict.fromkeys(notes)) if notes else None
    return nonempty(value)


def first_present(record: Any, keys: Iterable[str]) -> str | None:
    """Return the first non-empty value among ``keys``, honouring their order."""

    if not isinstance(record, dict):
        return None
    for key in keys:
        value = nonempty(record.get(key))
        if value is not None:
            return value
    return None


def money_value(value: Any, *, absolute: bool = False) -> str | None:
    """Return a plain decimal string for a monetary value, or ``None``.

    EasyStore reports amounts as numbers or as strings that may carry a currency
    prefix or thousands separators. HubSpot number properties need a bare
    decimal, so anything without a parseable amount is dropped rather than
    written as text.
    """

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
    """Return the datetime an ISO 8601 value denotes, or ``None``."""

    text = nonempty(value)
    if text is None:
        return None
    candidate = text[:-1] + "+00:00" if text[-1:] in {"Z", "z"} else text
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def timestamp_value(value: Any) -> str | None:
    """Return epoch milliseconds for a timestamp, or ``None``.

    HubSpot datetime properties accept epoch milliseconds, so ISO 8601 values are
    converted. EasyStore sends offsets for store-local timestamps; a value
    without an offset is read as UTC rather than guessed at.
    """

    text = nonempty(value)
    if text is None:
        return None

    if text.isdigit():
        epoch = int(text)
        # Ten digits or fewer is a seconds-precision epoch, otherwise milliseconds.
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
    """Return UTC midnight epoch milliseconds for a calendar date, or ``None``.

    HubSpot date properties store a day, not an instant, and reject a value that
    is not midnight UTC. A value that does not parse as a date is dropped rather
    than rounded to today.

    A date keeps the calendar day it was written with. Converting an
    offset-bearing midnight to UTC first would move a birthday to the previous
    day for every store east of Greenwich, and a compact ``19930420`` read as an
    epoch would land in 1970, so both are handled before the epoch heuristic.
    """

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
    """Return the HubSpot-ready value of one field, or ``None`` when absent."""

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
    """Return every mapped value for ``record``, keyed by field key."""

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
    """Write resolved field values onto a HubSpot property payload."""

    for key, value in values.items():
        target = field_properties.get(key)
        if target is not None:
            properties[target] = value
    return properties


def writable_property(prop: Any, kind: str) -> bool:
    """Report whether a HubSpot property accepts a written value of ``kind``."""

    if not isinstance(prop, dict):
        return False
    if bool(prop.get("calculated")) or bool(prop.get("archived")):
        return False
    metadata = prop.get("modificationMetadata")
    if isinstance(metadata, dict) and bool(metadata.get("readOnlyValue")):
        return False
    # An enumeration only accepts its own defined options while EasyStore sends
    # free-form labels, so matching the type keeps the write from being rejected.
    return str(prop.get("type") or "") == kind


def select_native(field: FieldSpec, schema: dict[str, dict[str, Any]]) -> str | None:
    """Return the native HubSpot property to use for ``field``, if any fits."""

    for name in field.native:
        if writable_property(schema.get(name), field.kind):
            return name
    return None


def describe_property(name: str, prop: dict[str, Any]) -> str:
    """Return a compact ``name:type`` rendering, flagging what cannot be written."""

    kind = str(prop.get("type") or "?")
    notes = []
    if bool(prop.get("calculated")):
        notes.append("calculated")
    metadata = prop.get("modificationMetadata")
    if isinstance(metadata, dict) and bool(metadata.get("readOnlyValue")):
        notes.append("read-only")
    return f"{name}:{kind}" + (f"[{','.join(notes)}]" if notes else "")


def field_keywords(field: FieldSpec) -> set[str]:
    """Return the words worth searching a portal's schema for."""

    tokens = {token for token in field.key.split("_") if token}
    return {token for token in tokens if token not in _GENERIC_TOKENS} or tokens


def matching_properties(
    schema: dict[str, dict[str, Any]],
    keywords: Iterable[str],
    *,
    limit: int = _HINT_LIMIT,
) -> list[str]:
    """Return portal properties whose name or label mentions any keyword.

    This is the answer to "the value landed in a custom property, so what is the
    native one called here?" — the portal names it rather than the sync guessing.
    """

    wanted = {keyword.casefold() for keyword in keywords}
    found: list[str] = []
    for name in sorted(schema):
        if name.startswith(PROPERTY_GROUP.split("_")[0] + "_"):
            continue  # Skip this sync's own easystore_* properties.
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
    """Return the portal's properties for ``object_type``, keyed by name.

    ``optional`` tolerates a portal whose token lacks the matching
    ``crm.schemas.*`` scope: the caller receives ``None`` and can carry on
    without the fields that depend on the schema.
    """

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
) -> None:
    """Create the ``easystore_sync`` property group when it is missing."""

    headers = {"Authorization": f"Bearer {access_token}"}
    allowed = {404, 403} if optional else {404}
    group = http_json(
        f"{HUBSPOT_BASE}/crm/v3/properties/{object_type}/groups/{PROPERTY_GROUP}",
        headers=headers,
        allow_statuses=allowed,
    )
    if group is None:
        http_json(
            f"{HUBSPOT_BASE}/crm/v3/properties/{object_type}/groups",
            method="POST",
            headers=headers,
            payload={
                "name": PROPERTY_GROUP,
                "label": PROPERTY_GROUP_LABEL,
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
) -> dict[str, str]:
    """Map every field key onto the HubSpot property that will carry it.

    Fields with no usable native property and no fallback are left out of the
    result, so a caller writes only what the portal can actually store. With
    ``optional`` set, a portal that will not disclose its schema yields an empty
    mapping instead of failing the stage.

    Pass ``report`` to collect diagnostics: ``inventory`` lists every property the
    portal has, and ``hints`` names the properties that look related to each field
    that did not find a native home. A value landing in an ``easystore_*``
    property is usually a native property this sync does not know the name of, and
    these hints are how that name gets found.
    """

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

    resolved: dict[str, str] = {}
    missing: list[FieldSpec] = []
    unresolved: list[FieldSpec] = []

    for field in fields:
        native = select_native(field, schema)
        if native is not None:
            resolved[field.key] = native
            continue

        # No native property fitted, so this field is a naming question.
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
                "groupName": PROPERTY_GROUP,
                "name": field.fallback,
                "label": field.label,
                "description": field.description,
                "type": field.kind,
                "fieldType": field.field_type or PROPERTY_FIELD_TYPES[field.kind],
                "formField": False,
            },
            # An optional stage may hold the schema read scope without the write
            # scope. Dropping the field beats failing a sync over an extra.
            allow_statuses={403} if optional else None,
        )
        if created is None and optional:
            continue
        resolved[field.key] = field.fallback

    return resolved


def observed_keys(seen: set[str], record: Any) -> None:
    """Record which keys a source record carried, for run diagnostics.

    Only key names are collected, never values, so the summary stays free of
    customer data while still answering "what does EasyStore actually send?".
    """

    if isinstance(record, dict):
        seen.update(str(key) for key in record)


def describe_mapping(field_properties: dict[str, str]) -> str:
    """Return a one-line, log-friendly rendering of a resolved mapping."""

    if not field_properties:
        return "none"
    return ", ".join(
        f"{key}={field_properties[key]}" for key in sorted(field_properties)
    )
