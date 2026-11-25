import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

from tools import live_demo, run_track4_demo as track4

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
WORKSPACE = "00000000-0000-0000-0000-000000000001"
LAKEHOUSE = "00000000-0000-0000-0000-000000000002"
SERVER = "example.datawarehouse.fabric.microsoft.com"
DATABASE = "Workshop Lakehouse"
SUBSCRIPTION = UUID("a9737323-1111-2222-3333-444455556666")


def live_response(text, urls=()):
    output = []
    if urls:
        output.append({"type": "web_search_call", "status": "completed"})
    output.append({
        "type": "message", "role": "assistant", "status": "completed",
        "content": [{
            "type": "output_text", "text": text,
            "annotations": [{"type": "url_citation", "title": url, "url": url} for url in urls],
        }],
    })
    return {"id": "resp_test", "status": "completed", "output": output}


class Track4DemoTests(unittest.TestCase):
    def test_missing_identity_records_blocked_report_without_service_calls(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(track4.auth, "cli_json") as az,
            patch.object(live_demo, "_json_request") as http,
            tempfile.TemporaryDirectory() as folder,
        ):
            report = track4.run(NOW)
            path = track4.save_report(report, Path(folder), NOW)
            self.assertEqual(json.loads(path.read_text()), report)
            markdown = path.with_suffix(".md").read_text()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["preflight"]["foundry"]["status"], "not-run")
        self.assertIn("IQ_AZURE_TENANT_ID", markdown)
        self.assertIn("Not run: Q1, Q2, Q3, Q4, Q5", markdown)
        az.assert_not_called()
        http.assert_not_called()

    def test_disabled_subscription_is_rejected_before_model_calls(self):
        identity = track4.auth.AzureDemoIdentity("tenant", "demo@example.com")
        with (
            patch.dict(os.environ, {"AZURE_OPENAI_SUBSCRIPTION": "selected"}, clear=True),
            patch.object(track4.auth, "require_separate_identity", return_value=identity),
            patch.object(track4, "_fabric_ready", return_value=(SERVER, DATABASE)),
            patch.object(track4.auth, "cli_json", return_value={
                "tenantId": "tenant", "user": {"name": "demo@example.com"}, "state": "Disabled",
            }) as az,
            patch.object(live_demo, "_post_foundry_response") as post,
        ):
            report = track4.run(NOW)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("not Enabled", report["preflight"]["foundry"]["error"])
        az.assert_called_once_with("account", "show", "--subscription", "selected")
        post.assert_not_called()

    def test_fabric_target_uses_selected_lakehouse_metadata_only(self):
        item = {
            "type": "Lakehouse", "id": LAKEHOUSE, "workspaceId": WORKSPACE, "displayName": DATABASE,
            "properties": {"sqlEndpointProperties": {"provisioningStatus": "Success", "connectionString": SERVER}},
        }
        identity = Mock()
        with (
            patch.dict(os.environ, {
                "FABRIC_WORKSPACE_ID": WORKSPACE, "FABRIC_LAKEHOUSE_ID": LAKEHOUSE,
                "FABRIC_SQL_SERVER": "unrelated.invalid", "FABRIC_SQL_DATABASE": "other",
            }, clear=True),
            patch.object(live_demo, "_json_request", return_value=item) as get,
        ):
            self.assertEqual(track4._fabric_ready(identity), (SERVER, DATABASE))
            get.assert_called_once_with(
                f"{track4.FABRIC_API}/v1/workspaces/{WORKSPACE}/lakehouses/{LAKEHOUSE}",
                token=identity.token.return_value, no_redirect=True,
            )
            item["properties"]["sqlEndpointProperties"]["connectionString"] += ".invalid"
            with self.assertRaisesRegex(ValueError, "valid SQL endpoint"):
                track4._fabric_ready(identity)

    def _run_pipeline(self, *, fail=False, scenario=None):
        web_requests = []
        synthesis = {}
        identity = Mock()

        def respond(body):
            if "tools" in body:
                web_requests.append(body)
                if fail and len(web_requests) == 1:
                    return live_response("not grounded")
                return live_response(body["input"], ["https://public.example/source"])
            self.assertFalse(body["store"])
            evidence = json.loads(body["input"])
            synthesis[evidence["scenarioId"]] = evidence
            if fail and evidence["scenarioId"] == "Q3":
                return {"id": "incomplete", "status": "incomplete", "output": []}
            return live_response("Synthesized answer")

        def fabric(scenario, *, azure, target):
            self.assertIs(azure, identity)
            self.assertEqual(target, (SERVER, DATABASE))
            if fail and scenario == "Q2":
                raise live_demo.LiveServiceError("SQL is unavailable")
            return {
                "queryId": scenario, "status": "succeeded", "rows": [{"orders": 1}],
                "identity": "azure@example.com",
            }

        with (
            patch.object(track4.auth, "require_separate_identity", return_value=identity),
            patch.object(live_demo, "prepare_separate_foundry", return_value=("model", respond)) as prepare,
            patch.object(track4, "_fabric_ready", return_value=(SERVER, DATABASE)),
            patch.object(live_demo, "_fabric_query", side_effect=fabric) as sql,
            patch.object(live_demo, "_work_search") as graph,
            patch.object(live_demo, "_web_search") as second_search,
        ):
            preflight = track4.run(NOW, scenario=scenario, preflight_only=True)
            self.assertEqual(preflight["status"], "ready")
            prepare.assert_called_once_with(identity, allow_services_endpoint=True)
            sql.assert_not_called()
            self.assertFalse(web_requests or synthesis)
            report = track4.run(NOW, scenario=scenario)
        graph.assert_not_called()
        second_search.assert_not_called()
        selected = [scenario] if scenario else list(track4.SCENARIOS)
        self.assertEqual([call.args[0] for call in sql.call_args_list], selected)
        specs = track4.webiq.load_specs("demo", NOW, 7)
        self.assertEqual([request["input"] for request in web_requests], [specs[key]["query"] for key in selected])
        return report, synthesis

    def test_standalone_scenarios_collect_aligned_citations_and_skip_graph(self):
        report, synthesis = self._run_pipeline()
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(set(synthesis), set(track4.SCENARIOS))
        for row in report["scenarios"]:
            evidence = synthesis[row["scenarioId"]]
            self.assertEqual(evidence["web"], row["web"])
            self.assertEqual(evidence["sources"]["work"]["status"], "skipped")
            self.assertNotIn("identity", evidence["fabric"])
            self.assertEqual(row["foundryResponseId"], "resp_test")

    def test_single_scenario_does_not_query_the_other_four(self):
        report, synthesis = self._run_pipeline(scenario="Q3")
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["plannedScenarios"], ["Q3"])
        self.assertEqual(list(synthesis), ["Q3"])

    def test_live_failures_are_isolated_and_never_reported_as_synthesis_success(self):
        report, synthesis = self._run_pipeline(fail=True)
        self.assertEqual(report["status"], "incomplete")
        rows = {row["scenarioId"]: row for row in report["scenarios"]}
        self.assertEqual(rows["Q1"]["sources"]["web"]["status"], "failed")
        self.assertEqual(rows["Q2"]["sources"]["fabric"]["status"], "failed")
        self.assertEqual(rows["Q3"]["synthesisStatus"], "failed")
        self.assertEqual(set(synthesis), {"Q3", "Q4", "Q5"})
        self.assertEqual(rows["Q5"]["synthesisStatus"], "succeeded")

    def test_provisioned_run_reuses_checked_live_rows_and_ignores_shared_foundry_settings(self):
        identity = Mock()
        calls = []

        def sql(scenario, *, azure, target):
            calls.append(f"sql:{scenario}")
            self.assertIs(azure, identity)
            self.assertEqual(target, (SERVER, DATABASE))
            return {"status": "succeeded", "queryId": scenario, "identity": "demo@example.com",
                    "rows": [{"order": index} for index in range(track4.FIXTURE_COUNTS[scenario])]}

        def provision(target, user):
            calls.append("provision")
            self.assertEqual(target.track, "foundryiq")
            self.assertIs(user, identity)

        def invoke(endpoint, body, *, azure, subscription, rate_limit_wait):
            self.assertEqual(endpoint, "https://iq-foundryiq-a97373231111.services.ai.azure.com/openai/v1")
            self.assertEqual(subscription, str(SUBSCRIPTION))
            self.assertIs(azure, identity)
            self.assertFalse(body["store"])
            if body.get("tools"):
                return live_response("Public context", ["https://public.example/source"])
            if body["input"] == "Reply with OK only.":
                calls.append("smoke")
                return live_response("OK")
            evidence = json.loads(body["input"])
            self.assertNotIn("identity", evidence["fabric"])
            self.assertEqual(len(evidence["fabric"]["rows"]), track4.FIXTURE_COUNTS[evidence["scenarioId"]])
            return live_response("Demo answer")

        with (
            patch.dict(os.environ, {"AZURE_OPENAI_ENDPOINT": "https://track3.openai.azure.com"}, clear=True),
            patch.object(track4.auth, "require_separate_identity", return_value=identity),
            patch.object(track4, "_fabric_ready", return_value=(SERVER, DATABASE)),
            patch.object(live_demo, "_fabric_query", side_effect=sql),
            patch.object(track4.provisioning, "provision", side_effect=provision),
            patch.object(live_demo, "_azure_foundry_responses", side_effect=invoke),
            patch.object(live_demo, "prepare_separate_foundry") as shared,
            patch.object(live_demo, "_work_search") as graph,
        ):
            report = track4.run(NOW, provision_subscription=SUBSCRIPTION)
        shared.assert_not_called()
        graph.assert_not_called()
        self.assertEqual(calls, [f"sql:{scenario}" for scenario in track4.SCENARIOS] + ["provision", "smoke"])
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["preflight"]["inference"]["responseId"], "resp_test")
        self.assertEqual(report["preflight"]["fabricSQL.Q5"]["rows"], 81)

    def test_provision_rejects_bad_fixture_or_standalone_key_before_azure_writes(self):
        for credentials, gate in (({}, "fabricSQL.Q1"), ({"AZURE_OPENAI_API_KEY": "unused"}, "foundryCredentials")):
            with (
                self.subTest(gate=gate), patch.dict(os.environ, credentials, clear=True),
                patch.object(track4.auth, "require_separate_identity"),
                patch.object(track4, "_fabric_ready", return_value=(SERVER, DATABASE)),
                patch.object(live_demo, "_fabric_query", return_value={"status": "succeeded", "rows": [{"wrong": 1}]}),
                patch.object(track4.provisioning, "provision") as provision,
                patch.object(live_demo, "_azure_foundry_responses") as respond,
            ):
                report = track4.run(NOW, scenario="Q1", provision_subscription=SUBSCRIPTION)
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(report["preflight"][gate]["status"], "blocked")
                provision.assert_not_called()
                respond.assert_not_called()

    def test_inference_smoke_retries_role_propagation_but_not_invalid_requests(self):
        pending = live_demo.LiveHttpError("HTTP 401: PermissionDenied", 401, None)
        with patch.object(track4.time, "sleep") as sleep:
            respond = Mock(side_effect=[pending, live_response("OK")])
            self.assertEqual(track4._verify_inference("model", respond), "resp_test")
            sleep.assert_called_once_with(15)

            for error in (live_demo.LiveHttpError("HTTP 400: InvalidRequest", 400, None), pending):
                with self.subTest(error=error):
                    respond = Mock(side_effect=error)
                    with self.assertRaises(live_demo.LiveHttpError):
                        track4._verify_inference("model", respond)
                    self.assertEqual(respond.call_count, 7 if error is pending else 1)

    def test_shared_stack_ownership_tags_cannot_be_reused_by_track4(self):
        target = track4._dedicated_target(SUBSCRIPTION)
        with (
            patch.object(track4.auth, "token_claims", return_value={"oid": str(SUBSCRIPTION)}),
            patch.object(track4.provisioning.Target, "arm", return_value={"state": "Enabled"}) as arm,
            patch.object(track4.provisioning.Target, "az", side_effect=[
                "Registered", True, {"tags": {"iq-demo-track": "webiq"}, "location": "eastus"},
            ]) as az,
            self.assertRaisesRegex(ValueError, "without the foundryiq tag"),
        ):
            track4.provisioning.provision(target, Mock(account="demo@example.com"))
        self.assertEqual([call.args[0] for call in arm.call_args_list], ["get"])
        self.assertEqual([call.args[:2] for call in az.call_args_list],
                         [("provider", "show"), ("group", "exists"), ("group", "show")])
