"""Prepare a Track1 Fabric workspace, lakehouse, files, and notebooks."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from track1 import upload_fabric_notebooks, workshop
from tools.azure_demo_auth import separate_identity

FABRIC_API = "https://api.fabric.microsoft.com/v1"
ONELAKE_VERSION = "2021-06-08"
UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024
LAKEHOUSE_NAME = "IQ_Workshop_Lakehouse"
WORKSPACE_DESCRIPTION = "FabricIQ Track1 workshop demo environment"
LAKEHOUSE_DESCRIPTION = "Track1 workshop sample data and Ontology helper scripts"
TRACK1_FILES = (
    (Path("load_fabric.py"), "load_fabric.py"),
    (Path("standardization.py"), "standardization.py"),
    (Path("create_ontology_fabric.py"), "create_ontology_fabric_v2.py"),
)
REPLACEABLE_RUNTIME_FILES = {"standardization.py", "create_ontology_fabric_v2.py"}


def _validate_uuid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be a UUID.") from error


def _get_token(resource: str) -> str:
    identity = separate_identity()
    if identity:
        return identity.token(resource=resource)
    try:
        result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--resource",
                resource,
                "--output",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            "Azure CLI access token retrieval failed. Run az login and verify access."
        ) from error
    token = json.loads(result.stdout).get("accessToken")
    if not token:
        raise RuntimeError(f"Azure CLI did not return a token for {resource}.")
    return token


def _fabric_request(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any, Any]:
    return upload_fabric_notebooks._request(method, url, token, body)


def _list_items(url: str, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while url:
        _, response, _ = _fabric_request("GET", url, token)
        if not isinstance(response, dict) or not isinstance(response.get("value"), list):
            raise RuntimeError(f"Fabric list response did not contain a value array: {url}")
        items.extend(response["value"])
        continuation = response.get("continuationToken")
        url = (
            f"{url.split('?', 1)[0]}?"
            f"{urllib.parse.urlencode({'continuationToken': continuation})}"
            if continuation
            else ""
        )
    return items


def _workspace(
    *,
    token: str,
    workspace_id: str | None,
    workspace_name: str | None,
    create: bool,
    capacity_id: str | None,
    apply: bool,
) -> tuple[dict[str, Any] | None, str]:
    if workspace_id:
        _, item, _ = _fabric_request(
            "GET", f"{FABRIC_API}/workspaces/{workspace_id}", token
        )
        if not isinstance(item, dict):
            raise RuntimeError("Fabric did not return the requested workspace.")
        return item, "existing"

    matches = [
        item
        for item in _list_items(f"{FABRIC_API}/workspaces", token)
        if item.get("displayName", "").casefold() == (workspace_name or "").casefold()
    ]
    if len(matches) > 1:
        raise RuntimeError(f"Multiple workspaces are named {workspace_name!r}.")
    if matches:
        return matches[0], "existing"
    if not create:
        raise RuntimeError(
            f"Workspace {workspace_name!r} does not exist. Use --create-workspace "
            "with --capacity-id to create it."
        )
    if not capacity_id:
        raise ValueError("--capacity-id is required with --create-workspace.")
    if not apply:
        return None, "create"
    _, created, _ = _fabric_request(
        "POST",
        f"{FABRIC_API}/workspaces",
        token,
        {
            "displayName": workspace_name,
            "description": WORKSPACE_DESCRIPTION,
            "capacityId": capacity_id,
        },
    )
    if not isinstance(created, dict) or not created.get("id"):
        raise RuntimeError("Fabric created a workspace but did not return its ID.")
    return created, "created"


def _lakehouse(
    *,
    workspace_id: str | None,
    lakehouse_name: str,
    token: str,
    apply: bool,
) -> tuple[dict[str, Any] | None, str]:
    if not workspace_id:
        return None, "create"
    matches = [
        item
        for item in _list_items(
            f"{FABRIC_API}/workspaces/{workspace_id}/lakehouses", token
        )
        if item.get("displayName", "").casefold() == lakehouse_name.casefold()
    ]
    if len(matches) > 1:
        raise RuntimeError(f"Multiple Lakehouses are named {lakehouse_name!r}.")
    if matches:
        return matches[0], "existing"
    if not apply:
        return None, "create"
    upload_fabric_notebooks._request_and_wait(
        "POST",
        f"{FABRIC_API}/workspaces/{workspace_id}/lakehouses",
        token,
        {
            "displayName": lakehouse_name,
            "description": LAKEHOUSE_DESCRIPTION,
        },
    )
    created = [
        item
        for item in _list_items(
            f"{FABRIC_API}/workspaces/{workspace_id}/lakehouses", token
        )
        if item.get("displayName", "").casefold() == lakehouse_name.casefold()
    ]
    if len(created) != 1:
        raise RuntimeError(
            f"Lakehouse creation finished, but {lakehouse_name!r} could not be resolved."
        )
    return created[0], "created"


def _local_files() -> list[tuple[str, bytes]]:
    root = Path(__file__).resolve().parent
    data_root = root / "data"
    files = []
    for name, (expected_digest, _) in workshop.FILES.items():
        path = data_root / f"{name}.csv"
        try:
            content = path.read_bytes()
        except OSError as error:
            raise RuntimeError(f"Required source CSV is missing: {path}") from error
        workshop.verify(name, content)
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise ValueError(f"{path.name}: source digest does not match the manifest.")
        files.append((path.name, content))
    for relative_path, lakehouse_name in TRACK1_FILES:
        path = root / relative_path
        try:
            content = path.read_bytes()
        except OSError as error:
            raise RuntimeError(f"Required Track1 script is missing: {path}") from error
        files.append((lakehouse_name, content))
    return files


def _storage_request(
    method: str,
    url: str,
    token: str,
    body: bytes | None = None,
) -> tuple[int, bytes, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
        "x-ms-version": ONELAKE_VERSION,
    }
    if body is not None:
        headers["Content-Type"] = "application/octet-stream"
        headers["Content-Length"] = str(len(body))
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(
            request,
            context=upload_fabric_notebooks._ssl_context(),
            timeout=120,
        ) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        if error.code in (404, 409):
            return error.code, error.read(), error.headers
        detail = error.read().decode("utf-8", "replace")
        raise RuntimeError(
            f"OneLake {method} {url} returned HTTP {error.code}: {detail}"
        ) from error


def _one_lake_file_url(files_path: str, name: str) -> str:
    return f"{files_path.rstrip('/')}/{urllib.parse.quote(name, safe='')}"


def _read_existing_file(url: str, token: str) -> bytes | None:
    status, _, _ = _storage_request("HEAD", url, token)
    if status == 404:
        return None
    status, existing, _ = _storage_request("GET", url, token)
    if status != 200:
        raise RuntimeError(f"Could not read existing OneLake file at {url}.")
    return existing


def _append_file(url: str, content: bytes, offset: int, token: str) -> None:
    for position in range(offset, len(content), UPLOAD_CHUNK_SIZE):
        chunk = content[position:position + UPLOAD_CHUNK_SIZE]
        append_url = f"{url}?action=append&position={position}"
        status, _, _ = _storage_request("PATCH", append_url, token, chunk)
        if status not in (200, 202):
            raise RuntimeError(f"Unexpected OneLake append response: HTTP {status}")
    flush_url = f"{url}?action=flush&position={len(content)}"
    status, _, _ = _storage_request("PATCH", flush_url, token)
    if status not in (200, 201, 202):
        raise RuntimeError(f"Unexpected OneLake flush response: HTTP {status}")


def _upload_file(files_path: str, name: str, content: bytes, token: str) -> str:
    url = _one_lake_file_url(files_path, name)
    existing = _read_existing_file(url, token)
    if existing == content:
        return "skipped-identical"
    if existing is not None:
        if not content.startswith(existing):
            raise RuntimeError(
                f"OneLake file already exists with different content; refusing to "
                f"overwrite: {urllib.parse.unquote(url.rsplit('/', 1)[-1])}"
            )
        offset = len(existing)
    else:
        status, _, _ = _storage_request("PUT", f"{url}?resource=file", token)
        if status == 409:
            existing = _read_existing_file(url, token)
            if existing == content:
                return "skipped-identical"
            if existing is None or not content.startswith(existing):
                raise RuntimeError(
                    f"OneLake file appeared with different content; refusing to "
                    f"overwrite: {urllib.parse.unquote(url.rsplit('/', 1)[-1])}"
                )
            offset = len(existing)
        elif status in (200, 201):
            offset = 0
        else:
            raise RuntimeError(f"Unexpected OneLake file-create response: HTTP {status}")
    _append_file(url, content, offset, token)
    if _read_existing_file(url, token) != content:
        raise RuntimeError(f"Uploaded OneLake file could not be verified: {name}")
    return "uploaded"


def _upload_runtime_file(
    files_path: str,
    name: str,
    content: bytes,
    token: str,
    *,
    replace_existing: bool,
) -> str:
    if name not in REPLACEABLE_RUNTIME_FILES:
        raise ValueError(f"Runtime replacement is not allowed for {name!r}.")
    url = _one_lake_file_url(files_path, name)
    existing = _read_existing_file(url, token)
    if existing == content:
        return "skipped-identical"
    if existing is not None and replace_existing:
        status, _, _ = _storage_request("DELETE", url, token)
        if status not in (200, 202, 204):
            raise RuntimeError(f"Could not replace the existing runtime module {name}: HTTP {status}")
    elif existing is not None:
        raise RuntimeError(
            f"OneLake runtime module differs from the repository; refusing to overwrite: {name}"
        )
    return _upload_file(files_path, name, content, token)


def _files_path(workspace_id: str, lakehouse: dict[str, Any], token: str) -> str:
    lakehouse_id = lakehouse.get("id")
    if not lakehouse_id:
        raise RuntimeError("Fabric Lakehouse response did not contain an ID.")
    _, details, _ = _fabric_request(
        "GET",
        f"{FABRIC_API}/workspaces/{workspace_id}/lakehouses/{lakehouse_id}",
        token,
    )
    path = details.get("properties", {}).get("oneLakeFilesPath")
    if not path:
        path = (
            f"https://onelake.dfs.fabric.microsoft.com/"
            f"{workspace_id}/{lakehouse_id}/Files"
        )
    if not path.startswith("https://") or "onelake.dfs.fabric.microsoft.com" not in path:
        raise RuntimeError(f"Unexpected Lakehouse OneLake Files path: {path}")
    return path


def deploy(
    *,
    workspace_id: str | None = None,
    workspace_name: str | None = None,
    create_workspace: bool = False,
    capacity_id: str | None = None,
    lakehouse_name: str = LAKEHOUSE_NAME,
    expected_lakehouse_id: str | None = None,
    apply: bool = False,
    update_existing_notebooks: bool = False,
    replace_existing_runtime_files: bool = False,
    fabric_token: str | None = None,
    storage_token: str | None = None,
) -> dict[str, Any]:
    if update_existing_notebooks and not apply:
        raise ValueError("--update-existing-notebooks requires --apply.")
    if replace_existing_runtime_files and not apply:
        raise ValueError("--replace-existing-runtime-files requires --apply.")
    if workspace_id:
        workspace_id = _validate_uuid(workspace_id, "workspace_id")
        if create_workspace:
            raise ValueError("Use either --workspace-id or --create-workspace, not both.")
    elif not workspace_name:
        raise ValueError("--workspace-id or --workspace-name is required.")
    if create_workspace and not capacity_id:
        raise ValueError("--capacity-id is required with --create-workspace.")
    if capacity_id:
        capacity_id = _validate_uuid(capacity_id, "capacity_id")
    if expected_lakehouse_id:
        expected_lakehouse_id = _validate_uuid(expected_lakehouse_id, "expected_lakehouse_id")
        if not workspace_id:
            raise ValueError("An expected Lakehouse ID requires an existing workspace ID.")

    local_files = _local_files()
    if not fabric_token:
        fabric_token = _get_token("https://api.fabric.microsoft.com")
    if apply and not storage_token:
        storage_token = _get_token("https://storage.azure.com/")

    workspace, workspace_action = _workspace(
        token=fabric_token,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        create=create_workspace,
        capacity_id=capacity_id,
        apply=apply,
    )
    resolved_workspace_id = workspace.get("id") if workspace else None
    lakehouse, lakehouse_action = _lakehouse(
        workspace_id=resolved_workspace_id,
        lakehouse_name=lakehouse_name,
        token=fabric_token,
        apply=apply and not expected_lakehouse_id,
    )
    if expected_lakehouse_id and (
        not lakehouse or str(lakehouse.get("id") or "").lower() != expected_lakehouse_id
    ):
        raise RuntimeError(
            "The named Lakehouse does not match the requested ID; refusing all writes. "
            f"Requested {expected_lakehouse_id}, resolved {(lakehouse or {}).get('id')}."
        )

    if not apply:
        notebook_actions = []
        if resolved_workspace_id:
            notebook_actions = upload_fabric_notebooks.publish(
                resolved_workspace_id,
                lakehouse_id=lakehouse.get("id") if lakehouse else None,
                lakehouse_name=lakehouse_name if lakehouse else None,
                token=fabric_token,
                apply=False,
                update_existing=update_existing_notebooks,
            )
        return {
            "mode": "dry-run",
            "workspace": {
                "action": workspace_action,
                "id": resolved_workspace_id,
                "name": (workspace or {}).get("displayName", workspace_name),
            },
            "lakehouse": {
                "action": lakehouse_action,
                "id": (lakehouse or {}).get("id"),
                "name": lakehouse_name,
            },
            "files": [
                {"name": name, "action": "upload-if-missing-or-identical"}
                for name, _ in local_files
            ],
            "notebooks": notebook_actions or [
                {
                    "display_name": path.stem,
                    "action": "create-after-workspace-provisioning",
                }
                for path in upload_fabric_notebooks.NOTEBOOKS
            ],
            "note": "No Fabric resources or OneLake files were changed.",
        }

    if not workspace or not resolved_workspace_id:
        raise RuntimeError("Workspace provisioning completed without an ID.")
    if not lakehouse:
        lakehouse, lakehouse_action = _lakehouse(
            workspace_id=resolved_workspace_id,
            lakehouse_name=lakehouse_name,
            token=fabric_token,
            apply=True,
        )
    if not lakehouse or not lakehouse.get("id"):
        raise RuntimeError("Lakehouse provisioning completed without an ID.")
    if not storage_token:
        raise RuntimeError("OneLake Storage access token is required for file uploads.")

    files_path = _files_path(resolved_workspace_id, lakehouse, fabric_token)
    uploaded_files = []
    for name, content in local_files:
        if replace_existing_runtime_files and name in REPLACEABLE_RUNTIME_FILES:
            action = _upload_runtime_file(
                files_path, name, content, storage_token, replace_existing=True
            )
        else:
            action = _upload_file(files_path, name, content, storage_token)
        uploaded_files.append(
            {"name": name, "action": action}
        )
    notebooks = upload_fabric_notebooks.publish(
        resolved_workspace_id,
        lakehouse_id=lakehouse["id"],
        lakehouse_name=lakehouse_name,
        token=fabric_token,
        apply=True,
        update_existing=update_existing_notebooks,
    )
    return {
        "mode": "apply",
        "workspace": {
            "action": workspace_action,
            "id": resolved_workspace_id,
            "name": workspace.get("displayName"),
        },
        "lakehouse": {
            "action": lakehouse_action,
            "id": lakehouse["id"],
            "name": lakehouse_name,
        },
        "files_path": files_path,
        "files": uploaded_files,
        "notebooks": notebooks,
        "next_step": (
            "Run track1/run_track1.py --workspace-id <id> --lakehouse-id <id> --apply "
            "to execute the end-to-end Track1 Notebook."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--workspace-id", help="Reuse an existing Fabric workspace ID.")
    target.add_argument("--workspace-name", help="Find or create a named workspace.")
    parser.add_argument(
        "--create-workspace",
        action="store_true",
        help="Create the named workspace if it does not exist.",
    )
    parser.add_argument(
        "--capacity-id",
        help="Fabric capacity ID; required when creating a workspace.",
    )
    parser.add_argument("--lakehouse-name", default=LAKEHOUSE_NAME)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create resources and upload files. Omit for read-only dry run.",
    )
    parser.add_argument(
        "--update-existing-notebooks",
        action="store_true",
        help="Replace existing Notebook definitions with repository versions.",
    )
    parser.add_argument(
        "--replace-existing-runtime-files",
        action="store_true",
        help="Replace the two named Track1 runtime modules in OneLake.",
    )
    args = parser.parse_args()
    try:
        result = deploy(
            workspace_id=args.workspace_id,
            workspace_name=args.workspace_name,
            create_workspace=args.create_workspace,
            capacity_id=args.capacity_id,
            lakehouse_name=args.lakehouse_name,
            apply=args.apply,
            update_existing_notebooks=args.update_existing_notebooks,
            replace_existing_runtime_files=args.replace_existing_runtime_files,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
