from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import grant_m365_consent as consent


class GrantM365ConsentTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "tenantId": "tenant-id",
            "publisherUpn": "publisher@example.com",
            "teamDisplayName": "demo",
        }
        self.state = {
            "tenantId": "tenant-id",
            "publisherUpn": "publisher@example.com",
            "applicationObjectId": "app-object-id",
            "clientId": "client-id",
            "servicePrincipalId": "client-sp-id",
        }
        self.admin = "admin@example.com"
        self.scope_ids = {name: f"id-{name}" for name in consent.SCOPES}
        self.graph_sp = {
            "id": "graph-sp-id",
            "oauth2PermissionScopes": [
                {"value": name, "id": value, "isEnabled": True}
                for name, value in self.scope_ids.items()
            ],
        }
        self.app = {
            **consent._app_body(self.scope_ids),
            "id": "app-object-id",
            "appId": "client-id",
        }
        self.service_principal = {"id": "client-sp-id", "appId": "client-id"}
        self.claims = {"tid": "tenant-id"}
        self.token_scopes = {"DelegatedPermissionGrant.ReadWrite.All"}

    def _run_grant(self, existing=None, admin=None):
        calls = []

        def az(*args):
            if args[:2] == ("account", "show"):
                return {"tenantId": "tenant-id"}
            return {"accessToken": "token"}

        def graph(method, url, body=None):
            calls.append((method, url, body))
            if "/me?" in url:
                return {"id": "admin-id", "userPrincipalName": admin or self.admin}
            if "/applications/" in url:
                return self.app
            if "/servicePrincipals/" in url:
                return self.service_principal
            if "/users/" in url:
                return {"id": "publisher-id", "userPrincipalName": self.config["publisherUpn"]}
            if method == "post":
                return {"id": "grant-id", **body}
            self.fail(f"Unexpected Graph request: {method} {url}")

        with patch.object(consent, "_az", side_effect=az), \
                patch.object(consent, "_graph", side_effect=graph), \
                patch.object(consent, "_graph_token_claims", return_value=(self.claims, self.token_scopes)), \
                patch.object(consent, "_list_graph", side_effect=[[self.graph_sp], existing or []]):
            result = consent.grant(self.config, self.state, self.admin)
        return result, calls

    def test_creates_only_exact_publisher_grant(self):
        result, calls = self._run_grant()
        posts = [call for call in calls if call[0] == "post"]
        self.assertEqual(len(posts), 1)
        self.assertTrue(posts[0][1].endswith("/oauth2PermissionGrants"))
        body = posts[0][2]
        self.assertEqual(body["consentType"], "Principal")
        self.assertEqual(body["principalId"], "publisher-id")
        self.assertEqual(body["clientId"], "client-sp-id")
        self.assertEqual(set(body["scope"].split()), consent.SCOPES)
        self.assertEqual(result["status"], "granted")

    def test_existing_matching_grant_is_not_duplicated(self):
        existing = {
            "id": "grant-id",
            "clientId": "client-sp-id",
            "resourceId": "graph-sp-id",
            "consentType": "Principal",
            "principalId": "publisher-id",
            "scope": " ".join(sorted(consent.SCOPES)),
        }
        result, calls = self._run_grant([existing])
        self.assertEqual(result["status"], "already-granted")
        self.assertFalse(any(call[0] == "post" for call in calls))

    def test_rejects_wrong_administrator(self):
        with self.assertRaisesRegex(consent.LiveServiceError, "administrator or tenant"):
            self._run_grant(admin="someone-else@example.com")

    def test_rejects_grant_with_different_scopes(self):
        existing = {
            "id": "grant-id",
            "clientId": "client-sp-id",
            "resourceId": "graph-sp-id",
            "consentType": "Principal",
            "principalId": "publisher-id",
            "scope": "User.Read",
        }
        with self.assertRaisesRegex(consent.LiveServiceError, "differs"):
            self._run_grant([existing])

    def test_plan_and_confirmation_do_not_log_in(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            state = root / "state.json"
            config.write_text(json.dumps(self.config))
            state.write_text(json.dumps(self.state))
            base = ["grant", "--config", str(config), "--state", str(state),
                    "--admin-upn", self.admin, "--azure-config-dir", str(root / "auth")]
            with patch("sys.argv", base), patch.object(consent, "_login") as login, \
                    redirect_stdout(StringIO()):
                self.assertEqual(consent.main(), 0)
                login.assert_not_called()
            with patch("sys.argv", base + ["--login", "--apply", "--confirm-tenant", "wrong"]), \
                    patch.object(consent, "_login") as login, redirect_stderr(StringIO()):
                self.assertEqual(consent.main(), 1)
                login.assert_not_called()
                self.assertFalse((root / "auth").exists())


if __name__ == "__main__":
    unittest.main()
