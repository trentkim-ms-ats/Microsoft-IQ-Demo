"""Paste into a Fabric Python notebook attached to the demo Lakehouse."""

from pyspark.sql import SparkSession, functions as F

DATA_ROOT = "/lakehouse/default/Files/iq-demo"

SCHEMAS = {
    "campaigns": "campaign_id STRING, campaign_name STRING",
    "products": "product_id STRING, product_name STRING",
    "orders": "order_id STRING, campaign_id STRING, order_date DATE",
    "payments": "payment_id STRING, order_id STRING, status STRING",
    "order_items": (
        "order_id STRING, product_id STRING, quantity INT, unit_price_krw BIGINT"
    ),
    "shipments": "shipment_id STRING, order_id STRING, delayed INT",
    "returns": "return_id STRING, order_id STRING, product_id STRING",
    "support_tickets": "ticket_id STRING, order_id STRING, topic STRING",
}

spark = SparkSession.builder.getOrCreate()
existing = [f"demo_{name}" for name in SCHEMAS if spark.catalog.tableExists(f"demo_{name}")]
if existing:
    raise RuntimeError(f"Existing tables; review before rerun: {existing}")

for name, schema in SCHEMAS.items():
    frame = (
        spark.read.option("header", True)
        .option("mode", "FAILFAST")
        .schema(schema)
        .csv(f"{DATA_ROOT}/{name}.csv")
    )
    if name == "order_items":
        frame = frame.withColumn("line_id", F.concat_ws(":", "order_id", "product_id"))
    frame.write.format("delta").mode("errorifexists").saveAsTable(f"demo_{name}")
    print(f"demo_{name}: {frame.count()} rows")
