"""Reusable Track1 source-to-standard-column rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnRule:
    source: str
    target: str
    property_name: str
    data_type: str
    storage_type: str
    mapping: tuple[tuple[str, str], ...] = ()


def _rule(
    source: str,
    property_name: str,
    data_type: str = "string",
    mapping: dict[str, str] | None = None,
    storage_type: str | None = None,
) -> ColumnRule:
    return ColumnRule(
        source=source,
        target=f"{source}_std",
        property_name=property_name,
        data_type=data_type,
        storage_type=storage_type or {
            "dateTime": "timestamp",
            "decimal": "decimal(38,6)",
            "int64": "long",
            "string": "string",
        }[data_type],
        mapping=tuple((mapping or {}).items()),
    )


RULES: dict[str, tuple[ColumnRule, ...]] = {
    "customers": (_rule("join_date", "join_date", "dateTime", storage_type="date"),),
    "products": (_rule("unit_price", "unit_price", "decimal"),),
    "campaigns": (
        _rule("start_date", "start_date", "dateTime", storage_type="date"),
        _rule("end_date", "end_date", "dateTime", storage_type="date"),
    ),
    "promotions": (
        _rule("discount_amount", "discount_amount", "decimal"),
        _rule("start_date", "start_date", "dateTime", storage_type="date"),
        _rule("end_date", "end_date", "dateTime", storage_type="date"),
    ),
    "orders": (
        _rule(
            "order_status",
            "status",
            mapping={
                "Completed": "PAID",
                "Cancelled": "CANCELLED",
                "NEW": "NEW",
                "PAID": "PAID",
                "SHIPPED": "SHIPPED",
                "CANCELLED": "CANCELLED",
                "RETURNED": "RETURNED",
            },
        ),
        _rule("order_date", "order_date", "dateTime", storage_type="date"),
        _rule("gross_amount", "gross_amount", "decimal"),
        _rule("discount_applied", "discount_applied", "decimal"),
        _rule("net_amount", "net_amount", "decimal"),
        _rule("order_value", "order_value", "decimal"),
    ),
    "order_items": (
        _rule("quantity", "quantity", "int64"),
        _rule("sales_amount", "sales_amount", "decimal"),
    ),
    "payments": (
        _rule(
            "payment_status",
            "status",
            mapping={
                "Success": "AUTHORIZED",
                "RetrySuccess": "AUTHORIZED",
                "Failed": "FAILED",
                "INITIATED": "INITIATED",
                "AUTHORIZED": "AUTHORIZED",
                "FAILED": "FAILED",
                "REFUNDED": "REFUNDED",
            },
        ),
        _rule("approved_amount", "approved_amount", "decimal"),
        _rule("approved_at", "approved_at", "dateTime"),
    ),
    "shipments": (
        _rule(
            "shipment_status",
            "status",
            mapping={
                "Delivered": "DELIVERED",
                "Delayed": "DELAYED",
                "InTransit": "IN_TRANSIT",
                "READY": "READY",
                "IN_TRANSIT": "IN_TRANSIT",
                "DELIVERED": "DELIVERED",
                "DELAYED": "DELAYED",
            },
        ),
        _rule("delivered_at", "delivered_at", "dateTime"),
    ),
    "returns": (_rule("return_date", "return_date", "dateTime", storage_type="date"),),
    "inventory_snapshots": (
        _rule("snapshot_date", "snapshot_date", "dateTime", storage_type="date"),
        _rule("on_hand_qty", "on_hand_qty", "int64"),
        _rule("reserved_qty", "reserved_qty", "int64"),
    ),
    "campaign_attribution": (_rule("attributed_revenue", "attributed_revenue", "decimal"),),
    "support_tickets": (
        _rule(
            "ticket_reason",
            "reason",
            mapping={
                "GeneralQuestion": "GENERAL_QUESTION",
                "LateDelivery": "LATE_DELIVERY",
                "NoTrackingUpdate": "NO_TRACKING_UPDATE",
                "NotAsDescribed": "NOT_AS_DESCRIBED",
                "PaymentFailed": "PAYMENT_FAILED",
                "SizeIssue": "SIZE_ISSUE",
            },
        ),
        _rule("created_at", "created_at", "dateTime"),
    ),
}


def standardize_value(value: str | None, rule: ColumnRule) -> str | None:
    """Apply a deterministic mapping rule; reject unmapped, non-empty values."""
    if value is None or value.strip() == "":
        return None
    if rule.mapping:
        mapping = dict(rule.mapping)
        if value not in mapping:
            raise ValueError(f"{rule.source}: unmapped value {value!r}")
        return mapping[value]
    return value


def apply_standardizations(frame: Any, source_name: str, *, validate: bool = True) -> Any:
    """Add typed `_std` columns without changing source columns."""
    from pyspark.sql import functions as F

    invalid_conditions = []
    for rule in RULES.get(source_name, ()):
        source = F.col(rule.source)
        if rule.mapping:
            mapped = F.create_map(
                *[value for pair in rule.mapping for value in (F.lit(pair[0]), F.lit(pair[1]))]
            )
            result = F.when(source.isNull() | (F.trim(source) == ""), F.lit(None)).otherwise(
                F.element_at(mapped, source)
            )
        else:
            result = source.cast(rule.storage_type)

        frame = frame.withColumn(rule.target, result)
        invalid_conditions.append(
            F.sum(
                F.when(
                    source.isNotNull()
                    & (F.trim(source.cast("string")) != "")
                    & F.col(rule.target).isNull(),
                    1,
                ).otherwise(0)
            ).alias(rule.source)
        )
    if validate and invalid_conditions:
        counts = frame.agg(*invalid_conditions).first().asDict()
        invalid_sources = [name for name, count in counts.items() if count]
        if invalid_sources:
            samples = {}
            for name in invalid_sources:
                samples[name] = [
                    row[name] for row in frame.filter(
                        F.col(name).isNotNull()
                        & (F.trim(F.col(name).cast("string")) != "")
                        & F.col(f"{name}_std").isNull()
                    ).select(name).distinct().limit(10).collect()
                ]
            raise ValueError(f"{source_name}: invalid standardization values {samples}")
    return frame


def property_bindings(source_name: str, columns: tuple[str, ...]) -> tuple[tuple[str, str, str], ...]:
    """Return ontology property, backing column, and TMDL type for an entity."""
    rules = {rule.source: rule for rule in RULES.get(source_name, ())}
    bindings = []
    for column in columns:
        rule = rules.get(column)
        if rule:
            bindings.append((f"{column}_raw", f"{column}_raw", "string"))
            bindings.append((rule.property_name, rule.target, rule.data_type))
        else:
            bindings.append((column, column, "string"))
    return tuple(bindings)
