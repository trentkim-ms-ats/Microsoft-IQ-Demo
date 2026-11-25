import base64
import json
import unittest
from unittest.mock import patch

from track1.create_ontology_fabric import FOREIGN_KEYS, TABLES, TABLE_BY_ENTITY
from track1 import materialize_graph
from track1.materialize_graph import _build_projection, _decode_parts
from track1.standardization import RULES


WORKSPACE = "11111111-2222-3333-4444-555555555555"
LAKEHOUSE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ONTOLOGY = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"


def _definition_parts(definition):
    return {
        part["path"]: json.loads(base64.b64decode(part["payload"]))
        for part in definition["parts"]
    }


class Track1GraphMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.definition, self.plan = _build_projection(
            workspace_id=WORKSPACE,
            lakehouse_id=LAKEHOUSE,
            ontology_display_name="Track1",
            graph_model_name="Track1_graph",
            current_definition={"parts": []},
        )
        self.parts = _definition_parts(self.definition)

    def test_projection_contains_every_track1_entity_and_relationship(self):
        graph_type = self.parts["graphType.json"]
        graph_definition = self.parts["graphDefinition.json"]
        self.assertEqual(len(graph_type["nodeTypes"]), len(TABLES))
        self.assertEqual(len(graph_type["edgeTypes"]), len(FOREIGN_KEYS))
        self.assertEqual(len(self.parts["dataSources.json"]["dataSources"]), len(TABLES))
        self.assertEqual(len(graph_definition["nodeTables"]), len(TABLES))
        self.assertEqual(len(graph_definition["edgeTables"]), len(FOREIGN_KEYS))

    def test_decimal_properties_keep_exact_source_text_in_graph(self):
        graph_type = self.parts["graphType.json"]
        graph_definition = self.parts["graphDefinition.json"]
        product = next(item for item in graph_type["nodeTypes"] if item["labels"] == ["Product"])
        price = next(item for item in product["properties"] if item["name"] == "unit_price")
        product_table = next(
            item for item in graph_definition["nodeTables"]
            if item["nodeTypeAlias"] == product["alias"]
        )
        price_mapping = next(
            item for item in product_table["propertyMappings"]
            if item["propertyName"] == "unit_price"
        )
        self.assertEqual(price["type"], "STRING")
        self.assertEqual(price_mapping["sourceColumn"], "unit_price_raw")
        expected_decimal_count = sum(
            rule.data_type == "decimal"
            for rules in RULES.values()
            for rule in rules
        )
        self.assertEqual(len(self.plan["decimal_properties_as_strings"]), expected_decimal_count)

    def test_graph_integer_properties_use_fabric_graph_type_name(self):
        graph_type = self.parts["graphType.json"]
        inventory = next(
            item for item in graph_type["nodeTypes"]
            if item["labels"] == ["InventorySnapshot"]
        )
        integer = next(
            item for item in inventory["properties"]
            if item["name"] == "on_hand_qty"
        )
        self.assertEqual(integer["type"], "INT")

    def test_edge_mappings_use_source_entity_key_and_foreign_key(self):
        graph_definition = self.parts["graphDefinition.json"]
        edge_types = self.parts["graphType.json"]["edgeTypes"]
        by_alias = {item["alias"]: item for item in edge_types}
        for link, edge in zip(FOREIGN_KEYS, graph_definition["edgeTables"]):
            source = TABLE_BY_ENTITY[link.from_entity]
            self.assertEqual(edge["dataSourceName"], link.from_entity)
            self.assertEqual(edge["sourceNodeKeyColumns"], [source.key])
            self.assertEqual(
                edge["destinationNodeKeyColumns"],
                [source.backing_column(link.from_column)],
            )
            self.assertEqual(by_alias[edge["edgeTypeAlias"]]["labels"], [link.name])

    def test_verify_only_queries_existing_graph_without_refresh(self):
        name = f"Track1_graph_{ONTOLOGY.replace('-', '')}"
        definition, _ = _build_projection(
            workspace_id=WORKSPACE,
            lakehouse_id=LAKEHOUSE,
            ontology_display_name="Track1",
            graph_model_name=name,
            current_definition={"parts": []},
        )
        with (
            patch.object(materialize_graph.deploy_fabric, "_list_items", side_effect=[
                [{"id": ONTOLOGY, "displayName": "Track1"}],
                [{"id": "graph", "displayName": name, "type": "GraphModel"}],
            ]),
            patch.object(materialize_graph.deploy_fabric, "_fabric_request", side_effect=[
                (200, {"type": "Lakehouse", "displayName": "Lakehouse"}, {}),
                (200, {"nodeTypes": [{}] * 14, "edgeTypes": [{}] * 18}, {}),
            ]),
            patch.object(materialize_graph, "_verify_ontology_definition", return_value={
                "entity_count": 14, "relationship_count": 18, "lakehouse_id": LAKEHOUSE,
            }),
            patch.object(materialize_graph, "_request_and_wait", return_value={"definition": definition}) as request,
            patch.object(materialize_graph, "_job_refresh_graph") as refresh,
            patch.object(materialize_graph, "_verify_query", side_effect=[
                {"count": 1200}, {"count": 2003},
            ]) as query,
        ):
            result = materialize_graph.run(
                workspace_id=WORKSPACE, ontology_id=ONTOLOGY, lakehouse_id=LAKEHOUSE,
                verify_only=True, fabric_token="token",
            )
        self.assertEqual(result["mode"], "verify-only")
        self.assertEqual([item["count"] for item in result["smoke_queries"]], [1200, 2003])
        self.assertEqual(query.call_count, 2)
        self.assertEqual(request.call_count, 1)
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
