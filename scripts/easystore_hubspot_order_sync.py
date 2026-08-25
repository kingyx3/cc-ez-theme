#!/usr/bin/env python3
"""Production Order sync entrypoint with portal-specific HubSpot mappings."""

from __future__ import annotations

import sys
import time
from typing import Any

import easystore_hubspot_orders as orders
from easystore_hubspot_contact_identity import hubspot_contact_index
from easystore_hubspot_schema import FieldSpec, first_present, nonempty


HUBSPOT_EXTERNAL_ORDER_STATUS = "hs_external_order_status"
HUBSPOT_EXTERNAL_ORDER_MODIFIED_DATE = "hs_external_modified_date"
HUBSPOT_SHIPPING_ADDRESS_NAME = "hs_shipping_address_name"
HUBSPOT_ORDER_PIPELINE = "hs_pipeline"
HUBSPOT_ORDER_PIPELINE_STAGE = "hs_pipeline_stage"
HUBSPOT_ORDER_IS_CLOSED = "hs_is_closed"
HUBSPOT_ORDER_CLOSED_DATE = "hs_closed_date"
HUBSPOT_ORDER_PIPELINES_URL = (
    f"{orders.HUBSPOT_BASE}/crm/pipelines/2026-03/order"
)
STAGE_VALIDATION_ATTEMPTS = 4
STAGE_VALIDATION_RETRY_SECONDS = 0.5

ORDER_MODIFIED_SOURCES = (
    "updated_at",
    "modified_at",
    "updated_on",
    "modified_on",
    "last_modified_at",
)
ORDER_STATUS_SOURCES = (
    "status_label",
    "order_status_label",
    "status",
    "order_status",
    "state_label",
    "state",
    "order_state",
)
PAYMENT_STATUS_SOURCES = (
    "payment_status_label",
    "financial_status_label",
    "payment_status",
    "financial_status",
)
FULFILLMENT_STATUS_SOURCES = (
    "fulfillment_status_label",
    "fulfillment_status",
    "shipment_status",
    "shipping_status",
)
CANCELLED_STATUS_KEYS = {"cancelled", "canceled", "deleted"}
FALSEY_CANCELLATION_KEYS = {"", "0", "false", "nil", "null", "none"}

# Labels are semantic preferences, not lifecycle-state promises. The production
# portal is allowed to classify any of these labels as OPEN or CLOSED; the live
# Pipelines API remains authoritative for state.
ORDER_STAGE_LABELS = {
    "open": "Open",
    "processed": "Processed",
    "shipped": "Shipped",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
    "refunded": "Refunded",
}
_BASE_COMPLETE_ORDER = orders.complete_order
_BASE_ORDER_PROPERTIES = orders.order_properties
_BASE_UPSERT_HUBSPOT_ORDER = orders._upsert_hubspot_order
_BASE_SYNC = orders.sync

_PIPELINE_ID: str | None = None
_STAGE_IDS: dict[str, str] = {}
_STAGE_EXPECTED_CLOSED: dict[str, bool | None] = {}
_STAGE_LABELS_BY_ID: dict[str, str] = {}
_VALIDATED_STAGE_IDS: set[str] = set()


def _status_key(value: Any) -> str:
    text = nonempty(value)
    if text is None:
        return ""
    return "_".join(text.casefold().replace("-", " ").split())


def _positive_cancellation_flag(value: Any) -> bool:
    """Accept EasyStore's boolean/integer/string cancellation flag shapes."""

    return _status_key(value) in {"1", "true", "yes"}


def _cancellation_status(
    order: dict[str, Any],
    order_state: str | None,
    payment_state: str | None,
    fulfillment_state: str | None,
) -> str | None:
    """Return EasyStore's cancellation label when any known signal cancels it."""

    for state in (order_state, payment_state, fulfillment_state):
        if _status_key(state) in CANCELLED_STATUS_KEYS:
            return state

    for key in ("is_cancelled", "cancelled", "canceled"):
        if _positive_cancellation_flag(order.get(key)):
            return "cancelled"

    for key in ("cancelled_at", "canceled_at", "cancellation_date"):
        value = nonempty(order.get(key))
        if value is not None and _status_key(value) not in FALSEY_CANCELLATION_KEYS:
            return "cancelled"

    return None


def easystore_order_status(order: dict[str, Any]) -> str | None:
    """Return one actionable EasyStore state for HubSpot's native Status field."""

    order_state = first_present(order, ORDER_STATUS_SOURCES)
    payment_state = first_present(order, PAYMENT_STATUS_SOURCES)
    fulfillment_state = first_present(order, FULFILLMENT_STATUS_SOURCES)

    cancellation = _cancellation_status(
        order,
        order_state,
        payment_state,
        fulfillment_state,
    )
    if cancellation is not None:
        return cancellation

    payment_key = _status_key(payment_state)
    fulfillment_key = _status_key(fulfillment_state)

    if "refund" in payment_key:
        return payment_state

    if fulfillment_key and fulfillment_key not in {"unfulfilled", "pending"}:
        return fulfillment_state

    if payment_state is not None:
        return payment_state
    return order_state or fulfillment_state


def easystore_order_pipeline_stage(order: dict[str, Any]) -> str:
    """Map EasyStore commerce state to a semantic HubSpot Order lifecycle key.

    The semantic key is resolved to the portal's live stage at startup. Payment
    alone never closes an order. Fulfilment can close it. Cancellation/refund keep
    their source meaning in native status fields even when the portal lacks a
    matching pipeline label and therefore needs a safe fallback stage.
    """

    order_state = first_present(order, ORDER_STATUS_SOURCES)
    payment_state = first_present(order, PAYMENT_STATUS_SOURCES)
    fulfillment_state = first_present(order, FULFILLMENT_STATUS_SOURCES)

    if _cancellation_status(
        order,
        order_state,
        payment_state,
        fulfillment_state,
    ) is not None:
        return "cancelled"

    fulfillment_key = _status_key(fulfillment_state)
    if fulfillment_key == "delivered":
        return "delivered"
    if fulfillment_key in {"fulfilled", "shipped"}:
        return "shipped"

    payment_key = _status_key(payment_state)
    if "refund" in payment_key:
        return "refunded"
    if payment_key in {"paid", "authorized", "partially_paid", "partial_paid"}:
        return "processed"

    order_key = _status_key(order_state)
    if order_key == "delivered":
        return "delivered"
    if order_key in {"fulfilled", "shipped"}:
        return "shipped"
    if "refund" in order_key:
        return "refunded"
    if order_key in {"processed", "processing", "paid"}:
        return "processed"
    return "open"


def _active_pipeline_records(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise orders.SyncError("HubSpot returned an invalid Order pipeline response")
    results = document.get("results")
    if not isinstance(results, list):
        raise orders.SyncError("HubSpot Order Pipelines API returned no results list")
    return [
        pipeline
        for pipeline in results
        if isinstance(pipeline, dict) and not bool(pipeline.get("archived"))
    ]


def _active_stage_records(stages: Any) -> list[dict[str, Any]]:
    if not isinstance(stages, list):
        raise orders.SyncError("HubSpot Order pipeline returned no stages list")
    return [
        stage
        for stage in stages
        if isinstance(stage, dict) and not bool(stage.get("archived"))
    ]


def _active_stage_by_label(
    stages: list[dict[str, Any]],
    label: str,
) -> dict[str, Any] | None:
    matches = [
        stage
        for stage in stages
        if _status_key(stage.get("label")) == _status_key(label)
    ]
    if len(matches) > 1:
        raise orders.SyncError(
            f"HubSpot Order pipeline exposes multiple active {label!r} stages."
        )
    if not matches:
        return None
    if nonempty(matches[0].get("id")) is None:
        raise orders.SyncError(f"HubSpot Order stage {label!r} has no ID")
    return matches[0]


def _pipeline_stage_state(stage: dict[str, Any]) -> str:
    metadata = stage.get("metadata")
    return _status_key(metadata.get("state")) if isinstance(metadata, dict) else ""


def _pipeline_stage_closed(stage: dict[str, Any]) -> bool | None:
    state = _pipeline_stage_state(stage)
    if state == "closed":
        return True
    if state == "open":
        return False
    return None


def _stage_display_order(stage: dict[str, Any]) -> int:
    try:
        return int(stage.get("displayOrder", 10**9))
    except (TypeError, ValueError):
        return 10**9


def _stage_label(stage: dict[str, Any]) -> str:
    return nonempty(stage.get("label")) or nonempty(stage.get("id")) or "unknown"


def _open_holding_stage(active_stages: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the safest OPEN holding stage without depending on a label."""

    named_open = _active_stage_by_label(active_stages, ORDER_STAGE_LABELS["open"])
    if named_open is not None and _pipeline_stage_closed(named_open) is False:
        return named_open

    open_candidates = [
        stage for stage in active_stages if _pipeline_stage_closed(stage) is False
    ]
    if not open_candidates:
        raise orders.SyncError(
            "HubSpot Order pipeline has no stage classified OPEN. EasyStore unpaid "
            "and paid-but-unfulfilled orders need a non-closed holding stage."
        )

    fallback = min(open_candidates, key=_stage_display_order)
    if named_open is not None:
        print(
            "WARNING: HubSpot Order stage 'Open' is not classified OPEN; "
            f"unfinished EasyStore orders will use {_stage_label(fallback)!r} instead.",
            file=sys.stderr,
        )
    else:
        print(
            "WARNING: HubSpot Order pipeline has no stage labelled 'Open'; "
            f"unfinished EasyStore orders will use {_stage_label(fallback)!r}, the "
            "earliest stage HubSpot classifies OPEN.",
            file=sys.stderr,
        )
    return fallback


def _resolved_fulfillment_stage(
    stages: dict[str, dict[str, Any] | None],
    *,
    preferred_key: str,
) -> dict[str, Any]:
    """Return a CLOSED fulfillment stage, preferring the matching HubSpot label."""

    alternate_key = "delivered" if preferred_key == "shipped" else "shipped"
    for stage_key in (preferred_key, alternate_key):
        stage = stages.get(stage_key)
        if stage is not None and _pipeline_stage_closed(stage) is True:
            if stage_key != preferred_key:
                print(
                    f"WARNING: HubSpot Order stage {ORDER_STAGE_LABELS[preferred_key]!r} "
                    f"is absent or not CLOSED; EasyStore {preferred_key} orders will "
                    f"use {_stage_label(stage)!r} instead.",
                    file=sys.stderr,
                )
            return stage

    observed = []
    for key in ("shipped", "delivered"):
        stage = stages.get(key)
        if stage is None:
            observed.append(f"{ORDER_STAGE_LABELS[key]}=MISSING")
        else:
            observed.append(
                f"{ORDER_STAGE_LABELS[key]}="
                f"{_pipeline_stage_state(stage).upper() or 'UNKNOWN'}"
            )
    raise orders.SyncError(
        "HubSpot Order pipeline has no CLOSED fulfillment-complete stage. "
        f"Observed {', '.join(observed)}. Configure Shipped or Delivered as CLOSED "
        "before syncing fulfilled EasyStore orders."
    )


def configure_production_order_pipeline(access_token: str) -> None:
    """Resolve EasyStore semantics onto the portal's live Order pipeline.

    Only two state invariants are non-negotiable: unfinished orders need an OPEN
    holding stage, and fulfilled orders need a CLOSED fulfillment stage. Labels
    such as Processed, Cancelled, and Refunded are preferences; portal-specific
    state configuration is data, not a hard-coded assumption.
    """

    global _PIPELINE_ID, _STAGE_IDS, _STAGE_EXPECTED_CLOSED, _STAGE_LABELS_BY_ID

    document = orders._http_json(
        HUBSPOT_ORDER_PIPELINES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    pipelines = _active_pipeline_records(document)
    if len(pipelines) != 1:
        raise orders.SyncError(
            "Production requires exactly one active HubSpot Order pipeline so "
            "EasyStore states cannot be routed ambiguously; found "
            f"{len(pipelines)}."
        )

    pipeline = pipelines[0]
    pipeline_id = nonempty(pipeline.get("id"))
    if pipeline_id is None:
        raise orders.SyncError("HubSpot Order pipeline has no ID")

    active_stages = _active_stage_records(pipeline.get("stages"))
    if not active_stages:
        raise orders.SyncError("HubSpot Order pipeline has no active stages")

    named_stages: dict[str, dict[str, Any] | None] = {
        key: _active_stage_by_label(active_stages, label)
        for key, label in ORDER_STAGE_LABELS.items()
    }
    open_stage = _open_holding_stage(active_stages)

    processed_stage = named_stages["processed"]
    if processed_stage is None or _pipeline_stage_closed(processed_stage) is not False:
        reported_state = (
            "MISSING"
            if processed_stage is None
            else (_pipeline_stage_state(processed_stage).upper() or "UNKNOWN")
        )
        processed_stage = open_stage
        print(
            "WARNING: HubSpot Order stage 'Processed' is not safely OPEN "
            f"(metadata.state={reported_state!r}); paid/unfulfilled EasyStore "
            f"orders will use {_stage_label(open_stage)!r} instead.",
            file=sys.stderr,
        )

    shipped_stage = _resolved_fulfillment_stage(
        named_stages,
        preferred_key="shipped",
    )
    delivered_stage = _resolved_fulfillment_stage(
        named_stages,
        preferred_key="delivered",
    )

    cancelled_stage = named_stages["cancelled"]
    if cancelled_stage is None:
        cancelled_stage = open_stage
        print(
            "WARNING: HubSpot Order pipeline has no 'Cancelled' stage; cancelled "
            f"EasyStore orders will keep their native cancellation status and use "
            f"the OPEN stage {_stage_label(open_stage)!r}.",
            file=sys.stderr,
        )

    refunded_stage = named_stages["refunded"]
    if refunded_stage is None:
        refunded_stage = cancelled_stage
        print(
            "WARNING: HubSpot Order pipeline has no 'Refunded' stage; refunded "
            "EasyStore orders will keep hs_external_order_status/hs_payment_status "
            f"as refunded and use stage {_stage_label(refunded_stage)!r}.",
            file=sys.stderr,
        )

    resolved_stages = {
        "open": open_stage,
        "processed": processed_stage,
        "shipped": shipped_stage,
        "delivered": delivered_stage,
        "cancelled": cancelled_stage,
        "refunded": refunded_stage,
    }

    resolved_ids: dict[str, str] = {}
    expected_closed: dict[str, bool | None] = {}
    labels_by_id: dict[str, str] = {}
    for semantic_key, stage in resolved_stages.items():
        stage_id = nonempty(stage.get("id"))
        if stage_id is None:
            raise orders.SyncError(
                f"Resolved HubSpot Order stage for {semantic_key!r} has no ID"
            )
        resolved_ids[semantic_key] = stage_id
        expected_closed[stage_id] = _pipeline_stage_closed(stage)
        labels_by_id[stage_id] = _stage_label(stage)

    _PIPELINE_ID = pipeline_id
    _STAGE_IDS = resolved_ids
    _STAGE_EXPECTED_CLOSED = expected_closed
    _STAGE_LABELS_BY_ID = labels_by_id
    _VALIDATED_STAGE_IDS.clear()


def order_properties_with_pipeline(
    order: dict[str, Any],
    *,
    external_id: str,
    store_domain: str,
    field_properties: dict[str, str] | None = None,
    fallback_dial_code: str = "65",
) -> dict[str, str]:
    """Add HubSpot's native Order pipeline/stage to the normal Order projection."""

    if _PIPELINE_ID is None or not _STAGE_IDS:
        raise orders.SyncError("HubSpot Order pipeline was not configured before mapping")

    properties = _BASE_ORDER_PROPERTIES(
        order,
        external_id=external_id,
        store_domain=store_domain,
        field_properties=field_properties,
        fallback_dial_code=fallback_dial_code,
    )
    stage_key = easystore_order_pipeline_stage(order)
    properties[HUBSPOT_ORDER_PIPELINE] = _PIPELINE_ID
    properties[HUBSPOT_ORDER_PIPELINE_STAGE] = _STAGE_IDS[stage_key]
    return properties


def _closed_value(value: Any) -> bool | None:
    if value is True or value == 1:
        return True
    if value is False or value == 0:
        return False
    key = _status_key(value)
    if key == "true":
        return True
    if key == "false":
        return False
    return None


def _stage_validation_problem(
    properties: dict[str, Any],
    *,
    stage_id: str,
    stage_label: str,
    expected_closed: bool | None,
) -> str | None:
    actual_stage = nonempty(properties.get(HUBSPOT_ORDER_PIPELINE_STAGE))
    if actual_stage != stage_id:
        return (
            f"did not retain pipeline stage {stage_label!r}; "
            f"HubSpot reported {actual_stage!r}"
        )

    actual_closed = _closed_value(properties.get(HUBSPOT_ORDER_IS_CLOSED))
    if actual_closed is None:
        return (
            f"returned unreadable hs_is_closed="
            f"{properties.get(HUBSPOT_ORDER_IS_CLOSED)!r} for stage {stage_label!r}"
        )

    if expected_closed is not None and actual_closed != expected_closed:
        expected_text = "CLOSED" if expected_closed else "OPEN"
        return (
            f"reported hs_is_closed={properties.get(HUBSPOT_ORDER_IS_CLOSED)!r} "
            f"for stage {stage_label!r}; expected {expected_text}"
        )

    if actual_closed and nonempty(properties.get(HUBSPOT_ORDER_CLOSED_DATE)) is None:
        return (
            f"reported stage {stage_label!r} as CLOSED but did not expose "
            "hs_closed_date"
        )
    return None


def _validate_order_stage_state(
    access_token: str,
    hubspot_order_id: str,
    stage_id: str,
) -> None:
    """Verify persisted stage, calculated closure, and close date with retries."""

    if stage_id in _VALIDATED_STAGE_IDS:
        return
    if stage_id not in _STAGE_IDS.values():
        raise orders.SyncError(f"Unknown HubSpot Order stage ID {stage_id!r}")

    stage_label = _STAGE_LABELS_BY_ID.get(stage_id, stage_id)
    expected_closed = _STAGE_EXPECTED_CLOSED.get(stage_id)
    last_problem = "HubSpot returned no readable Order state"

    for attempt in range(STAGE_VALIDATION_ATTEMPTS):
        document = orders._http_json(
            (
                f"{orders.HUBSPOT_ORDERS_URL}/{hubspot_order_id}"
                f"?properties={HUBSPOT_ORDER_PIPELINE_STAGE},"
                f"{HUBSPOT_ORDER_IS_CLOSED},{HUBSPOT_ORDER_CLOSED_DATE}"
            ),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        properties = document.get("properties") if isinstance(document, dict) else None
        if isinstance(properties, dict):
            last_problem = _stage_validation_problem(
                properties,
                stage_id=stage_id,
                stage_label=stage_label,
                expected_closed=expected_closed,
            ) or ""
            if not last_problem:
                actual_closed = _closed_value(properties.get(HUBSPOT_ORDER_IS_CLOSED))
                if expected_closed is None:
                    _STAGE_EXPECTED_CLOSED[stage_id] = actual_closed
                _VALIDATED_STAGE_IDS.add(stage_id)
                return
        else:
            last_problem = "returned no properties after the stage write"

        if attempt + 1 < STAGE_VALIDATION_ATTEMPTS:
            time.sleep(STAGE_VALIDATION_RETRY_SECONDS * (2**attempt))

    raise orders.SyncError(
        f"HubSpot Order {hubspot_order_id} did not settle into the resolved "
        f"lifecycle state after {STAGE_VALIDATION_ATTEMPTS} checks: {last_problem}. "
        "For CLOSED stages, hs_closed_date must be populated so Contact closed-order "
        "rollups can be trusted."
    )


def _upsert_hubspot_order_with_stage_validation(
    access_token: str,
    existing_id: str | None,
    properties: dict[str, str],
) -> tuple[str, bool]:
    hubspot_order_id, created = _BASE_UPSERT_HUBSPOT_ORDER(
        access_token,
        existing_id,
        properties,
    )
    stage_id = nonempty(properties.get(HUBSPOT_ORDER_PIPELINE_STAGE))
    if stage_id is None:
        raise orders.SyncError("Production Order write omitted hs_pipeline_stage")
    _validate_order_stage_state(access_token, hubspot_order_id, stage_id)
    return hubspot_order_id, created


def complete_order_with_modified_date(
    store_domain: str,
    access_token: str,
    order: dict[str, Any],
    *,
    commerce_fields: bool = True,
) -> dict[str, Any]:
    """Ensure production has EasyStore's source modification timestamp."""

    source_needs_modified_detail = (
        commerce_fields and first_present(order, ORDER_MODIFIED_SOURCES) is None
    )
    completed = _BASE_COMPLETE_ORDER(
        store_domain,
        access_token,
        order,
        commerce_fields=commerce_fields,
    )
    if not source_needs_modified_detail:
        return completed
    if first_present(completed, ORDER_MODIFIED_SOURCES) is not None:
        return completed

    if orders.order_needs_detail(order):
        return completed
    detail_required = dict(order)
    detail_required.pop("line_items", None)
    return _BASE_COMPLETE_ORDER(
        store_domain,
        access_token,
        detail_required,
        commerce_fields=True,
    )


def configure_production_order_mapping() -> None:
    """Install the portal's authoritative native Order mappings in one pass."""

    configured = []
    found_modified_date = False
    for field in orders.ORDER_FIELDS:
        if field.key == "modified_at":
            found_modified_date = True
            field = field._replace(
                sources=ORDER_MODIFIED_SOURCES,
                native=(HUBSPOT_EXTERNAL_ORDER_MODIFIED_DATE,),
                fallback=None,
                label="EasyStore Order Modified",
                description=(
                    "Most recent source-system modification timestamp reported "
                    "by EasyStore for this order."
                ),
                kind="datetime",
            )
        elif field.key == "order_status":
            field = field._replace(
                native=(HUBSPOT_EXTERNAL_ORDER_STATUS,),
                description=(
                    "Actionable EasyStore order state rolled up from payment, "
                    "fulfilment and terminal order status for HubSpot Status."
                ),
            )
        elif field.key == "shipping_recipient":
            field = field._replace(
                native=(HUBSPOT_SHIPPING_ADDRESS_NAME,),
                fallback=None,
                description=(
                    "Name EasyStore records on the delivery address, written "
                    "to HubSpot Shipping Address Customer Name."
                ),
            )
        configured.append(field)

    if not found_modified_date:
        configured.append(
            FieldSpec(
                key="modified_at",
                sources=ORDER_MODIFIED_SOURCES,
                native=(HUBSPOT_EXTERNAL_ORDER_MODIFIED_DATE,),
                fallback=None,
                label="EasyStore Order Modified",
                description=(
                    "Most recent source-system modification timestamp reported "
                    "by EasyStore for this order."
                ),
                kind="datetime",
            )
        )

    orders.ORDER_FIELDS = tuple(configured)
    orders.ORDER_FIELD_DERIVATIONS["order_status"] = easystore_order_status
    orders.DEFAULT_ORDER_FIELD_PROPERTIES = {
        field.key: field.native[0] if field.native else field.fallback
        for field in orders.ORDER_FIELDS
        if field.native or field.fallback
    }


def sync_with_production_pipeline(**kwargs: Any) -> dict[str, Any]:
    """Resolve the live Order pipeline before the generic production sync runs."""

    hubspot_access_token = nonempty(kwargs.get("hubspot_access_token"))
    if hubspot_access_token is None:
        raise orders.SyncError("HubSpot access token is required for Order pipeline mapping")
    configure_production_order_pipeline(hubspot_access_token)
    return _BASE_SYNC(**kwargs)


def main(argv: list[str] | None = None) -> int:
    # Keep the generic mapping implementation in easystore_hubspot_orders, but
    # inject the same authoritative Contact identity used by preflight/customer
    # sync plus the portal's actual native Order fields and pipeline lifecycle.
    orders.hubspot_contact_index = hubspot_contact_index
    orders.complete_order = complete_order_with_modified_date
    orders.order_properties = order_properties_with_pipeline
    orders._upsert_hubspot_order = _upsert_hubspot_order_with_stage_validation
    orders.sync = sync_with_production_pipeline
    configure_production_order_mapping()
    return orders.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
