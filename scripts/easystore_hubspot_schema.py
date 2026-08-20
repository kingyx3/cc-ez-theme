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
    "datetime": "date",
}

_MONEY_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


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


def nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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

    candidate = text[:-1] + "+00:00" if text[-1:] in {"Z", "z"} else text
    try:
        moment = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return str(int(moment.timestamp() * 1000))


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
) -> dict[str, str]:
    """Map every field key onto the HubSpot property that will carry it.

    Fields with no usable native property and no fallback are left out of the
    result, so a caller writes only what the portal can actually store. With
    ``optional`` set, a portal that will not disclose its schema yields an empty
    mapping instead of failing the stage.
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

    resolved: dict[str, str] = {}
    missing: list[FieldSpec] = []

    for field in fields:
        native = select_native(field, schema)
        if native is not None:
            resolved[field.key] = native
            continue
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
                "fieldType": PROPERTY_FIELD_TYPES[field.kind],
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


def describe_mapping(field_properties: dict[str, str]) -> str:
    """Return a one-line, log-friendly rendering of a resolved mapping."""

    if not field_properties:
        return "none"
    return ", ".join(
        f"{key}={field_properties[key]}" for key in sorted(field_properties)
    )
