from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from tools import m365_auth, publish_m365


class PublishM365Tests(unittest.TestCase):
    def test_plan_covers_all_original_live_content(self):
        catalog = publish_m365._catalog()
        self.assertEqual(
            publish_m365.build_plan(catalog),
            {
                "SharePoint files": 15,
                "OneDrive files": 12,
                "Outlook messages": 15,
                "Teams threads": 18,
                "Teams messages": 55,
            },
        )

    def test_plan_mode_does_not_make_graph_requests(self):
        config_path = Path(__file__).resolve().parents[1] / "track2/publish-config.example.json"
        with patch("sys.argv", [
            "publish_m365",
            "--config",
            str(config_path),
        ]), patch.object(publish_m365, "_request") as request:
            output = StringIO()
            with redirect_stdout(output):
                result = publish_m365.main()
        self.assertEqual(result, 0)
        self.assertIn('"mode": "write-plan"', output.getvalue())
        request.assert_not_called()

    def test_mail_is_addressed_only_to_the_live_publisher(self):
        catalog = publish_m365._catalog()
        item = next(entry for entry in catalog if entry["source"] == "Outlook")
        captured = {}

        def capture(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return {}

        with patch.object(publish_m365, "_request", side_effect=capture):
            result = publish_m365._send_mail(
                item, publish_m365._messages(), "publisher@example.com", "token"
            )
        body = captured["body"]
        recipients = body["message"]["toRecipients"]
        self.assertEqual(recipients, [{"emailAddress": {"address": "publisher@example.com"}}])
        self.assertIn("Original workshop role:", body["message"]["body"]["content"])
        self.assertEqual(result["accepted"], True)

    def test_thread_resume_posts_only_unpublished_replies(self):
        state = {
            "items": {
                "TM01": {
                    "completed": False,
                    "threadId": "parent-id",
                    "messageIds": ["root-id"],
                }
            }
        }
        thread = publish_m365._threads()[0]
        config = {
            "teams": {
                "teamId": "team-id",
                "channels": {thread["channel"]: "channel-id"},
            }
        }
        calls = []

        def capture(url, **kwargs):
            calls.append(url)
            return {"id": f"reply-{len(calls)}"}

        with patch.object(publish_m365, "_request", side_effect=capture), patch.object(
            publish_m365, "_save_state"
        ):
            result = publish_m365._post_thread(thread, config, "token", state)
        self.assertEqual(len(calls), len(thread["messages"]) - 1)
        self.assertIn("/messages/parent-id/replies", calls[0])
        self.assertTrue(result["completed"])
        self.assertEqual(len(result["messageIds"]), len(thread["messages"]))

    def test_post_honors_graph_rate_limit_retry_after(self):
        url = f"{publish_m365.GRAPH_API}/teams/team/channels/channel/messages"
        throttled = HTTPError(url, 429, "Too Many Requests", {"Retry-After": "12"}, BytesIO(b""))
        with patch.object(publish_m365.time, "sleep") as sleep, \
                patch.object(publish_m365.urllib.request, "urlopen") as open_url:
            response = open_url.return_value
            response.__enter__.return_value.read.return_value = b'{"id":"message-id"}'
            open_url.side_effect = [throttled, response]
            result = publish_m365._request(url, method="POST", token="token", body={"body": {}})
        self.assertEqual(result["id"], "message-id")
        sleep.assert_called_once_with(12)
        self.assertEqual(open_url.call_args_list[0], open_url.call_args_list[1])

    def test_live_apply_requires_exact_tenant_confirmation(self):
        config_path = Path(__file__).resolve().parents[1] / "track2/publish-config.example.json"
        with patch("sys.argv", [
            "publish_m365",
            "--config",
            str(config_path),
            "--apply",
            "--confirm-tenant",
            "not-the-configured-tenant",
        ]), patch.object(publish_m365, "_request") as request:
            errors = StringIO()
            with redirect_stderr(errors):
                result = publish_m365.main()
        self.assertEqual(result, 1)
        self.assertIn("exact configured tenantId", errors.getvalue())
        request.assert_not_called()

    def test_live_publish_rejects_different_user_in_the_same_tenant(self):
        config = {"tenantId": "tenant", "publisherUpn": "publisher@example.com"}
        with (
            patch.object(m365_auth, "_graph_token_claims", return_value=(
                {"tid": "tenant"}, publish_m365.REQUIRED_SCOPES
            )),
            patch.object(m365_auth, "_json_request", return_value={
                "id": "other", "userPrincipalName": "other@example.com"
            }),
            self.assertRaisesRegex(publish_m365.LiveServiceError, "configured publisherUpn"),
        ):
            publish_m365._live_identity(config, "token")

    def test_publisher_cannot_reuse_receipts_for_a_different_destination(self):
        config = {
            "tenantId": "tenant", "publisherUpn": "publisher@example.com",
            "sharepoint": {}, "onedrive": {}, "teams": {"teamId": "original"},
        }
        state = {"items": {}, "context": publish_m365._state_context(config)}
        changed = {**config, "teams": {"teamId": "other"}}
        with self.assertRaisesRegex(publish_m365.LiveServiceError, "different tenant, publisher, or targets"):
            publish_m365._validate_state_context(changed, state, allow_legacy=True)
        legacy = {"items": {"SP01": {"completed": True}}}
        publish_m365._validate_state_context(config, legacy, allow_legacy=True)
        with self.assertRaisesRegex(publish_m365.LiveServiceError, "no tenant/target context"):
            publish_m365._validate_state_context(config, legacy)


if __name__ == "__main__":
    unittest.main()
