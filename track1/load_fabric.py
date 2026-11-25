"""기본 Lakehouse를 연결한 Fabric Notebook에서 실행하는 원본 CSV 적재 코드."""

import csv
import hashlib
import io
from pathlib import Path

DATA_ROOT = Path("/lakehouse/default/Files")
SPARK_DATA_ROOT = "Files"
# 원본 CSV별 예상 행 수와 SHA-256입니다. 데이터가 바뀌면 적재를 중단합니다.
ROWS = {
    "channels": 4, "customers": 1200, "products": 1200, "campaigns": 1000,
    "promotions": 1000, "orders": 2003, "order_items": 4024, "payments": 2004,
    "shipments": 2004, "returns": 1000, "inventory_snapshots": 2096,
    "order_promotions": 1910, "campaign_attribution": 2250, "support_tickets": 1314,
}
SHA256 = {
    "channels": "2ce04ff27fd0662103f205e0d760dcf6da19502498ced244f729a9eaf23c576e",
    "customers": "ad5df1bf49b8cb3c3f11365656e328938f159eccab83b605aba481c001ac29ac",
    "products": "3adb8f5ee6236bcef208a1af6eeea2ec837e7708284c1bc685a301035e314c97",
    "campaigns": "8b5eb8156bcaa426e45e525338d2edc291382f0465c4421ee87b378d64ee7a4a",
    "promotions": "9f42a16b76c66ad65c8e4e78a89bf52dafc309c42d2497fa35a362a42b8e17c7",
    "orders": "87f199e0876f4ef1137107036ed563ab3d06829fc7c48d7d0a72ec626d0c0348",
    "order_items": "50aae9fd67062d3c46e7de935dc956d2c4e16577975d414df676fe9906e742c5",
    "payments": "6c6bae26fc5c0740900379b10a730724211a550c085398664d5686cf4fe21886",
    "shipments": "fed38bf19d58b61d69cf2c799505f5de1919f7a2154818cd5d760d9f59b1051e",
    "returns": "0c057f1cc79fa432b5d711b825c0e3509e5711f7da558e1210d8822612ef7d9b",
    "inventory_snapshots": "b7d1e7a0aeb8cdd12d9589a8ef81497a68c1b3b17b7aa3fd54e529bf7d6bdfec",
    "order_promotions": "69a00ddf80d47b07e41ea9d6ab4c4fb7db21a27adf4f4528a88528b678513f25",
    "campaign_attribution": "61f104752acaecd70cda95c85df07e6d6197fee413e4788885600778493b3283",
    "support_tickets": "2007e010ad4d7d50a1f79ce25d22d98780cee9a82ffa1d24434a1aaafa244fe0",
}


def verify_source_files():
    """CSV의 원본 해시, 열 머리글, 행 수를 확인하고 열 이름을 반환합니다."""
    headers = {}
    for name, expected in ROWS.items():
        path = DATA_ROOT / f"{name}.csv"
        if not path.is_file():
            raise FileNotFoundError(path)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != SHA256[name]:
            raise ValueError(f"{name}: SHA-256 mismatch")
        with io.StringIO(content.decode("utf-8-sig"), newline="") as stream:
            reader = csv.reader(stream, strict=True)
            columns = next(reader, None)
            if not columns or len(columns) != len(set(columns)):
                raise ValueError(f"{name}: invalid or duplicate CSV headers")
            actual_rows = sum(1 for _ in reader)
        if actual_rows != expected:
            raise ValueError(f"{name}: expected {expected} rows, got {actual_rows}")
        headers[name] = columns
        print(f"{name}.csv: {actual_rows}행, 원본 해시 일치")
    return headers


def load(spark):
    # 기존 테이블은 덮어쓰지 않습니다. 재적재 전에는 테이블을 직접 검토하세요.
    existing = [f"workshop_{name}" for name in ROWS
                if spark.catalog.tableExists(f"workshop_{name}")]
    if existing:
        raise RuntimeError(f"Existing tables; review before loading: {existing}")
    headers = verify_source_files()
    frames = {}
    for name, expected in ROWS.items():
        # Spark에서 Lakehouse Files의 CSV를 읽고 CSV 열 이름이 같은지 확인합니다.
        frame = (spark.read.option("header", True).option("inferSchema", False)
                 .option("mode", "FAILFAST").option("multiLine", True)
                 .csv(f"{SPARK_DATA_ROOT}/{name}.csv"))
        if frame.columns != headers[name]:
            raise ValueError(f"{name}: CSV column mismatch")
        actual = frame.count()
        if actual != expected:
            raise ValueError(f"{name}: expected {expected} rows, got {actual}")
        frames[name] = frame
    created = []
    try:
        for name, frame in frames.items():
            table = f"workshop_{name}"
            # 원본 컬럼을 문자열로 보존해 의도된 데이터 품질 사례를 변경하지 않습니다.
            frame.write.format("delta").mode("errorifexists").saveAsTable(table)
            created.append(table)
            if spark.table(table).count() != ROWS[name]:
                raise RuntimeError(f"{table}: saved row count mismatch")
            print(f"{table}: {ROWS[name]} rows")
    except Exception as exc:
        raise RuntimeError(f"Load failed; inspect these created tables before retry: {created}") from exc


if __name__ == "__main__":
    from pyspark.sql import SparkSession

    # Fabric Notebook에 연결된 Spark 세션으로 적재합니다.
    load(SparkSession.builder.getOrCreate())
