import ast
import json
import re
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from tools import demo


class DemoTests(unittest.TestCase):
    def test_metrics_and_denominators(self):
        metrics = demo.fabric()
        self.assertEqual([r["approval_rate_pct"] for r in metrics["Q1"]], [50, 75])
        self.assertEqual([r["order_count"] for r in metrics["Q1"]], [4, 4])
        self.assertEqual([r["returned_orders"] for r in metrics["Q2"]], [0, 2])
        self.assertEqual([r["contacted_orders"] for r in metrics["Q2"]], [1, 2])
        self.assertEqual([r["return_rate_pct"] for r in metrics["Q2"]], [0, 100])
        self.assertEqual([r["revenue_krw"] for r in metrics["Q3"]],
                         [200000, 200000, 200000])
        self.assertEqual([r["return_rate_pct"] for r in metrics["Q3"]], [50, 0, 100])

    def test_guest_no_restricted_evidence_or_traces(self):
        evidence = demo.work("guest")
        self.assertEqual({item["id"] for item in evidence}, {"D01", "D03", "D06"})
        responses = demo.combine(demo.fabric(), evidence, demo.web(), "normal", "guest")
        serialized = json.dumps(responses)
        for item in demo.work("presenter"):
            if "guest" not in item["roles"]:
                self.assertNotIn(item["path"], serialized)
                self.assertNotIn(item["id"], serialized)

    def test_failure_contract_all_scenarios(self):
        for mode, failed in demo.MODES.items():
            with self.subTest(mode=mode):
                responses = demo.combine(demo.fabric(), demo.work("presenter"),
                                         demo.web(), mode, "presenter")
                blocked = {"FabricIQ", "WorkIQ"}.issubset(failed)
                expected = "blocked" if blocked else ("partial" if failed else "complete")
                for response in responses:
                    self.assertEqual(response["status"], expected)
                    self.assertTrue(response["humanApprovalRequired"])
                    self.assertEqual(response["executionMode"], "simulation")
                    self.assertEqual(response["analysis"] is None, blocked)
                    self.assertEqual(response["metrics"] is None, "FabricIQ" in failed)
                    self.assertEqual(not response["evidenceLinks"], "WorkIQ" in failed)
                    self.assertEqual(not response["webCitations"], "WebIQ" in failed)
                    for trace in response["sourceTrace"]:
                        if trace["source"] in failed:
                            self.assertEqual(trace["references"], [])
                            self.assertEqual(trace["status"], "failed")

    def test_fixture_cannot_claim_live_fact_or_unapproved_host(self):
        original = demo.read_json
        for change in (
            {"url": "https://www.nist.gov.attacker.invalid/"},
            {"observedAt": "2026-01-01T00:00:00Z"},
            {"factStatus": "verified"},
        ):
            fixture = original("track3/data/citations.json")
            fixture["citations"][0].update(change)
            with self.subTest(change=change), patch.object(
                demo, "read_json",
                side_effect=lambda path: fixture if path.endswith("citations.json")
                else original(path),
            ):
                with self.assertRaises(ValueError):
                    demo.web()

    def test_missing_and_outside_input_fails(self):
        for path in ("missing.csv", "../outside.csv"):
            with self.assertRaises(ValueError):
                demo.local_file(path)

    def test_documents_json_python_and_local_links(self):
        root = demo.ROOT
        for path in root.rglob("*"):
            if ".git" in path.parts or "outputs" in path.parts or not path.is_file():
                continue
            if path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8"))
            if path.suffix == ".py":
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if path.suffix == ".md":
                text = path.read_text(encoding="utf-8")
                for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                    if "://" in target or target.startswith("#"):
                        continue
                    relative = unquote(target.split("#", 1)[0])
                    self.assertTrue((path.parent / relative).exists(),
                                    f"{path.relative_to(root)} -> {target}")
        ontology = demo.read_json("track1/ontology.json")
        names = {entity["name"] for entity in ontology["entities"]}
        self.assertEqual(len(names), 8)
        for relation in ontology["relationships"]:
            self.assertIn(relation["from"].split(".")[0], names)
            self.assertIn(relation["to"].split(".")[0], names)


if __name__ == "__main__":
    unittest.main()
