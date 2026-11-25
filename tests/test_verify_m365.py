import unittest
from unittest.mock import patch

from tools import verify_m365


class VerifyM365Tests(unittest.TestCase):
    def test_search_only_counts_live_published_hits_and_separates_channel_reads(self):
        with (
            patch.object(verify_m365, "_read_json", return_value={"Q1": {"workSearchTerms": ["SummerPush"]}}),
            patch.object(verify_m365, "_graph_search", side_effect=[
                [{"id": "known"}, {"id": "unrelated"}, {"id": "known"}],
                [{"id": "unrelated"}],
                [{"title": "verified subject"}, {"title": "another subject"}],
            ]) as search,
        ):
            result = verify_m365._search_scenarios(
                {"SharePoint": ["https://example.test/sp"], "OneDrive": ["https://example.test/od"]},
                {"SharePoint": {"known"}, "OneDrive": {"other-known"}},
                {"verified subject"},
                {"TM01": ["summerpush report", "SummerPushX is unrelated"]},
                "token",
            )["Q1"]
        self.assertIn('path:"https://example.test/sp"', search.call_args_list[0].args[1])
        self.assertEqual([call.args[0] for call in search.call_args_list], ["driveItem", "driveItem", "message"])
        self.assertEqual(result["SharePoint"]["publishedHits"], 1)
        self.assertEqual(result["OneDrive"]["status"], "no-evidence")
        self.assertEqual(result["Outlook"]["publishedHits"], 1)
        self.assertEqual(result["Teams (direct channel read)"]["publishedMessageHits"], 1)

    def test_inbox_does_not_count_send_acceptance_or_duplicate_subjects_as_delivery(self):
        messages = {
            "EM01": {"id": "EM01", "thread": "T", "subject": "Included"},
            "EM02": {"id": "EM02", "thread": "T", "subject": "Duplicate"},
            "EM03": {"id": "EM03", "thread": "T", "subject": "Not delivered"},
        }
        receipts = {key: {"accepted": True} for key in messages}
        items = [{"id": key, "source": "Outlook"} for key in messages]
        unique = verify_m365.publisher.workshop_subject(messages["EM01"])
        duplicate = verify_m365.publisher.workshop_subject(messages["EM02"])
        inbox = [{"id": str(i), "subject": subject, "webLink": "https://example.test/mail"}
                 for i, subject in enumerate([unique, duplicate, duplicate])]
        failures = {}
        with (
            patch.object(verify_m365.publisher, "_messages", return_value=messages),
            patch.object(verify_m365.provision, "_collection", return_value=inbox),
        ):
            self.assertEqual(verify_m365._read_outlook(items, receipts, "token", failures), {unique})
        self.assertEqual(set(failures), {"EM02", "EM03"})

    def test_missing_teams_reply_fails_even_with_complete_local_receipt(self):
        target = {"teams": {"teamId": "team", "channels": {"payments": "channel"}}}
        thread = {"id": "TM01", "channel": "payments", "title": "Example", "messages": [
            ("Lead", "2026-01-01", "Parent"), ("Member", "2026-01-02", "Reply"),
        ]}
        receipt = {"TM01": {"threadId": "root", "messageIds": ["root", "reply"], "channel": "payments"}}
        parent = {"id": "root", "webUrl": "https://example.test/teams", "body": {
            "contentType": "html", "content": "Example<br>[Original role: Lead | 2026-01-01] Parent",
        }}
        failures = {}
        with (
            patch.object(verify_m365.publisher, "_threads", return_value=[thread]),
            patch.object(verify_m365, "_get", return_value={"id": "team", "visibility": "private"}),
            patch.object(verify_m365.provision, "_request", return_value=(parent, {}, 200)),
            patch.object(verify_m365.provision, "_collection", side_effect=[
                [{"id": "channel", "displayName": "payments", "membershipType": "shared"}],
                [],
            ]),
        ):
            channels, threads = verify_m365._read_teams(target, receipt, "token", failures)
        self.assertEqual(channels, {"payments"})
        self.assertEqual(threads, {})
        self.assertIn("missing", failures["TM01"])
