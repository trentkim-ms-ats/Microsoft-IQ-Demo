import unittest
from unittest.mock import patch

from track1 import run_track1
from track1.standardization import RULES


WORKSPACE = "11111111-2222-3333-4444-555555555555"
LAKEHOUSE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class Track1RunnerTests(unittest.TestCase):
    def test_dry_run_does_not_execute_notebook(self):
        planned = {"mode": "dry-run", "note": "No changes"}
        with (
            patch.object(run_track1.deploy_fabric, "deploy", return_value=planned),
            patch.object(run_track1, "_execute_notebook") as execute,
        ):
            result = run_track1.run(
                workspace_id=WORKSPACE,
                lakehouse_id=LAKEHOUSE,
                fabric_token="token",
            )
        self.assertEqual(result, planned)
        execute.assert_not_called()

    def test_apply_requires_query_and_standardized_ontology_verification(self):
        count = sum(len(rules) for rules in RULES.values())
        deployment = {
            "lakehouse": {"id": LAKEHOUSE},
            "notebooks": [{"display_name": run_track1.NOTEBOOK_NAME, "notebook_id": "notebook"}],
        }
        completed = {
            "job_status": "Completed",
            "exit_value": {
                "queries": {"status": "passed"},
                "ontology": {
                    "ontology_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                    "mode": "apply",
                    "generation": 2,
                    "verified_definition": {
                        "binding_mode": "oneLake",
                        "lakehouse_binding_count": 14,
                        "standardized_property_count": count,
                    },
                },
            },
        }
        with (
            patch.object(run_track1.deploy_fabric, "deploy", return_value=deployment),
            patch.object(run_track1, "_execute_notebook", return_value=completed),
            patch.object(run_track1.materialize_graph, "run", return_value={"mode": "apply"}) as graph,
        ):
            result = run_track1.run(
                workspace_id=WORKSPACE,
                lakehouse_id=LAKEHOUSE,
                apply=True,
                fabric_token="token",
            )
        self.assertEqual(result["execution"], completed)
        self.assertEqual(result["graph"], {"mode": "apply"})
        graph.assert_called_once_with(
            workspace_id=WORKSPACE,
            ontology_id=completed["exit_value"]["ontology"]["ontology_id"],
            lakehouse_id=LAKEHOUSE,
            apply=True,
            fabric_token="token",
        )

    def test_apply_rejects_missing_standardized_ontology_proof(self):
        deployment = {
            "lakehouse": {"id": LAKEHOUSE},
            "notebooks": [{"display_name": run_track1.NOTEBOOK_NAME, "notebook_id": "notebook"}],
        }
        with (
            patch.object(run_track1.deploy_fabric, "deploy", return_value=deployment),
            patch.object(
                run_track1,
                "_execute_notebook",
                return_value={"job_status": "Completed", "exit_value": {"queries": {"status": "passed"}}},
            ),
            self.assertRaisesRegex(RuntimeError, "expected Track1 query"),
        ):
            run_track1.run(
                workspace_id=WORKSPACE,
                lakehouse_id=LAKEHOUSE,
                apply=True,
                fabric_token="token",
            )


if __name__ == "__main__":
    unittest.main()
