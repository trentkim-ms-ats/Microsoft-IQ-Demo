from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import register_m365_app as registration


class RegisterM365AppTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "tenantId": "tenant-id",
            "publisherUpn": "publisher@example.com",
            "teamDisplayName": "demo",
        }
        self.scope_ids = {name: f"id-{name}" for name in registration.SCOPES}
        self.graph_sp = {
            "id": "graph-sp",
            "oauth2PermissionScopes": [
                {"value": name, "id": value, "isEnabled": True}
                for name, value in self.scope_ids.items()
            ],
        }
        self.app = {
            **registration._app_body(self.scope_ids),
            "id": "object-id",
            "appId": "client-id",
        }
        self.account = {"tenantId": "tenant-id"}
        self.profile = {"id": "publisher-id", "userPrincipalName": "publisher@example.com"}

    def test_creation_saves_state_and_does_not_grant_consent(self):
        calls = []

        def graph(method, url, body=None):
            calls.append((method, url, body))
            if "/me?" in url:
                return self.profile
            if url.endswith("/applications") and method == "post":
                return self.app
            if url.endswith("/servicePrincipals") and method == "post":
                return {"id": "sp-id", "appId": "client-id"}
            self.fail(f"Unexpected Graph call: {method} {url}")

        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch.object(registration, "STATE_PATH", path), \
                    patch.object(registration, "_az", return_value=self.account), \
                    patch.object(registration, "_graph", side_effect=graph), \
                    patch.object(registration, "_list_graph", side_effect=[[self.graph_sp], [], []]):
                result = registration.register(self.config)
                self.assertEqual(json.loads(path.read_text()), result)

        posts = [(url, body) for method, url, body in calls if method == "post"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0][1], registration._app_body(self.scope_ids))
        self.assertEqual(posts[1][1], {"appId": "client-id"})
        self.assertFalse(any("oauth2PermissionGrants" in url for _, url, _ in calls))
        self.assertEqual(result["servicePrincipalId"], "sp-id")

    def test_rejects_mismatched_existing_app_permissions(self):
        wrong = {**self.app, "requiredResourceAccess": []}
        with TemporaryDirectory() as directory:
            with patch.object(registration, "STATE_PATH", Path(directory) / "state.json"), \
                    patch.object(registration, "_az", return_value=self.account), \
                    patch.object(registration, "_list_graph", return_value=[self.graph_sp]), \
                    patch.object(registration, "_graph", side_effect=[self.profile, wrong]):
                with self.assertRaisesRegex(registration.LiveServiceError, "unexpected API resources"):
                    registration.register(self.config, "object-id")

    def test_full_demo_requires_matching_browser_redirect_on_reuse(self):
        scope_ids = {name: f"id-{name}" for name in registration.FULL_DEMO_SCOPES}
        graph_sp = {
            **self.graph_sp,
            "oauth2PermissionScopes": [
                {"value": name, "id": value, "isEnabled": True}
                for name, value in scope_ids.items()
            ],
        }
        app = {
            **registration._app_body(scope_ids, full_demo=True),
            "id": "object-id",
            "appId": "client-id",
        }
        app["publicClient"] = {"redirectUris": ["https://example.com"]}
        with TemporaryDirectory() as directory, \
                patch.object(registration, "STATE_PATH", Path(directory) / "state.json"), \
                patch.object(registration, "_az", return_value=self.account), \
                patch.object(registration, "_list_graph", return_value=[graph_sp]), \
                patch.object(registration, "_graph", side_effect=[self.profile, app]):
            with self.assertRaisesRegex(registration.LiveServiceError, "unexpected public client redirects"):
                registration.register(self.config, "object-id", full_demo=True)

    def test_existing_name_fails_instead_of_creating_duplicate(self):
        with TemporaryDirectory() as directory:
            with patch.object(registration, "STATE_PATH", Path(directory) / "state.json"), \
                    patch.object(registration, "_az", return_value=self.account), \
                    patch.object(registration, "_graph", return_value=self.profile) as graph, \
                    patch.object(registration, "_list_graph", side_effect=[[self.graph_sp], [self.app]]):
                with self.assertRaisesRegex(registration.LiveServiceError, "exists"):
                    registration.register(self.config)
        graph.assert_called_once()

    def test_plan_and_confirmation_do_not_contact_graph(self):
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps(self.config))
            with patch("sys.argv", ["register", "--config", str(config)]), \
                    patch.object(registration, "_az") as az, redirect_stdout(StringIO()):
                self.assertEqual(registration.main(), 0)
                az.assert_not_called()
            with patch("sys.argv", ["register", "--config", str(config), "--apply",
                                    "--confirm-tenant", "wrong"]), \
                    patch.object(registration, "_az") as az, redirect_stderr(StringIO()):
                self.assertEqual(registration.main(), 1)
                az.assert_not_called()


if __name__ == "__main__":
    unittest.main()
