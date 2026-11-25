"""Track1 Fabric Notebook 파일을 Workspace Notebook 항목으로 게시합니다."""

import argparse
import base64
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.azure_demo_auth import separate_identity

FABRIC_API = "https://api.fabric.microsoft.com/v1"
NOTEBOOKS = (
    Path("IQ_Workshop_Track1_KO.ipynb"),
    Path("IQ_Workshop_Ontology_AutoCreate.ipynb"),
)
MAX_OPERATION_POLLS = 60


def _ssl_context() -> ssl.SSLContext:
    ca_file = os.environ.get("SSL_CERT_FILE")
    if ca_file:
        return ssl.create_default_context(cafile=ca_file)
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _get_token() -> str:
    identity = separate_identity()
    if identity:
        return identity.token(resource="https://api.fabric.microsoft.com")
    try:
        result = subprocess.run(
            [
                "az",
                "account",
                "get-access-token",
                "--resource",
                "https://api.fabric.microsoft.com",
                "--output",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            "Fabric 인증 토큰을 가져오지 못했습니다. Azure CLI 로그인 상태를 확인하세요."
        ) from error
    token = json.loads(result.stdout).get("accessToken")
    if not token:
        raise RuntimeError("Azure CLI 응답에 Fabric access token이 없습니다.")
    return token


def _request(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any, Any]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(
            request, context=_ssl_context(), timeout=60
        ) as response:
            raw = response.read()
            payload = json.loads(raw.decode("utf-8")) if raw else None
            return response.status, payload, response.headers
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", "replace")
        raise RuntimeError(
            f"Fabric API {method} {url} returned HTTP {error.code}: {details}"
        ) from error


def _header(headers: Any, name: str) -> str | None:
    return next(
        (value for key, value in headers.items() if key.lower() == name.lower()),
        None,
    )


def _request_and_wait(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> Any:
    status, payload, headers = _request(method, url, token, body)
    if status != 202:
        return payload

    operation_id = _header(headers, "x-ms-operation-id")
    operation_url = _header(headers, "Location")
    if not operation_url and operation_id:
        operation_url = f"{FABRIC_API}/operations/{operation_id}"
    if not operation_url:
        raise RuntimeError("Fabric returned HTTP 202 without an operation URL or ID.")

    retry_after = int(_header(headers, "Retry-After") or "5")
    for _ in range(MAX_OPERATION_POLLS):
        time.sleep(min(max(retry_after, 1), 30))
        _, state, state_headers = _request("GET", operation_url, token)
        if not isinstance(state, dict):
            raise RuntimeError("Fabric operation status response was not a JSON object.")
        operation_status = state.get("status")
        if operation_status == "Succeeded":
            result_url = (
                f"{FABRIC_API}/operations/{operation_id}/result"
                if operation_id
                else None
            )
            if result_url:
                _, result, _ = _request("GET", result_url, token)
                return result
            updated_location = _header(state_headers, "Location")
            if updated_location and updated_location != operation_url:
                _, result, _ = _request("GET", updated_location, token)
                return result
            return state
        if operation_status in ("Failed", "Canceled"):
            raise RuntimeError(f"Fabric operation {operation_status}: {state}")
        retry_after = int(_header(state_headers, "Retry-After") or retry_after)

    raise TimeoutError(
        f"Fabric operation did not finish after {MAX_OPERATION_POLLS} status checks: "
        f"{operation_url}"
    )


def _load_notebook(
    path: Path,
    *,
    workspace_id: str | None = None,
    lakehouse_id: str | None = None,
    lakehouse_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Notebook을 읽을 수 없습니다: {path}") from error
    if notebook.get("nbformat") != 4 or not isinstance(notebook.get("cells"), list):
        raise ValueError(f"유효한 nbformat 4 Notebook이 아닙니다: {path}")
    if any((workspace_id, lakehouse_id, lakehouse_name)):
        if not all((workspace_id, lakehouse_id, lakehouse_name)):
            raise ValueError(
                "workspace_id, lakehouse_id, lakehouse_name must be provided together."
            )
        lakehouse_metadata = {
            "default_lakehouse": lakehouse_id,
            "default_lakehouse_name": lakehouse_name,
            "default_lakehouse_workspace_id": workspace_id,
            "known_lakehouses": [{"id": lakehouse_id}],
        }
        notebook.setdefault("metadata", {}).setdefault("dependencies", {})[
            "lakehouse"
        ] = lakehouse_metadata
        replacements = {
            "WORKSPACE_ID": workspace_id,
            "LAKEHOUSE_ID": lakehouse_id,
        }
        for cell in notebook["cells"]:
            if cell.get("cell_type") != "code":
                continue
            source = cell.get("source", [])
            source_text = "".join(source) if isinstance(source, list) else source
            for variable, value in replacements.items():
                source_text = re.sub(
                    rf'(?m)^({variable}\s*=\s*)["\'][^"\']*["\']\s*$',
                    lambda match, replacement=value: (
                        f'{match.group(1)}"{replacement}"'
                    ),
                    source_text,
                )
            cell["source"] = source_text.splitlines(keepends=True)
    content = (
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n"
    ).encode("utf-8")
    definition = {
        "format": "ipynb",
        "parts": [
            {
                "path": "artifact.content.ipynb",
                "payload": base64.b64encode(content).decode("ascii"),
                "payloadType": "InlineBase64",
            }
        ],
    }
    return path.stem, definition


def _list_notebooks(workspace_id: str, token: str) -> list[dict[str, Any]]:
    url = f"{FABRIC_API}/workspaces/{workspace_id}/notebooks"
    results: list[dict[str, Any]] = []
    while url:
        _, response, _ = _request("GET", url, token)
        if not isinstance(response, dict) or not isinstance(response.get("value"), list):
            raise RuntimeError("Fabric list-notebooks response has no value array.")
        results.extend(response["value"])
        continuation = response.get("continuationToken")
        url = (
            f"{FABRIC_API}/workspaces/{workspace_id}/notebooks?"
            f"{urllib.parse.urlencode({'continuationToken': continuation})}"
            if continuation
            else ""
        )
    return results


def _verify_notebook(
    workspace_id: str,
    notebook_id: str,
    expected_definition: dict[str, Any],
    token: str,
) -> None:
    url = (
        f"{FABRIC_API}/workspaces/{workspace_id}/notebooks/"
        f"{notebook_id}/getDefinition"
    )
    response = _request_and_wait("POST", url, token, {})
    parts = response.get("definition", {}).get("parts", []) if isinstance(response, dict) else []
    by_path = {
        part.get("path"): part
        for part in parts
        if isinstance(part, dict)
    }
    try:
        expected = json.loads(
            base64.b64decode(
                expected_definition["parts"][0]["payload"], validate=True
            )
        )
        content_path = next(
            path
            for path in ("artifact.content.ipynb", "notebook-content.py")
            if path in by_path
        )
        content_part = by_path[content_path]
        if content_part.get("payloadType") != "InlineBase64":
            raise ValueError(f"Unsupported payload type: {content_part.get('payloadType')}")
        content = base64.b64decode(content_part["payload"], validate=True).decode("utf-8")
        if content_path == "artifact.content.ipynb":
            if json.loads(content) != expected:
                raise RuntimeError(
                    f"Fabric Notebook definition did not match the local source: {notebook_id}"
                )
        else:
            markdown_cells = sum(
                cell.get("cell_type") == "markdown" for cell in expected["cells"]
            )
            code_cells = sum(
                cell.get("cell_type") == "code" for cell in expected["cells"]
            )
            if (
                content.count("# MARKDOWN ********************") != markdown_cells
                or content.count("# CELL ********************") != code_cells
            ):
                raise RuntimeError(
                    f"Fabric Notebook definition has a different cell structure: {notebook_id}"
                )
            missing_lines = []
            for cell in expected["cells"]:
                for line in "".join(cell.get("source", [])).splitlines():
                    if line and line not in content:
                        missing_lines.append(line)
            if missing_lines:
                raise RuntimeError(
                    f"Fabric Notebook source is missing lines from the local file: "
                    f"{notebook_id}"
                )
    except (KeyError, StopIteration, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Fabric returned an invalid Notebook definition.") from error


def publish(
    workspace_id: str,
    *,
    lakehouse_id: str | None = None,
    lakehouse_name: str | None = None,
    apply: bool = False,
    update_existing: bool = False,
    token: str | None = None,
) -> list[dict[str, Any]]:
    if update_existing and not apply:
        raise ValueError("--update-existing requires --apply.")
    root = Path(__file__).resolve().parent
    sources = [
        _load_notebook(
            root / relative_path,
            workspace_id=workspace_id if lakehouse_id else None,
            lakehouse_id=lakehouse_id,
            lakehouse_name=lakehouse_name,
        )
        for relative_path in NOTEBOOKS
    ]
    if not token:
        token = _get_token()
    items = _list_notebooks(workspace_id, token)
    existing_names = {
        item.get("displayName", "").casefold()
        for item in items
    }

    plan = []
    for display_name, definition in sources:
        exists = display_name.casefold() in existing_names
        action = "update" if exists and update_existing else "skip" if exists else "create"
        plan.append(
            {
                "display_name": display_name,
                "action": action,
                "definition": definition,
            }
        )
    if not apply:
        return [
            {"display_name": item["display_name"], "action": item["action"]}
            for item in plan
        ]

    outcomes = []
    for item in plan:
        name = item["display_name"]
        matches = [
            existing
            for existing in items
            if existing.get("displayName", "").casefold() == name.casefold()
        ]
        if len(matches) > 1:
            raise RuntimeError(f"Multiple Fabric Notebooks use the name {name!r}.")
        if matches and not update_existing:
            outcomes.append({"display_name": name, "action": "skipped-existing"})
            continue
        if matches:
            notebook_id = matches[0]["id"]
            _request_and_wait(
                "POST",
                f"{FABRIC_API}/workspaces/{workspace_id}/notebooks/"
                f"{notebook_id}/updateDefinition",
                token,
                {"definition": item["definition"]},
            )
            action = "updated"
        else:
            result = _request_and_wait(
                "POST",
                f"{FABRIC_API}/workspaces/{workspace_id}/notebooks",
                token,
                {
                    "displayName": name,
                    "description": "Track1 Notebook published from the repository.",
                    "definition": item["definition"],
                },
            )
            notebook_id = result.get("id") if isinstance(result, dict) else None
            if not notebook_id:
                created = [
                    existing
                    for existing in _list_notebooks(workspace_id, token)
                    if existing.get("displayName", "").casefold() == name.casefold()
                ]
                if len(created) != 1:
                    raise RuntimeError(
                        f"Notebook creation finished, but {name!r} could not be resolved."
                    )
                notebook_id = created[0]["id"]
            action = "created"

        _verify_notebook(workspace_id, notebook_id, item["definition"], token)
        outcomes.append(
            {"display_name": name, "action": action, "notebook_id": notebook_id}
        )
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Track1 ipynb 파일을 Fabric Workspace Notebook 항목으로 게시합니다."
    )
    parser.add_argument(
        "--workspace-id",
        default=os.environ.get("FABRIC_WORKSPACE_ID"),
        help="대상 Fabric Workspace ID (또는 FABRIC_WORKSPACE_ID 환경 변수)",
    )
    parser.add_argument("--lakehouse-id", help="Notebook 기본 Lakehouse ID")
    parser.add_argument("--lakehouse-name", help="Notebook 기본 Lakehouse 이름")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 API 쓰기 작업을 수행합니다. 생략 시 dry run입니다.",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="기존 Notebook의 definition 전체를 저장소 파일로 교체합니다.",
    )
    args = parser.parse_args()
    if not args.workspace_id:
        parser.error("--workspace-id 또는 FABRIC_WORKSPACE_ID가 필요합니다.")
    try:
        print(
            json.dumps(
                publish(
                    args.workspace_id,
                    lakehouse_id=args.lakehouse_id,
                    lakehouse_name=args.lakehouse_name,
                    apply=args.apply,
                    update_existing=args.update_existing,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
