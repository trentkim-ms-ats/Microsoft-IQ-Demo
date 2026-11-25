"""Provision isolated Microsoft 365 resources for the live Track2 workshop."""

import argparse
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from tools.live_demo import GRAPH_API, LiveServiceError, _graph_token_claims
from tools.m365_auth import publisher_token

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "track2/provision_state.local.json"
LOCK_PATH = ROOT / "track2/provision_state.local.lock"
PUBLISH_CONFIG_PATH = ROOT / "track2/publish-config.provisioned.local.json"
ACL_FOLDERS = {
    "Workshop-Participants": "IQ-Workshop/Participants",
    "Workshop-Leaders": "IQ-Workshop/Leaders",
    "Workshop-Data-Stewards": "IQ-Workshop/Data-Stewards",
}
CHANNELS = (
    "cs-tier2",
    "logistics",
    "inventory",
    "payments",
    "campaign-ops",
    "data-quality",
    "leadership-briefing",
)
RESTRICTED_CHANNELS = frozenset(
    {"cs-tier2", "logistics", "inventory", "payments", "campaign-ops"}
)
REQUIRED_SCOPES = {
    "User.Read",
    "User.ReadBasic.All",
    "Team.Create",
    "Team.ReadBasic.All",
    "TeamMember.Read.All",
    "Channel.Create",
    "Channel.ReadBasic.All",
    "ChannelMember.ReadWrite.All",
    "Files.ReadWrite.All",
    "Sites.ReadWrite.All",
}
MAX_OPERATION_POLLS = 20
OPERATION_POLL_SECONDS = 30


class GraphRequestError(LiveServiceError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _request(url, *, method="GET", token=None, body=None):
    headers = {"Accept": "application/json"}
    if method == "GET":
        headers["Prefer"] = "include-unknown-enum-members"
    raw = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=raw, headers=headers, method=method)
    attempts = 3 if method == "GET" else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read()
                result = json.loads(payload) if payload else {}
                return result, response.headers, response.status
        except http.client.RemoteDisconnected as error:
            if attempt == attempts - 1:
                raise LiveServiceError(
                    f"Microsoft Graph disconnected during {method}; inspect saved state before retrying."
                ) from error
            time.sleep(2 ** attempt)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise GraphRequestError(
                error.code,
                f"Microsoft Graph request to {urlsplit(url).netloc} failed with "
                f"HTTP {error.code}: {detail[:500]}",
            ) from error
        except urllib.error.URLError as error:
            raise LiveServiceError(
                f"Microsoft Graph request failed: {error.reason}"
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LiveServiceError("Microsoft Graph returned invalid JSON.") from error


def _validate_config(config, publisher_only=False):
    if not isinstance(config, dict):
        raise LiveServiceError("Provision config must be a JSON object.")
    keys = ["tenantId", "publisherUpn", "teamDisplayName"]
    if not publisher_only:
        keys.append("restrictedUpn")
    for key in keys:
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise LiveServiceError(f"Provision config requires a non-empty {key}.")
    if not publisher_only and config["publisherUpn"].casefold() == config["restrictedUpn"].casefold():
        raise LiveServiceError("Publisher and restricted test accounts must be different.")
    return config


def build_plan(config, publisher_only=False):
    restricted_user = None if publisher_only else config["restrictedUpn"]
    shared_folders = [] if publisher_only else ["IQ-Workshop/Participants"]
    return {
        "tenantId": config["tenantId"],
        "publisher": config["publisherUpn"],
        "restrictedUser": restricted_user,
        "team": config["teamDisplayName"],
        "sharePoint": {
            "library": "Team's default Documents library",
            "folders": list(ACL_FOLDERS.values()),
            "restrictedUserReadAccess": shared_folders,
        },
        "oneDrive": {
            "owner": config["publisherUpn"],
            "folders": list(ACL_FOLDERS.values()),
            "restrictedUserReadAccess": shared_folders,
        },
        "teams": {
            "privateTeamMembers": [config["publisherUpn"]],
            "sharedChannels": list(CHANNELS),
            "restrictedUserChannels": [] if publisher_only else sorted(RESTRICTED_CHANNELS),
        },
        "restrictedAccessVerification": "not performed",
        "userAccountsAndLicensesCreated": False,
    }


def _save_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _load_state():
    if not STATE_PATH.exists():
        return {"team": {}, "channels": {}, "folders": {}, "shares": {}}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LiveServiceError(f"Invalid provisioning state file: {STATE_PATH}") from error
    if not isinstance(state, dict):
        raise LiveServiceError(f"Invalid provisioning state file: {STATE_PATH}")
    for key in ("team", "channels", "folders", "shares"):
        if not isinstance(state.get(key), dict):
            raise LiveServiceError(f"Invalid {key} state in {STATE_PATH}")
    return state


def _graph_location(location):
    if not isinstance(location, str) or not location:
        raise LiveServiceError("Microsoft Graph omitted an async operation location.")
    parsed = urlsplit(location)
    if parsed.scheme:
        if parsed.scheme != "https" or parsed.netloc.casefold() != "graph.microsoft.com":
            raise LiveServiceError("Graph returned an unexpected async operation host.")
        return location
    if not location.startswith("/"):
        raise LiveServiceError("Graph returned an invalid async operation location.")
    if location.casefold().startswith("/v1.0/"):
        return "https://graph.microsoft.com" + location
    return GRAPH_API + location


def _resource_id(location, resource_name):
    if not isinstance(location, str):
        return None
    escaped = urllib.parse.quote(resource_name, safe="")
    patterns = (
        rf"/{escaped}\('([^']+)'\)",
        rf"/{escaped}/([^/?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, location, flags=re.IGNORECASE)
        if match:
            return urllib.parse.unquote(match.group(1))
    return None


def _wait_for_operation(location, token, resource_name):
    url = _graph_location(location)
    for _ in range(MAX_OPERATION_POLLS):
        time.sleep(OPERATION_POLL_SECONDS)
        operation, _, _ = _request(url, token=token)
        status = str(operation.get("status", "")).casefold()
        if status == "succeeded":
            return operation
        if status in {"failed", "cancelled"}:
            detail = operation.get("error", {}).get("message", "no error detail")
            raise LiveServiceError(
                f"Graph {resource_name} operation {status}: {detail}"
            )
    raise LiveServiceError(
        f"Graph {resource_name} operation did not finish after "
        f"{MAX_OPERATION_POLLS * OPERATION_POLL_SECONDS} seconds. "
        "Rerun the same command to resume."
    )


def _collection(url, token):
    items = []
    while url:
        page, _, _ = _request(url, token=token)
        values = page.get("value")
        if not isinstance(values, list):
            raise LiveServiceError("Microsoft Graph returned an invalid collection.")
        items.extend(values)
        next_link = page.get("@odata.nextLink")
        if next_link:
            parsed = urlsplit(next_link)
            if parsed.scheme != "https" or parsed.netloc.casefold() != "graph.microsoft.com":
                raise LiveServiceError("Graph returned an unexpected pagination host.")
        url = next_link
    return items


def _get_user(upn, token):
    encoded = urllib.parse.quote(upn, safe="")
    url = (
        f"{GRAPH_API}/users/{encoded}"
        "?$select=id,userPrincipalName,mail,accountEnabled"
    )
    user, _, _ = _request(url, token=token)
    if not user.get("id") or not user.get("userPrincipalName"):
        raise LiveServiceError(f"Could not resolve account {upn} in the demo tenant.")
    if user.get("accountEnabled") is False:
        raise LiveServiceError(f"Demo account {upn} is disabled.")
    return user


def _ensure_team(config, publisher, state, token):
    team_state = state["team"]
    if team_state.get("id"):
        return team_state["id"]
    if not team_state.get("operationUrl"):
        payload = {
            "displayName": config["teamDisplayName"],
            "description": config.get(
                "teamDescription", "Private team for the live Microsoft IQ workshop."
            ),
            "visibility": "private",
            "firstChannelName": "General",
            "template@odata.bind": f"{GRAPH_API}/teamsTemplates('standard')",
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": (
                        f"{GRAPH_API}/users('{publisher['id']}')"
                    ),
                }
            ],
        }
        _, headers, status = _request(
            f"{GRAPH_API}/teams", method="POST", token=token, body=payload
        )
        if status != 202:
            raise LiveServiceError(
                f"Graph returned HTTP {status} instead of 202 for Team creation."
            )
        operation_url = headers.get("Location")
        if not operation_url:
            raise LiveServiceError("Graph did not return a Team creation operation URL.")
        team_state["operationUrl"] = operation_url
        _save_json(STATE_PATH, state)
    operation = _wait_for_operation(
        team_state["operationUrl"], token, "teams"
    )
    team_id = operation.get("targetResourceId") or _resource_id(
        operation.get("targetResourceLocation"), "teams"
    )
    if not team_id:
        raise LiveServiceError("Graph completed the teams operation without a resource ID.")
    team_state["id"] = team_id
    team_state.pop("operationUrl", None)
    _save_json(STATE_PATH, state)
    return team_id


def _member_id(member):
    return member.get("userId") or member.get("id")


def _verify_team_members(team_id, publisher_id, restricted_id, token):
    members = _collection(f"{GRAPH_API}/teams/{team_id}/members", token)
    member_ids = {_member_id(member) for member in members if _member_id(member)}
    if restricted_id and restricted_id in member_ids:
        raise LiveServiceError(
            "Restricted account is a member of the private Team. Remove it from the "
            "Team before provisioning; channel-scoped access would not be isolated."
        )
    unexpected = member_ids - {publisher_id}
    if unexpected:
        raise LiveServiceError(
            "The private Team has members other than the publisher. Remove them "
            "before provisioning to preserve the demo access boundary."
        )
    if publisher_id not in member_ids:
        raise LiveServiceError(
            "Publisher is not a member of the private Team; refusing to continue."
        )


def _find_shared_channel(team_id, name, token):
    channels = _collection(
        f"{GRAPH_API}/teams/{team_id}/channels?$select=id,displayName,membershipType", token
    )
    matching = [channel for channel in channels if channel.get("displayName") == name]
    if len(matching) > 1:
        raise LiveServiceError(f"Team contains duplicate channels named {name}.")
    if not matching:
        return None
    channel = matching[0]
    if channel.get("membershipType") != "shared":
        raise LiveServiceError(f"Existing channel {name} is not a shared channel.")
    if not channel.get("id") or channel["id"] == team_id:
        raise LiveServiceError(f"Microsoft Graph did not identify shared channel {name}.")
    return channel["id"]


def _ensure_channel(team_id, name, publisher, state, token):
    saved = state["channels"].get(name, {})
    if saved.get("id") and saved["id"] != team_id:
        return saved["id"]
    operation_url = saved.get("operationUrl")
    channel_id = None
    if not operation_url:
        channel_id = _find_shared_channel(team_id, name, token)
        if not channel_id and saved.get("id") == team_id:
            raise LiveServiceError(f"Cannot yet resolve saved shared channel {name}. Rerun to resume.")
        if not channel_id:
            payload = {
                "displayName": name,
                "description": "Live Microsoft IQ workshop channel.",
                "membershipType": "shared",
                "members": [
                    {
                        "@odata.type": "#microsoft.graph.aadUserConversationMember",
                        "roles": ["owner"],
                        "user@odata.bind": f"{GRAPH_API}/users('{publisher['id']}')",
                    }
                ],
            }
            channel, headers, status = _request(
                f"{GRAPH_API}/teams/{team_id}/channels",
                method="POST",
                token=token,
                body=payload,
            )
            if status == 201:
                channel_id = channel.get("id") or _resource_id(
                    headers.get("Content-Location"), "channels"
                )
                if not channel_id:
                    raise LiveServiceError(
                        f"Graph did not identify the new {name} channel."
                    )
            elif status == 202:
                operation_url = headers.get("Location")
                if not operation_url:
                    raise LiveServiceError(
                        f"Graph did not return a {name} channel operation URL."
                    )
                saved["operationUrl"] = operation_url
                state["channels"][name] = saved
                _save_json(STATE_PATH, state)
            else:
                raise LiveServiceError(
                    f"Graph returned HTTP {status} instead of 201/202 for {name}."
                )
    if operation_url:
        _wait_for_operation(operation_url, token, "channels")
        # Shared channel operations can report the parent Team ID as their target.
        channel_id = _find_shared_channel(team_id, name, token)
        if not channel_id:
            raise LiveServiceError(f"Shared channel {name} is not listed yet. Rerun to resume.")
    state["channels"][name] = {"id": channel_id}
    _save_json(STATE_PATH, state)
    return channel_id


def _verify_channel_members(team_id, channel_id, name, publisher_id, restricted_id, token):
    members = _collection(
        f"{GRAPH_API}/teams/{team_id}/channels/{urllib.parse.quote(channel_id, safe='')}"
        "/members",
        token,
    )
    by_id = {_member_id(member): member for member in members if _member_id(member)}
    allowed = {publisher_id}
    if restricted_id and name in RESTRICTED_CHANNELS:
        allowed.add(restricted_id)
    extra = set(by_id) - allowed
    if extra:
        raise LiveServiceError(
            f"Channel {name} has unexpected members; remove them before provisioning."
        )
    publisher_member = by_id.get(publisher_id)
    if not publisher_member or "owner" not in publisher_member.get("roles", []):
        raise LiveServiceError(
            f"Publisher must be an owner of shared channel {name}."
        )
    restricted_member = by_id.get(restricted_id)
    if restricted_member and "owner" in restricted_member.get("roles", []):
        raise LiveServiceError(
            f"Restricted account must not be an owner of shared channel {name}."
        )
    if restricted_id and name in RESTRICTED_CHANNELS and restricted_id not in by_id:
        _request(
            f"{GRAPH_API}/teams/{team_id}/channels/"
            f"{urllib.parse.quote(channel_id, safe='')}/members",
            method="POST",
            token=token,
            body={
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": [],
                "user@odata.bind": f"{GRAPH_API}/users('{restricted_id}')",
            },
        )
        members = _collection(
            f"{GRAPH_API}/teams/{team_id}/channels/"
            f"{urllib.parse.quote(channel_id, safe='')}/members",
            token,
        )
        by_id = {
            _member_id(member): member
            for member in members
            if _member_id(member)
        }
        restricted_member = by_id.get(restricted_id)
        if not restricted_member or "owner" in restricted_member.get("roles", []):
            raise LiveServiceError(
                f"Could not verify restricted user's member role in channel {name}."
            )


def _drive(token, path):
    value, _, _ = _request(f"{GRAPH_API}/{path}", token=token)
    drive_id = value.get("id")
    if not drive_id:
        raise LiveServiceError(f"Graph returned no drive ID for {path}.")
    return drive_id


def _sharepoint_drive(team_id, token):
    try:
        return _drive(token, f"groups/{team_id}/drive")
    except GraphRequestError as error:
        if error.status != 404:
            raise

    channels = _collection(
        f"{GRAPH_API}/teams/{team_id}/channels?$select=id,displayName,membershipType", token
    )
    general = [channel for channel in channels if channel.get("displayName") == "General"]
    if len(general) != 1 or not general[0].get("id"):
        raise LiveServiceError(
            "Could not find the Team's General channel to trigger SharePoint setup."
        )
    files_folder_url = (
        f"{GRAPH_API}/teams/{team_id}/channels/"
        f"{urllib.parse.quote(general[0]['id'], safe='')}/filesFolder"
    )
    try:
        _request(files_folder_url, token=token)
    except GraphRequestError as error:
        if error.status != 404:
            raise

    for _ in range(20):
        time.sleep(15)
        try:
            return _drive(token, f"groups/{team_id}/drive")
        except GraphRequestError as error:
            if error.status != 404:
                raise
    raise LiveServiceError(
        "The Team SharePoint Documents library is not ready after triggering "
        "provisioning. Wait a few minutes and rerun; saved state will resume."
    )


def _get_item_by_path(drive_id, path, token):
    encoded = urllib.parse.quote(path.strip("/"), safe="/")
    url = (
        f"{GRAPH_API}/drives/{urllib.parse.quote(drive_id, safe='')}"
        f"/root:/{encoded}"
    )
    return _request(url, token=token)[0]


def _ensure_folder(drive_id, path, state, token):
    parts = path.strip("/").split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise LiveServiceError(f"Invalid folder path: {path}")
    for end in range(1, len(parts) + 1):
        partial_path = "/".join(parts[:end])
        try:
            item = _get_item_by_path(drive_id, partial_path, token)
        except GraphRequestError as error:
            if error.status != 404:
                raise
            parent_id = "root"
            if end > 1:
                parent = _get_item_by_path(
                    drive_id, "/".join(parts[: end - 1]), token
                )
                parent_id = parent["id"]
            parent_prefix = (
                f"/drives/{urllib.parse.quote(drive_id, safe='')}/root"
                if parent_id == "root"
                else (
                    f"/drives/{urllib.parse.quote(drive_id, safe='')}/items/"
                    f"{urllib.parse.quote(parent_id, safe='')}"
                )
            )
            parent_url = f"{GRAPH_API}{parent_prefix}/children"
            try:
                item, _, _ = _request(
                    parent_url,
                    method="POST",
                    token=token,
                    body={
                        "name": parts[end - 1],
                        "folder": {},
                        "@microsoft.graph.conflictBehavior": "fail",
                    },
                )
            except GraphRequestError as create_error:
                if create_error.status != 409:
                    raise
                item = _get_item_by_path(drive_id, partial_path, token)
        if not isinstance(item.get("folder"), dict):
            raise LiveServiceError(f"Configured path is not a folder: {partial_path}")
        state["folders"][f"{drive_id}:{partial_path}"] = item["id"]
        _save_json(STATE_PATH, state)
    return state["folders"][f"{drive_id}:{path}"]


def _has_user_permission(permission, user_id, upn):
    recipients = []
    for key in ("grantedToV2", "grantedToIdentitiesV2"):
        value = permission.get(key)
        if isinstance(value, dict):
            recipients.append(value)
        elif isinstance(value, list):
            recipients.extend(value)
    for recipient in recipients:
        user = recipient.get("user", {})
        if user.get("id") == user_id:
            return True
        if (user.get("email") or "").casefold() == upn.casefold():
            return True
    return False


def _user_permissions(permissions, user_id, upn):
    return [
        permission
        for permission in permissions
        if _has_user_permission(permission, user_id, upn)
    ]


def _ensure_read_share(drive_id, item_id, user, state, token, state_key):
    url = (
        f"{GRAPH_API}/drives/{urllib.parse.quote(drive_id, safe='')}"
        f"/items/{urllib.parse.quote(item_id, safe='')}/permissions"
    )
    permissions = _collection(url, token)
    matching = _user_permissions(permissions, user["id"], user["userPrincipalName"])
    if matching:
        for permission in matching:
            if permission.get("inheritedFrom"):
                raise LiveServiceError(
                    "Restricted user's Participants access is inherited from a parent. "
                    "Remove the broader parent grant and rerun provisioning."
                )
            if set(permission.get("roles", [])) != {"read"}:
                raise LiveServiceError(
                    "Restricted user's Participants folder grant is not read-only."
                )
    else:
        _request(
            url.rsplit("/permissions", 1)[0] + "/invite",
            method="POST",
            token=token,
            body={
                "recipients": [{"email": user.get("mail") or user["userPrincipalName"]}],
                "requireSignIn": True,
                "sendInvitation": False,
                "roles": ["read"],
            },
        )
        permissions = _collection(url, token)
        matching = _user_permissions(
            permissions, user["id"], user["userPrincipalName"]
        )
        if not matching or any(
            permission.get("inheritedFrom")
            or set(permission.get("roles", [])) != {"read"}
            for permission in matching
        ):
            raise LiveServiceError(
                "Could not verify a direct read-only Participants folder grant."
            )
    state["shares"][state_key] = True
    _save_json(STATE_PATH, state)


def _assert_no_user_permission(drive_id, item_id, user, token, folder_label):
    url = (
        f"{GRAPH_API}/drives/{urllib.parse.quote(drive_id, safe='')}"
        f"/items/{urllib.parse.quote(item_id, safe='')}/permissions"
    )
    permissions = _collection(url, token)
    if _user_permissions(permissions, user["id"], user["userPrincipalName"]):
        raise LiveServiceError(
            f"Restricted user already has a direct or inherited grant on "
            f"{folder_label}. Remove it before provisioning."
        )


def _build_publish_config(config, sharepoint_drive, onedrive_drive, team_id, channels, publisher_only=False):
    sharepoint_folders = dict(ACL_FOLDERS)
    onedrive_folders = dict(ACL_FOLDERS)
    result = {
        "tenantId": config["tenantId"],
        "publisherUpn": config["publisherUpn"],
        "sharepoint": {
            "driveId": sharepoint_drive,
            "aclFolders": sharepoint_folders,
        },
        "onedrive": {
            "driveId": onedrive_drive,
            "aclFolders": onedrive_folders,
        },
        "teams": {"teamId": team_id, "channels": channels},
    }
    if not publisher_only:
        result["restrictedUpn"] = config["restrictedUpn"]
    return result


def provision(config, token, state, publisher_only=False):
    claims, scopes = _graph_token_claims(token)
    if claims.get("tid", "").casefold() != config["tenantId"].casefold():
        raise LiveServiceError("Graph token tenant does not match provision config.")
    required_scopes = REQUIRED_SCOPES - ({"User.ReadBasic.All"} if publisher_only else set())
    missing = required_scopes - scopes
    if missing:
        raise LiveServiceError(
            "Delegated Graph token lacks provisioning scopes: "
            + ", ".join(sorted(missing))
        )
    context = {
        "tenantId": config["tenantId"],
        "publisherUpn": config["publisherUpn"],
        "restrictedUpn": None if publisher_only else config["restrictedUpn"],
        "teamDisplayName": config["teamDisplayName"],
    }
    if state.get("context") is not None and state["context"] != context:
        raise LiveServiceError(
            "Provisioning state belongs to a different tenant or account setup. "
            "Use its original config or choose a separate state location."
        )
    if state.get("context") is None:
        if any(state[key] for key in ("team", "channels", "folders", "shares")):
            raise LiveServiceError(
                "Provisioning state has resources but no identity context; refusing "
                "to reuse it."
            )
        state["context"] = context
        _save_json(STATE_PATH, state)
    profile, _, _ = _request(
        f"{GRAPH_API}/me?$select=id,userPrincipalName", token=token
    )
    if not profile.get("id") or (
        (profile.get("userPrincipalName") or "").casefold()
        != config["publisherUpn"].casefold()
    ):
        raise LiveServiceError(
            "The delegated Graph token must belong to publisherUpn."
        )
    publisher = profile
    restricted = None if publisher_only else _get_user(config["restrictedUpn"], token)
    if restricted and publisher["id"] == restricted["id"]:
        raise LiveServiceError("Publisher and restricted test accounts must be different.")
    restricted_id = restricted["id"] if restricted else None

    team_id = _ensure_team(config, publisher, state, token)
    _verify_team_members(team_id, publisher["id"], restricted_id, token)
    channels = {}
    for name in CHANNELS:
        channel_id = _ensure_channel(team_id, name, publisher, state, token)
        _verify_channel_members(
            team_id, channel_id, name, publisher["id"], restricted_id, token
        )
        channels[name] = channel_id

    sharepoint_drive = _sharepoint_drive(team_id, token)
    onedrive_drive = _drive(token, "me/drive")

    for acl, path in ACL_FOLDERS.items():
        sharepoint_item = _ensure_folder(sharepoint_drive, path, state, token)
        onedrive_item = _ensure_folder(onedrive_drive, path, state, token)
        if not restricted:
            continue
        if acl == "Workshop-Participants":
            _ensure_read_share(
                sharepoint_drive,
                sharepoint_item,
                restricted,
                state,
                token,
                f"sharepoint:{sharepoint_item}",
            )
            _ensure_read_share(
                onedrive_drive,
                onedrive_item,
                restricted,
                state,
                token,
                f"onedrive:{onedrive_item}",
            )
        else:
            _assert_no_user_permission(
                sharepoint_drive,
                sharepoint_item,
                restricted,
                token,
                f"SharePoint {acl}",
            )
            _assert_no_user_permission(
                onedrive_drive,
                onedrive_item,
                restricted,
                token,
                f"OneDrive {acl}",
            )

    return _build_publish_config(
        config, sharepoint_drive, onedrive_drive, team_id, channels, publisher_only
    )


def _provision_with_lock(config, token, publisher_only=False):
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
            state = _load_state()
            publish_config = provision(config, token, state, publisher_only)
            return publish_config
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "track2/provision-config.local.json",
        help="Local tenant/account config (default: track2/provision-config.local.json).",
    )
    parser.add_argument("--apply", action="store_true", help="Create live M365 resources.")
    parser.add_argument("--interactive", action="store_true", help="Sign in through IQ Workshop Provisioner (publisher-only).")
    parser.add_argument(
        "--publisher-only",
        action="store_true",
        help="Skip restricted-account sharing and access verification.",
    )
    parser.add_argument(
        "--confirm-tenant",
        help="Must exactly match tenantId before any live Graph writes.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PUBLISH_CONFIG_PATH,
        help="Path for the generated publisher config.",
    )
    parser.add_argument(
        "--overwrite-output",
        action="store_true",
        help="Replace the generated publisher config if it already exists.",
    )
    args = parser.parse_args()
    try:
        config = _validate_config(
            json.loads(args.config.read_text(encoding="utf-8")), args.publisher_only
        )
        plan = build_plan(config, args.publisher_only)
        if not args.apply:
            print(json.dumps({"mode": "provision-plan", "plan": plan}, indent=2))
            print("No Microsoft 365 requests were made. Review before --apply.")
            return 0
        if args.confirm_tenant != config["tenantId"]:
            raise LiveServiceError(
                "For live provisioning, pass --confirm-tenant with the exact tenantId."
            )
        if args.output.exists() and not args.overwrite_output:
            raise LiveServiceError(
                f"Output already exists: {args.output}. Choose another --output or "
                "explicitly pass --overwrite-output."
            )
        if args.interactive and not args.publisher_only:
            raise LiveServiceError("The registered Track2 app supports --interactive with --publisher-only.")
        scopes = REQUIRED_SCOPES - ({"User.ReadBasic.All"} if args.publisher_only else set())
        token = publisher_token(config, scopes, interactive=args.interactive)
        publish_config = _provision_with_lock(config, token, args.publisher_only)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        _save_json(args.output, publish_config)
        print(json.dumps({
            "mode": "live",
            "plan": plan,
            "publishConfig": str(args.output),
            "stateFile": str(STATE_PATH.relative_to(ROOT)),
            "verification": (
                "Restricted-user access was not tested; effective SharePoint "
                "permissions must be reviewed before publishing."
            ),
        }, ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, LiveServiceError) as error:
        print(f"M365 provisioning failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
