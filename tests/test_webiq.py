import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from tools import azure_demo_auth as auth, live_demo, run_track3_daily_briefing as briefing, webiq
from tools import provision_track3_foundry as provisioning

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def response_with(*urls, call_status="completed"):
    return {
        "status": "completed",
        "id": "resp_test",
        "output": [
            {"type": "web_search_call", "status": call_status, "action": {
                "sources": [{"url": "https://status.stripe.com/source-only"}],
            }},
            {"type": "message", "role": "assistant", "content": [{
                "type": "output_text", "text": "Review this grounded output.",
                "annotations": [{"type": "url_citation", "url": url, "title": "Official source"} for url in urls],
            }]},
        ],
    }


class WebIQTests(unittest.TestCase):
    def setUp(self):
        self.spec = webiq.load_specs("workshop", NOW, 7)["Q1"]

    def test_workshop_sends_only_public_prompt_and_enforces_domain_filter(self):
        respond = Mock(return_value=response_with(
            "https://status.stripe.com/incidents/a", "https://www.paypal-status.com/incident/b",
        ))
        with patch.dict(os.environ, {"GRAPH_ACCESS_TOKEN": "private-marker"}, clear=False):
            actual = webiq.search("Q1", self.spec, "deployment", respond)
        payload = respond.call_args.args[0]
        self.assertNotIn("private-marker", json.dumps(payload))
        self.assertIn("2026-11-16", payload["input"])
        self.assertEqual(payload["tool_choice"], {"type": "web_search"})
        self.assertFalse(payload["store"])
        self.assertEqual(payload["tools"][0]["filters"]["allowed_domains"], self.spec["allowedDomains"])
        self.assertIn("URL host is exactly one of: " + ", ".join(self.spec["allowedDomains"]), payload["instructions"])
        self.assertEqual(actual["status"], "succeeded")
        self.assertEqual(len(actual["citations"]), 2)
        self.assertTrue(all(cite["factStatus"] == "live-observation" for cite in actual["citations"]))
        self.assertTrue(actual["humanApprovalRequired"])

    def test_consulted_links_and_duplicate_annotations_do_not_satisfy_minimum(self):
        response = response_with(
            "https://status.stripe.com/incidents/a?utm_source=first",
            "https://status.stripe.com/incidents/a#other",
        )
        result = webiq.search("Q1", self.spec, "deployment", Mock(return_value=response))
        self.assertEqual(result["status"], "no-evidence")
        self.assertEqual(result["validCitations"], 1)
        self.assertNotIn("answer", result)

    def test_invalid_domain_blocks_publication_even_with_two_valid_citations(self):
        response = response_with(
            "https://status.stripe.com/incidents/a", "https://www.paypal-status.com/b",
            "https://status.stripe.com.example.test/impersonation",
        )
        result = webiq.search("Q1", self.spec, "deployment", Mock(return_value=response))
        self.assertEqual(result["status"], "no-evidence")
        self.assertEqual(result["rejectedCitations"], 1)
        self.assertEqual(result["citations"], [])

    def test_incomplete_search_call_cannot_be_reported_as_live_evidence(self):
        with self.assertRaisesRegex(ValueError, "no completed web_search_call"):
            webiq.search("Q1", self.spec, "deployment", Mock(return_value=response_with(
                "https://status.stripe.com", call_status="in_progress",
            )))

    def test_workshop_q3_remains_separate_from_integrated_q3(self):
        workshop = webiq.load_specs("workshop", NOW, 7)
        demo = webiq.load_specs("demo", NOW, 7)
        self.assertIn("CPSC", workshop["Q3"]["query"])
        self.assertIn("promotion discounts", demo["Q3"]["query"])
        self.assertNotIn("AeroPhone", workshop["Q3"]["query"])

    def test_briefing_preserves_real_failure_and_still_runs_other_scenarios(self):
        spec = {"Q1": self.spec, "Q2": self.spec}
        respond = Mock(side_effect=[
            live_demo.LiveServiceError("HTTP 403"),
            response_with("https://status.stripe.com/a", "https://paypal-status.com/b"),
        ])
        report = briefing.run("workshop", spec, "deployment", respond, NOW)
        self.assertEqual(report["status"], "incomplete")
        with tempfile.TemporaryDirectory() as output:
            path = briefing.save_report(report, Path(output), NOW)
            saved = json.loads((path / "briefing.json").read_text())
            self.assertEqual([r["status"] for r in saved["scenarios"]], ["failed", "succeeded"])
            self.assertIn("HTTP 403", (path / "briefing.md").read_text())

    def test_all_profiles_run_public_searches_only_and_write_separate_briefings(self):
        def respond(body):
            self.assertEqual(body["tool_choice"], {"type": "web_search"})
            domains = body["tools"][0].get("filters", {}).get("allowed_domains")
            return response_with(
                f"https://{domains[0]}/reference/a", f"https://{domains[0]}/reference/b",
            ) if domains else response_with("https://public.example/source")

        with (
            tempfile.TemporaryDirectory() as output,
            patch("sys.argv", ["briefing", "--profile", "all", "--output-dir", output]),
            patch.object(briefing, "require_separate_identity") as identity,
            patch.object(live_demo, "prepare_separate_foundry", return_value=("model", Mock(side_effect=respond))) as foundry,
            patch.object(live_demo, "_fabric_query") as sql,
            patch.object(live_demo, "_work_search") as graph,
            redirect_stdout(io.StringIO()) as stdout,
        ):
            self.assertEqual(briefing.main(), 0)
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["status"], "succeeded")
            self.assertEqual(set(summary["profiles"]), {"workshop", "demo"})
            for profile, result in summary["profiles"].items():
                saved = json.loads(Path(result["report"]).read_text())
                self.assertEqual([row["scenarioId"] for row in saved["scenarios"]], list(webiq.PROFILES[profile]))
            foundry.assert_called_once_with(identity.return_value, allow_services_endpoint=True)
            self.assertEqual(foundry.return_value[1].call_count, 8)
            sql.assert_not_called()
            graph.assert_not_called()

    def test_azure_endpoint_rejects_credentials_and_non_azure_hosts(self):
        for endpoint in ("https://service.openai.azure.com@other.test", "https://other.test"):
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {
                "AZURE_OPENAI_ENDPOINT": endpoint, "AZURE_OPENAI_MODEL": "test", "AZURE_OPENAI_API_KEY": "key",
            }, clear=True), self.assertRaises(live_demo.LiveServiceError):
                live_demo._foundry_config()

    def test_foundry_uses_azure_cli_without_persisting_the_bearer(self):
        with (
            patch.dict(os.environ, {
                "AZURE_OPENAI_ENDPOINT": "https://service.openai.azure.com/openai/v1/responses",
                "AZURE_OPENAI_MODEL": "test", "AZURE_OPENAI_SUBSCRIPTION": "target-subscription",
            }, clear=True),
            patch.object(live_demo, "_azure_cli_json", return_value="bearer-in-memory") as az,
            patch.object(live_demo, "_json_request", return_value={}) as post,
        ):
            live_demo._foundry_responses({"input": "public only"})
            self.assertNotIn("AZURE_OPENAI_AUTH_TOKEN", os.environ)
        self.assertIn("target-subscription", az.call_args.args)
        self.assertEqual(post.call_args.args, ("https://service.openai.azure.com/openai/v1/responses",))
        self.assertEqual(post.call_args.kwargs["token"], "bearer-in-memory")
        self.assertTrue(post.call_args.kwargs["no_redirect"])

    def test_separate_runners_recover_missing_endpoint_from_approved_account(self):
        identity = auth.AzureDemoIdentity("tenant", "demo@example.com")
        with (
            patch.dict(os.environ, {
                "AZURE_OPENAI_SUBSCRIPTION": "chosen", "AZURE_RESOURCE_GROUP": "demo",
                "AZURE_AI_ACCOUNT_NAME": "approved", "AZURE_OPENAI_MODEL": "deployment",
            }, clear=True),
            patch.object(auth, "cli_json", side_effect=[
                {"tenantId": "tenant", "user": {"name": "demo@example.com"}, "state": "Enabled"}, "verified-domain",
            ]),
            patch.object(live_demo, "_azure_cli_json", return_value="Succeeded"),
            patch.object(live_demo, "_azure_foundry_responses") as responses,
        ):
            model, respond = live_demo.prepare_separate_foundry(identity)
            respond({"model": model, "input": "public question"})
            self.assertNotIn("AZURE_OPENAI_ENDPOINT", os.environ)
        responses.assert_called_once_with(
            "https://verified-domain.openai.azure.com/openai/v1",
            {"model": "deployment", "input": "public question"}, azure=identity, subscription="chosen",
        )

    def test_track3_accepts_explicit_services_endpoint_of_approved_account(self):
        env = {"AZURE_OPENAI_ENDPOINT": "https://approved.services.ai.azure.com"}
        with (
            tempfile.TemporaryDirectory() as output,
            patch.dict(os.environ, env, clear=True),
            patch("sys.argv", [
                "briefing", "--scenario", "Q1", "--output-dir", output, "--subscription", "chosen",
                "--resource-group", "demo", "--account", "approved", "--deployment", "my-deployment",
            ]),
            patch.object(briefing, "require_separate_identity", return_value=auth.AzureDemoIdentity("tenant", "demo@example.com")),
            patch.object(auth, "cli_json", side_effect=[
                {"tenantId": "tenant", "user": {"name": "demo@example.com"}, "state": "Enabled"}, "approved",
                {"tenantId": "tenant", "user": {"name": "demo@example.com"}, "state": "Enabled"}, "approved",
            ]),
            patch.object(live_demo, "_azure_cli_json", return_value="Succeeded"),
            patch.object(live_demo, "_azure_foundry_responses", return_value=response_with(
                "https://status.stripe.com/a", "https://paypal-status.com/b",
            )) as respond,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(briefing.main(), 0)
            self.assertEqual(respond.call_args.args[0], "https://approved.services.ai.azure.com/openai/v1")
            self.assertEqual(os.environ["AZURE_OPENAI_ENDPOINT"], env["AZURE_OPENAI_ENDPOINT"])
            os.environ["AZURE_OPENAI_ENDPOINT"] = "https://other.services.ai.azure.com"
            self.assertEqual(briefing.main(), 1)
            self.assertEqual(respond.call_count, 1)

    def test_provisioned_config_replaces_only_the_live_track3_target(self):
        target = {
            "subscription": "selected", "resourceGroup": "dedicated", "account": "webiq",
            "deployment": "deployment", "endpoint": "https://webiq.services.ai.azure.com",
        }
        respond = Mock(return_value=response_with("https://example.com/source"))
        with (
            tempfile.TemporaryDirectory() as output,
            patch.dict(os.environ, {"AZURE_OPENAI_ENDPOINT": "https://original.openai.azure.com"}, clear=True),
            patch.object(briefing, "require_separate_identity"),
            patch.object(live_demo, "prepare_separate_foundry") as foundry,
            redirect_stdout(io.StringIO()),
        ):
            path = Path(output) / "foundry.local.json"
            path.write_text(json.dumps(target), encoding="utf-8")

            def prepare(*args, **kwargs):
                self.assertEqual(os.environ["AZURE_OPENAI_ENDPOINT"], target["endpoint"])
                self.assertEqual(os.environ["AZURE_OPENAI_SUBSCRIPTION"], target["subscription"])
                self.assertEqual(os.environ["AZURE_AI_ACCOUNT_NAME"], target["account"])
                return "deployment", respond

            foundry.side_effect = prepare
            argv = ["briefing", "--profile", "demo", "--scenario", "Q1", "--output-dir", output,
                    "--provisioned-config", str(path)]
            with patch("sys.argv", argv):
                self.assertEqual(briefing.main(), 0)
            with patch("sys.argv", argv + ["--subscription", "other"]):
                self.assertEqual(briefing.main(), 1)
            foundry.assert_called_once_with(unittest.mock.ANY, allow_services_endpoint=True, rate_limit_wait=120)
            self.assertEqual(respond.call_args.args[0]["max_output_tokens"], 10_000)


class WebIQProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.target = provisioning.Target(
            "11111111-1111-1111-1111-111111111111", "webiq-rg", "webiq-ai",
            "eastus", "gpt-5.6-sol", "2026-07-09", 100,
        )
        self.principal = "22222222-2222-2222-2222-222222222222"
        self.identity = Mock(account="demo@example.com")

    def test_provision_plan_does_not_access_azure_or_write_config(self):
        argv = [
            "provision", "--subscription", self.target.subscription, "--resource-group", self.target.group,
            "--account", self.target.account, "--location", self.target.location,
        ]
        with (
            patch("sys.argv", argv), patch.object(auth, "require_separate_identity") as identity,
            patch.object(provisioning, "CONFIG_PATH") as config, redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(provisioning.main(), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "plan")
            identity.assert_not_called()
            config.write_text.assert_not_called()

    def test_provision_refuses_an_existing_group_that_is_not_track3(self):
        with (
            patch.object(auth, "token_claims", return_value={"oid": self.principal}),
            patch.object(provisioning.Target, "arm", return_value={"state": "Enabled"}) as arm,
            patch.object(provisioning.Target, "az", side_effect=["Registered", True, {"tags": {}}]) as az,
            self.assertRaisesRegex(ValueError, "existing resource group"),
        ):
            provisioning.provision(self.target, self.identity)
        self.assertEqual([call.args[0] for call in arm.call_args_list], ["get"])
        self.assertEqual([call.args[:2] for call in az.call_args_list],
                         [("provider", "show"), ("group", "exists"), ("group", "show")])

    def test_quota_is_checked_before_any_resource_is_created(self):
        model = {"name": self.target.model, "version": self.target.version, "format": "OpenAI",
                 "skus": [{"name": provisioning.SKU, "capacity": {"maximum": 1000}}]}
        usage = {"name": {"value": "OpenAI.GlobalStandard.gpt-5.6-sol"}, "limit": 100, "currentValue": 90}
        with (
            patch.object(auth, "token_claims", return_value={"oid": self.principal}),
            patch.object(provisioning.Target, "arm", side_effect=[
                {"state": "Enabled"}, {"isSubdomainAvailable": True},
            ]) as arm,
            patch.object(provisioning.Target, "az", side_effect=[
                "Registered", False, [{"model": model}], [usage],
            ]) as az,
            self.assertRaisesRegex(ValueError, "10 capacity units available, 100 requested"),
        ):
            provisioning.provision(self.target, self.identity)
        self.assertEqual([call.args[0] for call in arm.call_args_list], ["get", "post"])
        self.assertFalse(any("create" in call.args for call in az.call_args_list))

    def test_inference_role_is_added_only_on_the_new_account_and_then_reused(self):
        role = {
            "scope": self.target.account_id, "principalId": self.principal,
            "roleDefinitionId": f"/providers/Microsoft.Authorization/roleDefinitions/{provisioning.INFERENCE_ROLE}",
        }
        with patch.object(provisioning.Target, "az", side_effect=[[], role, [role]]) as az:
            provisioning.ensure_inference_role(self.target, self.principal)
            provisioning.ensure_inference_role(self.target, self.principal)
        creates = [call.args for call in az.call_args_list if call.args[:3] == ("role", "assignment", "create")]
        self.assertEqual(creates, [(
            "role", "assignment", "create", "--scope", self.target.account_id, "--role", provisioning.INFERENCE_ROLE,
            "--assignee-object-id", self.principal, "--assignee-principal-type", "User",
        )])
