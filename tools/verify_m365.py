"""Verify Track2 publication receipts and Q1-Q5 against live Microsoft 365 without writing."""

import argparse
import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote, urlencode

from tools import provision_m365 as provision, publish_m365 as publisher
from tools.live_demo import GRAPH_API, LiveServiceError, _graph_search, _read_json
from tools.m365_auth import publisher_profile, publisher_token

READ_SCOPES = {
    "User.Read", "Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Read.All",
    "Sites.Read.All", "Files.Read.All", "Mail.Read",
}


def _get(path, fields, token):
    resource, _, _ = provision._request(f"{GRAPH_API}/{path}?$select={fields}", token=token)
    return resource


def _drive_target(target, path):
    return f"drives/{quote(target['driveId'], safe='')}/root:/{publisher._encoded_path(path)}"


def _read_documents(config, items, receipts, token, failures):
    roots, ids = {}, defaultdict(set)
    for source in ("SharePoint", "OneDrive"):
        target = config[source.casefold()]
        paths = {Path(folder).parent.as_posix() for folder in target["aclFolders"].values()}
        for path in sorted(paths | set(target["aclFolders"].values())):
            try:
                folder = _get(_drive_target(target, path), "id,folder,webUrl", token)
                if not isinstance(folder.get("folder"), dict) or not folder.get("webUrl"):
                    raise LiveServiceError("Configured path did not resolve to a folder with a URL.")
                if path in paths:
                    roots.setdefault(source, []).append(folder["webUrl"])
            except LiveServiceError as error:
                failures[f"{source}/{path}"] = str(error)

        for item in (entry for entry in items if entry["source"] == source):
            key = item["id"]
            filename = Path(item["location"]).name
            folder = target["aclFolders"][item["acl"]]
            try:
                remote = _get(_drive_target(target, f"{folder}/{filename}"), "id,name,file,webUrl", token)
                receipt_id = receipts.get(key, {}).get("id")
                if (
                    not receipt_id or remote.get("id") != receipt_id
                    or remote.get("name") != filename
                    or not isinstance(remote.get("file"), dict) or not remote.get("webUrl")
                ):
                    raise LiveServiceError("The file at the configured path did not match its receipt.")
                ids[source].add(receipt_id)
            except LiveServiceError as error:
                failures[key] = str(error)
    return roots, ids


def _read_outlook(items, receipts, token, failures):
    query = urlencode({
        "$select": "id,subject,webLink",
        "$filter": "startswith(subject,'[IQ Workshop ')",
        "$top": 50,
    })
    try:
        inbox = provision._collection(f"{GRAPH_API}/me/mailFolders/inbox/messages?{query}", token)
    except LiveServiceError as error:
        failures["Outlook inbox"] = str(error)
        return set()
    inbox_count = defaultdict(int)
    for mail in inbox:
        if mail.get("id") and mail.get("webLink"):
            inbox_count[mail.get("subject")] += 1
    verified = set()
    messages = publisher._messages()
    for item in (entry for entry in items if entry["source"] == "Outlook"):
        key = item["id"]
        subject = publisher.workshop_subject(messages[key])
        if receipts.get(key, {}).get("accepted") and inbox_count[subject] == 1:
            verified.add(subject)
        else:
            failures[key] = f"Expected one matching message in the publisher inbox; found {inbox_count[subject]}."
    return verified


def _message_text(value):
    content = value.get("content") or ""
    if value.get("contentType", "").casefold() == "html":
        content = html.unescape(re.sub(r"<[^>]*>", " ", content))
    return " ".join(content.split())


def _read_teams(config, receipts, token, failures):
    teams = config["teams"]
    team_id = quote(teams["teamId"], safe="")
    base = f"teams/{team_id}"
    try:
        team = _get(base, "id,visibility", token)
        if team.get("id") != teams["teamId"] or team.get("visibility", "").casefold() != "private":
            raise LiveServiceError("The configured Team is not private or does not match.")
        channels = provision._collection(
            f"{GRAPH_API}/{base}/channels?$select=id,displayName,membershipType", token,
        )
    except LiveServiceError as error:
        failures["Teams target"] = str(error)
        return set(), {}
    shared = {
        channel["displayName"]: channel["id"]
        for channel in channels if channel.get("membershipType") == "shared"
    }
    verified_channels = {name for name, channel_id in teams["channels"].items() if shared.get(name) == channel_id}
    for name in teams["channels"].keys() - verified_channels:
        failures[f"Teams/{name}"] = "The configured channel was not found as a shared channel."

    verified_threads = {}
    for thread in publisher._threads():
        key = thread["id"]
        receipt = receipts.get(key, {})
        channel = thread["channel"]
        thread_id = receipt.get("threadId")
        ids = receipt.get("messageIds", [])
        if (
            channel not in verified_channels or receipt.get("channel") != channel or not thread_id
            or len(ids) != len(thread["messages"]) or ids[0] != thread_id or len(set(ids)) != len(ids)
        ):
            failures[key] = "Missing or inconsistent thread receipt for the configured channel."
            continue
        path = (
            f"{base}/channels/{quote(teams['channels'][channel], safe='')}"
            f"/messages/{quote(thread_id, safe='')}"
        )
        try:
            parent, _, _ = provision._request(f"{GRAPH_API}/{path}", token=token)
            replies = provision._collection(f"{GRAPH_API}/{path}/replies", token)
            remote = {msg.get("id"): msg for msg in [parent, *replies]}
            texts = []
            for msg_id, (role, timestamp, text) in zip(ids, thread["messages"]):
                msg = remote.get(msg_id, {})
                body = _message_text(msg.get("body") or {})
                expected = f"[Original role: {role} | {timestamp}] {text}"
                if msg_id == thread_id:
                    expected = f"{thread['title']} {expected}"
                if (
                    msg.get("deletedDateTime") or not msg.get("webUrl")
                    or " ".join(expected.split()) not in body
                ):
                    raise LiveServiceError("A recorded Teams message was missing, deleted or did not match the sample.")
                texts.append(body)
            verified_threads[key] = texts
        except LiveServiceError as error:
            failures[key] = str(error)
    return verified_channels, verified_threads


def _search_scenarios(roots, document_ids, subjects, threads, token):
    results = {}
    for scenario_id, scenario in _read_json("track4/scenarios.json").items():
        terms = scenario["workSearchTerms"]
        query = " OR ".join(f'"{term}"' for term in terms)
        sources = {}
        for source in ("SharePoint", "OneDrive", "Outlook"):
            if source == "Outlook":
                restriction = 'subject:"IQ Workshop"'
                entity, field, verified = "message", "title", subjects
            else:
                paths = roots.get(source, [])
                if not paths:
                    sources[source] = {"status": "failed", "error": "No live demo folder URL."}
                    continue
                restriction = " OR ".join(f'path:"{path}"' for path in paths)
                entity, field, verified = "driveItem", "id", document_ids.get(source, set())
            try:
                hits = _graph_search(entity, f"({query}) AND ({restriction})", token, size=50)
                count = len({hit[field] for hit in hits if hit.get(field) in verified})
                sources[source] = {"status": "matched" if count else "no-evidence", "publishedHits": count}
            except LiveServiceError as error:
                sources[source] = {"status": "failed", "error": str(error)}

        pattern = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, terms)) + r")(?!\w)", re.I)
        matches = [sum(bool(pattern.search(text)) for text in texts) for texts in threads.values()]
        sources["Teams (direct channel read)"] = {
            "status": "matched" if any(matches) else "no-evidence",
            "publishedThreadHits": sum(count > 0 for count in matches),
            "publishedMessageHits": sum(matches),
        }
        results[scenario_id] = sources
    return results


def verify(config, items, state, token):
    publisher_profile(config, token, READ_SCOPES)
    receipts = state["items"]
    failures = {
        item["id"]: "Missing completed, source-matched publication receipt."
        for item in items if (
            not receipts.get(item["id"], {}).get("completed")
            or receipts[item["id"]].get("source") != item["source"]
        )
    }
    roots, document_ids = _read_documents(config, items, receipts, token, failures)
    subjects = _read_outlook(items, receipts, token, failures)
    channels, threads = _read_teams(config, receipts, token, failures)
    scenarios = _search_scenarios(roots, document_ids, subjects, threads, token)
    search_ok = all(
        all(sources[name]["status"] != "failed" for name in ("SharePoint", "OneDrive", "Outlook"))
        and any(sources[name]["status"] == "matched" for name in ("SharePoint", "OneDrive", "Outlook"))
        for sources in scenarios.values()
    )
    return {
        "executionMode": "live-read-only",
        "publicationVerified": not failures,
        "readBack": {
            "SharePoint": len(document_ids["SharePoint"]),
            "OneDrive": len(document_ids["OneDrive"]),
            "Outlook": len(subjects),
            "TeamsChannels": len(channels),
            "TeamsThreads": len(threads),
            "TeamsMessages": sum(map(len, threads.values())),
        },
        "failures": failures,
        "graphSearchSmokePassed": search_ok,
        "scenarios": scenarios,
        "teamsMicrosoftSearch": "not-tested (direct channel reads do not test the Microsoft Search index)",
        "restrictedAccess": "not-tested",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=provision.PUBLISH_CONFIG_PATH)
    parser.add_argument("--interactive", action="store_true", help="Sign in through IQ Workshop Provisioner.")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        items = publisher._catalog()
        publisher._validate_config(config, items)
        state = publisher._load_state()
        if not state["items"]:
            raise LiveServiceError("No publication receipts were found; verify after publishing.")
        publisher._validate_state_context(config, state, allow_legacy=True)
        token = publisher_token(config, READ_SCOPES, interactive=args.interactive)
        result = verify(config, items, state, token)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result["publicationVerified"] and result["graphSearchSmokePassed"] else 1
    except (OSError, json.JSONDecodeError, KeyError, LiveServiceError) as error:
        print(f"M365 verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
