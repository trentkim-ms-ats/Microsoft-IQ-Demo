import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import call, patch

from tools import run_tracks_3_4 as sequence

TENANT = "00000000-0000-0000-0000-000000000001"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000002"
ACCOUNT = "demo@example.com"
AZ_PROFILE = {"tenantId": TENANT, "id": SUBSCRIPTION, "user": {"name": ACCOUNT}}


class TrackSequenceTests(unittest.TestCase):
    def test_pins_existing_login_and_runs_track4_after_track3_failure(self):
        def child(command, *, check):
            self.assertEqual(os.environ["IQ_AZURE_ACCOUNT"], ACCOUNT)
            self.assertEqual(os.environ["IQ_AZURE_TENANT_ID"], TENANT)
            self.assertEqual(os.environ["AZURE_OPENAI_SUBSCRIPTION"], SUBSCRIPTION)
            return subprocess.CompletedProcess(command, 1 if command[2].endswith("briefing") else 0)

        with (
            tempfile.TemporaryDirectory() as cache,
            patch.dict(os.environ, {"AZURE_CONFIG_DIR": cache}, clear=True),
            patch.object(sequence.auth, "cli_json", return_value=AZ_PROFILE) as az,
            patch.object(sequence.auth, "require_separate_identity") as verify,
            patch.object(sequence.subprocess, "run", side_effect=child) as run,
            patch.object(sys, "argv", ["run_tracks_3_4"]),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(sequence.main(), 1)
        az.assert_called_once_with("account", "show")
        verify.assert_called_once()
        self.assertEqual(run.call_args_list, [
            call([sys.executable, "-m", "tools.run_track3_daily_briefing", "--profile", "all"], check=False),
            call([sys.executable, "-m", "tools.run_track4_demo"], check=False),
        ])

    def test_conflicting_subscription_stops_before_either_track(self):
        with (
            tempfile.TemporaryDirectory() as cache,
            patch.dict(os.environ, {"AZURE_CONFIG_DIR": cache, "AZURE_OPENAI_SUBSCRIPTION": TENANT}, clear=True),
            patch.object(sequence.auth, "cli_json", return_value=AZ_PROFILE),
            patch.object(sequence.subprocess, "run") as run,
            patch.object(sys, "argv", ["run_tracks_3_4"]),
            redirect_stderr(io.StringIO()) as stderr,
        ):
            self.assertEqual(sequence.main(), 1)
        self.assertIn("AZURE_OPENAI_SUBSCRIPTION does not match", stderr.getvalue())
        run.assert_not_called()

    def test_track3_target_does_not_change_track4_arguments(self):
        with (
            tempfile.TemporaryDirectory() as cache,
            patch.dict(os.environ, {"AZURE_CONFIG_DIR": cache}, clear=True),
            patch.object(sequence.auth, "cli_json", return_value=AZ_PROFILE),
            patch.object(sequence.auth, "require_separate_identity"),
            patch.object(sequence.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run,
            patch.object(sys, "argv", ["run_tracks_3_4", "--track3-provisioned-config", "track3/target.local.json"]),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(sequence.main(), 0)
        self.assertEqual(run.call_args_list, [
            call([sys.executable, "-m", "tools.run_track3_daily_briefing", "--profile", "all",
                  "--provisioned-config", "track3/target.local.json"], check=False),
            call([sys.executable, "-m", "tools.run_track4_demo"], check=False),
        ])
