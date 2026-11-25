import ast
import base64
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from track1 import create_ontology_fabric as ontology
from track1 import load_fabric
from track1.standardization import RULES

WORKSPACE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
LAKEHOUSE_ID = "11111111-2222-3333-4444-555555555555"
LAKEHOUSE_NAME = "IQ_Workshop_Lakehouse"


class OntologyDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.definition = ontology.build_definition(
            display_name="IQ_Workshop_Track1_Ontology",
            workspace_id=WORKSPACE_ID,
            lakehouse_id=LAKEHOUSE_ID,
            lakehouse_name=LAKEHOUSE_NAME,
        )
        self.parts = {
            part["path"]: base64.b64decode(part["payload"]).decode("utf-8")
            for part in self.definition["parts"]
        }

    def test_definition_binds_every_workshop_table_and_entity(self):
        entity_parts = [path for path in self.parts if path.startswith("entities/")]
        table_parts = [path for path in self.parts if path.startswith("tables/")]
        self.assertEqual(len(entity_parts), 14)
        self.assertEqual(len(table_parts), 14)
        self.assertEqual(
            {table.source_name: table.expected_rows for table in ontology.TABLES},
            load_fabric.ROWS,
        )
        for table in ontology.TABLES:
            self.assertIn(f"entities/{table.entity_name}.tmdl", self.parts)
            self.assertIn(f"tables/{table.backing_table}.tmdl", self.parts)
            entity = self.parts[f"entities/{table.entity_name}.tmdl"]
            properties = re.findall(r"(?m)^\tproperty ([^\r\n]+)", entity)
            self.assertEqual(len(properties), len(set(properties)))
            self.assertIn(f"\tbackingTable: {table.backing_table}", entity)
            self.assertIn(f"\tkeyProperty: {table.key}", entity)

    def test_directlake_bindings_use_the_selected_onelake_lakehouse(self):
        self.assertEqual(
            self.parts["expressions.tmdl"],
            "expression 'DirectLake - IQ_Workshop_Lakehouse' =\n"
            "\t\tlet\n"
            '\t\t    Source = AzureStorage.DataLake("https://onelake.dfs.fabric.microsoft.com/'
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/11111111-2222-3333-4444-555555555555\", "
            "[HierarchicalNavigation=true])\n"
            "\t\tin\n"
            "\t\t    Source\n"
            f"\tlineageTag: {ontology._stable_lineage_tag('expression', 'DirectLake - IQ_Workshop_Lakehouse')}\n",
        )
        self.assertEqual(self.parts["tables/workshop_channels.tmdl"].count("dataType: string"), 2)
        self.assertIn("entityName: workshop_channels", self.parts["tables/workshop_channels.tmdl"])
        self.assertIn("expressionSource: 'DirectLake - IQ_Workshop_Lakehouse'", self.parts["tables/workshop_channels.tmdl"])
        self.assertIn(f"annotation ONT_WorkspaceId = {WORKSPACE_ID}", self.parts["tables/workshop_channels.tmdl"])
        self.assertIn(f"annotation ONT_ItemId = {LAKEHOUSE_ID}", self.parts["tables/workshop_channels.tmdl"])
        self.assertNotIn("Sql.Database(", self.parts["expressions.tmdl"])

    def test_duplicate_and_composite_key_sources_get_synthetic_identity(self):
        helper_sources = {
            table.source_name for table in ontology.TABLES if table.needs_synthetic_key
        }
        self.assertEqual(
            helper_sources,
            {"order_items", "shipments", "order_promotions", "campaign_attribution"},
        )
        for table in ontology.TABLES:
            if table.needs_synthetic_key:
                backing = self.parts[f"tables/{table.backing_table}.tmdl"]
                entity = self.parts[f"entities/{table.entity_name}.tmdl"]
                self.assertIn(f"column {ontology.SYNTHETIC_KEY_COLUMN}", backing)
                self.assertIn(f"keyProperty: {ontology.SYNTHETIC_KEY_COLUMN}", entity)

    def test_standardized_columns_are_typed_and_bound_to_canonical_properties(self):
        expected = {
            "Order": ("status", "workshop_orders_ontology_v4.order_status_std", "string"),
            "Payment": ("status", "workshop_payments_ontology_v4.payment_status_std", "string"),
            "Shipment": ("status", "workshop_shipments_ontology_v4.shipment_status_std", "string"),
            "SupportTicket": ("reason", "workshop_support_tickets_ontology_v4.ticket_reason_std", "string"),
        }
        for entity_name, (property_name, value_column, data_type) in expected.items():
            entity = self.parts[f"entities/{entity_name}.tmdl"]
            self.assertIn(f"\tproperty {property_name}\n\t\tdataType: {data_type}", entity)
            self.assertIn(f"\t\t\tvalueColumn: {value_column}", entity)
        order_entity = self.parts["entities/Order.tmdl"]
        self.assertIn(
            "\tproperty order_status_raw\n\t\tdataType: string\n",
            order_entity,
        )
        self.assertIn("valueColumn: workshop_orders_ontology_v4.order_status_raw", order_entity)
        order_table = self.parts["tables/workshop_orders_ontology_v4.tmdl"]
        self.assertIn("column order_date_std\n\t\tdataType: dateTime", order_table)
        self.assertIn("column order_date_raw\n\t\tdataType: string", order_table)
        self.assertIn("column gross_amount_std\n\t\tdataType: decimal", order_table)
        self.assertTrue(
            all(
                rule.storage_type == "decimal(38,6)"
                for rules in RULES.values()
                for rule in rules
                if rule.data_type == "decimal"
            )
        )
        self.assertEqual(sum(len(rules) for rules in RULES.values()), 27)

    def test_definition_verifier_keeps_property_blocks_across_blank_lines(self):
        with patch.object(
            ontology,
            "_request_and_wait",
            return_value={"definition": {"parts": self.definition["parts"]}},
        ):
            result = ontology._verify_created_definition(
                WORKSPACE_ID,
                "ontology",
                "token",
                lakehouse_id=LAKEHOUSE_ID,
                lakehouse_name=LAKEHOUSE_NAME,
            )
        self.assertEqual(result["standardized_property_count"], 27)
        self.assertEqual(result["lakehouse_binding_count"], 14)
        self.assertEqual(result["binding_mode"], "oneLake")

    def test_existing_backing_table_with_wrong_decimal_scale_is_rejected(self):
        table = next(table for table in ontology.TABLES if table.source_name == "products")

        class FakeType:
            def __init__(self, value):
                self.value = value

            def simpleString(self):
                return self.value

        def fake_frame(decimal_type):
            fields = [
                SimpleNamespace(
                    name=column,
                    dataType=FakeType(decimal_type if column == "unit_price_std" else "string"),
                )
                for column in table.backing_columns
            ]
            return SimpleNamespace(
                columns=list(table.backing_columns),
                schema=SimpleNamespace(fields=fields),
            )

        existing = fake_frame("decimal(18,2)")
        candidate = fake_frame("decimal(38,6)")
        spark = SimpleNamespace(
            catalog=SimpleNamespace(tableExists=lambda name: True),
            table=lambda name: existing,
        )
        with self.assertRaisesRegex(RuntimeError, "unexpected column types"):
            ontology._ensure_identity_table(spark, table, candidate)

    def test_all_relationships_have_model_and_ontology_bindings(self):
        model_relationships = self.parts["relationships.tmdl"]
        entity_relationships = self.parts["entityRelationships.tmdl"]
        self.assertEqual(len(ontology.FOREIGN_KEYS), 18)
        self.assertEqual(model_relationships.count("\nrelationship "), 17)
        self.assertEqual(entity_relationships.count("\nentityRelationship "), 17)
        for link in ontology.FOREIGN_KEYS:
            self.assertIn(f"relationship {link.name}", model_relationships)
            self.assertIn(f"relationship: {link.name}", entity_relationships)

    def test_new_experience_definition_includes_required_platform_and_namespace(self):
        platform = json.loads(self.parts[".platform"])
        self.assertEqual(platform["metadata"]["type"], "Ontology")
        self.assertEqual(platform["metadata"]["displayName"], "IQ_Workshop_Track1_Ontology")
        self.assertEqual(platform["config"]["version"], "2.0")
        model_lines = self.parts["model.tmdl"].splitlines()
        self.assertEqual(model_lines[0], "model Model")
        self.assertEqual(model_lines[1], "ref namespace default")
        self.assertFalse(model_lines[1].startswith("\t"))
        self.assertTrue(all(not line.startswith("\tref ") for line in model_lines))
        self.assertEqual(self.parts["database.tmdl"], "database\n\tcompatibilityLevel: 1000000\n")

    def test_invalid_display_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "display name"):
            ontology.build_definition(
                display_name="invalid name",
                workspace_id=WORKSPACE_ID,
                lakehouse_id=LAKEHOUSE_ID,
                lakehouse_name=LAKEHOUSE_NAME,
            )

    def test_fabric_runner_notebook_defaults_to_dry_run(self):
        path = Path(__file__).resolve().parents[1] / "track1/IQ_Workshop_Ontology_AutoCreate.ipynb"
        notebook = json.loads(path.read_text(encoding="utf-8"))
        code = [
            "".join(cell["source"])
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        ]
        tree = ast.parse("\n".join(code))
        apply_assignments = [
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "APPLY" for target in node.targets)
            and isinstance(node.value, ast.Constant)
        ]
        self.assertEqual(apply_assignments, [False])
        self.assertIn("create_ontology_fabric.run", "\n".join(code))
        self.assertIn("importlib.reload(create_ontology_fabric)", "\n".join(code))

    def test_track1_notebook_runs_and_verifies_ontology_after_q1_to_q5(self):
        path = Path(__file__).resolve().parents[1] / "track1/IQ_Workshop_Track1_KO.ipynb"
        notebook = json.loads(path.read_text(encoding="utf-8"))
        code = "\n".join(
            "".join(cell["source"])
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        )
        self.assertIn("create_ontology_fabric_v2.run(", code)
        self.assertIn("apply=True", code)
        self.assertIn("update_existing=True", code)
        self.assertLess(code.index('if report["status"] != "passed"'), code.index("ontology_result ="))
        self.assertLess(code.index("ontology_result ="), code.index("mssparkutils.notebook.exit"))


if __name__ == "__main__":
    unittest.main()
