"""Get an in-memory delegated Graph token for the configured Track2 publisher."""

import json
import os
import sys
from pathlib import Path
from uuid import UUID

from tools.live_demo import GRAPH_API, ROOT, LiveServiceError, _graph_token_claims, _json_request

APP_STATE_PATH = ROOT / "track2/entra-app-state.local.json"


def publisher_profile(config, token, required_scopes):
    claims, scopes = _graph_token_claims(token)
    if (claims.get("tid") or "").casefold() != config["tenantId"].casefold():
        raise LiveServiceError("The Graph token is from a different tenant.")
    missing = required_scopes - scopes
    if missing:
        raise LiveServiceError("Graph token lacks delegated scopes: " + ", ".join(sorted(missing)))
    profile = _json_request(f"{GRAPH_API}/me?$select=id,userPrincipalName,mail", token=token)
    if (
        not profile.get("id")
        or (profile.get("userPrincipalName") or "").casefold() != config["publisherUpn"].casefold()
    ):
        raise LiveServiceError("Sign in with the configured publisherUpn; no operation was run.")
    return profile


def publisher_token(config, scopes, *, interactive=False, app_state=APP_STATE_PATH):
    if not interactive:
        token = os.environ.get("GRAPH_ACCESS_TOKEN")
        if not token:
            raise LiveServiceError("Use --interactive or set a delegated GRAPH_ACCESS_TOKEN.")
        return token

    app = json.loads(Path(app_state).read_text(encoding="utf-8"))
    if (
        not isinstance(app, dict)
        or app.get("tenantId") != config["tenantId"]
        or (app.get("publisherUpn") or "").casefold() != config["publisherUpn"].casefold()
    ):
        raise LiveServiceError("The Entra app state belongs to a different tenant or publisher.")
    try:
        tenant = str(UUID(config["tenantId"]))
        client_id = str(UUID(app.get("clientId", "")))
    except (AttributeError, ValueError) as error:
        raise LiveServiceError("The Entra state must have valid tenant and client IDs.") from error
    try:
        from msal import PublicClientApplication
        from msal.oauth2cli.oauth2 import BrowserInteractionTimeoutError
    except ImportError as error:
        raise LiveServiceError("Install MSAL with `python3 -m pip install -r requirements-live.txt`.") from error

    client = PublicClientApplication(
        client_id, authority=f"https://login.microsoftonline.com/{tenant}",
        exclude_scopes=["offline_access"],
    )
    print("Opening Microsoft sign-in for the configured publisher.", file=sys.stderr, flush=True)
    try:
        result = client.acquire_token_interactive(
            [f"https://graph.microsoft.com/{scope}" for scope in sorted(scopes)],
            login_hint=config["publisherUpn"],
            timeout=180,
        )
    except BrowserInteractionTimeoutError:
        raise LiveServiceError("Microsoft browser sign-in timed out without a token.") from None
    token = result.get("access_token")
    if not token:
        raise LiveServiceError(f"Microsoft sign-in failed: {result.get('error', 'no token')}.")
    claims, _ = _graph_token_claims(token)
    if (claims.get("azp") or claims.get("appid")) != client_id:
        raise LiveServiceError("The Graph token was not issued to IQ Workshop Provisioner.")
    return token
