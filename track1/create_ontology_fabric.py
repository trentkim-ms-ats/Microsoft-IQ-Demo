"""Create a Fabric Ontology from the original Track1 workshop Lakehouse tables."""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

try:
    from track1.standardization import RULES, apply_standardizations, property_bindings
except ModuleNotFoundError:
    from standardization import RULES, apply_standardizations, property_bindings


FABRIC_API = "https://api.fabric.microsoft.com/v1"
LINEAGE_NAMESPACE = uuid.UUID("61a2a334-36c5-4db4-b78e-c77b4c85a8bb")
SYNTHETIC_KEY_COLUMN = "ontology_entity_id"
MAX_OPERATION_POLLS = 120


@dataclass(frozen=True)
class TableSpec:
    source_name: str
    expected_rows: int
    columns: tuple[str, ...]
    entity_name: str
    key_column: str
    needs_synthetic_key: bool = False

    @property
    def source_table(self) -> str:
        return f"workshop_{self.source_name}"

    @property
    def backing_table(self) -> str:
        suffix = "_ontology_v4" if self.needs_synthetic_key or RULES.get(self.source_name) else ""
        return f"{self.source_table}{suffix}"

    @property
    def backing_columns(self) -> tuple[str, ...]:
        rules = {rule.source for rule in RULES.get(self.source_name, ())}
        source_columns = tuple(
            f"{column}_raw" if column in rules else column for column in self.columns
        )
        standardized = tuple(rule.target for rule in RULES.get(self.source_name, ()))
        identity = (SYNTHETIC_KEY_COLUMN,) if self.needs_synthetic_key else ()
        return (*source_columns, *standardized, *identity)

    def backing_column(self, source_column: str) -> str:
        if source_column not in self.columns:
            raise ValueError(f"{self.source_name}: unknown source column {source_column!r}")
        if source_column in {rule.source for rule in RULES.get(self.source_name, ())}:
            return f"{source_column}_raw"
        return source_column

    @property
    def key(self) -> str:
        return SYNTHETIC_KEY_COLUMN if self.needs_synthetic_key else self.key_column


@dataclass(frozen=True)
class ForeignKeySpec:
    name: str
    from_entity: str
    from_column: str
    to_entity: str
    to_column: str


TABLES = (
    TableSpec("channels", 4, ("channel_id", "channel_name"), "Channel", "channel_id"),
    TableSpec(
        "customers", 1200,
        ("customer_id", "customer_segment", "customer_tier", "join_date"),
        "Customer", "customer_id",
    ),
    TableSpec(
        "products", 1200,
        ("product_id", "product_name", "category", "unit_price", "currency"),
        "Product", "product_id",
    ),
    TableSpec(
        "campaigns", 1000,
        ("campaign_id", "campaign_name", "campaign_type", "channel_id", "start_date", "end_date"),
        "Campaign", "campaign_id",
    ),
    TableSpec(
        "promotions", 1000,
        ("promotion_id", "promotion_name", "promotion_type", "discount_amount", "start_date", "end_date"),
        "Promotion", "promotion_id",
    ),
    TableSpec(
        "orders", 2003,
        (
            "order_id", "customer_id", "channel_id", "order_date", "order_status",
            "gross_amount", "discount_applied", "net_amount", "order_value", "currency",
        ),
        "Order", "order_id",
    ),
    TableSpec(
        "order_items", 4024,
        ("order_id", "product_id", "quantity", "sales_amount"),
        "OrderItem", SYNTHETIC_KEY_COLUMN, True,
    ),
    TableSpec(
        "payments", 2004,
        ("payment_id", "order_id", "payment_status", "approved_amount", "approved_at"),
        "Payment", "payment_id",
    ),
    TableSpec(
        "shipments", 2004,
        ("shipment_id", "order_id", "shipment_status", "delivered_at"),
        "Shipment", SYNTHETIC_KEY_COLUMN, True,
    ),
    TableSpec(
        "returns", 1000,
        ("return_id", "order_id", "product_id", "customer_id", "return_reason", "return_date"),
        "Return", "return_id",
    ),
    TableSpec(
        "inventory_snapshots", 2096,
        ("snapshot_id", "product_id", "snapshot_date", "on_hand_qty", "reserved_qty"),
        "InventorySnapshot", "snapshot_id",
    ),
    TableSpec(
        "order_promotions", 1910,
        ("order_id", "promotion_id"),
        "OrderPromotion", SYNTHETIC_KEY_COLUMN, True,
    ),
    TableSpec(
        "campaign_attribution", 2250,
        ("campaign_id", "order_id", "customer_id", "attribution_model", "attributed_revenue"),
        "CampaignAttribution", SYNTHETIC_KEY_COLUMN, True,
    ),
    TableSpec(
        "support_tickets", 1314,
        ("ticket_id", "customer_id", "order_id", "ticket_type", "ticket_reason", "created_at"),
        "SupportTicket", "ticket_id",
    ),
)

FOREIGN_KEYS = (
    ForeignKeySpec("rel_campaign_channel", "Campaign", "channel_id", "Channel", "channel_id"),
    ForeignKeySpec("rel_order_customer", "Order", "customer_id", "Customer", "customer_id"),
    ForeignKeySpec("rel_order_channel", "Order", "channel_id", "Channel", "channel_id"),
    ForeignKeySpec("rel_order_item_order", "OrderItem", "order_id", "Order", "order_id"),
    ForeignKeySpec("rel_order_item_product", "OrderItem", "product_id", "Product", "product_id"),
    ForeignKeySpec("rel_payment_order", "Payment", "order_id", "Order", "order_id"),
    ForeignKeySpec("rel_shipment_order", "Shipment", "order_id", "Order", "order_id"),
    ForeignKeySpec("rel_return_order", "Return", "order_id", "Order", "order_id"),
    ForeignKeySpec("rel_return_product", "Return", "product_id", "Product", "product_id"),
    ForeignKeySpec("rel_return_customer", "Return", "customer_id", "Customer", "customer_id"),
    ForeignKeySpec(
        "rel_inventory_snapshot_product", "InventorySnapshot", "product_id", "Product", "product_id"
    ),
    ForeignKeySpec("rel_order_promotion_order", "OrderPromotion", "order_id", "Order", "order_id"),
    ForeignKeySpec(
        "rel_order_promotion_promotion", "OrderPromotion", "promotion_id", "Promotion", "promotion_id"
    ),
    ForeignKeySpec(
        "rel_campaign_attribution_campaign",
        "CampaignAttribution", "campaign_id", "Campaign", "campaign_id",
    ),
    ForeignKeySpec(
        "rel_campaign_attribution_order", "CampaignAttribution", "order_id", "Order", "order_id"
    ),
    ForeignKeySpec(
        "rel_campaign_attribution_customer",
        "CampaignAttribution", "customer_id", "Customer", "customer_id",
    ),
    ForeignKeySpec(
        "rel_support_ticket_customer", "SupportTicket", "customer_id", "Customer", "customer_id"
    ),
    ForeignKeySpec("rel_support_ticket_order", "SupportTicket", "order_id", "Order", "order_id"),
)

TABLE_BY_ENTITY = {table.entity_name: table for table in TABLES}


def _stable_lineage_tag(kind: str, name: str) -> str:
    return str(uuid.uuid5(LINEAGE_NAMESPACE, f"track1:{kind}:{name}"))


def _validate_display_name(display_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,98}", display_name):
        raise ValueError(
            "Ontology display name must start with a letter, contain only letters, "
            "numbers, and underscores, and be at most 99 characters."
        )


def _part(path: str, content: str) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "payloadType": "InlineBase64",
    }


def build_definition(
    *,
    display_name: str,
    workspace_id: str,
    lakehouse_id: str,
    lakehouse_name: str,
) -> dict[str, list[dict[str, str]]]:
    """Build a generation-2 TMDL definition bound directly to OneLake."""
    _validate_display_name(display_name)
    for label, value in (("workspace_id", workspace_id), ("lakehouse_id", lakehouse_id)):
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as error:
            raise ValueError(f"{label} must be a UUID.") from error
    if not lakehouse_name or any(char in lakehouse_name for char in "'\"\r\n"):
        raise ValueError(f"Unsupported Lakehouse name: {lakehouse_name!r}")

    platform = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
                   "platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Ontology", "displayName": display_name},
        "config": {"version": "2.0", "logicalId": _stable_lineage_tag("ontology", display_name)},
    }
    expression_name = f"DirectLake - {lakehouse_name}"
    onelake_url = f"https://onelake.dfs.fabric.microsoft.com/{workspace_id}/{lakehouse_id}"
    model_lines = ["model Model", "ref namespace default"]
    model_lines.extend(f"ref table {table.backing_table}" for table in TABLES)
    model_lines.extend(f"ref entity {table.entity_name}" for table in TABLES)

    parts = [
        _part(".platform", json.dumps(platform, ensure_ascii=False, indent=2)),
        _part("database.tmdl", "database\n\tcompatibilityLevel: 1000000\n"),
        _part("model.tmdl", "\n".join(model_lines) + "\n"),
        _part("namespaces/default.tmdl", "namespace default\n\tlineageTag: default\n"),
        _part(
            "expressions.tmdl",
            f"expression '{expression_name}' =\n"
            "\t\tlet\n"
            f'\t\t    Source = AzureStorage.DataLake("{onelake_url}", '
            "[HierarchicalNavigation=true])\n"
            "\t\tin\n"
            "\t\t    Source\n"
            f"\tlineageTag: {_stable_lineage_tag('expression', expression_name)}\n",
        ),
    ]

    for table in TABLES:
        table_lines = [
            f"table {table.backing_table}",
            f"\tlineageTag: {_stable_lineage_tag('table', table.backing_table)}",
        ]
        rules = {rule.target: rule for rule in RULES.get(table.source_name, ())}
        for column in table.backing_columns:
            rule = rules.get(column)
            data_type = rule.data_type if rule else "string"
            table_lines.extend(
                (
                    f"\tcolumn {column}",
                    f"\t\tdataType: {data_type}",
                    f"\t\tsourceColumn: {column}",
                    f"\t\tlineageTag: {_stable_lineage_tag('column', f'{table.backing_table}.{column}')}",
                )
            )
        table_lines.extend(
            (
                f"\tpartition {table.backing_table} = entity",
                "\t\tmode: directLake",
                "\t\tsource",
                f"\t\t\tentityName: {table.backing_table}",
                f"\t\t\texpressionSource: '{expression_name}'",
                "",
                f"\t\tannotation ONT_WorkspaceId = {workspace_id}",
                f"\t\tannotation ONT_ItemId = {lakehouse_id}",
                "\t\tannotation ONT_ItemKind = Lakehouse",
                f"\t\tannotation ONT_ItemName = {lakehouse_name}",
            )
        )
        parts.append(_part(f"tables/{table.backing_table}.tmdl", "\n".join(table_lines) + "\n"))

    for table in TABLES:
        entity_lines = [
            f"entity {table.entity_name}",
            f"\tlineageTag: {_stable_lineage_tag('entity', table.entity_name)}",
            f"\tbackingTable: {table.backing_table}",
            f"\tkeyProperty: {table.key}",
        ]
        bindings = property_bindings(table.source_name, table.columns)
        for property_name, value_column, data_type in bindings:
            entity_lines.extend(
                (
                    f"\tproperty {property_name}",
                    f"\t\tdataType: {data_type}",
                    f"\t\tlineageTag: {_stable_lineage_tag('property', f'{table.entity_name}.{property_name}')}",
                    "\t\tbackingConfiguration",
                    f"\t\t\tvalueColumn: {table.backing_table}.{value_column}",
                )
            )
        if table.needs_synthetic_key:
            entity_lines.extend(
                (
                    f"\tproperty {SYNTHETIC_KEY_COLUMN}",
                    "\t\tdataType: string",
                    f"\t\tlineageTag: {_stable_lineage_tag('property', f'{table.entity_name}.{SYNTHETIC_KEY_COLUMN}')}",
                    "\t\tbackingConfiguration",
                    f"\t\t\tvalueColumn: {table.backing_table}.{SYNTHETIC_KEY_COLUMN}",
                )
            )
        parts.append(_part(f"entities/{table.entity_name}.tmdl", "\n".join(entity_lines) + "\n"))

    relationship_lines = []
    entity_relationship_lines = []
    for link in FOREIGN_KEYS:
        from_spec = TABLE_BY_ENTITY[link.from_entity]
        to_spec = TABLE_BY_ENTITY[link.to_entity]
        from_table = from_spec.backing_table
        to_table = to_spec.backing_table
        relationship_lines.extend(
            (
                f"relationship {link.name}",
                f"\tfromColumn: {from_table}.{from_spec.backing_column(link.from_column)}",
                f"\ttoColumn: {to_table}.{to_spec.backing_column(link.to_column)}",
                "\tfromCardinality: many",
                "\ttoCardinality: one",
            )
        )
        entity_relationship_lines.extend(
            (
                f"entityRelationship {link.name.removeprefix('rel_')}",
                f"\tlineageTag: {_stable_lineage_tag('entityRelationship', link.name)}",
                f"\tfromEntity: {link.from_entity}",
                f"\ttoEntity: {link.to_entity}",
                "\tbackingConfiguration",
                f"\t\trelationship: {link.name}",
            )
        )

    parts.append(_part("relationships.tmdl", "\n\n".join(relationship_lines) + "\n"))
    parts.append(_part("entityRelationships.tmdl", "\n\n".join(entity_relationship_lines) + "\n"))
    return {"parts": parts}


def _missing_value(column: Any, functions: Any) -> Any:
    return column.isNull() | (functions.trim(column) == "")


def _assert_unique_key(frame: Any, key_column: str, label: str) -> None:
    from pyspark.sql import functions as F

    missing = _missing_value(F.col(key_column), F)
    summary = frame.agg(
        F.count(F.lit(1)).alias("rows"),
        F.countDistinct(F.col(key_column)).alias("distinct_keys"),
        F.sum(F.when(missing, 1).otherwise(0)).alias("missing_keys"),
    ).first()
    row_count = int(summary["rows"])
    distinct_count = int(summary["distinct_keys"] or 0)
    missing_count = int(summary["missing_keys"] or 0)
    if missing_count or distinct_count != row_count:
        raise ValueError(
            f"{label}.{key_column} is not a unique, non-empty key "
            f"(rows={row_count}, distinct={distinct_count}, missing={missing_count})."
        )


def _synthetic_identity_frame(frame: Any, table: TableSpec) -> Any:
    from pyspark.sql import functions as F
    from pyspark.sql.window import Window

    columns = [F.col(column) for column in table.columns]
    row_json = F.to_json(
        F.struct(*columns),
        options={"ignoreNullFields": "false"},
    )
    duplicate_window = Window.partitionBy(*columns).orderBy(
        *[F.col(column).asc_nulls_first() for column in table.columns]
    )
    return (
        frame.withColumn("_ontology_row_hash", F.sha2(row_json, 256))
        .withColumn("_ontology_duplicate_rank", F.row_number().over(duplicate_window))
        .withColumn(
            SYNTHETIC_KEY_COLUMN,
            F.concat(
                F.lit(f"{table.source_name}_"),
                F.col("_ontology_row_hash"),
                F.lit("_"),
                F.col("_ontology_duplicate_rank").cast("string"),
            ),
        )
        .drop("_ontology_row_hash", "_ontology_duplicate_rank")
    )


def _ensure_identity_table(spark: Any, table: TableSpec, candidate: Any) -> Any:
    existing_name = table.backing_table
    if spark.catalog.tableExists(existing_name):
        existing = spark.table(existing_name)
        if tuple(existing.columns) != table.backing_columns:
            raise RuntimeError(
                f"Existing backing table {existing_name} has unexpected columns; "
                "it was not overwritten."
            )
        candidate_types = tuple(
            (field.name, field.dataType.simpleString()) for field in candidate.schema.fields
        )
        existing_types = tuple(
            (field.name, field.dataType.simpleString()) for field in existing.schema.fields
        )
        if existing_types != candidate_types:
            raise RuntimeError(
                f"Existing backing table {existing_name} has unexpected column types; "
                "it was not overwritten."
            )
        differences = candidate.exceptAll(existing).unionByName(existing.exceptAll(candidate))
        if differences.limit(1).count():
            raise RuntimeError(
                f"Existing backing table {existing_name} differs from its source; "
                "it was not overwritten."
            )
        return existing

    candidate.write.format("delta").mode("errorifexists").saveAsTable(existing_name)
    return spark.table(existing_name)


def _inspect_sample_tables(spark: Any, *, create_helpers: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    from pyspark.sql import functions as F

    frames: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {
        "row_counts": {},
        "orphan_references": {},
        "standardized_columns": {},
    }
    for table in TABLES:
        if not spark.catalog.tableExists(table.source_table):
            raise RuntimeError(f"Required source table is missing: {table.source_table}")
        source = spark.table(table.source_table)
        if tuple(source.columns) != table.columns:
            raise ValueError(
                f"{table.source_table} columns differ from the workshop sample: "
                f"expected {table.columns}, got {tuple(source.columns)}."
            )
        non_string_columns = [
            field.name for field in source.schema.fields if field.dataType.simpleString() != "string"
        ]
        if non_string_columns:
            raise ValueError(
                f"{table.source_table} must preserve the workshop CSV columns as strings; "
                f"non-string columns: {non_string_columns}."
            )
        candidate = apply_standardizations(source, table.source_name, validate=False)
        candidate_types = {
            field.name: field.dataType.simpleString() for field in candidate.schema.fields
        }
        for rule in RULES.get(table.source_name, ()):
            if (
                rule.data_type == "decimal"
                and candidate_types.get(rule.target) != rule.storage_type
            ):
                raise RuntimeError(
                    f"{table.source_name}.{rule.target} has type "
                    f"{candidate_types.get(rule.target)!r}; expected {rule.storage_type!r}."
                )
        if table.needs_synthetic_key:
            candidate = _synthetic_identity_frame(candidate, table)

        validation = [
            F.count(F.lit(1)).alias("_rows"),
            F.countDistinct(F.col(table.key)).alias("_distinct_keys"),
            F.sum(F.when(_missing_value(F.col(table.key), F), 1).otherwise(0)).alias("_missing_keys"),
        ]
        for rule in RULES.get(table.source_name, ()):
            validation.extend(
                (
                    F.count(F.col(rule.target)).alias(f"{rule.source}_non_null"),
                    F.countDistinct(F.col(rule.target)).alias(f"{rule.source}_distinct"),
                    F.sum(
                        F.when(
                            F.col(rule.source).isNotNull()
                            & (F.trim(F.col(rule.source)) != "")
                            & F.col(rule.target).isNull(),
                            1,
                        ).otherwise(0)
                    ).alias(f"{rule.source}_invalid"),
                )
            )
        stats = candidate.agg(*validation).first().asDict()
        row_count = int(stats["_rows"])
        if row_count != table.expected_rows:
            raise ValueError(
                f"{table.source_table} has {row_count} rows; expected {table.expected_rows}."
            )
        diagnostics["row_counts"][table.source_table] = row_count
        if stats["_missing_keys"] or stats["_distinct_keys"] != row_count:
            raise ValueError(
                f"{table.backing_table}.{table.key} is not a unique, non-empty key "
                f"(rows={row_count}, distinct={stats['_distinct_keys']}, "
                f"missing={stats['_missing_keys']})."
            )
        if RULES.get(table.source_name):
            diagnostics["standardized_columns"][table.source_name] = {}
            for rule in RULES[table.source_name]:
                invalid_count = stats[f"{rule.source}_invalid"]
                if invalid_count:
                    values = [
                        row[rule.source]
                        for row in candidate.filter(
                            F.col(rule.source).isNotNull()
                            & (F.trim(F.col(rule.source)) != "")
                            & F.col(rule.target).isNull()
                        ).select(rule.source).distinct().limit(10).collect()
                    ]
                    raise ValueError(
                        f"{table.source_name}.{rule.source}: invalid standardization values {values}"
                    )
                diagnostics["standardized_columns"][table.source_name][rule.target] = {
                    "type": rule.storage_type,
                    "non_null": int(stats[f"{rule.source}_non_null"]),
                    "distinct": int(stats[f"{rule.source}_distinct"] or 0),
                    "rows": row_count,
                }
        backing_candidate = candidate
        for rule in RULES.get(table.source_name, ()):
            backing_candidate = backing_candidate.withColumnRenamed(
                rule.source, f"{rule.source}_raw"
            )
        if table.backing_table != table.source_table:
            frame = (
                _ensure_identity_table(spark, table, backing_candidate)
                if create_helpers
                else backing_candidate
            )
        else:
            frame = backing_candidate
        frames[table.backing_table] = frame

    for link in FOREIGN_KEYS:
        child_table = TABLE_BY_ENTITY[link.from_entity].backing_table
        parent_table = TABLE_BY_ENTITY[link.to_entity].backing_table
        child_spec = TABLE_BY_ENTITY[link.from_entity]
        parent_spec = TABLE_BY_ENTITY[link.to_entity]
        child = frames[child_table].alias("child")
        parent = (
            frames[parent_table]
            .select(F.col(parent_spec.backing_column(link.to_column)).alias("_ontology_parent_key"))
            .dropDuplicates()
            .alias("parent")
        )
        child_key = F.col(f"child.`{child_spec.backing_column(link.from_column)}`")
        parent_key = F.col("parent._ontology_parent_key")
        missing = _missing_value(child_key, F)
        orphan_count = (
            child.join(parent, child_key == parent_key, "left_anti")
            .filter(~missing)
            .count()
        )
        missing_count = child.filter(missing).count()
        diagnostics["orphan_references"][link.name] = {
            "missing": missing_count,
            "orphan": orphan_count,
        }
    return frames, diagnostics


def _header(headers: Any, name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def _fabric_request(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any, Any]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            payload = json.loads(raw.decode("utf-8")) if raw else None
            return response.status, payload, response.headers
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", "replace")
        raise RuntimeError(
            f"Fabric API {method} {url} returned HTTP {error.code}: {details}"
        ) from error


def _request_and_wait(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> Any:
    status, payload, headers = _fabric_request(method, url, token, body)
    if status != 202:
        return payload

    operation_id = _header(headers, "x-ms-operation-id")
    operation_url = _header(headers, "Location")
    if not operation_url and operation_id:
        operation_url = f"{FABRIC_API}/operations/{operation_id}"
    if not operation_url:
        raise RuntimeError("Fabric returned HTTP 202 without an operation URL or ID.")

    retry_after = int(_header(headers, "Retry-After") or "5")
    for _ in range(MAX_OPERATION_POLLS):
        time.sleep(min(max(retry_after, 1), 30))
        _, state, state_headers = _fabric_request("GET", operation_url, token)
        if not isinstance(state, dict):
            raise RuntimeError("Fabric operation status response was not a JSON object.")
        operation_status = state.get("status")
        if operation_status == "Succeeded":
            result_url = f"{FABRIC_API}/operations/{operation_id}/result" if operation_id else None
            if result_url:
                _, result, _ = _fabric_request("GET", result_url, token)
                return result
            updated_location = _header(state_headers, "Location")
            if updated_location and updated_location != operation_url:
                _, result, _ = _fabric_request("GET", updated_location, token)
                return result
            return state
        if operation_status in ("Failed", "Canceled"):
            raise RuntimeError(f"Fabric operation {operation_status}: {state}")
        retry_after = int(_header(state_headers, "Retry-After") or retry_after)

    raise TimeoutError(
        f"Fabric operation did not finish after {MAX_OPERATION_POLLS} status checks: {operation_url}"
    )


def _list_ontologies(workspace_id: str, token: str) -> list[dict[str, Any]]:
    url = f"{FABRIC_API}/workspaces/{workspace_id}/ontologies"
    results: list[dict[str, Any]] = []
    while url:
        _, response, _ = _fabric_request("GET", url, token)
        if not isinstance(response, dict) or not isinstance(response.get("value"), list):
            raise RuntimeError("Fabric list-ontologies response did not contain a value array.")
        results.extend(response["value"])
        continuation = response.get("continuationToken")
        url = (
            f"{FABRIC_API}/workspaces/{workspace_id}/ontologies?"
            f"{urllib.parse.urlencode({'continuationToken': continuation})}"
            if continuation else ""
        )
    return results


def _decode_definition_part(part: dict[str, Any]) -> str:
    if part.get("payloadType") != "InlineBase64":
        raise RuntimeError(f"Unsupported definition payload type: {part.get('payloadType')!r}")
    try:
        return base64.b64decode(part["payload"], validate=True).decode("utf-8")
    except (KeyError, ValueError, UnicodeDecodeError) as error:
        raise RuntimeError(f"Invalid ontology definition part: {part.get('path')}") from error


def _verify_created_definition(
    workspace_id: str,
    ontology_id: str,
    token: str,
    *,
    lakehouse_id: str,
    lakehouse_name: str,
) -> dict[str, Any]:
    url = f"{FABRIC_API}/workspaces/{workspace_id}/ontologies/{ontology_id}/getDefinition"
    response = _request_and_wait("POST", url, token, {})
    parts = response.get("definition", {}).get("parts", []) if isinstance(response, dict) else []
    by_path = {part.get("path"): part for part in parts if isinstance(part, dict)}
    expected_paths = {
        *(f"entities/{table.entity_name}.tmdl" for table in TABLES),
        *(f"tables/{table.backing_table}.tmdl" for table in TABLES),
        "entityRelationships.tmdl",
        "relationships.tmdl",
    }
    missing = sorted(expected_paths - by_path.keys())
    if missing:
        raise RuntimeError(f"Ontology was created, but its definition is missing parts: {missing}")
    expression_name = f"DirectLake - {lakehouse_name}"
    expressions = _decode_definition_part(by_path["expressions.tmdl"])
    if (
        "AzureStorage.DataLake(" not in expressions
        or "Sql.Database(" in expressions
        or f"expression '{expression_name}'" not in expressions
        or f"/{workspace_id}/{lakehouse_id}" not in expressions
    ):
        raise RuntimeError(
            "Ontology definition is not bound directly to the selected OneLake Lakehouse."
        )
    entity_relationships = _decode_definition_part(by_path["entityRelationships.tmdl"])
    relationship_count = len(re.findall(r"(?m)^entityRelationship\s+", entity_relationships))
    if relationship_count != len(FOREIGN_KEYS):
        raise RuntimeError(
            f"Ontology was created with {relationship_count} entity relationships; "
            f"expected {len(FOREIGN_KEYS)}."
        )
    verified_standardizations = 0
    for table in TABLES:
        entity_path = f"entities/{table.entity_name}.tmdl"
        table_path = f"tables/{table.backing_table}.tmdl"
        entity_text = _decode_definition_part(by_path[entity_path])
        table_text = _decode_definition_part(by_path[table_path])
        partition = re.search(
            rf"(?ms)^\tpartition {re.escape(table.backing_table)} = entity\r?\n(.*)\Z",
            table_text,
        )
        if (
            not partition
            or f"entityName: {table.backing_table}" not in partition.group(1)
            or f"expressionSource: '{expression_name}'" not in partition.group(1)
            or f"annotation ONT_WorkspaceId = {workspace_id}" not in partition.group(1)
            or f"annotation ONT_ItemId = {lakehouse_id}" not in partition.group(1)
            or "\t\tannotation ONT_ItemKind = Lakehouse" not in partition.group(1)
            or f"annotation ONT_ItemName = {lakehouse_name}" not in partition.group(1)
        ):
            raise RuntimeError(
                f"Ontology table {table.backing_table} is not bound to the selected "
                "OneLake Lakehouse table."
            )
        for rule in RULES.get(table.source_name, ()):
            property_block = re.search(
                rf"(?ms)^\tproperty {re.escape(rule.property_name)}\r?\n(.*?)(?=^\tproperty |\Z)",
                entity_text,
            )
            column_block = re.search(
                rf"(?ms)^\tcolumn {re.escape(rule.target)}\r?\n(.*?)(?=^\t(?:column |partition )|\Z)",
                table_text,
            )
            if (
                not property_block
                or not column_block
                or f"dataType: {rule.data_type}" not in property_block.group(1)
                or f"valueColumn: {table.backing_table}.{rule.target}" not in property_block.group(1)
                or f"dataType: {rule.data_type}" not in column_block.group(1)
                or f"sourceColumn: {rule.target}" not in column_block.group(1)
            ):
                raise RuntimeError(
                    f"Ontology definition has an invalid standardization binding: "
                    f"{table.entity_name}.{rule.property_name} -> {rule.target}."
                )
            verified_standardizations += 1
    return {
        "entity_count": len(TABLES),
        "backing_table_count": len(TABLES),
        "relationship_count": relationship_count,
        "standardized_property_count": verified_standardizations,
        "binding_mode": "oneLake",
        "lakehouse_binding_count": len(TABLES),
        "lakehouse_id": lakehouse_id,
        "definition_part_count": len(parts),
    }


def run(
    spark: Any,
    *,
    token: str,
    workspace_id: str,
    lakehouse_id: str,
    display_name: str,
    apply: bool = False,
    update_existing: bool = False,
) -> dict[str, Any]:
    """Validate, dry-run, or create/update the ontology in Fabric."""
    _validate_display_name(display_name)
    for label, value in (("workspace_id", workspace_id), ("lakehouse_id", lakehouse_id)):
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as error:
            raise ValueError(f"{label} must be a UUID.") from error
    if not token:
        raise ValueError("A Fabric API access token is required; do not print or save it.")

    _, diagnostics = _inspect_sample_tables(spark, create_helpers=False)
    _, lakehouse, _ = _fabric_request(
        "GET",
        f"{FABRIC_API}/workspaces/{workspace_id}/lakehouses/{lakehouse_id}",
        token,
    )
    if not isinstance(lakehouse, dict) or lakehouse.get("type") != "Lakehouse":
        raise RuntimeError("The configured Fabric item is not a Lakehouse.")
    lakehouse_name = lakehouse.get("displayName")
    if not isinstance(lakehouse_name, str) or not lakehouse_name:
        raise RuntimeError("The configured Lakehouse did not return a display name.")
    definition = build_definition(
        display_name=display_name,
        workspace_id=workspace_id,
        lakehouse_id=lakehouse_id,
        lakehouse_name=lakehouse_name,
    )
    existing = [
        item for item in _list_ontologies(workspace_id, token)
        if item.get("displayName", "").casefold() == display_name.casefold()
    ]
    if len(existing) > 1:
        raise RuntimeError(f"Multiple Ontologies already use the name {display_name!r}.")
    if existing and not update_existing:
        if apply:
            raise RuntimeError(
                f"Ontology {display_name!r} already exists. Set update_existing=True only "
                "if you intend to replace its complete definition."
            )
        return {
            "mode": "dry-run",
            "action": "blocked-existing-item",
            "existing_ontology_id": existing[0].get("id"),
            "display_name": display_name,
            "data_quality": diagnostics,
        }

    if not apply:
        return {
            "mode": "dry-run",
            "action": "update" if existing else "create",
            "display_name": display_name,
            "source_csv_count": len(TABLES),
            "entity_count": len(TABLES),
            "backing_table_count": len(TABLES),
            "relationship_count": len(FOREIGN_KEYS),
            "helper_tables_to_create": [
                table.backing_table for table in TABLES if table.backing_table != table.source_table
            ],
            "definition_part_count": len(definition["parts"]),
            "data_quality": diagnostics,
        }

    _inspect_sample_tables(spark, create_helpers=True)
    description = (
        "Track1 ontology generated from all 14 original workshop CSV tables; "
        "source rows are preserved."
    )
    if existing:
        ontology_id = existing[0]["id"]
        _request_and_wait(
            "POST",
            f"{FABRIC_API}/workspaces/{workspace_id}/ontologies/{ontology_id}/updateDefinition",
            token,
            {"definition": definition},
        )
        action = "updated"
    else:
        _request_and_wait(
            "POST",
            f"{FABRIC_API}/workspaces/{workspace_id}/ontologies",
            token,
            {
                "displayName": display_name,
                "description": description,
                "definition": definition,
            },
        )
        action = "created"

    created_items = [
        item for item in _list_ontologies(workspace_id, token)
        if item.get("displayName", "").casefold() == display_name.casefold()
    ]
    if len(created_items) != 1:
        raise RuntimeError(
            f"Ontology {display_name!r} was submitted, but list-ontologies returned "
            f"{len(created_items)} matching items."
        )
    item = created_items[0]
    generation = item.get("properties", {}).get("generation")
    if generation != 2:
        raise RuntimeError(f"Expected a generation-2 Ontology; Fabric reports {generation!r}.")
    verification = _verify_created_definition(
        workspace_id,
        item["id"],
        token,
        lakehouse_id=lakehouse_id,
        lakehouse_name=lakehouse_name,
    )
    return {
        "mode": "apply",
        "action": action,
        "display_name": display_name,
        "ontology_id": item["id"],
        "generation": generation,
        "helper_tables": [
            table.backing_table for table in TABLES if table.backing_table != table.source_table
        ],
        "data_quality": diagnostics,
        "verified_definition": verification,
    }
