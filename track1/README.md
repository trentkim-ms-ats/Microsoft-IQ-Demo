# Track1 · FabricIQ (live)

Track1's live metric source is the Lakehouse SQL analytics endpoint. The original workshop's 14 CSV files and five fixed queries are used. Local download/analysis commands validate source integrity and query definitions; they are not a substitute for the live demo.

## Complete Track1 automatically

After signing in with the Fabric demo identity, run the single end-to-end command:

```bash
python3 track1/run_track1.py \
  --workspace-id <workspace-id> --lakehouse-id <lakehouse-id> \
  --apply
```

The command publishes the repository Notebook and versioned runtime modules, runs the Notebook through Fabric's on-demand job API, and waits for Q1-Q5 plus generation-2 Ontology validation to finish. It then configures the Ontology-linked GraphModel through Fabric REST APIs, materializes it, and verifies graph type and two graph queries. The optional Lakehouse ID guard fails before deployment writes if the name resolves differently. The Notebook preserves original CSV-backed tables, creates separate typed `_ontology_v4` backing tables, and updates the complete `IQ_Workshop_Track1_Ontology` definition. Ontology tables bind directly to Lakehouse Delta tables through OneLake, rather than through the SQL analytics endpoint. Decimal standard columns use `decimal(38,6)` to match the Ontology decimal property precision and scale. Fabric Graph does not support Decimal properties, so the graph projection exposes each decimal value as exact source text from its `_raw` string column; numeric decimal properties remain unchanged in the Ontology. Updating replaces that Ontology definition; back up any hand-authored additions first. Existing raw and prior `_ontology` tables are not overwritten or deleted. Omit `--apply` to inspect the deployment plan without changes.

To materialize the graph after a previously completed Ontology run, without rerunning the Notebook:

```bash
python3 track1/materialize_graph.py \
  --workspace-id <workspace-id> \
  --ontology-id <ontology-id> \
  --lakehouse-id <lakehouse-id> \
  --apply
```

Replace `--apply` with `--verify-only` to check the existing definition, queryable graph type, 1,200 Product nodes, and 2,003 Order→Customer edges without changing or refreshing the graph. These are smoke checks, not a complete row-by-row graph audit; the Graph API result alone does not establish what the Ontology UI displays.

The standardized status mappings and type conversions are defined in [standardization.py](standardization.py). For the underlying setup and standalone Ontology Notebook, see [Fabric environment setup](FABRIC_SETUP.md) and [Ontology auto-create](ONTOLOGY_AUTO_CREATE.md).

For local source validation only:

```bash
python3 track1/workshop.py download
python3 track1/workshop.py analyze
```

`analyze` reads local CSVs and writes `outputs/workshop-track1.json`. Do not present that output as a live Fabric response.

## Run FabricIQ live

Install [live dependencies](../requirements-live.txt), then sign in with the [separate Azure demo identity](../docs/SETUP.md#separate-azure-identity-for-tracks-1-3-and-4) that can read the Lakehouse SQL endpoint. Set:

- `FABRIC_SQL_SERVER`: the Lakehouse SQL analytics endpoint hostname.
- `FABRIC_SQL_DATABASE`: the Lakehouse SQL database name.

Run one live fixed query:

```bash
python3 -m tools.live_demo --track fabric --scenario Q1
```

The runner reads the approved Q1-Q5 statements from [queries.sql](queries.sql) and reports its SQL identity with returned rows. Separate mode uses the selected Azure CLI identity; legacy mode uses `ActiveDirectoryDefault`. The legacy integrated run compares SQL and Graph token identities before combining internal evidence.

## Metric definitions and caveats

| Question | Measure | Limitation |
| --- | --- | --- |
| Q1 | Campaign-attributed orders; successful, failed, and unknown payment orders | Not a visitor conversion rate; `RetrySuccess` is non-standard |
| Q2 | Return and complaint rates for delayed vs. other orders | `InTransit` is not counted as delayed; comparison is not causal |
| Q3 | Net-to-gross proxy and repeat-customer rate by promotion type | Not cost-based margin or post-promotion repeat rate |
| Q4 | Cancellation rate and tickets per order for orders containing stockout-snapshot products | Snapshot time is not aligned to order time |
| Q5 | Repeat-customer rate by channel, tier, and return reason | Repeat means at least two orders overall; missing tiers/reasons remain missing |

Keep the original data-quality issues visible. Never repair missing or orphan records silently or describe a correlation as a cause.
