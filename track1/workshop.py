"""Download, verify and analyze the original Track1 workshop dataset."""

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "track1" / "data"
COMMIT = "b16d5fd8ed481f86eb47d5d4625268ef65a7793b"
FILES = {
    "channels": ("2ce04ff27fd0662103f205e0d760dcf6da19502498ced244f729a9eaf23c576e", 4),
    "customers": ("ad5df1bf49b8cb3c3f11365656e328938f159eccab83b605aba481c001ac29ac", 1200),
    "products": ("3adb8f5ee6236bcef208a1af6eeea2ec837e7708284c1bc685a301035e314c97", 1200),
    "campaigns": ("8b5eb8156bcaa426e45e525338d2edc291382f0465c4421ee87b378d64ee7a4a", 1000),
    "promotions": ("9f42a16b76c66ad65c8e4e78a89bf52dafc309c42d2497fa35a362a42b8e17c7", 1000),
    "orders": ("87f199e0876f4ef1137107036ed563ab3d06829fc7c48d7d0a72ec626d0c0348", 2003),
    "order_items": ("50aae9fd67062d3c46e7de935dc956d2c4e16577975d414df676fe9906e742c5", 4024),
    "payments": ("6c6bae26fc5c0740900379b10a730724211a550c085398664d5686cf4fe21886", 2004),
    "shipments": ("fed38bf19d58b61d69cf2c799505f5de1919f7a2154818cd5d760d9f59b1051e", 2004),
    "returns": ("0c057f1cc79fa432b5d711b825c0e3509e5711f7da558e1210d8822612ef7d9b", 1000),
    "inventory_snapshots": ("b7d1e7a0aeb8cdd12d9589a8ef81497a68c1b3b17b7aa3fd54e529bf7d6bdfec", 2096),
    "order_promotions": ("69a00ddf80d47b07e41ea9d6ab4c4fb7db21a27adf4f4528a88528b678513f25", 1910),
    "campaign_attribution": ("61f104752acaecd70cda95c85df07e6d6197fee413e4788885600778493b3283", 2250),
    "support_tickets": ("2007e010ad4d7d50a1f79ce25d22d98780cee9a82ffa1d24434a1aaafa244fe0", 1314),
}


def verify(name, content):
    digest, expected_count = FILES[name]
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"{name}.csv: SHA-256 mismatch")
    text = content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    if not rows or len(rows) - 1 != expected_count or any(
        len(row) != len(rows[0]) for row in rows
    ):
        raise ValueError(f"{name}.csv: unexpected row count or malformed CSV")
    return rows


def download(data_dir=DATA):
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = data_dir / f"{name}.csv"
        if target.exists():
            verify(name, target.read_bytes())
            print(f"{name}: already verified")
            continue
        url = (
            "https://raw.githubusercontent.com/trentkim-ms-ats/"
            f"microsoft-iq-workshop/{COMMIT}/track1/data/{name}.csv"
        )
        with urlopen(url, timeout=30) as response:
            content = response.read()
        verify(name, content)
        target.write_bytes(content)
        print(f"{name}: verified")


def analyze(data_dir=DATA):
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        for name in FILES:
            path = data_dir / f"{name}.csv"
            rows = verify(name, path.read_bytes())
            columns = rows[0]
            if any(not c.isidentifier() for c in columns) or len(set(columns)) != len(columns):
                raise ValueError(f"{name}.csv: invalid column names")
            fields = ", ".join(f'"{c}" TEXT' for c in columns)
            connection.execute(f"CREATE TABLE workshop_{name} ({fields})")
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(
                f"INSERT INTO workshop_{name} VALUES ({placeholders})",
                [[value if value != "" else None for value in row] for row in rows[1:]],
            )
        sql = (ROOT / "track1" / "queries.sql").read_text(encoding="utf-8")
        statements, statement = [], ""
        for line in sql.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                statements.append(statement)
                statement = ""
        if statement.strip() or len(statements) != 5:
            raise ValueError("Expected five complete SQL statements")
        return {
            f"Q{i}": [dict(row) for row in connection.execute(query)]
            for i, query in enumerate(statements, 1)
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("download", "analyze"))
    args = parser.parse_args()
    if args.action == "download":
        download()
    else:
        result = analyze()
        output = ROOT / "outputs" / "workshop-track1.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(output.relative_to(ROOT))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Track1 failed: {exc}", file=sys.stderr)
        sys.exit(1)
