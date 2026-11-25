"""Configure, materialize, and verify the Track1 Ontology graph."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from track1 import create_ontology_fabric, deploy_fabric
from track1.create_ontology_fabric import FOREIGN_KEYS, TABLES, TABLE_BY_ENTITY
from track1.standardization import RULES, property_bindings

GRAPH_API = "https://api.fabric.microsoft.com/v1"
ONELAKE_GRAPH_HOST = "onelake.pbidedicated.windows.net"
GRAPH_NAMESPACE = uuid.UUID("61a2a334-36c5-4db4-b78e-c77b4c85a8bb")
GRAPH_TYPE_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/graphIndex/"
    "definition/graphType/1.0.0/schema.json"
)
DATA_SOURCES_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/graphIndex/"
    "definition/dataSources/1.0.0/schema.json"
)
GRAPH_DEFINITION_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/graphIndex/"
    "definition/graphDefinition/1.0.0/schema.json"
)
STYLING_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/graphIndex/"
    "definition/stylingConfiguration/1.0.0/schema.json"
)
GRAPH_SETTINGS_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/graphIndex/"
    "definition/graphSettings/1.0.0/schema.json"
)
MAX_JOB_POLLS = 240


def _request_and_wait(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> Any:
    return deploy_fabric.upload_fabric_notebooks._request_and_wait(
        method, url, token, body
    )


def _verify_ontology_definition(
    workspace_id: str,
    ontology_id: str,
    lakehouse_id: str,
    lakehouse_name: str,
    token: str,
) -> dict[str, int]:
    url = (
        f"{GRAPH_API}/workspaces/{workspace_id}/ontologies/{ontology_id}/getDefinition"
    )
    response = _request_and_wait("POST", url, token, {})
    definition = response.get("definition") if isinstance(response, dict) else None
    if not isinstance(definition, dict):
        raise RuntimeError("Ontology did not return a public definition.")
    parts = {
        part.get("path"): part
        for part in definition.get("parts", [])
        if isinstance(part, dict)
    }
    expressions = create_ontology_fabric._decode_definition_part(
        parts.get("expressions.tmdl", {})
    )
    expected_expression = f"DirectLake - {lakehouse_name}"
    if (
        "AzureStorage.DataLake(" not in expressions
        or "Sql.Database(" in expressions
        or f"/{workspace_id}/{lakehouse_id}" not in expressions
        or f"expression '{expected_expression}'" not in expressions
    ):
        raise RuntimeError("Ontology is not directly bound to the target OneLake Lakehouse.")
    for table in TABLES:
        entity_part = parts.get(f"entities/{table.entity_name}.tmdl")
        table_part = parts.get(f"tables/{table.backing_table}.tmdl")
        if not entity_part or not table_part:
            raise RuntimeError(
                f"Ontology definition is missing {table.entity_name} or "
                f"{table.backing_table}."
            )
        entity_text = create_ontology_fabric._decode_definition_part(entity_part)
        table_text = create_ontology_fabric._decode_definition_part(table_part)
        if (
            f"backingTable: {table.backing_table}" not in entity_text
            or f"keyProperty: {table.key}" not in entity_text
            or f"entityName: {table.backing_table}" not in table_text
            or f"annotation ONT_WorkspaceId = {workspace_id}" not in table_text
            or f"annotation ONT_ItemId = {lakehouse_id}" not in table_text
        ):
            raise RuntimeError(
                f"Ontology binding for {table.entity_name} does not match the target Lakehouse."
            )
    relationship_part = parts.get("entityRelationships.tmdl")
    if not relationship_part:
        raise RuntimeError("Ontology definition has no entity relationships.")
    relationships = create_ontology_fabric._decode_definition_part(relationship_part)
    import re

    count = len(re.findall(r"(?m)^entityRelationship\s+", relationships))
    if count != len(FOREIGN_KEYS):
        raise RuntimeError(
            f"Ontology has {count} relationships; expected {len(FOREIGN_KEYS)}."
        )
    return {
        "entity_count": len(TABLES),
        "relationship_count": count,
        "lakehouse_id": lakehouse_id,
    }


def _alias(kind: str, name: str) -> str:
    return str(uuid.uuid5(GRAPH_NAMESPACE, f"track1-graph:{kind}:{name}"))


def _encode_part(path: str, content: dict[str, Any]) -> dict[str, str]:
    payload = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
    return {
        "path": path,
        "payload": base64.b64encode(payload).decode("ascii"),
        "payloadType": "InlineBase64",
    }


def _decode_parts(definition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    parts = definition.get("parts")
    if not isinstance(parts, list):
        raise RuntimeError("GraphModel definition did not contain a parts array.")
    decoded = {}
    for part in parts:
        if not isinstance(part, dict) or part.get("payloadType") != "InlineBase64":
            raise RuntimeError("GraphModel contains an unsupported definition payload.")
        path = part.get("path")
        try:
            decoded[path] = json.loads(base64.b64decode(part["payload"], validate=True))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError(f"GraphModel has an invalid JSON definition part: {path!r}") from error
    return decoded


def _build_projection(
    *,
    workspace_id: str,
    lakehouse_id: str,
    ontology_display_name: str,
    graph_model_name: str,
    current_definition: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    node_aliases = {
        table.entity_name: _alias("node", table.entity_name) for table in TABLES
    }
    data_sources = []
    node_types = []
    node_tables = []
    decimal_as_strings = []

    for table in TABLES:
        data_source_name = table.entity_name
        data_sources.append(
            {
                "name": data_source_name,
                "type": "DeltaTable",
                "properties": {
                    "path": (
                        f"abfss://{workspace_id}@{ONELAKE_GRAPH_HOST}/"
                        f"{lakehouse_id}/Tables/{table.backing_table}"
                    )
                },
            }
        )

        graph_properties = []
        property_mappings = []
        source_columns = set(table.backing_columns)
        rules_by_source = {
            rule.source: rule for rule in RULES.get(table.source_name, ())
        }
        for property_name, source_column, ontology_type in property_bindings(
            table.source_name, table.columns
        ):
            if property_name.endswith("_raw"):
                source_name = property_name.removesuffix("_raw")
                if source_name in rules_by_source:
                    continue
            graph_type = {
                "string": "STRING",
                "int64": "INT",
                "dateTime": "ZONED DATETIME",
            }.get(ontology_type)
            if ontology_type == "decimal":
                rule = next(
                    rule for rule in RULES[table.source_name]
                    if rule.property_name == property_name
                )
                source_column = f"{rule.source}_raw"
                graph_type = "STRING"
                decimal_as_strings.append(
                    {
                        "entity": table.entity_name,
                        "property": property_name,
                        "source_column": source_column,
                    }
                )
            if not graph_type:
                raise ValueError(
                    f"Unsupported Ontology type {ontology_type!r} for "
                    f"{table.entity_name}.{property_name}."
                )
            if source_column not in source_columns:
                raise ValueError(
                    f"Missing graph source column {table.backing_table}.{source_column}."
                )
            graph_properties.append({"name": property_name, "type": graph_type})
            property_mappings.append(
                {"propertyName": property_name, "sourceColumn": source_column}
            )

        if table.key not in source_columns:
            raise ValueError(f"Missing graph key {table.backing_table}.{table.key}.")
        if table.key not in {item["name"] for item in graph_properties}:
            graph_properties.append({"name": table.key, "type": "STRING"})
            property_mappings.append(
                {"propertyName": table.key, "sourceColumn": table.key}
            )

        alias = node_aliases[table.entity_name]
        node_types.append(
            {
                "alias": alias,
                "labels": [table.entity_name],
                "primaryKeyProperties": [table.key],
                "properties": graph_properties,
            }
        )
        node_tables.append(
            {
                "id": alias,
                "nodeTypeAlias": alias,
                "dataSourceName": data_source_name,
                "propertyMappings": property_mappings,
            }
        )

    edge_types = []
    edge_tables = []
    for link in FOREIGN_KEYS:
        source_spec = TABLE_BY_ENTITY[link.from_entity]
        target_spec = TABLE_BY_ENTITY[link.to_entity]
        source_column = source_spec.backing_column(link.from_column)
        if source_spec.key not in source_spec.backing_columns:
            raise ValueError(
                f"Missing edge source key {source_spec.backing_table}.{source_spec.key}."
            )
        if source_column not in source_spec.backing_columns:
            raise ValueError(
                f"Missing edge destination key {source_spec.backing_table}.{source_column}."
            )
        if target_spec.key != link.to_column:
            raise ValueError(
                f"{link.name} destination column {link.to_column!r} does not match "
                f"{link.to_entity} key {target_spec.key!r}."
            )
        alias = _alias("edge", link.name)
        edge_types.append(
            {
                "alias": alias,
                "labels": [link.name],
                "sourceNodeType": {"alias": node_aliases[link.from_entity]},
                "destinationNodeType": {"alias": node_aliases[link.to_entity]},
                "properties": [],
            }
        )
        edge_tables.append(
            {
                "id": alias,
                "edgeTypeAlias": alias,
                "edgeIdMapping": None,
                "dataSourceName": link.from_entity,
                "sourceNodeKeyColumns": [source_spec.key],
                "destinationNodeKeyColumns": [source_column],
                "propertyMappings": [],
            }
        )

    current_parts = _decode_parts(current_definition)
    platform = current_parts.get(
        ".platform",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/"
            "gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {
                "type": "GraphModel",
                "displayName": graph_model_name,
                "description": f"Ontology graph for {ontology_display_name}",
            },
            "config": {
                "version": "2.0",
                "logicalId": _alias("platform", graph_model_name),
            },
        },
    )
    settings = current_parts.get(
        "graphSettings.json",
        {"$schema": GRAPH_SETTINGS_SCHEMA},
    )
    styling = current_parts.get(
        "stylingConfiguration.json",
        {"$schema": STYLING_SCHEMA, "modelLayout": None, "visualFormat": None},
    )
    styling["$schema"] = STYLING_SCHEMA
    styling["scenario"] = "OntologyV2"

    generated = {
        "graphType.json": {
            "$schema": GRAPH_TYPE_SCHEMA,
            "nodeTypes": node_types,
            "edgeTypes": edge_types,
        },
        "dataSources.json": {
            "$schema": DATA_SOURCES_SCHEMA,
            "dataSources": data_sources,
        },
        "graphDefinition.json": {
            "$schema": GRAPH_DEFINITION_SCHEMA,
            "nodeTables": node_tables,
            "edgeTables": edge_tables,
        },
        "stylingConfiguration.json": styling,
    }
    parts = []
    seen = set()
    for part in current_definition.get("parts", []):
        path = part["path"]
        if path in generated:
            parts.append(_encode_part(path, generated[path]))
            seen.add(path)
        else:
            parts.append(part)
    for path, content in generated.items():
        if path not in seen:
            parts.append(_encode_part(path, content))
    return {"format": "json", "parts": parts}, {
        "node_count": len(node_types),
        "edge_count": len(edge_types),
        "data_source_count": len(data_sources),
        "decimal_properties_as_strings": decimal_as_strings,
        "node_aliases": node_aliases,
    }


def _projection_is_empty(parts: dict[str, dict[str, Any]]) -> bool:
    graph_type = parts.get("graphType.json", {})
    graph_definition = parts.get("graphDefinition.json", {})
    data_sources = parts.get("dataSources.json", {})
    return (
        not graph_type.get("nodeTypes")
        and not graph_type.get("edgeTypes")
        and not graph_definition.get("nodeTables")
        and not graph_definition.get("edgeTables")
        and not data_sources.get("dataSources")
    )


def _same_projection(
    current_parts: dict[str, dict[str, Any]],
    expected_definition: dict[str, Any],
) -> bool:
    expected_parts = _decode_parts(expected_definition)
    return all(
        current_parts.get(path) == expected_parts.get(path)
        for path in ("graphType.json", "dataSources.json", "graphDefinition.json")
    )


def _job_refresh_graph(workspace_id: str, graph_model_id: str, token: str) -> dict[str, Any]:
    jobs_url = (
        f"{GRAPH_API}/workspaces/{workspace_id}/items/{graph_model_id}/jobs/instances"
    )

    def wait_for_job(job_url: str, job_id: str | None = None) -> dict[str, Any]:
        parsed = urlparse(job_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError("Fabric did not return a valid graph refresh job URL.")
        retry_after = 30
        for _ in range(MAX_JOB_POLLS):
            time.sleep(min(max(retry_after, 1), 120))
            poll_status, result, poll_headers = deploy_fabric._fabric_request(
                "GET", job_url, token
            )
            if poll_status != 200 or not isinstance(result, dict):
                raise RuntimeError(
                    f"Graph refresh job status request failed (HTTP {poll_status})."
                )
            state = result.get("status")
            if state == "Completed":
                return {
                    "status": state,
                    "job_id": result.get("id") or job_id,
                    "start_time_utc": result.get("startTimeUtc"),
                    "end_time_utc": result.get("endTimeUtc"),
                }
            if state in {"Failed", "Cancelled", "Canceled"}:
                raise RuntimeError(
                    f"Graph refresh ended with status {state}: "
                    f"{json.dumps(result.get('failureReason'), ensure_ascii=False)}"
                )
            if state == "Deduped":
                active = [
                    item
                    for item in deploy_fabric._list_items(jobs_url, token)
                    if item.get("jobType") in {"Refresh", "RefreshGraph"}
                    and item.get("status") in {"NotStarted", "InProgress"}
                ]
                if active:
                    active.sort(key=lambda item: item.get("startTimeUtc") or "", reverse=True)
                    active_job = active[0]
                    return wait_for_job(
                        f"{GRAPH_API}/workspaces/{workspace_id}/items/{graph_model_id}"
                        f"/jobs/instances/{active_job['id']}",
                        active_job["id"],
                    )
                raise RuntimeError(
                    "Graph refresh was deduplicated, but no active refresh job was found."
                )
            retry_after = int(
                deploy_fabric.upload_fabric_notebooks._header(
                    poll_headers, "Retry-After"
                )
                or retry_after
            )
        raise TimeoutError(
            f"Graph refresh did not finish after {MAX_JOB_POLLS} polls: {job_url}"
        )

    active_jobs = [
        item
        for item in deploy_fabric._list_items(jobs_url, token)
        if item.get("jobType") in {"Refresh", "RefreshGraph"}
        and item.get("status") in {"NotStarted", "InProgress"}
    ]
    if active_jobs:
        active_jobs.sort(key=lambda item: item.get("startTimeUtc") or "", reverse=True)
        active_job = active_jobs[0]
        return wait_for_job(
            f"{GRAPH_API}/workspaces/{workspace_id}/items/{graph_model_id}"
            f"/jobs/instances/{active_job['id']}",
            active_job["id"],
        )

    url = (
        f"{GRAPH_API}/workspaces/{workspace_id}/graphModels/{graph_model_id}"
        "/jobs/refreshGraph/instances"
    )
    status, payload, headers = deploy_fabric._fabric_request("POST", url, token)
    if status == 200:
        return {"status": "Completed"}
    if status != 202:
        raise RuntimeError(f"Graph refresh was not accepted (HTTP {status}).")
    job_url = deploy_fabric.upload_fabric_notebooks._header(headers, "Location")
    if not job_url:
        raise RuntimeError("Fabric did not return a graph refresh job URL.")
    return wait_for_job(
        job_url, job_url.rstrip("/").rsplit("/", 1)[-1]
    )


def _verify_query(
    workspace_id: str,
    graph_model_id: str,
    token: str,
    query: str,
    expected_count: int,
) -> dict[str, Any]:
    url = (
        f"{GRAPH_API}/workspaces/{workspace_id}/graphModels/{graph_model_id}"
        "/executeQuery?beta=true"
    )
    status, result, _ = deploy_fabric._fabric_request(
        "POST", url, token, {"query": query}
    )
    if status != 200 or not isinstance(result, dict):
        raise RuntimeError(f"Graph smoke query failed (HTTP {status}): {result!r}")
    query_status = result.get("status", {}).get("code")
    rows = result.get("result", {}).get("data")
    if query_status != "00000" or not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError(
            f"Graph smoke query returned an invalid result: "
            f"{json.dumps(result, ensure_ascii=False)}"
        )
    values = list(rows[0].values())
    if len(values) != 1 or int(values[0]) != expected_count:
        raise RuntimeError(
            f"Graph smoke query expected {expected_count}, got {values!r}."
        )
    return {"query": query, "count": expected_count}


def run(
    *,
    workspace_id: str,
    ontology_id: str,
    lakehouse_id: str,
    apply: bool = False,
    verify_only: bool = False,
    fabric_token: str | None = None,
) -> dict[str, Any]:
    """Dry-run or configure, refresh, and query the Ontology's GraphModel."""
    if apply and verify_only:
        raise ValueError("apply and verify_only are mutually exclusive.")
    for label, value in (
        ("workspace_id", workspace_id),
        ("ontology_id", ontology_id),
        ("lakehouse_id", lakehouse_id),
    ):
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as error:
            raise ValueError(f"{label} must be a UUID.") from error
    token = fabric_token or deploy_fabric._get_token("https://api.fabric.microsoft.com")

    ontologies = deploy_fabric._list_items(
        f"{GRAPH_API}/workspaces/{workspace_id}/ontologies", token
    )
    ontology = next((item for item in ontologies if item.get("id") == ontology_id), None)
    if not ontology or not ontology.get("displayName"):
        raise RuntimeError(f"Ontology {ontology_id} was not found in workspace {workspace_id}.")
    lakehouse_status, lakehouse, _ = deploy_fabric._fabric_request(
        "GET",
        f"{GRAPH_API}/workspaces/{workspace_id}/lakehouses/{lakehouse_id}",
        token,
    )
    if (
        lakehouse_status != 200
        or not isinstance(lakehouse, dict)
        or lakehouse.get("type") != "Lakehouse"
    ):
        raise RuntimeError(f"Lakehouse {lakehouse_id} was not found in the target workspace.")
    ontology_verification = _verify_ontology_definition(
        workspace_id,
        ontology_id,
        lakehouse_id,
        lakehouse["displayName"],
        token,
    )
    if (
        ontology_verification.get("entity_count") != len(TABLES)
        or ontology_verification.get("relationship_count") != len(FOREIGN_KEYS)
        or ontology_verification.get("lakehouse_id") != lakehouse_id
    ):
        raise RuntimeError(
            f"Ontology is not ready for Track1 graph materialization: "
            f"{ontology_verification}"
        )

    graph_model_name = (
        f"{ontology['displayName']}_graph_{ontology_id.replace('-', '')}"
    )
    graph_models = deploy_fabric._list_items(
        f"{GRAPH_API}/workspaces/{workspace_id}/graphModels", token
    )
    matches = [
        item for item in graph_models
        if item.get("displayName", "").casefold() == graph_model_name.casefold()
        and item.get("type") == "GraphModel"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one GraphModel named {graph_model_name!r}, found {len(matches)}."
        )
    graph_model_id = matches[0]["id"]
    definition_url = (
        f"{GRAPH_API}/workspaces/{workspace_id}/graphModels/{graph_model_id}/getDefinition"
        "?format=json"
    )
    current_response = _request_and_wait(
        "POST", definition_url, token
    )
    current_definition = (
        current_response.get("definition")
        if isinstance(current_response, dict)
        else None
    )
    if not isinstance(current_definition, dict):
        raise RuntimeError("GraphModel did not return a public definition.")
    expected_definition, plan = _build_projection(
        workspace_id=workspace_id,
        lakehouse_id=lakehouse_id,
        ontology_display_name=ontology["displayName"],
        graph_model_name=graph_model_name,
        current_definition=current_definition,
    )
    current_parts = _decode_parts(current_definition)
    if not _projection_is_empty(current_parts) and not _same_projection(
        current_parts, expected_definition
    ):
        raise RuntimeError(
            "The linked GraphModel already has a different projection. "
            "It was not overwritten."
        )

    result: dict[str, Any] = {
        "mode": "apply" if apply else "verify-only" if verify_only else "dry-run",
        "ontology_id": ontology_id,
        "graph_model_id": graph_model_id,
        "graph_model_name": graph_model_name,
        "projection": {
            "nodes": plan["node_count"],
            "edges": plan["edge_count"],
            "data_sources": plan["data_source_count"],
        },
        "decimal_properties_as_strings": plan["decimal_properties_as_strings"],
        "configuration_action": (
            "unchanged" if _same_projection(current_parts, expected_definition)
            else "configure"
        ),
    }
    if not apply and not verify_only:
        return result

    if verify_only and result["configuration_action"] != "unchanged":
        raise RuntimeError("GraphModel is not configured with the expected projection.")

    if result["configuration_action"] == "configure":
        update_url = (
            f"{GRAPH_API}/workspaces/{workspace_id}/graphModels/{graph_model_id}"
            "/updateDefinition"
        )
        _request_and_wait(
            "POST",
            update_url,
            token,
            {"definition": expected_definition},
        )
        updated_response = _request_and_wait(
            "POST", definition_url, token
        )
        updated_definition = (
            updated_response.get("definition")
            if isinstance(updated_response, dict)
            else None
        )
        if not isinstance(updated_definition, dict) or not _same_projection(
            _decode_parts(updated_definition), expected_definition
        ):
            raise RuntimeError("GraphModel definition did not match the requested projection.")

    if apply:
        result["refresh"] = _job_refresh_graph(workspace_id, graph_model_id, token)
    queryable_url = (
        f"{GRAPH_API}/workspaces/{workspace_id}/graphModels/{graph_model_id}"
        "/getQueryableGraphType?beta=true"
    )
    type_status, graph_type, _ = deploy_fabric._fabric_request(
        "GET", queryable_url, token
    )
    if (
        type_status != 200
        or not isinstance(graph_type, dict)
        or len(graph_type.get("nodeTypes", [])) != plan["node_count"]
        or len(graph_type.get("edgeTypes", [])) != plan["edge_count"]
    ):
        raise RuntimeError(
            f"Materialized graph type verification failed (HTTP {type_status}): "
            f"{json.dumps(graph_type, ensure_ascii=False)}"
        )
    result["verified_graph_type"] = {
        "nodes": len(graph_type["nodeTypes"]),
        "edges": len(graph_type["edgeTypes"]),
    }
    result["smoke_queries"] = [
        _verify_query(
            workspace_id,
            graph_model_id,
            token,
            "MATCH (n:`Product`) RETURN count(n) AS row_count",
            next(table.expected_rows for table in TABLES if table.entity_name == "Product"),
        ),
        _verify_query(
            workspace_id,
            graph_model_id,
            token,
            "MATCH (o:`Order`)-[r:`rel_order_customer`]->(c:`Customer`) "
            "RETURN count(r) AS row_count",
            2003,
        ),
    ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--ontology-id", required=True)
    parser.add_argument("--lakehouse-id", required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--apply",
        action="store_true",
        help="Configure the linked GraphModel, refresh it, and run smoke queries.",
    )
    action.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify the existing projection and materialized graph without refreshing.",
    )
    args = parser.parse_args()
    try:
        result = run(
            workspace_id=args.workspace_id,
            ontology_id=args.ontology_id,
            lakehouse_id=args.lakehouse_id,
            apply=args.apply,
            verify_only=args.verify_only,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        print(f"Track1 graph materialization failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
