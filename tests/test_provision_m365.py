from contextlib import redirect_stderr, redirect_stdout
from http.client import RemoteDisconnected
from io import StringIO
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import provision_m365, publish_m365


class ProvisionM365Tests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "tenantId": "demo-tenant",
            "publisherUpn": "publisher@example.com",
            "restrictedUpn": "restricted@example.com",
            "teamDisplayName": "IQ Workshop Live Demo",
        }

    def test_plan_limits_restricted_user_to_participant_scope(self):
        plan = provision_m365.build_plan(self.config)
        self.assertEqual(
            plan["sharePoint"]["restrictedUserReadAccess"],
            ["IQ-Workshop/Participants"],
        )
        self.assertEqual(
            set(plan["teams"]["restrictedUserChannels"]),
            provision_m365.RESTRICTED_CHANNELS,
        )
        self.assertFalse(plan["userAccountsAndLicensesCreated"])

    def test_publisher_only_plan_does_not_grant_restricted_access(self):
        config = {key: value for key, value in self.config.items() if key != "restrictedUpn"}
        provision_m365._validate_config(config, publisher_only=True)
        plan = provision_m365.build_plan(config, publisher_only=True)
        self.assertIsNone(plan["restrictedUser"])
        self.assertEqual(plan["sharePoint"]["restrictedUserReadAccess"], [])
        self.assertEqual(plan["oneDrive"]["restrictedUserReadAccess"], [])
        self.assertEqual(plan["teams"]["restrictedUserChannels"], [])
        self.assertEqual(plan["restrictedAccessVerification"], "not performed")
        with self.assertRaises(provision_m365.LiveServiceError):
            provision_m365._validate_config(config)

    def test_publisher_only_provision_skips_restricted_user_and_grants(self):
        config = {key: value for key, value in self.config.items() if key != "restrictedUpn"}
        state = {"team": {}, "channels": {}, "folders": {}, "shares": {}}
        claims = {"tid": config["tenantId"]}
        scopes = provision_m365.REQUIRED_SCOPES - {"User.ReadBasic.All"}
        profile = {"id": "publisher-id", "userPrincipalName": config["publisherUpn"]}
        with patch.object(provision_m365, "_graph_token_claims", return_value=(claims, scopes)), \
                patch.object(provision_m365, "_save_json"), \
                patch.object(provision_m365, "_request", return_value=(profile, {}, 200)), \
                patch.object(provision_m365, "_get_user") as get_user, \
                patch.object(provision_m365, "_ensure_team", return_value="team-id"), \
                patch.object(provision_m365, "_verify_team_members") as verify_team, \
                patch.object(provision_m365, "_ensure_channel", side_effect=lambda team, name, *args: name), \
                patch.object(provision_m365, "_verify_channel_members") as verify_channel, \
                patch.object(provision_m365, "_sharepoint_drive", return_value="sp-drive"), \
                patch.object(provision_m365, "_drive", return_value="od-drive"), \
                patch.object(provision_m365, "_ensure_folder", return_value="folder-id") as folder, \
                patch.object(provision_m365, "_ensure_read_share") as share, \
                patch.object(provision_m365, "_assert_no_user_permission") as check:
            result = provision_m365.provision(config, "token", state, publisher_only=True)
        get_user.assert_not_called()
        share.assert_not_called()
        check.assert_not_called()
        verify_team.assert_called_once_with("team-id", "publisher-id", None, "token")
        self.assertEqual(verify_channel.call_count, len(provision_m365.CHANNELS))
        self.assertEqual(folder.call_count, 6)
        self.assertNotIn("restrictedUpn", result)
        publish_m365._validate_config(result, publish_m365._catalog())

    def test_graph_empty_folder_facet_is_accepted(self):
        state = {"folders": {}}
        with patch.object(provision_m365, "_get_item_by_path",
                          return_value={"id": "folder-id", "folder": {}}), \
                patch.object(provision_m365, "_save_json"):
            result = provision_m365._ensure_folder("drive", "folder", state, "token")
        self.assertEqual(result, "folder-id")

    def test_channel_lookup_follows_graph_pagination_without_top(self):
        state = {"channels": {}}
        first = (
            f"{provision_m365.GRAPH_API}/teams/team-id/channels"
            "?$select=id,displayName,membershipType"
        )
        second = f"{provision_m365.GRAPH_API}/teams/team-id/channels?$skiptoken=next"
        channel = {"id": "channel-id", "displayName": "payments", "membershipType": "shared"}
        with patch.object(provision_m365, "_request", side_effect=[
            ({"value": [], "@odata.nextLink": second}, {}, 200),
            ({"value": [channel]}, {}, 200),
        ]) as request, patch.object(provision_m365, "_save_json"):
            returned = provision_m365._ensure_channel(
                "team-id", "payments", {"id": "publisher-id"}, state, "token"
            )
        self.assertEqual(returned, "channel-id")
        self.assertEqual([call.args[0] for call in request.call_args_list], [first, second])

    def test_graph_disconnect_retries_reads_but_not_writes(self):
        url = f"{provision_m365.GRAPH_API}/teams"
        with patch.object(provision_m365.time, "sleep"), \
                patch.object(provision_m365.urllib.request, "urlopen") as open_url:
            response = open_url.return_value
            response.__enter__.return_value.read.return_value = b'{"value":[]}'
            open_url.side_effect = [RemoteDisconnected(), response]
            self.assertEqual(provision_m365._request(url)[0], {"value": []})
            self.assertEqual(open_url.call_count, 2)
            open_url.reset_mock()
            open_url.side_effect = RemoteDisconnected()
            with self.assertRaisesRegex(provision_m365.LiveServiceError, "disconnected during POST"):
                provision_m365._request(url, method="POST", body={})
            open_url.assert_called_once()

    def test_shared_channel_async_target_uses_canonical_channel_id(self):
        operation = f"{provision_m365.GRAPH_API}/teams/team-id/operations/operation-id"
        channel = {"id": "channel-id", "displayName": "payments", "membershipType": "shared"}
        for saved in ({"operationUrl": operation}, {"id": "team-id"}):
            with self.subTest(saved=saved):
                state = {"channels": {"payments": saved}}
                with patch.object(provision_m365.time, "sleep"), \
                        patch.object(provision_m365, "_request") as request, \
                        patch.object(provision_m365, "_save_json"):
                    request.side_effect = (
                        [({"status": "succeeded", "targetResourceId": "team-id"}, {}, 200)]
                        if "operationUrl" in saved else []
                    ) + [({"value": [channel]}, {}, 200)]
                    returned = provision_m365._ensure_channel(
                        "team-id", "payments", {"id": "publisher-id"}, state, "token"
                    )
                self.assertEqual(returned, "channel-id")
                self.assertEqual(state["channels"]["payments"], {"id": "channel-id"})
                self.assertTrue(all(call.kwargs.get("method", "GET") == "GET" for call in request.call_args_list))

    def test_plan_mode_makes_no_graph_requests(self):
        config_path = (
            Path(__file__).resolve().parents[1] / "track2/provision-config.example.json"
        )
        with patch("sys.argv", [
            "provision_m365",
            "--config",
            str(config_path),
        ]), patch.object(provision_m365, "_request") as request:
            output = StringIO()
            with redirect_stdout(output):
                result = provision_m365.main()
        self.assertEqual(result, 0)
        self.assertIn('"mode": "provision-plan"', output.getvalue())
        request.assert_not_called()

    def test_apply_requires_exact_tenant_confirmation_before_graph(self):
        config_path = (
            Path(__file__).resolve().parents[1] / "track2/provision-config.example.json"
        )
        with patch("sys.argv", [
            "provision_m365",
            "--config",
            str(config_path),
            "--apply",
            "--confirm-tenant",
            "wrong-tenant",
        ]), patch.object(provision_m365, "_request") as request:
            errors = StringIO()
            with redirect_stderr(errors):
                result = provision_m365.main()
        self.assertEqual(result, 1)
        self.assertIn("exact tenantId", errors.getvalue())
        request.assert_not_called()

    def test_generated_publisher_config_matches_publishers_expected_shape(self):
        config = provision_m365._build_publish_config(
            self.config,
            "sharepoint-drive",
            "onedrive-drive",
            "team-id",
            {name: f"channel-{name}" for name in provision_m365.CHANNELS},
        )
        self.assertEqual(
            config["sharepoint"]["aclFolders"],
            provision_m365.ACL_FOLDERS,
        )
        self.assertEqual(
            config["onedrive"]["aclFolders"],
            provision_m365.ACL_FOLDERS,
        )
        self.assertEqual(set(config["teams"]["channels"]), set(provision_m365.CHANNELS))
        self.assertEqual(json.loads(json.dumps(config)), config)
        publish_m365._validate_config(config, publish_m365._catalog())

    def test_restricted_user_is_added_only_to_approved_shared_channels(self):
        publisher = {"id": "publisher-id"}
        existing = [{"userId": "publisher-id", "roles": ["owner"]}]
        added = []
        member_reads = []

        def capture(url, **kwargs):
            added.append((url, kwargs["body"]))
            return {}, {}, 201

        def list_members(url, token):
            member_reads.append(url)
            if added:
                return existing + [{"userId": "restricted-id", "roles": []}]
            return existing

        with patch.object(provision_m365, "_collection", side_effect=list_members), patch.object(
            provision_m365, "_request", side_effect=capture
        ), patch.object(provision_m365, "_save_json"):
            provision_m365._verify_channel_members(
                "team-id", "channel-1", "campaign-ops",
                "publisher-id", "restricted-id", "token"
            )
        self.assertEqual(len(added), 1)
        self.assertEqual(len(member_reads), 2)
        self.assertTrue(all("/channels/channel-1/members" in url for url in member_reads))
        self.assertIn("/channels/channel-1/members", added[0][0])
        self.assertEqual(added[0][1]["roles"], [])
        self.assertIn("restricted-id", added[0][1]["user@odata.bind"])

        added.clear()
        member_reads.clear()
        with patch.object(provision_m365, "_collection", return_value=existing), patch.object(
            provision_m365, "_request", side_effect=capture
        ):
            provision_m365._verify_channel_members(
                "team-id", "channel-2", "leadership-briefing",
                "publisher-id", "restricted-id", "token"
            )
        self.assertEqual(added, [])

    def test_restricted_user_cannot_have_inherited_leadership_folder_access(self):
        user = {
            "id": "restricted-id",
            "userPrincipalName": "restricted@example.com",
        }
        inherited = {
            "roles": ["read"],
            "inheritedFrom": {"id": "parent-folder"},
            "grantedToV2": {
                "user": {
                    "id": "restricted-id",
                    "email": "restricted@example.com",
                }
            },
        }
        with patch.object(provision_m365, "_collection", return_value=[inherited]):
            with self.assertRaisesRegex(provision_m365.LiveServiceError, "already has"):
                provision_m365._assert_no_user_permission(
                    "drive-id", "folder-id", user, "token", "SharePoint Leaders"
                )

    def test_graph_async_locations_cannot_change_host(self):
        with self.assertRaisesRegex(provision_m365.LiveServiceError, "unexpected"):
            provision_m365._graph_location(
                "https://attacker.example/teams('team')/operations('op')"
            )
        self.assertEqual(
            provision_m365._graph_location("/teams('team')/operations('op')"),
            f"{provision_m365.GRAPH_API}/teams('team')/operations('op')",
        )


if __name__ == "__main__":
    unittest.main()
