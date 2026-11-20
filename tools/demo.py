"""Offline demo only: no network, credentials, or third-party packages."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def local_file(path):
    candidate = (ROOT / path).resolve()
    if not candidate.is_relative_to(ROOT) or not candidate.is_file():
        raise ValueError(f"Missing or out-of-scope input: {path}")
    return candidate


def work(role):
    if role not in {"presenter", "guest"}:
        raise ValueError("Unsupported simulation role")
    catalog = read_json("track2/data/catalog.json")
    if catalog["executionMode"] != "simulation":
        raise ValueError("Only simulation catalog is supported")
    evidence = []
    seen = set()
    for item in catalog["items"]:
        if item["id"] in seen or not item["roles"]:
            raise ValueError("Duplicate evidence ID or missing roles")
        seen.add(item["id"])
        path = local_file(item["path"])
        if role in item["roles"]:
            evidence.append({**item, "body": path.read_text(encoding="utf-8")})
    return evidence


def web():
    policy = read_json("track3/data/queries.json")
    fixture = read_json("track3/data/citations.json")
    if fixture["executionMode"] != "simulation":
        raise ValueError("Only simulation citations are supported")
    grouped = {scenario: [] for scenario in policy}
    for citation in fixture["citations"]:
        scenario = citation["scenarioId"]
        url = urlsplit(citation["url"])
        if (
            scenario not in policy
            or url.scheme != "https"
            or url.hostname != citation["domain"]
            or url.hostname not in policy[scenario]["allowedDomains"]
            or url.username
            or url.password
            or url.port not in (None, 443)
            or citation["observedAt"] is not None
            or citation["factStatus"] != "fixture"
            or not all(citation[key] for key in ("title", "scope", "limitations"))
        ):
            raise ValueError("Invalid fixture citation")
        grouped[scenario].append(citation)
    if any(len({c["url"] for c in citations}) < 2 for citations in grouped.values()):
        raise ValueError("Each scenario needs two distinct fixture URLs")
    return grouped


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(path.relative_to(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=["work", "web"], required=True)
    parser.add_argument("--role", choices=["presenter", "guest"], default="presenter")
    args = parser.parse_args()
    output = ROOT / "outputs"
    if args.track == "work":
        evidence = work(args.role)
        write_json(output / "work.json", {
            "executionMode": "simulation", "role": args.role, "evidence": evidence,
        })
    if args.track == "web":
        citations = web()
        write_json(output / "web.json", {
            "executionMode": "simulation", "citations": citations,
        })


if __name__ == "__main__":
    main()
