"""Offline demo only: no network, credentials, or third-party packages."""

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MODES = {
    "normal": set(),
    "fabric-down": {"FabricIQ"},
    "work-down": {"WorkIQ"},
    "web-down": {"WebIQ"},
    "internal-down": {"FabricIQ", "WorkIQ"},
    "all-down": {"FabricIQ", "WorkIQ", "WebIQ"},
}
SCHEMAS = {
    "campaigns": "campaign_id TEXT PRIMARY KEY, campaign_name TEXT NOT NULL",
    "products": "product_id TEXT PRIMARY KEY, product_name TEXT NOT NULL",
    "orders": "order_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES demo_campaigns, order_date TEXT NOT NULL",
    "payments": "payment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE REFERENCES demo_orders, status TEXT NOT NULL CHECK(status IN ('approved','failed'))",
    "order_items": "order_id TEXT NOT NULL REFERENCES demo_orders, product_id TEXT NOT NULL REFERENCES demo_products, quantity INTEGER NOT NULL CHECK(quantity>0), unit_price_krw INTEGER NOT NULL CHECK(unit_price_krw>=0), PRIMARY KEY(order_id,product_id)",
    "shipments": "shipment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE REFERENCES demo_orders, delayed INTEGER NOT NULL CHECK(delayed IN (0,1))",
    "returns": "return_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES demo_shipments(order_id), product_id TEXT NOT NULL, UNIQUE(order_id,product_id), FOREIGN KEY(order_id,product_id) REFERENCES demo_order_items(order_id,product_id)",
    "support_tickets": "ticket_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES demo_orders, topic TEXT NOT NULL",
}


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def local_file(path):
    candidate = (ROOT / path).resolve()
    if not candidate.is_relative_to(ROOT) or not candidate.is_file():
        raise ValueError(f"Missing or out-of-scope input: {path}")
    return candidate


def fabric():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for name, schema in SCHEMAS.items():
            table = f"demo_{name}"
            connection.execute(f"CREATE TABLE {table} ({schema})")
            with local_file(f"track1/data/{name}.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                reader = csv.reader(handle)
                columns = next(reader)
                expected = [
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                ]
                if columns != expected:
                    raise ValueError(f"Unexpected columns in {name}")
                rows = list(reader)
            if not rows or any(
                len(row) != len(columns) or any(not value for value in row)
                for row in rows
            ):
                raise ValueError(f"Empty or malformed rows in {name}")
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
        invalid = connection.execute(
            """SELECT o.order_id FROM demo_orders o
               LEFT JOIN demo_payments p ON p.order_id=o.order_id
               WHERE p.order_id IS NULL OR NOT EXISTS
                 (SELECT 1 FROM demo_order_items i WHERE i.order_id=o.order_id)
               UNION ALL
               SELECT s.order_id FROM demo_shipments s
               JOIN demo_payments p ON p.order_id=s.order_id
               WHERE p.status!='approved'"""
        ).fetchall()
        if invalid:
            raise ValueError("Missing payment/items or shipment for failed payment")
        queries = []
        statement = ""
        for line in local_file("track1/queries.sql").read_text(encoding="utf-8").splitlines():
            statement += line + "\n"
            if sqlite3.complete_statement(statement):
                queries.append(statement)
                statement = ""
        if statement.strip():
            raise ValueError("Incomplete SQL statement")
        if len(queries) != 3:
            raise ValueError("Expected exactly Q1-Q3 SQL queries")
        return {
            f"Q{index}": [
                dict(row) for row in connection.execute(query).fetchall()
            ]
            for index, query in enumerate(queries, 1)
        }
    finally:
        connection.close()


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


def combine(metrics, evidence, citations, mode, role):
    failures = MODES[mode]
    blocked = {"FabricIQ", "WorkIQ"}.issubset(failures)
    warnings = {
        "FabricIQ": "정형 수치 미검증",
        "WorkIQ": "업무 문서 근거 없음",
        "WebIQ": "외부 최신 근거 없음",
    }
    responses = []
    for scenario in read_json("track4/scenarios.json"):
        sid = scenario["id"]
        documents = (
            [] if "WorkIQ" in failures
            else [item for item in evidence if sid in item["scenarios"]]
        )
        links = [] if "WebIQ" in failures else citations[sid]
        traces = [
            {"source": "FabricIQ",
             "status": "failed" if "FabricIQ" in failures else "ok",
             "references": [] if "FabricIQ" in failures else
             ["track1/queries.sql", *[f"track1/data/{n}.csv" for n in SCHEMAS]]},
            {"source": "WorkIQ",
             "status": "failed" if "WorkIQ" in failures else
             ("ok" if documents else "no-evidence"),
             "references": [item["path"] for item in documents]},
            {"source": "WebIQ",
             "status": "failed" if "WebIQ" in failures else "fixture",
             "references": [item["url"] for item in links]},
            {"source": "FoundryIQ", "status": "local-combiner",
             "references": ["track4/agent-instructions.txt",
                            "track4/knowledge/definitions.md"]},
        ]
        notices = [warnings[source] for source in warnings if source in failures]
        if not documents and "WorkIQ" not in failures:
            notices.append("현재 역할에 허용된 업무 근거 없음")
        if blocked:
            notices.append("내부 근거 부족으로 분석 차단")
        responses.append({
            "scenarioId": sid, "question": scenario["question"],
            "executionMode": "simulation", "simulationRole": role,
            "status": "blocked" if blocked else
                      ("partial" if failures or not documents else "complete"),
            "metrics": None if "FabricIQ" in failures else metrics[sid],
            "evidenceLinks": documents, "webCitations": links,
            "sourceTrace": traces, "warnings": notices,
            "analysis": None if blocked else
                        "정형 수치·내부 근거·외부 fixture를 구분해 확인하세요. 원인은 확정하지 않습니다.",
            "limitations": [
                scenario["limitation"],
                "웹 페이지 미조회; fixture는 현재 사실이 아님",
                "로컬 규칙 기반 결합; 실제 Foundry/ACL/LLM 호출 없음",
            ],
            "humanApprovalRequired": True,
            "knowledgeReference": "track4/knowledge/definitions.md",
        })
    return responses


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(path.relative_to(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=["all", "fabric", "work", "web", "foundry"],
                        default="all")
    parser.add_argument("--mode", choices=MODES, default="normal")
    parser.add_argument("--role", choices=["presenter", "guest"], default="presenter")
    args = parser.parse_args()
    output = ROOT / "outputs"
    if args.track in {"fabric", "all", "foundry"}:
        metrics = fabric()
        write_json(output / "fabric.json", {
            "executionMode": "simulation", "metrics": metrics,
            "definitions": "track1/data/README.md",
        })
    if args.track in {"work", "all", "foundry"}:
        evidence = work(args.role)
        write_json(output / "work.json", {
            "executionMode": "simulation", "role": args.role, "evidence": evidence,
        })
    if args.track in {"web", "all", "foundry"}:
        citations = web()
        write_json(output / "web.json", {
            "executionMode": "simulation", "citations": citations,
        })
    if args.track in {"all", "foundry"}:
        responses = combine(metrics, evidence, citations, args.mode, args.role)
        write_json(output / "responses" / f"{args.mode}-{args.role}.json", responses)


if __name__ == "__main__":
    main()
