#!/usr/bin/env python3
"""Production Order sync entrypoint with portal-specific HubSpot mappings."""

from __future__ import annotations

import sys
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
HUBSPOT_ORDER_PIPELINES_URL = (
    f"{orders.HUBSPOT_BASE}/crm/pipelines/2026-03/order"
)

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

# The production portal has one HubSpot Order pipeline. Resolve its IDs from the
# Pipelines API rather than the hs_pipeline property definition: HubSpot treats
# pipelines/stages as first-class CRM resources and property option visibility is
# not an authoritative pipeline inventory.
ORDER_STAGE_LABELS = {
    "open": "Open",
    "processed": "Processed",
    "shipped": "Shipped",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
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
    """Return EasyStore's cancellation label when any known signal cancels it.

    The storefront receives several EasyStore order shapes. Depending on the
    route, cancellation can be a status label, an integer/boolean flag, or a
    timestamp. Treat only positive signals as cancellation so missing/false
    fields never invent a cancelled state.
    """

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
    """Return one actionable EasyStore state for HubSpot's native Status field.

    EasyStore exposes order, payment and fulfilment state separately. HubSpot's
    ``hs_external_order_status`` is one source-system status, so the production
    sync rolls those source facts up without inventing HubSpot-only states:

    * any explicit cancellation signal wins, including flags/timestamps;
    * refunded/partially-refunded payment state wins next;
    * fulfilled/partially-fulfilled/restocked wins over paid;
    * otherwise payment state wins, then the raw EasyStore order state.

    Cancellation is intentionally first: EasyStore can refund an order as part of
    cancelling it, but HubSpot Status should still say Cancelled when the order is
    explicitly cancelled. Payment and fulfilment remain synchronized separately
    to ``hs_payment_status`` and ``hs_fulfillment_status``.
    """

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
    """Map EasyStore commerce state onto the production HubSpot Order pipeline.

    HubSpot's Orders API documents pipeline stages as the lifecycle mechanism and
    distinguishes OPEN from CLOSED stages. Payment-only orders must remain open;
    the configured pipeline resolver may therefore route this semantic
    ``processed`` state to HubSpot's Open stage when the portal configures its
    Processed stage as CLOSED. Shipment/delivery must resolve to a CLOSED stage;
    cancellation follows the portal's own Cancelled-stage semantics.

    A standalone refund has no lossless target in the current portal because it
    has no Refunded stage. Refusing that case is safer than calling a refund a
    cancellation or pretending it is still merely processed.
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
        raise orders.SyncError(
            "EasyStore returned a refunded order that is not cancelled, but the "
            "production HubSpot Order pipeline has no Refunded stage. Add a "
            "lossless Refunded stage before syncing this order."
        )
    if payment_key in {"paid", "authorized", "partially_paid", "partial_paid"}:
        return "processed"

    order_key = _status_key(order_state)
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


def _active_stage_by_label(
    stages: Any,
    label: str,
) -> dict[str, Any]:
    if not isinstance(stages, list):
        raise orders.SyncError("HubSpot Order pipeline returned no stages list")
    matches = [
        stage
        for stage in stages
        if isinstance(stage, dict)
        and not bool(stage.get("archived"))
        and _status_key(stage.get("label")) == _status_key(label)
    ]
    if len(matches) != 1:
        raise orders.SyncError(
            f"HubSpot Order pipeline must expose exactly one active {label!r} "
            f"stage; found {len(matches)}."
        )
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


def _require_pipeline_stage_state(
    stage_key: str,
    stage: dict[str, Any],
    *,
    closed: bool,
) -> None:
    """Require a state only where EasyStore's business semantics demand one."""

    actual_closed = _pipeline_stage_closed(stage)
    expected_text = "CLOSED" if closed else "OPEN"
    if actual_closed is None:
        raise orders.SyncError(
            f"HubSpot stage {ORDER_STAGE_LABELS[stage_key]!r} must report "
            f"metadata.state={expected_text!r} for EasyStore Order lifecycle "
            "routing, but the Pipelines API did not classify it as OPEN or CLOSED."
        )
    if actual_closed != closed:
        actual_text = "CLOSED" if actual_closed else "OPEN"
        raise orders.SyncError(
            f"HubSpot stage {ORDER_STAGE_LABELS[stage_key]!r} cannot satisfy "
            f"EasyStore's required {expected_text} lifecycle state; the Pipelines "
            f"API reported metadata.state={actual_text!r}."
        )


def _resolved_fulfillment_stage(
    stages: dict[str, dict[str, Any]],
    *,
    preferred_key: str,
) -> str:
    """Return a CLOSED fulfillment stage, preferring the matching HubSpot label."""

    alternate_key = "delivered" if preferred_key == "shipped" else "shipped"
    for stage_key in (preferred_key, alternate_key):
        if _pipeline_stage_closed(stages[stage_key]) is True:
            if stage_key != preferred_key:
                print(
                    f"WARNING: HubSpot Order stage "
                    f"{ORDER_STAGE_LABELS[preferred_key]!r} is not CLOSED; "
                    f"EasyStore {preferred_key} orders will use HubSpot stage "
                    f"{ORDER_STAGE_LABELS[stage_key]!r} instead.",
                    file=sys.stderr,
                )
            return stage_key

    states = ", ".join(
        f"{ORDER_STAGE_LABELS[key]}={_pipeline_stage_state(stages[key]).upper() or 'UNKNOWN'}"
        for key in ("shipped", "delivered")
    )
    raise orders.SyncError(
        "HubSpot Order pipeline has no CLOSED fulfillment-complete stage. "
        f"Observed {states}. Configure either Shipped or Delivered as CLOSED "
        "before syncing fulfilled EasyStore orders."
    )


def configure_production_order_pipeline(access_token: str) -> None:
    """Resolve semantic EasyStore states onto the portal's live Order pipeline.

    HubSpot stage labels do not determine OPEN/CLOSED behavior. The Pipelines API
    metadata is authoritative, so routing adapts to portal configuration:

    * unpaid/open orders always use an actually OPEN stage;
    * paid but not fully fulfilled orders use Processed only when it is OPEN,
      otherwise they remain on Open;
    * shipped/delivered orders use an actually CLOSED fulfillment stage, with the
      sibling fulfillment stage as a safe fallback;
    * cancelled orders keep the portal's Cancelled stage exactly as configured,
      whether HubSpot classifies it OPEN or CLOSED.

    The resolved stage's live state is cached by stage ID and verified after the
    first write, so aliases cannot be misclassified by semantic label.
    """

    global _PIPELINE_ID, _STAGE_IDS, _STAGE_EXPECTED_CLOSED, _STAGE_LABELS_BY_ID

    headers = {"Authorization": f"Bearer {access_token}"}
    document = orders._http_json(
        HUBSPOT_ORDER_PIPELINES_URL,
        headers=headers,
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

    stages = {
        stage_key: _active_stage_by_label(pipeline.get("stages"), label)
        for stage_key, label in ORDER_STAGE_LABELS.items()
    }
    raw_stage_ids = {
        stage_key: nonempty(stage.get("id"))
        for stage_key, stage in stages.items()
    }
    if any(stage_id is None for stage_id in raw_stage_ids.values()):
        raise orders.SyncError("HubSpot Order pipeline returned a stage without an ID")

    # "Open" is the safe holding state for unpaid and payment-only orders.
    _require_pipeline_stage_state("open", stages["open"], closed=False)

    processed_key = (
        "processed"
        if _pipeline_stage_closed(stages["processed"]) is False
        else "open"
    )
    if processed_key == "open":
        reported_state = _pipeline_stage_state(stages["processed"]).upper() or "UNKNOWN"
        print(
            "WARNING: HubSpot Order stage 'Processed' is not safely OPEN "
            f"(metadata.state={reported_state!r}); paid/unfulfilled EasyStore "
            "orders will use HubSpot stage 'Open' instead.",
            file=sys.stderr,
        )

    shipped_key = _resolved_fulfillment_stage(stages, preferred_key="shipped")
    delivered_key = _resolved_fulfillment_stage(stages, preferred_key="delivered")

    resolved_stage_keys = {
        "open": "open",
        "processed": processed_key,
        "shipped": shipped_key,
        "delivered": delivered_key,
        "cancelled": "cancelled",
    }
    stage_ids = {
        semantic_key: raw_stage_ids[stage_key]
        for semantic_key, stage_key in resolved_stage_keys.items()
    }

    # All IDs were checked above; narrow the type once for the runtime maps.
    resolved_ids = {
        key: value for key, value in stage_ids.items() if value is not None
    }
    expected_closed: dict[str, bool | None] = {}
    labels_by_id: dict[str, str] = {}
    for semantic_key, resolved_stage_key in resolved_stage_keys.items():
        stage_id = resolved_ids[semantic_key]
        stage = stages[resolved_stage_key]
        expected_closed[stage_id] = _pipeline_stage_closed(stage)
        labels_by_id[stage_id] = ORDER_STAGE_LABELS[resolved_stage_key]

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


def _validate_order_stage_state(
    access_token: str,
    hubspot_order_id: str,
    stage_id: str,
) -> None:
    """Verify the persisted stage against the live state resolved by stage ID."""

    if stage_id in _VALIDATED_STAGE_IDS:
        return
    if stage_id not in _STAGE_IDS.values():
        raise orders.SyncError(f"Unknown HubSpot Order stage ID {stage_id!r}")

    document = orders._http_json(
        (
            f"{orders.HUBSPOT_ORDERS_URL}/{hubspot_order_id}"
            f"?properties={HUBSPOT_ORDER_PIPELINE_STAGE},{HUBSPOT_ORDER_IS_CLOSED}"
        ),
        headers={"Authorization": f"Bearer {access_token}"},
    )
    properties = document.get("properties") if isinstance(document, dict) else None
    if not isinstance(properties, dict):
        raise orders.SyncError(
            f"HubSpot Order {hubspot_order_id} returned no properties after stage write"
        )

    actual_stage = nonempty(properties.get(HUBSPOT_ORDER_PIPELINE_STAGE))
    stage_label = _STAGE_LABELS_BY_ID.get(stage_id, stage_id)
    if actual_stage != stage_id:
        raise orders.SyncError(
            f"HubSpot Order {hubspot_order_id} did not retain pipeline stage "
            f"{stage_label!r}."
        )

    actual_closed = _closed_value(properties.get(HUBSPOT_ORDER_IS_CLOSED))
    if actual_closed is None:
        raise orders.SyncError(
            f"HubSpot Order {hubspot_order_id} returned an unreadable "
            f"hs_is_closed={properties.get(HUBSPOT_ORDER_IS_CLOSED)!r} after "
            f"writing stage {stage_label!r}."
        )

    expected_closed = _STAGE_EXPECTED_CLOSED.get(stage_id)
    if expected_closed is not None and actual_closed != expected_closed:
        expected_text = "CLOSED" if expected_closed else "OPEN"
        raise orders.SyncError(
            f"HubSpot stage {stage_label!r} changed lifecycle semantics after "
            f"pipeline discovery: expected {expected_text}, but HubSpot reported "
            f"hs_is_closed={properties.get(HUBSPOT_ORDER_IS_CLOSED)!r}."
        )

    # If the Pipelines API omitted metadata.state, learn it safely from HubSpot's
    # calculated flag after the first persisted write and use it for this run.
    if expected_closed is None:
        _STAGE_EXPECTED_CLOSED[stage_id] = actual_closed

    _VALIDATED_STAGE_IDS.add(stage_id)


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
    """Ensure production has EasyStore's source modification timestamp.

    EasyStore list records can be thinner than order detail. The generic order
    completion path already fetches detail when commerce data is incomplete; this
    wrapper additionally fetches detail when the production Order sync has no
    modification timestamp to write to HubSpot's native Modified Date field.
    Reconciliation opts out because it only needs line items.
    """

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

    # If the generic completion path already needed detail, a second fetch cannot
    # reveal more. Otherwise force one detail read by removing line_items from a
    # copy; complete_order treats that shape as thin without changing the source.
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
