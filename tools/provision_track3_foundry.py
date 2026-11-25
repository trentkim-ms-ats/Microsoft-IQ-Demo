"""Create a dedicated keyless Foundry account and WebIQ model deployment."""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from tools import azure_demo_auth as auth

ARM = "https://management.azure.com"
PROVIDER = "Microsoft.CognitiveServices"
API = "2025-06-01"
TAG = "iq-demo-track"
TAG_VALUE = "webiq"
INFERENCE_ROLE = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"  # Cognitive Services OpenAI User
SKU = "GlobalStandard"
CONFIG_PATH = Path("track3/foundry.provisioned.local.json")


@dataclass(frozen=True)
class Target:
    subscription: str
    group: str
    account: str
    location: str
    model: str
    version: str
    capacity: int
    track: str = TAG_VALUE

    @property
    def group_id(self):
        return f"/subscriptions/{self.subscription}/resourceGroups/{self.group}"

    @property
    def account_id(self):
        return f"{self.group_id}/providers/{PROVIDER}/accounts/{self.account}"

    @property
    def deployment_id(self):
        return f"{self.account_id}/deployments/{self.model}"

    def configuration(self):
        return {
            "subscription": self.subscription, "resourceGroup": self.group,
            "account": self.account, "deployment": self.model,
            "endpoint": f"https://{self.account}.services.ai.azure.com",
        }

    def az(self, *args, **kwargs):
        return auth.cli_json(*args, "--subscription", self.subscription, **kwargs)

    def arm(self, method, path, api=API, body=None):
        payload = ("--body", json.dumps(body)) if body is not None else ()
        return self.az("rest", "--method", method, "--uri", f"{ARM}{path}?api-version={api}", *payload)


def check_capacity(target):
    models = target.az("cognitiveservices", "model", "list", "--location", target.location)
    skus = [
        sku for row in models for model in [row["model"]]
        if (model["name"], model["version"], model["format"]) == (target.model, target.version, "OpenAI")
        for sku in model.get("skus") or [] if sku["name"] == SKU
    ]
    if not skus:
        raise ValueError(f"{target.model} {target.version} is not offered as {SKU} in {target.location}.")
    for sku in skus:
        limits = sku.get("capacity") or {}
        minimum, maximum, step = limits.get("minimum") or 1, limits.get("maximum"), limits.get("step") or 1
        values = limits.get("allowedValues")
        if target.capacity >= minimum and (target.capacity - minimum) % step == 0 and (
            maximum is None or target.capacity <= maximum
        ) and (not values or target.capacity in values):
            break
    else:
        raise ValueError(f"The model catalog does not allow capacity {target.capacity} for {SKU}.")

    quota_name = sku.get("usageName") or f"OpenAI.{SKU}.{target.model}"
    rows = target.az("cognitiveservices", "usage", "list", "--location", target.location)
    quota = next((row for row in rows if row["name"]["value"] == quota_name), None)
    if quota is None:
        raise ValueError(f"No quota record was returned for {quota_name} in {target.location}.")
    available = quota["limit"] - quota["currentValue"]
    if target.capacity > available:
        raise ValueError(f"{quota_name} in {target.location}: {available:g} capacity units available, "
                         f"{target.capacity} requested. Existing deployments were not changed.")


def wait_ready(target, resource_id):
    for attempt in range(40):
        resource = target.arm("get", resource_id)
        state = resource["properties"]["provisioningState"]
        if state == "Succeeded":
            return resource
        if state in ("Failed", "Canceled", "Deleting"):
            raise ValueError(f"Azure returned provisioning state {state} for {resource_id}.")
        if attempt < 39:
            time.sleep(5)
    raise ValueError(f"{resource_id} is still provisioning. Rerun with the same target to resume.")


def verify_account(target):
    resource = wait_ready(target, target.account_id)
    props = resource["properties"]
    endpoint = (props.get("endpoints") or {}).get("AI Foundry API") or ""
    if (
        (resource.get("tags") or {}).get(TAG) != target.track
        or resource["kind"] != "AIServices" or resource["location"] != target.location
        or resource["sku"]["name"] != "S0" or props.get("customSubDomainName") != target.account
        or props.get("disableLocalAuth") is not True or props.get("publicNetworkAccess") != "Enabled"
        or endpoint.rstrip("/") != target.configuration()["endpoint"]
    ):
        raise ValueError(f"The Foundry account does not match this {target.track} stack; no updates were made to it.")


def ensure_inference_role(target, principal):
    scope = target.account_id
    scoped = ("--scope", scope)

    def matches(row):
        return (
            row["scope"].casefold() == scope.casefold()
            and row["principalId"].casefold() == principal
            and row["roleDefinitionId"].casefold().endswith("/" + INFERENCE_ROLE)
            and not row.get("condition")
        )

    roles = target.az("role", "assignment", "list", *scoped, "--fill-principal-name", "false")
    if any(matches(row) for row in roles):
        return
    assigned = target.az(
        "role", "assignment", "create", *scoped, "--role", INFERENCE_ROLE,
        "--assignee-object-id", principal, "--assignee-principal-type", "User",
    )
    if not matches(assigned):
        raise ValueError("Azure did not return the requested account-scoped inference role assignment.")


def provision(target, identity):
    if "@" not in identity.account:
        raise ValueError("Provision with the approved Azure user login; run with OIDC separately.")
    token = identity.token(scope=f"{ARM}/.default", subscription=target.subscription)
    principal = str(UUID(auth.token_claims(token)["oid"]))
    subscription = target.arm("get", f"/subscriptions/{target.subscription}", api="2022-12-01")
    if subscription["state"] != "Enabled":
        raise ValueError("The selected subscription is not Enabled in Azure Resource Manager.")
    if target.az("provider", "show", "--namespace", PROVIDER, "--query", "registrationState") != "Registered":
        raise ValueError(f"{PROVIDER} must already be registered on the selected subscription.")

    group = target.az("group", "exists", "--name", target.group)
    account = deployment = False
    if group:
        resource = target.az("group", "show", "--name", target.group)
        if (resource.get("tags") or {}).get(TAG) != target.track or resource["location"] != target.location:
            raise ValueError(f"Refusing an existing resource group without the {target.track} tag and matching region.")
        ids = {item.casefold() for item in target.az("resource", "list", "-g", target.group, "--query", "[].id")}
        if ids - {target.account_id.casefold(), target.deployment_id.casefold()}:
            raise ValueError(f"Refusing a resource group containing resources outside this {target.track} stack.")
        account = target.account_id.casefold() in ids
    if account:
        verify_account(target)
        names = target.az("cognitiveservices", "account", "deployment", "list", "-g", target.group,
                          "-n", target.account, "--query", "[].name")
        deployment = target.model in names
        if set(names) - {target.model}:
            raise ValueError(f"Refusing a Foundry account that contains deployments outside this {target.track} stack.")
    else:
        available = target.arm("post", f"/subscriptions/{target.subscription}/providers/{PROVIDER}/checkDomainAvailability",
                               body={"subdomainName": target.account, "type": f"{PROVIDER}/accounts"})
        if available.get("isSubdomainAvailable") is not True:
            raise ValueError("The requested Foundry subdomain is unavailable; choose a unique --account.")

    if not deployment:
        check_capacity(target)
    if not group:
        target.az("group", "create", "--name", target.group, "--location", target.location,
                  "--tags", f"{TAG}={target.track}")
    if not account:
        target.arm("put", target.account_id, body={
            "location": target.location, "kind": "AIServices", "sku": {"name": "S0"},
            "tags": {TAG: target.track}, "properties": {
                "customSubDomainName": target.account, "disableLocalAuth": True, "publicNetworkAccess": "Enabled",
            },
        })
        verify_account(target)

    model = {"format": "OpenAI", "name": target.model, "version": target.version}
    if not deployment:
        target.arm("put", target.deployment_id, body={
            "sku": {"name": SKU, "capacity": target.capacity},
            "properties": {"model": model, "versionUpgradeOption": "NoAutoUpgrade"},
        })
    deployed = wait_ready(target, target.deployment_id)
    actual_model = deployed["properties"]["model"]
    if any(actual_model.get(key) != value for key, value in model.items()) or (
        deployed["sku"]["name"], deployed["sku"]["capacity"]
    ) != (SKU, target.capacity):
        raise ValueError("The existing deployment does not match the requested model, version, SKU, or capacity.")
    ensure_inference_role(target, principal)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", type=UUID, required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--account", required=True, help="Globally unique Foundry account and custom subdomain.")
    parser.add_argument("--location", required=True)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--model-version", default="2026-07-09")
    parser.add_argument("--capacity", type=int, default=400, help="GlobalStandard deployment capacity units.")
    parser.add_argument("--apply", action="store_true", help="Create resources and grant the signed-in user inference access.")
    args = parser.parse_args()
    if any(not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]", value) for value in (
        args.account, args.resource_group, args.location,
    )) or any(not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,61}[a-z0-9]", value) for value in (
        args.model, args.model_version,
    )) or args.capacity < 1:
        parser.error("Use lowercase names, a valid model and version, and a positive capacity.")
    target = Target(str(args.subscription), args.resource_group, args.account, args.location,
                    args.model, args.model_version, args.capacity)
    result = {
        "target": target.configuration(), "location": target.location, "modelVersion": target.version,
        "sku": SKU, "capacity": target.capacity, "inferenceRoleScope": target.account_id,
    }
    try:
        if not args.apply:
            print(json.dumps(result | {"status": "plan"}, indent=2))
            return 0
        provision(target, auth.require_separate_identity())
        CONFIG_PATH.write_text(json.dumps(target.configuration(), indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result | {"status": "provisioned", "config": str(CONFIG_PATH)}, indent=2))
        return 0
    except (OSError, KeyError, ValueError) as error:
        print(f"Track 3 provisioning failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
