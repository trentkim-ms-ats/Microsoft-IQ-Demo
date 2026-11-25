"""Pin Fabric and Foundry calls to a separate, explicitly selected Entra identity."""

import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
TRACK2_CONFIG = ROOT / "track2/provision-config.local.json"


class AzureContextError(ValueError):
    """The selected identity or resource could not be verified."""


def cli_json(*args):
    try:
        result = subprocess.run(
            ["az", *args, "--only-show-errors", "-o", "json"],
            capture_output=True, text=True, check=False, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise AzureContextError("Azure CLI is missing or did not respond.") from error
    if result.returncode:
        raise AzureContextError("Azure CLI command failed: " + result.stderr.strip()[:400])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AzureContextError("Azure CLI did not return JSON.") from error


def _tenant_id(value, label):
    try:
        return str(UUID(value))
    except (AttributeError, ValueError) as error:
        raise AzureContextError(f"{label} must contain a tenant UUID.") from error


def token_claims(token):
    try:
        segment = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    except (AttributeError, IndexError, ValueError) as error:
        raise AzureContextError("The Azure access token identity could not be checked.") from error
    if not isinstance(claims, dict):
        raise AzureContextError("The Azure access token identity could not be checked.")
    return claims


@dataclass(frozen=True)
class AzureDemoIdentity:
    tenant: str
    account: str

    def verify_cli(self, subscription=None):
        args = ("--subscription", subscription) if subscription else ()
        current = cli_json("account", "show", *args)
        if not isinstance(current, dict) or (current.get("tenantId") or "").casefold() != self.tenant:
            raise AzureContextError("Azure CLI is not using the configured Azure demo tenant.")
        if (current.get("user", {}).get("name") or "").casefold() != self.account:
            raise AzureContextError("Azure CLI is not signed in as the configured Azure demo account.")
        if subscription and current.get("state") != "Enabled":
            raise AzureContextError(
                "The selected Azure demo subscription is not Enabled. "
                "Restore the selected subscription before rerunning; no fallback subscription is used."
            )

    def token(self, *, scope=None, resource=None, subscription=None):
        self.verify_cli(subscription)
        args = ("--subscription", subscription) if subscription else ("--tenant", self.tenant)
        audience = ("--scope", scope) if scope else ("--resource", resource)
        token = cli_json("account", "get-access-token", *audience, *args, "--query", "accessToken")
        claims = token_claims(token)
        if (claims.get("tid") or "").casefold() != self.tenant:
            raise AzureContextError("Access token tenant differs from the configured Azure demo tenant.")
        if "@" in self.account:
            identity = claims.get("preferred_username") or claims.get("upn") or claims.get("unique_name")
        else:
            identity = claims.get("azp") or claims.get("appid")
        if not isinstance(identity, str) or identity.casefold() != self.account:
            raise AzureContextError("Access token does not belong to the configured Azure demo account.")
        return token

    def get_token(self, scope):
        return SimpleNamespace(token=self.token(scope=scope))


def separate_identity():
    tenant = os.environ.get("IQ_AZURE_TENANT_ID", "").strip()
    account = os.environ.get("IQ_AZURE_ACCOUNT", "").strip().casefold()
    track2_tenant = os.environ.get("IQ_M365_TENANT_ID", "").strip()
    if not (tenant or account or track2_tenant):
        return None
    tenant = _tenant_id(tenant, "IQ_AZURE_TENANT_ID")
    if "@" not in account:
        try:
            account = str(UUID(account))
        except ValueError as error:
            raise AzureContextError("Set IQ_AZURE_ACCOUNT to the Azure login UPN or federated application client ID.") from error
    cache = os.environ.get("AZURE_CONFIG_DIR")
    if not cache or Path(cache).expanduser().resolve() == (Path.home() / ".azure").resolve():
        raise AzureContextError("Set AZURE_CONFIG_DIR to a dedicated Azure demo login cache.")

    publisher = os.environ.get("IQ_M365_ACCOUNT", "").strip().casefold()
    if TRACK2_CONFIG.is_file():
        try:
            track2 = json.loads(TRACK2_CONFIG.read_text(encoding="utf-8"))
            local_tenant = _tenant_id(track2["tenantId"], "Track 2 tenantId")
            publisher = track2["publisherUpn"].casefold()
        except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
            raise AzureContextError("Could not verify the existing Track 2 identity.") from error
        if track2_tenant and _tenant_id(track2_tenant, "IQ_M365_TENANT_ID") != local_tenant:
            raise AzureContextError("IQ_M365_TENANT_ID does not match the local Track 2 tenant.")
        track2_tenant = local_tenant
    if "@" in account and not publisher:
        raise AzureContextError("Set IQ_M365_ACCOUNT to the Track 2 publisher when there is no local Track 2 config.")
    if publisher == account:
        raise AzureContextError("The Azure demo account must differ from the Track 2 publisher.")
    if tenant == _tenant_id(track2_tenant, "IQ_M365_TENANT_ID (required when no local Track 2 config exists)"):
        raise AzureContextError("The Azure demo tenant must differ from the Track 2 tenant.")
    return AzureDemoIdentity(tenant, account)


def require_separate_identity():
    missing = [
        name for name in ("IQ_AZURE_TENANT_ID", "IQ_AZURE_ACCOUNT", "AZURE_CONFIG_DIR")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise AzureContextError("Set " + ", ".join(missing) + " for the separate Azure tenant.")
    return separate_identity()


def resolve_foundry_target(identity):
    subscription = os.environ.get("AZURE_OPENAI_SUBSCRIPTION")
    if not subscription:
        raise AzureContextError("Set AZURE_OPENAI_SUBSCRIPTION to the approved Azure subscription.")
    identity.verify_cli(subscription)
    group = os.environ.get("AZURE_RESOURCE_GROUP")
    account = os.environ.get("AZURE_AI_ACCOUNT_NAME")
    if not group or not account:
        raise AzureContextError(
            "Set AZURE_RESOURCE_GROUP and AZURE_AI_ACCOUNT_NAME to the approved Foundry resource."
        )
    domain = cli_json(
        "cognitiveservices", "account", "show", "-g", group, "-n", account,
        "--subscription", subscription, "--query", "properties.customSubDomainName",
    )
    if not isinstance(domain, str) or not re.fullmatch(r"[a-z0-9-]+", domain):
        raise AzureContextError("The selected Foundry account did not return a valid custom subdomain.")
    return subscription, f"https://{domain}.openai.azure.com/openai/v1"


def verify_foundry_target(identity, endpoint):
    subscription, expected = resolve_foundry_target(identity)
    if endpoint != expected:
        raise AzureContextError("The Foundry endpoint does not match the account in the selected subscription.")
    return subscription
