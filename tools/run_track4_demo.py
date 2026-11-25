"""Run the standalone live Track 4 demo in the isolated Azure tenant."""

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from tools import azure_demo_auth as auth
from tools import live_demo, provision_track3_foundry as provisioning, webiq

SCENARIOS = webiq.PROFILES["demo"]
FABRIC_API = "https://api.fabric.microsoft.com"
OPERATION_ERRORS = (live_demo.LiveServiceError, OSError, ValueError)
FIXTURE_COUNTS = {"Q1": 60, "Q2": 2, "Q3": 4, "Q4": 2, "Q5": 81}


def _dedicated_target(subscription):
    return provisioning.Target(
        str(subscription), "rg-iq-foundryiq", f"iq-foundryiq-{subscription.hex[:12]}",
        "eastus", "gpt-6.2-sol", "2026-11-17", 400, track="foundryiq",
    )


def _reject_credentials():
    if os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_AUTH_TOKEN"):
        raise auth.AzureContextError("Remove standalone Foundry keys/tokens; Track 4 uses the isolated Azure CLI login.")


def _prepare_dedicated_foundry(target, identity):
    provisioning.provision(target, identity)
    endpoint = target.configuration()["endpoint"] + "/openai/v1"

    def respond(body):
        body = {**body, "max_output_tokens": min(body.get("max_output_tokens", 10_000), 10_000)}
        return live_demo._azure_foundry_responses(
            endpoint, body, azure=identity, subscription=target.subscription, rate_limit_wait=120,
        )

    return target.model, respond


def _verify_inference(model, respond):
    for attempt in range(7):
        try:
            response = respond({"model": model, "input": "Reply with OK only.",
                                "max_output_tokens": 256, "store": False})
            live_demo._response_text(response)
            return response["id"]
        except live_demo.LiveHttpError as error:
            if (
                attempt == 6 or error.status not in (401, 403)
                or not str(error).endswith((": PermissionDenied", ": AuthorizationFailed"))
            ):
                raise
            time.sleep(15)


def _read_fixture(identity, target, scenario):
    fabric = live_demo._fabric_query(scenario, azure=identity, target=target)
    actual = len(fabric["rows"])
    expected = FIXTURE_COUNTS[scenario]
    if fabric["status"] != "succeeded" or actual != expected:
        raise live_demo.LiveServiceError(f"{scenario}: the original workshop fixture must return {expected} rows, got {actual}.")
    return fabric


def _fabric_ready(identity):
    try:
        workspace, lakehouse = (
            str(UUID(os.environ.get(key, ""))) for key in ("FABRIC_WORKSPACE_ID", "FABRIC_LAKEHOUSE_ID")
        )
    except ValueError as error:
        raise auth.AzureContextError("Set FABRIC_WORKSPACE_ID and FABRIC_LAKEHOUSE_ID to the approved demo item IDs.") from error
    token = identity.token(resource=FABRIC_API)
    try:
        item = live_demo._json_request(
            f"{FABRIC_API}/v1/workspaces/{workspace}/lakehouses/{lakehouse}",
            token=token, no_redirect=True,
        )
    except live_demo.LiveHttpError as error:
        if error.status not in (401, 403):
            raise
        raise live_demo.LiveServiceError(
            f"{error}. Verify that the current demo login can open the selected Fabric workspace and Lakehouse."
        ) from error
    if (
        not isinstance(item, dict) or item.get("type") != "Lakehouse"
        or item.get("id") != lakehouse or item.get("workspaceId") != workspace
    ):
        raise auth.AzureContextError("Fabric did not return the selected demo lakehouse.")
    properties = item.get("properties")
    sql = properties.get("sqlEndpointProperties") if isinstance(properties, dict) else None
    if not isinstance(sql, dict):
        raise auth.AzureContextError("Fabric did not return SQL endpoint metadata for the selected lakehouse.")
    server, database = sql.get("connectionString"), item.get("displayName")
    if (
        sql.get("provisioningStatus") != "Success" or not isinstance(server, str)
        or not re.fullmatch(r"[a-z0-9-]+\.datawarehouse\.fabric\.microsoft\.com", server, re.I)
        or not isinstance(database, str) or not re.fullmatch(r"[a-z0-9_ -]+", database, re.I)
    ):
        raise auth.AzureContextError("The selected lakehouse does not have a ready, valid SQL endpoint.")
    return server, database


def _check(call):
    try:
        return {"status": "ready"}, call()
    except OPERATION_ERRORS as error:
        return {"status": "blocked", "error": str(error)}, None


def run(now, *, scenario=None, preflight_only=False, provision_subscription=None):
    selected = (scenario,) if scenario else SCENARIOS
    dedicated = _dedicated_target(provision_subscription) if provision_subscription else None
    if dedicated and preflight_only:
        raise ValueError("Provisioning cannot be combined with a read-only preflight.")
    preflight = {}
    preflight["identity"], identity = _check(auth.require_separate_identity)
    preflight["catalog"], specs = _check(lambda: webiq.load_specs("demo", now, 7))
    foundry = target = None
    fixture = {}
    if identity:
        preflight["fabric"], target = _check(lambda: _fabric_ready(identity))
        if not dedicated:
            preflight["foundry"], foundry = _check(
                lambda: live_demo.prepare_separate_foundry(identity, allow_services_endpoint=True)
            )
    else:
        preflight["fabric"] = {"status": "not-run"}
        preflight["foundry"] = {"status": "not-run"}

    report = {
        "mode": "preflight" if preflight_only else "live",
        "startedAt": now.isoformat(timespec="seconds"),
        "status": "blocked",
        "preflight": preflight,
        "plannedScenarios": list(selected),
        "scenarios": [],
        "workIQ": "excluded-by-tenant-separation",
        "humanApprovalRequired": True,
    }
    if dedicated:
        report["foundryTarget"] = dedicated.configuration() | {
            "region": dedicated.location, "modelVersion": dedicated.version,
            "sku": provisioning.SKU, "capacity": dedicated.capacity,
        }
        preflight["foundry"] = {"status": "not-run"}
        preflight["inference"] = {"status": "not-run"}
        preflight["foundryCredentials"], _ = _check(_reject_credentials)
        if not (identity and specs and target and preflight["foundryCredentials"]["status"] == "ready"):
            return report
        for scenario_id in selected:
            check, fabric = _check(lambda: _read_fixture(identity, target, scenario_id))
            preflight[f"fabricSQL.{scenario_id}"] = check
            if fabric:
                check["rows"] = len(fabric["rows"])
                fixture[scenario_id] = fabric
        if len(fixture) != len(selected):
            return report
        preflight["foundry"], foundry = _check(lambda: _prepare_dedicated_foundry(dedicated, identity))
        if foundry:
            preflight["inference"], smoke_id = _check(lambda: _verify_inference(*foundry))
            if not smoke_id:
                return report
            preflight["inference"]["responseId"] = smoke_id

    if preflight_only:
        if specs and foundry and target:
            report["status"] = "ready"
        return report
    if not (specs and foundry and target):
        return report

    model, respond = foundry
    for scenario in selected:
        web = live_demo.collect_web_evidence(scenario, specs[scenario], model, respond)
        try:
            result = live_demo.run_separate(
                scenario, azure=identity, fabric_target=target, web=web, model=model, respond=respond,
                current_fabric=fixture.get(scenario),
            )
        except OPERATION_ERRORS as error:
            result = {"scenarioId": scenario, "status": "failed", "synthesisStatus": "not-run", "error": str(error)}
        report["scenarios"].append(result)
    report["status"] = (
        "succeeded"
        if all(row["status"] == row["synthesisStatus"] == "succeeded" for row in report["scenarios"])
        else "incomplete"
    )
    return report


def save_report(report, output, now):
    directory = output / now.strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    json_path = directory / "demo.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=live_demo._json_default) + "\n", encoding="utf-8")
    lines = [
        "# Track 4 — FoundryIQ", "",
        f"Mode: `{report['mode']}` | Status: `{report['status']}` | UTC: {report['startedAt']}", "",
        "Track 2 (WorkIQ) is excluded. Live evidence requires human review before presentation.", "",
        "## Preflight", "",
    ]
    if target := report.get("foundryTarget"):
        lines.extend([f"Foundry: `{target['resourceGroup']}` / `{target['account']}` / "
                      f"`{target['deployment']}` (`{target['modelVersion']}`, {target['sku']}).", ""])
    for name, check in report["preflight"].items():
        lines.extend([f"- {name}: `{check['status']}`", ""])
        if check.get("error"):
            lines.extend([live_demo.markdown_literal(check["error"]), ""])
    lines.extend(["## Fabric + WebIQ synthesis", ""])
    if not report["scenarios"]:
        lines.extend(["Not run: " + ", ".join(report["plannedScenarios"]), ""])
    for row in report["scenarios"]:
        lines.extend([f"### {row['scenarioId']} — {row['status']}", ""])
        lines.extend([f"Synthesis: `{row['synthesisStatus']}`", ""])
        for key in ("question", "answer", "limitations", "error", "synthesisError"):
            if row.get(key):
                lines.extend([live_demo.markdown_literal(row[key]), ""])
        for source, value in row.get("sources", {}).items():
            lines.append(f"- {source}: `{value['status']}`")
            if value.get("error"):
                lines.extend(["", live_demo.markdown_literal(value["error"]), ""])
        if row.get("fabric"):
            fabric = row["fabric"]
            lines.extend(["", f"Fabric `{fabric['queryId']}`: {len(fabric['rows'])} rows (see `demo.json`).", ""])
        citations = row.get("web", {}).get("citations", [])
        if citations:
            lines.append("")
            for cite in citations:
                lines.extend([
                    live_demo.markdown_literal(f"{cite['id']}: {cite['title']}\n{cite['url']}\n{cite['observedAt']}"), "",
                ])
    (directory / "demo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, help="Run one scenario instead of Q1–Q5.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight-only", action="store_true", help="Check identity and resource metadata without querying models or SQL.")
    mode.add_argument(
        "--provision", type=UUID, metavar="SUBSCRIPTION_ID",
        help="Create or reuse the dedicated FoundryIQ stack in this subscription, then run the live demo.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/track4"))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    report = run(now, scenario=args.scenario, preflight_only=args.preflight_only, provision_subscription=args.provision)
    path = save_report(report, args.output_dir, now)
    print(json.dumps({"status": report["status"], "report": str(path)}))
    return 0 if report["status"] in ("ready", "succeeded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
