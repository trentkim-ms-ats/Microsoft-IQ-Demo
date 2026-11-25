"""Publish the Track2 workshop package to explicitly configured live M365 targets."""

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email import policy
from email.parser import BytesParser
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from tools.live_demo import GRAPH_API, LiveServiceError, _read_json
from tools.m365_auth import publisher_profile, publisher_token

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "track2/data/workshop/generated"
STATE_PATH = ROOT / "track2/publish_state.local.json"
LOCK_PATH = ROOT / "track2/publish_state.local.lock"
EXPECTED_COUNTS = {"SharePoint": 15, "OneDrive": 12, "Outlook": 15, "Teams": 18}
REQUIRED_SCOPES = {
    "Files.ReadWrite.All",
    "Sites.ReadWrite.All",
    "Mail.Send",
    "ChannelMessage.Send",
    "User.Read",
}


def _request(url, *, method="GET", token=None, body=None, headers=None, raw=None):
    request_headers = {"Accept": "application/json"}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=raw, headers=request_headers, method=method)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read()
            break
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            if error.code == 429 and attempt < 3:
                retry_after = error.headers.get("Retry-After", "") if error.headers else ""
                delay = int(retry_after) if retry_after.isdecimal() else 10 * 2 ** attempt
                if delay <= 120:
                    time.sleep(max(1, delay))
                    continue
            raise LiveServiceError(
                f"Microsoft Graph request to {urllib.parse.urlsplit(url).netloc} "
                f"failed with HTTP {error.code}: {detail[:500]}"
            ) from error
        except urllib.error.URLError as error:
            raise LiveServiceError(
                f"Microsoft Graph request failed: {error.reason}"
            ) from error
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LiveServiceError("Microsoft Graph returned an invalid JSON response.") from error


def _catalog():
    catalog = _read_json("track2/data/workshop/generated/manifests/content_catalog.json")
    if not isinstance(catalog, list):
        raise LiveServiceError("Track2 content catalog must be a JSON list.")
    counts = {source: 0 for source in EXPECTED_COUNTS}
    ids = set()
    locations = set()
    for item in catalog:
        source = item.get("source")
        if source not in counts:
            raise LiveServiceError(f"Unknown Track2 source in catalog: {source}")
        key = item.get("id")
        if not isinstance(key, str) or not key or key in ids:
            raise LiveServiceError("Track2 catalog has a missing or duplicate sample ID.")
        ids.add(key)
        counts[source] += 1
        location = Path(item.get("location", ""))
        if location.is_absolute() or ".." in location.parts:
            raise LiveServiceError(f"Unsafe content location for {item.get('id')}.")
        if not (DATA_ROOT / location).is_file():
            raise LiveServiceError(f"Missing Track2 source file: {location}")
        # The Teams catalog entries share threads.json; every other entry must map to its own asset.
        if source != "Teams" and location in locations:
            raise LiveServiceError(f"Multiple Track2 entries reference {location}.")
        locations.add(location)
    if counts != EXPECTED_COUNTS:
        raise LiveServiceError(
            f"Track2 manifest counts differ from the expected live package: {counts}"
        )
    for source, entries in (("Outlook", _messages()), ("Teams", [t["id"] for t in _threads()])):
        expected = {item["id"] for item in catalog if item["source"] == source}
        if len(entries) != len(expected) or set(entries) != expected:
            raise LiveServiceError(f"Track2 {source} sources do not match the catalog IDs.")
    return catalog


def _messages():
    messages = _read_json("track2/data/workshop/generated/outlook/messages.json")
    by_id = {item["id"]: item for item in messages}
    if len(by_id) != len(messages):
        raise LiveServiceError("Track2 Outlook data contains duplicate message IDs.")
    return by_id


def _threads():
    threads = _read_json("track2/data/workshop/generated/teams/threads.json")
    return threads


def _validate_config(config, catalog):
    if not isinstance(config, dict):
        raise LiveServiceError("Publisher config must be a JSON object.")
    tenant_id = config.get("tenantId")
    sharepoint = config.get("sharepoint", {})
    onedrive = config.get("onedrive", {})
    teams = config.get("teams", {})
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise LiveServiceError("Publisher config must specify the expected tenantId.")
    if not isinstance(config.get("publisherUpn"), str) or not config["publisherUpn"].strip():
        raise LiveServiceError("Publisher config must specify the expected publisherUpn.")
    for name, target in (("sharepoint", sharepoint), ("onedrive", onedrive)):
        if (
            not isinstance(target, dict)
            or not isinstance(target.get("driveId"), str)
            or not target["driveId"].strip()
            or not isinstance(target.get("aclFolders"), dict)
        ):
            raise LiveServiceError(
                f"Publisher config requires {name}.driveId and per-ACL aclFolders."
            )
    required_acl = {
        item["acl"] for item in catalog if item["source"] in {"SharePoint", "OneDrive"}
    }
    for source, target in (("SharePoint", sharepoint), ("OneDrive", onedrive)):
        missing = required_acl - set(target["aclFolders"])
        if missing:
            raise LiveServiceError(
                f"Publisher config lacks {source} folders for ACL labels: "
                f"{', '.join(sorted(missing))}"
            )
        for folder in target["aclFolders"].values():
            if not isinstance(folder, str) or folder.startswith("/") or ".." in Path(folder).parts:
                raise LiveServiceError(f"Invalid configured {source} folder path.")
    if (
        not isinstance(teams, dict)
        or not isinstance(teams.get("teamId"), str)
        or not teams["teamId"].strip()
        or not isinstance(teams.get("channels"), dict)
    ):
        raise LiveServiceError("Publisher config requires a Teams teamId and channel map.")
    required_channels = {
        thread["channel"] for thread in _threads()
    }
    missing_channels = required_channels - set(teams["channels"])
    if missing_channels:
        raise LiveServiceError(
            "Publisher config lacks Teams channel IDs for: "
            + ", ".join(sorted(missing_channels))
        )
    for channel_id in teams["channels"].values():
        if not isinstance(channel_id, str) or not channel_id:
            raise LiveServiceError("Teams channel IDs must be non-empty strings.")


def _live_identity(config, token):
    profile = publisher_profile(config, token, REQUIRED_SCOPES)
    return profile.get("mail") or profile["userPrincipalName"]


def _load_state():
    if not STATE_PATH.exists():
        return {"items": {}}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("items"), dict):
        raise LiveServiceError(f"Invalid publisher state file: {STATE_PATH}")
    return state


def _save_state(state):
    temporary = STATE_PATH.with_name(STATE_PATH.name + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def _state_context(config):
    return {
        key: config[key] for key in ("tenantId", "publisherUpn", "sharepoint", "onedrive", "teams")
    }


def _validate_state_context(config, state, *, allow_legacy=False):
    if "context" not in state:
        if state["items"] and not allow_legacy:
            raise LiveServiceError(
                "Existing publication receipts have no tenant/target context. Preserve them "
                "and reconcile with tools.verify_m365 before any more writes."
            )
    elif state["context"] != _state_context(config):
        raise LiveServiceError("Publication state belongs to different tenant, publisher, or targets.")


def _record(state, key, result):
    state["items"][key] = {"completed": True, **result}
    _save_state(state)


def _publish_with_lock(config, catalog, token, publisher):
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
            _validate_state_context(config, state)
            state.setdefault("context", _state_context(config))
            return publish(config, catalog, token, publisher, state)
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file, fcntl.LOCK_UN)


def _encoded_path(path):
    return urllib.parse.quote(path.strip("/"), safe="/")


def _upload_document(item, config, token):
    source_key = item["source"].casefold()
    target = config[source_key]
    acl_folder = target["aclFolders"][item["acl"]].strip("/")
    filename = Path(item["location"]).name
    path = "/".join(part for part in (acl_folder, filename) if part)
    url = (
        f"{GRAPH_API}/drives/{urllib.parse.quote(target['driveId'], safe='')}"
        f"/root:/{_encoded_path(path)}:/createUploadSession"
    )
    session = _request(
        url,
        method="POST",
        token=token,
        body={"item": {"@microsoft.graph.conflictBehavior": "fail"}},
    )
    upload_url = session.get("uploadUrl")
    if not upload_url:
        raise LiveServiceError(f"Graph did not create an upload session for {item['id']}.")
    content = (DATA_ROOT / item["location"]).read_bytes()
    if len(content) >= 60 * 1024 * 1024:
        raise LiveServiceError(f"File {item['id']} exceeds the single-chunk upload limit.")
    final = _request(
        upload_url,
        method="PUT",
        headers={
            "Content-Length": str(len(content)),
            "Content-Range": f"bytes 0-{len(content) - 1}/{len(content)}",
        },
        raw=content,
    )
    if not final.get("id") or not final.get("webUrl"):
        raise LiveServiceError(f"Graph returned no final file receipt for {item['id']}; inspect the target before resuming.")
    return {
        "id": final["id"],
        "webUrl": final["webUrl"],
        "source": item["source"],
    }


def workshop_subject(source):
    return f"[IQ Workshop {source['id']} | {source['thread']}] {source['subject']}"


def _send_mail(item, messages, publisher, token):
    source = messages[item["id"]]
    path = DATA_ROOT / item["location"]
    parsed = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    if parsed.get("Subject") != source["subject"]:
        raise LiveServiceError(f"EML subject does not match the catalog for {item['id']}.")
    body = "\n".join(source["body"])
    body = (
        f"Original workshop role: {source['sender']}\n"
        f"Original date: {source['date']}\n\n"
        f"{body}\n\n"
        f"Published by: {publisher}"
    )
    subject = workshop_subject(source)
    _request(
        f"{GRAPH_API}/me/sendMail",
        method="POST",
        token=token,
        body={
            "message": {
                "subject": subject,
                "body": {"contentType": "text", "content": body},
                "toRecipients": [{"emailAddress": {"address": publisher}}],
                "internetMessageHeaders": [
                    {"name": "X-IQ-Workshop-Source", "value": item["id"]},
                ],
            },
            "saveToSentItems": True,
        },
    )
    return {
        "accepted": True,
        "sentTo": publisher,
        "source": "Outlook",
        "note": "Graph accepted the send request; verify the message in the mailbox.",
    }


def _post_thread(thread, config, token, state):
    team_id = urllib.parse.quote(config["teams"]["teamId"], safe="")
    channel_id = urllib.parse.quote(
        config["teams"]["channels"][thread["channel"]], safe=""
    )
    previous = state["items"].get(thread["id"], {})
    parent_id = previous.get("threadId")
    message_ids = list(previous.get("messageIds", []))
    for index in range(len(message_ids), len(thread["messages"])):
        role, timestamp, text = thread["messages"][index]
        body_text = f"[Original role: {role} | {timestamp}] {text}"
        if index == 0:
            body_text = f"{thread['title']}\n{body_text}"
            url = f"{GRAPH_API}/teams/{team_id}/channels/{channel_id}/messages"
        else:
            url = (
                f"{GRAPH_API}/teams/{team_id}/channels/{channel_id}"
                f"/messages/{urllib.parse.quote(parent_id, safe='')}/replies"
            )
        result = _request(
            url,
            method="POST",
            token=token,
            body={
                "body": {
                    "contentType": "html",
                    "content": html.escape(body_text).replace("\n", "<br>"),
                }
            },
        )
        if index == 0:
            parent_id = result.get("id")
            if not parent_id:
                raise LiveServiceError(f"Teams did not return a thread ID for {thread['id']}.")
        if not result.get("id"):
            raise LiveServiceError(
                f"Teams did not return a message ID for {thread['id']} message {index + 1}."
            )
        message_ids.append(result["id"])
        state["items"][thread["id"]] = {
            "completed": False,
            "source": "Teams",
            "threadId": parent_id,
            "messageIds": message_ids,
            "channel": thread["channel"],
        }
        _save_state(state)
    return {
        "completed": True,
        "source": "Teams",
        "threadId": parent_id,
        "messageIds": message_ids,
        "channel": thread["channel"],
    }


def build_plan(catalog):
    return {
        "SharePoint files": sum(item["source"] == "SharePoint" for item in catalog),
        "OneDrive files": sum(item["source"] == "OneDrive" for item in catalog),
        "Outlook messages": sum(item["source"] == "Outlook" for item in catalog),
        "Teams threads": sum(item["source"] == "Teams" for item in catalog),
        "Teams messages": sum(
            len(thread["messages"]) for thread in _threads()
        ),
    }


def publish(config, catalog, token, publisher, state):
    messages = _messages()
    threads = {thread["id"]: thread for thread in _threads()}
    outcomes = {"published": [], "skipped": []}
    for item in catalog:
        key = item["id"]
        if state["items"].get(key, {}).get("completed"):
            outcomes["skipped"].append(key)
            continue
        if item["source"] in {"SharePoint", "OneDrive"}:
            result = _upload_document(item, config, token)
        elif item["source"] == "Outlook":
            result = _send_mail(item, messages, publisher, token)
        else:
            result = _post_thread(threads[key], config, token, state)
        _record(state, key, result)
        outcomes["published"].append(key)
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Local tenant target JSON.")
    parser.add_argument("--apply", action="store_true", help="Perform live M365 writes.")
    parser.add_argument("--interactive", action="store_true", help="Sign in through IQ Workshop Provisioner.")
    parser.add_argument(
        "--confirm-tenant",
        help="Must exactly match the configured tenantId to enable live writes.",
    )
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        catalog = _catalog()
        _validate_config(config, catalog)
        plan = build_plan(catalog)
        if not args.apply:
            print(json.dumps({"mode": "write-plan", "writePlan": plan}, indent=2))
            print("No Microsoft 365 data was written. Review the target ACLs before --apply.")
            return 0
        if args.confirm_tenant != config["tenantId"]:
            raise LiveServiceError(
                "For live writes, pass --confirm-tenant with the exact configured tenantId."
            )
        token = publisher_token(config, REQUIRED_SCOPES, interactive=args.interactive)
        publisher = _live_identity(config, token)
        outcomes = _publish_with_lock(config, catalog, token, publisher)
        print(json.dumps({
            "executionMode": "live",
            "publisher": publisher,
            "plan": plan,
            "outcomes": outcomes,
            "stateFile": str(STATE_PATH.relative_to(ROOT)),
        }, ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, KeyError, LiveServiceError) as error:
        print(f"M365 publish failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
