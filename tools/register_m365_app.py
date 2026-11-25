"""Register the Track2 publisher-only public client using Microsoft Graph."""

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

from tools.live_demo import GRAPH_API, LiveServiceError
from tools.m365_auth import APP_STATE_PATH as STATE_PATH
from tools.provision_m365 import REQUIRED_SCOPES, ROOT, _save_json, _validate_config

if os.name == "nt":
    import msvcrt
else:
    import fcntl

GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
DISPLAY_NAME = "IQ Workshop Provisioner"
SCOPES = REQUIRED_SCOPES - {"User.ReadBasic.All"}
FULL_DEMO_SCOPES = SCOPES | {
    "Mail.Send", "ChannelMessage.Send", "Sites.Read.All", "Files.Read.All",
    "Mail.Read", "ChannelMessage.Read.All",
}
LOOPBACK_REDIRECT = "http://localhost"
LOCK_PATH = ROOT / "track2/entra-app-state.local.lock"


def _az(*args):
    try:
        result = subprocess.run(
            ["az", *args, "-o", "json"], capture_output=True, text=True,
            check=False, timeout=120
        )
    except OSError as error:
        raise LiveServiceError(f"Unable to run Azure CLI: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise LiveServiceError(
            "Azure CLI timed out; inspect the tenant before retrying any write."
        ) from error
    if result.returncode:
        raise LiveServiceError(f"Azure CLI failed: {result.stderr.strip()[:1000]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LiveServiceError("Azure CLI did not return valid JSON.") from error


def _graph(method, url, body=None):
    args = ["rest", "--method", method, "--url", url]
    if body is not None:
        args.extend(["--body", json.dumps(body)])
    return _az(*args)


def _list_graph(url):
    values = []
    while url:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc.casefold() != "graph.microsoft.com":
            raise LiveServiceError("Unexpected Microsoft Graph pagination URL.")
        page = _graph("get", url)
        if not isinstance(page.get("value"), list):
            raise LiveServiceError("Microsoft Graph returned an invalid collection.")
        values.extend(page["value"])
        url = page.get("@odata.nextLink")
    return values


def _app_body(scope_ids, full_demo=False):
    scopes = FULL_DEMO_SCOPES if full_demo else SCOPES
    body = {
        "displayName": DISPLAY_NAME,
        "signInAudience": "AzureADMyOrg",
        "isFallbackPublicClient": True,
        "requiredResourceAccess": [{
            "resourceAppId": GRAPH_APP_ID,
            "resourceAccess": [
                {"id": scope_ids[name], "type": "Scope"} for name in sorted(scopes)
            ],
        }],
    }
    if full_demo:
        body["publicClient"] = {"redirectUris": [LOOPBACK_REDIRECT]}
    return body


def _validate_app(app, expected):
    for key in ("displayName", "signInAudience", "isFallbackPublicClient"):
        if app.get(key) != expected[key]:
            raise LiveServiceError(f"Existing app has an unexpected {key}.")
    if "publicClient" in expected and app.get("publicClient") != expected["publicClient"]:
        raise LiveServiceError("Existing app has unexpected public client redirects.")
    resources = app.get("requiredResourceAccess") or []
    if len(resources) != 1 or resources[0].get("resourceAppId") != GRAPH_APP_ID:
        raise LiveServiceError("Existing app has unexpected API resources.")
    wanted = {(item["id"], item["type"]) for item in expected["requiredResourceAccess"][0]["resourceAccess"]}
    actual = {(item.get("id"), item.get("type")) for item in resources[0].get("resourceAccess", [])}
    if actual != wanted or not app.get("id") or not app.get("appId"):
        raise LiveServiceError("Existing app has unexpected permissions or missing IDs.")


def register(config, existing_object_id=None, full_demo=False):
    account = _az("account", "show")
    profile = _graph("get", f"{GRAPH_API}/me?$select=id,userPrincipalName")
    if (
        account.get("tenantId", "").casefold() != config["tenantId"].casefold()
        or (profile.get("userPrincipalName") or "").casefold()
        != config["publisherUpn"].casefold()
    ):
        raise LiveServiceError("Azure CLI tenant or Graph user does not match config.")

    graph_url = (
        f"{GRAPH_API}/servicePrincipals?"
        f"$filter=appId%20eq%20'{GRAPH_APP_ID}'&"
        "$select=id,appId,oauth2PermissionScopes"
    )
    graph_principals = _list_graph(graph_url)
    if len(graph_principals) != 1:
        raise LiveServiceError("Microsoft Graph service principal lookup was not unique.")
    graph_sp = graph_principals[0]
    scopes = FULL_DEMO_SCOPES if full_demo else SCOPES
    scope_ids = {
        item["value"]: item["id"]
        for item in graph_sp.get("oauth2PermissionScopes", [])
        if item.get("isEnabled") and item.get("value") in scopes
    }
    if set(scope_ids) != scopes:
        raise LiveServiceError("Microsoft Graph is missing required delegated scopes.")
    body = _app_body(scope_ids, full_demo)

    state = None
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if (
            not isinstance(state, dict)
            or state.get("tenantId") != config["tenantId"]
            or state.get("publisherUpn", "").casefold() != config["publisherUpn"].casefold()
            or not state.get("applicationObjectId")
        ):
            raise LiveServiceError("Existing app state belongs to another configuration.")
        if existing_object_id and state["applicationObjectId"] != existing_object_id:
            raise LiveServiceError("App ID does not match the saved state.")
        existing_object_id = state["applicationObjectId"]
    if existing_object_id:
        app = _graph(
            "get",
            f"{GRAPH_API}/applications/{urllib.parse.quote(existing_object_id, safe='')}"
            "?$select=id,appId,displayName,signInAudience,isFallbackPublicClient,publicClient,requiredResourceAccess",
        )
        _validate_app(app, body)
        if state and state.get("clientId") != app["appId"]:
            raise LiveServiceError("Saved client ID does not match the existing app.")
    else:
        apps = _list_graph(
            f"{GRAPH_API}/applications?"
            "$filter=displayName%20eq%20'IQ%20Workshop%20Provisioner'&"
            "$select=id,appId,displayName"
        )
        if apps:
            raise LiveServiceError(
                "An app with this name exists. Inspect it and use "
                "--existing-app-object-id explicitly rather than creating a duplicate."
            )
        app = _graph("post", f"{GRAPH_API}/applications", body)
        _validate_app(app, body)

    state = {
        "tenantId": config["tenantId"],
        "publisherUpn": config["publisherUpn"],
        "applicationObjectId": app["id"],
        "clientId": app["appId"],
    }
    _save_json(STATE_PATH, state)
    service_principals = _list_graph(
        f"{GRAPH_API}/servicePrincipals?"
        f"$filter=appId%20eq%20'{app['appId']}'&$select=id,appId"
    )
    if len(service_principals) > 1:
        raise LiveServiceError("Multiple service principals matched this app.")
    sp = service_principals[0] if service_principals else _graph(
        "post", f"{GRAPH_API}/servicePrincipals", {"appId": app["appId"]}
    )
    if not sp.get("id") or sp.get("appId") != app["appId"]:
        raise LiveServiceError("Service principal did not match the registered app.")
    state["servicePrincipalId"] = sp["id"]
    _save_json(STATE_PATH, state)
    return state


def _register_with_lock(config, existing_object_id, full_demo=False):
    with LOCK_PATH.open("a+b") as lock_file:
        if os.name == "nt":
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            return register(config, existing_object_id, full_demo)
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "track2/provision-config.local.json")
    parser.add_argument("--apply", action="store_true", help="Register or verify live resources.")
    parser.add_argument("--confirm-tenant", help="Exact configured tenant ID.")
    parser.add_argument(
        "--full-demo", action="store_true",
        help="Also configure publishing and search scopes and browser sign-in.",
    )
    parser.add_argument(
        "--existing-app-object-id",
        help="Verify and reuse this explicitly identified existing application.",
    )
    args = parser.parse_args()
    try:
        config = _validate_config(json.loads(args.config.read_text(encoding="utf-8")), True)
        plan = {
            "tenantId": config["tenantId"],
            "publisher": config["publisherUpn"],
            "displayName": DISPLAY_NAME,
            "publicClient": True,
            "delegatedGraphPermissions": sorted(FULL_DEMO_SCOPES if args.full_demo else SCOPES),
            "adminConsent": "not granted by this script",
        }
        if not args.apply:
            print(json.dumps({"mode": "plan", "plan": plan}, indent=2))
            return 0
        if args.confirm_tenant != config["tenantId"]:
            raise LiveServiceError("Pass --confirm-tenant with the exact tenantId.")
        state = _register_with_lock(config, args.existing_app_object_id, args.full_demo)
        print(json.dumps({
            "mode": "live",
            "applicationObjectId": state["applicationObjectId"],
            "clientId": state["clientId"],
            "servicePrincipalId": state["servicePrincipalId"],
            "adminConsent": "not granted by this script; verify separately",
        }, indent=2))
    except (OSError, ValueError, LiveServiceError) as error:
        print(f"App registration failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
