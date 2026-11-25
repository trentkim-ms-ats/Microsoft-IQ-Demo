import base64
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from track1 import upload_fabric_notebooks as uploader


class FabricNotebookUploadTests(unittest.TestCase):
    def test_upload_manifest_includes_both_track1_notebooks(self):
        self.assertEqual(
            uploader.NOTEBOOKS,
            (
                Path("IQ_Workshop_Track1_KO.ipynb"),
                Path("IQ_Workshop_Ontology_AutoCreate.ipynb"),
            ),
        )

    def test_ipynb_definition_contains_source_notebook(self):
        notebook_path = Path(__file__).resolve().parents[1] / "track1" / uploader.NOTEBOOKS[1]
        display_name, definition = uploader._load_notebook(notebook_path)
        self.assertEqual(display_name, "IQ_Workshop_Ontology_AutoCreate")
        self.assertEqual(definition["format"], "ipynb")
        part = definition["parts"][0]
        self.assertEqual(part["path"], "artifact.content.ipynb")
        self.assertEqual(part["payloadType"], "InlineBase64")
        decoded = json.loads(base64.b64decode(part["payload"]))
        self.assertEqual(decoded, json.loads(notebook_path.read_text(encoding="utf-8")))

    def test_notebook_definition_binds_target_lakehouse_and_workspace(self):
        notebook_path = Path(__file__).resolve().parents[1] / "track1" / uploader.NOTEBOOKS[1]
        _, definition = uploader._load_notebook(
            notebook_path,
            workspace_id="11111111-2222-3333-4444-555555555555",
            lakehouse_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            lakehouse_name="DemoLakehouse",
        )
        decoded = json.loads(base64.b64decode(definition["parts"][0]["payload"]))
        self.assertEqual(
            decoded["metadata"]["dependencies"]["lakehouse"],
            {
                "default_lakehouse": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "default_lakehouse_name": "DemoLakehouse",
                "default_lakehouse_workspace_id": "11111111-2222-3333-4444-555555555555",
                "known_lakehouses": [{"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}],
            },
        )
        code = "".join(
            "".join(cell["source"])
            for cell in decoded["cells"]
            if cell["cell_type"] == "code"
        )
        self.assertIn('WORKSPACE_ID = "11111111-2222-3333-4444-555555555555"', code)
        self.assertIn('LAKEHOUSE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"', code)

    def test_track1_pipeline_uses_the_deployed_lakehouse_ids(self):
        notebook_path = Path(__file__).resolve().parents[1] / "track1/IQ_Workshop_Track1_KO.ipynb"
        _, definition = uploader._load_notebook(
            notebook_path,
            workspace_id="11111111-2222-3333-4444-555555555555",
            lakehouse_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            lakehouse_name="DemoLakehouse",
        )
        decoded = json.loads(base64.b64decode(definition["parts"][0]["payload"]))
        code = "\n".join(
            "".join(cell.get("source", []))
            for cell in decoded["cells"]
            if cell["cell_type"] == "code"
        )
        self.assertIn('WORKSPACE_ID = "11111111-2222-3333-4444-555555555555"', code)
        self.assertIn('LAKEHOUSE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"', code)

    def test_dry_run_does_not_replace_existing_notebooks(self):
        existing = [{"displayName": "IQ_Workshop_Track1_KO", "id": "notebook-id"}]
        with (
            patch.object(uploader, "_get_token", return_value="token"),
            patch.object(uploader, "_list_notebooks", return_value=existing),
        ):
            result = uploader.publish("workspace-id")
        self.assertEqual(
            result,
            [
                {"display_name": "IQ_Workshop_Track1_KO", "action": "skip"},
                {
                    "display_name": "IQ_Workshop_Ontology_AutoCreate",
                    "action": "create",
                },
            ],
        )

    def test_existing_definition_updates_require_apply(self):
        with self.assertRaisesRegex(ValueError, "requires --apply"):
            uploader.publish("workspace-id", update_existing=True)


if __name__ == "__main__":
    unittest.main()
