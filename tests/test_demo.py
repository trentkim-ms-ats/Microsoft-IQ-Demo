import ast
import json
import re
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from tools import demo


class DemoTests(unittest.TestCase):
    def test_removed_legacy_tracks_are_rejected(self):
        for track in ("fabric", "all", "foundry"):
            result = subprocess.run(
                [sys.executable, str(demo.ROOT / "tools/demo.py"), "--track", track],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid choice", result.stderr)

    def test_guest_no_restricted_evidence(self):
        evidence = demo.work("guest")
        self.assertEqual({item["id"] for item in evidence}, {"D01", "D03", "D06"})
        serialized = json.dumps(evidence)
        for item in demo.work("presenter"):
            if "guest" not in item["roles"]:
                self.assertNotIn(item["path"], serialized)
                self.assertNotIn(item["id"], serialized)

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

if __name__ == "__main__":
    unittest.main()
