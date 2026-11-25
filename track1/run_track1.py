"""Deploy and execute the complete Track1 Fabric pipeline."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from track1 import deploy_fabric, materialize_graph
from track1.standardization import RULES

NOTEBOOK_NAME = "IQ_Workshop_Track1_KO"
MAX_JOB_POLLS = 240


def _header(headers: Any, name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def _execute_notebook(
    workspace_id: str,
    notebook_id: str,
    lakehouse_id: str,
    token: str,
) -> dict[str, Any]:
    url = (
        f"{deploy_fabric.FABRIC_API}/workspaces/{workspace_id}/notebooks/{notebook_id}"
        "/jobs/execute/instances?beta=false"
    )
    status, _, headers = deploy_fabric._fabric_request(
        "POST",
        url,
        token,
        {
            "executionData": {
                "compute": "Spark",
                "computeConfiguration": {
                    "defaultLakehouse": {
                        "referenceType": "ById",
                        "itemId": lakehouse_id,
                        "workspaceId": workspace_id,
                    }
                },
            }
        },
    )
    if status != 202:
        raise RuntimeError(f"Fabric accepted no Notebook job (HTTP {status}).")
    job_url = _header(headers, "Location")
    if not job_url or urlparse(job_url).scheme != "https":
        raise RuntimeError("Fabric did not return a valid Notebook job URL.")
    retry_after = int(_header(headers, "Retry-After") or "30")
    for _ in range(MAX_JOB_POLLS):
        time.sleep(min(max(retry_after, 1), 120))
        poll_status, result, poll_headers = deploy_fabric._fabric_request("GET", job_url, token)
        if poll_status != 200 or not isinstance(result, dict):
            raise RuntimeError(f"Notebook job status request failed (HTTP {poll_status}).")
        state = result.get("status")
        if state == "Completed":
            job_id = result.get("id") or job_url.rstrip("/").rsplit("/", 1)[-1]
            details_url = (
                f"{deploy_fabric.FABRIC_API}/workspaces/{workspace_id}/notebooks/{notebook_id}"
                f"/jobs/execute/instances/{job_id}?beta=true"
            )
            details_status, details, _ = deploy_fabric._fabric_request("GET", details_url, token)
            if details_status != 200 or not isinstance(details, dict):
                raise RuntimeError(
                    f"Could not retrieve completed Notebook output (HTTP {details_status})."
                )
            exit_value = details.get("properties", {}).get("exitValue", details.get("exitValue"))
            if isinstance(exit_value, str):
                try:
                    exit_value = json.loads(exit_value)
                except json.JSONDecodeError:
                    pass
            return {"job_status": state, "job_id": job_id, "exit_value": exit_value}
        if state in {"Failed", "Cancelled", "Canceled"}:
            raise RuntimeError(
                f"Track1 Notebook {state} (job {result.get('id')}): "
                f"{json.dumps(result.get('failureReason'), ensure_ascii=False)}"
            )
        retry_after = int(_header(poll_headers, "Retry-After") or retry_after)
    raise TimeoutError(f"Track1 Notebook did not finish after {MAX_JOB_POLLS} status checks.")


def run(
    *,
    workspace_id: str,
    lakehouse_id: str | None = None,
    lakehouse_name: str = deploy_fabric.LAKEHOUSE_NAME,
    apply: bool = False,
    fabric_token: str | None = None,
    storage_token: str | None = None,
) -> dict[str, Any]:
    fabric_token = fabric_token or deploy_fabric._get_token("https://api.fabric.microsoft.com")
    result = deploy_fabric.deploy(
        workspace_id=workspace_id,
        lakehouse_name=lakehouse_name,
        expected_lakehouse_id=lakehouse_id,
        apply=apply,
        update_existing_notebooks=apply,
        replace_existing_runtime_files=apply,
        fabric_token=fabric_token,
        storage_token=storage_token,
    )
    if not apply:
        return result
    resolved_lakehouse_id = result["lakehouse"].get("id")
    if not resolved_lakehouse_id:
        raise RuntimeError("The target Lakehouse did not return an ID.")
    if lakehouse_id and resolved_lakehouse_id.casefold() != lakehouse_id.casefold():
        raise RuntimeError(
            "The named Lakehouse resolved to a different ID; refusing to run the Notebook. "
            f"Requested {lakehouse_id}, resolved {resolved_lakehouse_id}."
        )
    notebook = next(
        (
            item for item in result["notebooks"]
            if item.get("display_name") == NOTEBOOK_NAME and item.get("notebook_id")
        ),
        None,
    )
    if not notebook:
        raise RuntimeError(f"Published Notebook {NOTEBOOK_NAME!r} did not return an ID.")
    execution = _execute_notebook(
        workspace_id, notebook["notebook_id"], resolved_lakehouse_id, fabric_token
    )
    exit_value = execution.get("exit_value")
    if not isinstance(exit_value, dict):
        raise RuntimeError("Track1 Notebook completed without a structured verification result.")
    queries = exit_value.get("queries", {})
    ontology = exit_value.get("ontology", {})
    if (
        queries.get("status") != "passed"
        or ontology.get("mode") != "apply"
        or ontology.get("generation") != 2
        or ontology.get("verified_definition", {}).get("binding_mode") != "oneLake"
        or ontology.get("verified_definition", {}).get("lakehouse_binding_count") != 14
        or ontology.get("verified_definition", {}).get("standardized_property_count")
        != sum(len(rules) for rules in RULES.values())
    ):
        raise RuntimeError(
            "Notebook completed without the expected Track1 query and Ontology verification: "
            + json.dumps(exit_value, ensure_ascii=False)
        )
    ontology_id = ontology.get("ontology_id")
    if not ontology_id:
        raise RuntimeError("Track1 Notebook verification did not return an Ontology ID.")
    graph = materialize_graph.run(
        workspace_id=workspace_id,
        ontology_id=ontology_id,
        lakehouse_id=resolved_lakehouse_id,
        apply=True,
        fabric_token=fabric_token,
    )
    return {"deployment": result, "execution": execution, "graph": graph}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--lakehouse-id", help="Optional ID guard; otherwise resolve by name.")
    parser.add_argument("--lakehouse-name", default=deploy_fabric.LAKEHOUSE_NAME)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Deploy/update Track1 artifacts and execute the Notebook (writes Fabric resources).",
    )
    args = parser.parse_args()
    try:
        result = run(
            workspace_id=args.workspace_id,
            lakehouse_id=args.lakehouse_id,
            lakehouse_name=args.lakehouse_name,
            apply=args.apply,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        print(f"Track1 pipeline failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
