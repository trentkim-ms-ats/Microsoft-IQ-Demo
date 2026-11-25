"""Grant the registered Track2 app's delegated Graph permissions to its publisher."""

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

from tools.live_demo import GRAPH_API, LiveServiceError, _graph_token_claims
from tools.provision_m365 import ROOT, _validate_config
from tools.register_m365_app import (
    FULL_DEMO_SCOPES, GRAPH_APP_ID, SCOPES, STATE_PATH, _app_body, _az, _graph,
    _list_graph, _validate_app,
)


def _login(tenant):
    try:
        result = subprocess.run(
            [
                "az", "login", "--tenant", tenant,
                "--allow-no-subscriptions", "--output", "none",
            ],
            check=False,
        )
    except OSError as error:
        raise LiveServiceError(f"Unable to run Azure CLI: {error}") from error
    if result.returncode:
        raise LiveServiceError("Azure CLI administrator login failed.")


def grant(config, state, admin_upn, full_demo=False):
    account = _az("account", "show")
    profile = _graph("get", f"{GRAPH_API}/me?$select=id,userPrincipalName")
    token = _az("account", "get-access-token", "--resource-type", "ms-graph")
    claims, token_scopes = _graph_token_claims(token.get("accessToken", ""))
    if (
        account.get("tenantId", "").casefold() != config["tenantId"].casefold()
        or claims.get("tid", "").casefold() != config["tenantId"].casefold()
        or (profile.get("userPrincipalName") or "").casefold() != admin_upn.casefold()
    ):
        raise LiveServiceError("The signed-in Graph administrator or tenant does not match.")
    if not token_scopes.intersection(
        {"DelegatedPermissionGrant.ReadWrite.All", "Directory.ReadWrite.All"}
    ):
        raise LiveServiceError(
            "The admin Graph token lacks DelegatedPermissionGrant.ReadWrite.All. "
            "An authorized administrator must use an appropriately consented client."
        )
    if (
        not isinstance(state, dict)
        or state.get("tenantId") != config["tenantId"]
        or state.get("publisherUpn", "").casefold() != config["publisherUpn"].casefold()
        or not all(state.get(key) for key in ("applicationObjectId", "clientId", "servicePrincipalId"))
    ):
        raise LiveServiceError("App registration state does not match the configured tenant.")

    graph_sps = _list_graph(
        f"{GRAPH_API}/servicePrincipals?"
        f"$filter=appId%20eq%20'{GRAPH_APP_ID}'&"
        "$select=id,appId,oauth2PermissionScopes"
    )
    if len(graph_sps) != 1 or not graph_sps[0].get("id"):
        raise LiveServiceError("Microsoft Graph service principal lookup was not unique.")
    graph_sp = graph_sps[0]
    scopes = FULL_DEMO_SCOPES if full_demo else SCOPES
    scope_ids = {
        item["value"]: item["id"]
        for item in graph_sp.get("oauth2PermissionScopes", [])
        if item.get("isEnabled") and item.get("value") in scopes
    }
    if set(scope_ids) != scopes:
        raise LiveServiceError("Microsoft Graph is missing required delegated scopes.")
    app_id = urllib.parse.quote(state["applicationObjectId"], safe="")
    app = _graph(
        "get",
        f"{GRAPH_API}/applications/{app_id}?"
        "$select=id,appId,displayName,signInAudience,isFallbackPublicClient,publicClient,requiredResourceAccess",
    )
    _validate_app(app, _app_body(scope_ids, full_demo))
    if app["appId"] != state["clientId"]:
        raise LiveServiceError("App client ID differs from saved state.")
    sp_id = urllib.parse.quote(state["servicePrincipalId"], safe="")
    sp = _graph("get", f"{GRAPH_API}/servicePrincipals/{sp_id}?$select=id,appId")
    if sp.get("id") != state["servicePrincipalId"] or sp.get("appId") != state["clientId"]:
        raise LiveServiceError("App service principal does not match saved state.")

    if admin_upn.casefold() == config["publisherUpn"].casefold():
        publisher = profile
    else:
        publisher_upn = urllib.parse.quote(config["publisherUpn"], safe="")
        publisher = _graph(
            "get", f"{GRAPH_API}/users/{publisher_upn}?$select=id,userPrincipalName",
        )
    if (
        (publisher.get("userPrincipalName") or "").casefold() != config["publisherUpn"].casefold()
        or not publisher.get("id")
    ):
        raise LiveServiceError("Could not resolve the publisher in the configured tenant.")
    grants_url = (
        f"{GRAPH_API}/oauth2PermissionGrants?"
        f"$filter=clientId%20eq%20'{sp_id}'"
    )
    expected = {
        "clientId": state["servicePrincipalId"],
        "resourceId": graph_sp["id"],
        "consentType": "Principal",
        "principalId": publisher["id"],
    }
    existing = [item for item in _list_graph(grants_url) if all(
        item.get(key) == value for key, value in expected.items()
    )]
    if len(existing) > 1:
        raise LiveServiceError("Multiple grants exist for the publisher; review them manually.")
    if existing:
        consent = existing[0]
        if set((consent.get("scope") or "").split()) != scopes:
            raise LiveServiceError(
                "The publisher's existing grant differs; refusing to alter it."
            )
        status = "already-granted"
    else:
        try:
            consent = _graph("post", f"{GRAPH_API}/oauth2PermissionGrants", {
                **expected,
                "scope": " ".join(sorted(scopes)),
            })
        except LiveServiceError as error:
            raise LiveServiceError(
                f"Publisher delegated consent request failed: {error}"
            ) from error
        status = "granted"

    if (
        not consent.get("id") or any(consent.get(key) != value for key, value in expected.items())
        or set((consent.get("scope") or "").split()) != scopes
    ):
        raise LiveServiceError("Graph did not confirm the requested grant.")

    return {
        "status": status,
        "tenantId": config["tenantId"],
        "administrator": profile["userPrincipalName"],
        "clientId": state["clientId"],
        "grantId": consent["id"],
        "consentType": "Principal",
        "publisher": config["publisherUpn"],
        "delegatedGraphPermissions": sorted(scopes),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "track2/provision-config.local.json")
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--admin-upn", required=True, help="Expected administrator UPN.")
    parser.add_argument(
        "--azure-config-dir", required=True, type=Path,
        help="Separate Azure CLI authentication cache directory.",
    )
    parser.add_argument("--login", action="store_true", help="Sign in interactively.")
    parser.add_argument("--apply", action="store_true", help="Grant consent for the configured publisher.")
    parser.add_argument("--confirm-tenant", help="Exact configured tenant ID.")
    parser.add_argument("--full-demo", action="store_true", help="Match an app registered with --full-demo.")
    args = parser.parse_args()
    try:
        config = _validate_config(json.loads(args.config.read_text(encoding="utf-8")), True)
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not state.get("clientId"):
            raise LiveServiceError("App state is invalid or missing a client ID.")
        if not args.apply:
            print(json.dumps({
                "mode": "plan",
                "tenantId": config["tenantId"],
                "administrator": args.admin_upn,
                "clientId": state["clientId"],
                "consentType": "Principal",
                "publisher": config["publisherUpn"],
                "delegatedGraphPermissions": sorted(FULL_DEMO_SCOPES if args.full_demo else SCOPES),
            }, indent=2))
            return 0
        if args.confirm_tenant != config["tenantId"]:
            raise LiveServiceError("Pass --confirm-tenant with the exact tenantId.")
        args.azure_config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.environ["AZURE_CONFIG_DIR"] = str(args.azure_config_dir.resolve())
        if args.login:
            _login(config["tenantId"])
        print(json.dumps(grant(config, state, args.admin_upn, args.full_demo), indent=2))
    except (OSError, ValueError, LiveServiceError) as error:
        print(f"Admin consent failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
