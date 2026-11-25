import base64
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tools import live_demo
from tools import azure_demo_auth


def graph_token(claims):
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"header.{payload}.signature"


class LiveDemoTests(unittest.TestCase):
    def test_all_live_scenarios_match_track3_queries(self):
        scenarios = live_demo._read_json("track4/scenarios.json")
        queries = live_demo._read_json("track3/data/queries.json")
        self.assertEqual(set(scenarios), {f"Q{i}" for i in range(1, 6)})
        self.assertEqual(set(queries) - {"executionMode"}, set(scenarios))
        self.assertEqual(queries["executionMode"], "live")
        for scenario_id in scenarios:
            self.assertIn("workSearchTerms", scenarios[scenario_id])
            self.assertIn("limitations", scenarios[scenario_id])
            self.assertNotIn("publicSearchQuery", scenarios[scenario_id])

    def test_graph_token_rejects_non_graph_audience(self):
        token = graph_token({"aud": "https://example.invalid", "scp": "Mail.Read"})
        with self.assertRaisesRegex(live_demo.LiveServiceError, "not issued for Microsoft Graph"):
            live_demo._graph_token_claims(token)

    def test_graph_search_scopes_fail_per_source_not_as_a_global_gate(self):
        token = graph_token({
            "aud": "https://graph.microsoft.com/",
            "preferred_username": "demo@example.com",
            "scp": "Sites.Read.All Mail.Read",
        })
        env = {
            "TRACK2_SHAREPOINT_SCOPE": 'path:"/sites/demo"',
            "TRACK2_ONEDRIVE_SCOPE": 'path:"/users/demo"',
            "TRACK2_OUTLOOK_SCOPE": 'subject:demo',
            "TRACK2_TEAMS_SCOPE": 'channel:demo',
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            live_demo, "_graph_search", return_value=[]
        ) as search:
            result = live_demo._work_search(
                live_demo._scenario("Q1"), token=token
            )
        self.assertEqual(result["identity"], "demo@example.com")
        self.assertEqual(result["sources"]["SharePoint"]["status"], "no-evidence")
        self.assertEqual(result["sources"]["Outlook"]["status"], "no-evidence")
        self.assertEqual(result["sources"]["OneDrive"]["status"], "failed")
        self.assertEqual(result["sources"]["Teams"]["status"], "failed")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(search.call_count, 2)

    def test_teams_index_requires_channel_and_chat_scopes(self):
        for scopes, expected in (
            ("ChannelMessage.Read.All", False),
            ("Chat.Read", False),
            ("ChannelMessage.Read.All Chat.Read", True),
            ("ChannelMessage.Read.All Chat.ReadWrite", True),
        ):
            with self.subTest(scopes=scopes), patch.dict(
                os.environ, {"TRACK2_TEAMS_SCOPE": "channel:demo"}, clear=True
            ), patch.object(live_demo, "_graph_search", return_value=[]) as search:
                token = graph_token({"aud": "https://graph.microsoft.com", "scp": scopes})
                result = live_demo._work_search(live_demo._scenario("Q1"), token=token)
                self.assertEqual(search.called, expected)
                self.assertEqual(result["sources"]["Teams"]["status"], "no-evidence" if expected else "failed")

    def test_integrated_run_blocks_when_both_internal_sources_are_unavailable(self):
        with (
            patch.object(live_demo, "_fabric_query", side_effect=live_demo.LiveServiceError("offline")),
            patch.object(live_demo, "_work_search", side_effect=live_demo.LiveServiceError("offline")),
            patch.object(live_demo, "_web_search", return_value={
                "status": "succeeded", "citations": [{"url": "https://example.com"}]
            }),
            patch.object(live_demo, "_foundry_responses") as synthesis,
        ):
            result = live_demo.run_live("Q1")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["executionMode"], "live")
        self.assertFalse(synthesis.called)

    def test_identity_mismatch_discards_work_results(self):
        with (
            patch.object(live_demo, "_fabric_query", return_value={
                "identity": "fabric@example.com",
                "status": "succeeded",
                "rows": [{"order_count": 1}],
            }),
            patch.object(live_demo, "_work_search", return_value={
                "status": "succeeded",
                "identity": "other@example.com",
                "sources": {"SharePoint": {"items": [{"id": "secret"}]}}
            }),
            patch.object(live_demo, "_web_search", return_value={
                "status": "succeeded", "citations": [{"url": "https://example.com"}]
            }),
        ):
            _, _, work_result, _ = live_demo._scenario_evidence("Q1")
        self.assertEqual(work_result["status"], "failed")
        self.assertNotIn("data", work_result)
        self.assertIn("same user", work_result["error"])

    def test_separate_azure_run_does_not_read_or_synthesize_track2_evidence(self):
        azure = azure_demo_auth.AzureDemoIdentity("azure-tenant", "azure@example.com")
        with (
            patch.object(live_demo, "separate_identity", return_value=azure),
            patch.object(live_demo, "_fabric_query", return_value={
                "identity": "azure@example.com", "status": "succeeded", "rows": [{"orders": 1}],
            }),
            patch.object(live_demo, "_work_search") as work,
            patch.object(live_demo, "_web_search", return_value={"status": "succeeded", "citations": []}),
            patch.object(live_demo, "_foundry_config", return_value=("endpoint", "model", None, None)),
            patch.object(live_demo, "_foundry_responses") as foundry,
            patch.object(live_demo, "_response_text", return_value="result"),
        ):
            result = live_demo.run_live("Q1")
            sent = json.loads(foundry.call_args.args[0]["input"])
        work.assert_not_called()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(sent["sources"]["work"]["status"], "skipped")
        self.assertNotIn("work", sent)

    def test_separate_profile_rejects_the_track2_tenant_before_access(self):
        tenant = "00000000-0000-0000-0000-000000000001"
        with (
            patch.dict(os.environ, {
                "AZURE_CONFIG_DIR": "/tmp/iq-separate-cache",
                "IQ_AZURE_TENANT_ID": tenant, "IQ_M365_TENANT_ID": tenant,
                "IQ_AZURE_ACCOUNT": "azure@example.com", "IQ_M365_ACCOUNT": "publisher@example.com",
            }, clear=True),
            patch.object(azure_demo_auth, "TRACK2_CONFIG") as config,
            patch.object(azure_demo_auth, "cli_json") as az,
        ):
            config.is_file.return_value = False
            with self.assertRaisesRegex(azure_demo_auth.AzureContextError, "tenant must differ"):
                azure_demo_auth.separate_identity()
            az.assert_not_called()

    def test_separate_profile_checks_cli_and_token_identity(self):
        azure = azure_demo_auth.AzureDemoIdentity("azure-tenant", "dev@example.com")
        account = {"tenantId": "azure-tenant", "user": {"name": "Dev@example.com"}, "state": "Enabled"}
        good = graph_token({"tid": "azure-tenant", "upn": "dev@example.com"})
        wrong = graph_token({"tid": "azure-tenant", "upn": "other@example.com"})
        with patch.object(azure_demo_auth, "cli_json", side_effect=[account, good, account, wrong]) as az:
            self.assertEqual(azure.get_token("https://database.windows.net/.default").token, good)
            self.assertIn("--tenant", az.call_args_list[1].args)
            with self.assertRaisesRegex(azure_demo_auth.AzureContextError, "does not belong"):
                azure.token(scope="https://ai.azure.com/.default", subscription="one")
            self.assertIn("--subscription", az.call_args.args)

    def test_separate_foundry_will_not_send_evidence_to_an_unverified_endpoint(self):
        azure = azure_demo_auth.AzureDemoIdentity("azure-tenant", "dev@example.com")
        with (
            patch.dict(os.environ, {
                "AZURE_OPENAI_ENDPOINT": "https://wrong.openai.azure.com",
                "AZURE_OPENAI_MODEL": "some-model",
                "AZURE_OPENAI_SUBSCRIPTION": "one",
                "AZURE_RESOURCE_GROUP": "rg",
                "AZURE_AI_ACCOUNT_NAME": "correct",
            }, clear=True),
            patch.object(live_demo, "separate_identity", return_value=azure),
            patch.object(azure_demo_auth, "cli_json", side_effect=[
                {"tenantId": "azure-tenant", "user": {"name": "dev@example.com"}, "state": "Enabled"},
                "correct",
            ]),
            patch.object(live_demo, "_json_request") as post,
        ):
            with self.assertRaisesRegex(azure_demo_auth.AzureContextError, "endpoint does not match"):
                live_demo._foundry_responses({"input": "private data"})
            post.assert_not_called()

    def test_fabric_identity_normalizes_sql_server_prefix(self):
        self.assertEqual(
            live_demo._normalize_identity(r"AzureAD\Demo@Example.com"),
            "demo@example.com",
        )

    def test_fabric_uses_driver_login_timeout_and_verified_token_provider(self):
        connect = MagicMock()
        connection = connect.return_value.__enter__.return_value
        identity_cursor, data_cursor = MagicMock(), MagicMock()
        connection.cursor.side_effect = [identity_cursor, data_cursor]
        identity_cursor.fetchone.return_value = ("demo@example.com",)
        data_cursor.description = [("orders",)]
        data_cursor.fetchall.return_value = [(1,)]
        azure = azure_demo_auth.AzureDemoIdentity("tenant", "demo@example.com")
        with patch.dict(sys.modules, {"mssql_python": SimpleNamespace(connect=connect)}):
            result = live_demo._fabric_query("Q1", azure=azure, target=("demo.example.com", "demo"))
        self.assertEqual(result["rows"], [{"orders": 1}])
        self.assertNotIn("Connection Timeout", connect.call_args.args[0])
        self.assertEqual(connect.call_args.kwargs, {"timeout": 30, "token_provider": azure})

    def test_foundry_retries_only_bounded_transient_http_errors(self):
        for status, after, sleeps in ((429, "3", [3, 3]), (503, None, [1, 2]), (503, "31", []), (403, None, [])):
            with (
                self.subTest(status=status, retry_after=after),
                patch.object(live_demo, "_json_request", side_effect=live_demo.LiveHttpError("request failed", status, after)) as post,
                patch.object(live_demo.time, "sleep") as sleep,
            ):
                with self.assertRaises(live_demo.LiveHttpError):
                    live_demo._post_foundry_response("https://example.invalid", {})
                self.assertEqual(post.call_count, 1 + len(sleeps))
                self.assertEqual([call.args[0] for call in sleep.call_args_list], sleeps)

    def test_provisioned_briefing_can_wait_for_rate_limit_to_reset(self):
        for status, after, sleeps in ((429, "75", [75]), (429, "121", []), (429, None, [120]), (503, "75", [])):
            err = live_demo.LiveHttpError("request failed", status, after)
            with (
                self.subTest(status=status, after=after),
                patch.object(live_demo, "_json_request", side_effect=[err, {"status": "completed"}]),
                patch.object(live_demo.time, "sleep") as sleep,
            ):
                if sleeps:
                    result = live_demo._post_foundry_response("https://example.invalid", {}, rate_limit_wait=120)
                    self.assertEqual(result["status"], "completed")
                else:
                    with self.assertRaises(live_demo.LiveHttpError):
                        live_demo._post_foundry_response("https://example.invalid", {}, rate_limit_wait=120)
                self.assertEqual([call.args[0] for call in sleep.call_args_list], sleeps)


if __name__ == "__main__":
    unittest.main()
