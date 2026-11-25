# Live response contract

`tools.live_demo` calls the Fabric SQL endpoint, delegated Microsoft Graph Search (legacy same-identity mode only), and Foundry Responses/Web Search at runtime. `tools.run_track4_demo` requires the separate Azure identity and excludes Graph. It runs independently of the Track 3 briefing. Neither reads stored responses as evidence.

## Evidence classes

| Class | Live data | Required boundary |
| --- | --- | --- |
| FabricIQ | Rows returned by the fixed Q1-Q5 Lakehouse query and SQL identity | Preserve denominator, unit, source query, and metric limitations |
| WorkIQ | Graph Search result IDs, titles, URLs, bodies, and delegated user identity | Search runs under the token user; source restrictions are filters, not ACLs |
| WebIQ | Foundry Web Search answer and citations from actual `web_search_call` output | The public query contains no internal context; citations cannot prove an internal cause |
| FoundryIQ | Responses API answer for this invocation's evidence payload | No remote Foundry IQ/AI Search knowledge connector is configured |

## Status and failure behavior

- Each evidence class is reported in `sources` as `succeeded`, `no-evidence`, `failed`, or `skipped`, with data or an explicit reason.
- In the legacy `tools.live_demo` CLI, analysis is `blocked` when neither Fabric rows nor internal WorkIQ hits are available. If only one internal class is available, or a source fails/returns no evidence, the result can be `partial`.
- In standalone Track 4, WorkIQ is `skipped`. Each selected scenario requires live Fabric rows, fresh validated `demo`-profile citations, and a completed Foundry answer. Missing evidence blocks synthesis; synthesis errors preserve the collected evidence but do not pass. Run status `succeeded` means every selected Track 4 scenario passed; it makes no claim about Track 3 or WorkIQ.
- Track 4 consumes Fabric SQL, not the materialized Ontology graph. A successful answer does not prove graph traversal or native Foundry IQ knowledge-base retrieval.
- In `--provision` mode, the selected workshop queries must also match their expected row counts before any Azure resource changes. Those same live rows feed synthesis; expected counts are a validation gate, not evidence. The report identifies the pinned Track 4 Foundry target and records the inference smoke-test response ID on success.
- A source identity mismatch discards WorkIQ results before synthesis.
- No local output, cached result, or fixture may be substituted for a live failure.
- Missing/invalid credentials, HTTP errors, unexpected schemas, and absent Web Search calls are errors, never empty success.

## Output shape

The CLI returns `scenarioId`, `executionMode=live`, `status`, `question`, `limitations`, per-source `sources` statuses, and any collected `fabric`/`work`/`web` evidence. `synthesisStatus` (`not-run`, `succeeded`, or `failed`) is distinct from the scenario status. A successful answer includes `foundryResponseId`; a synthesis failure includes `synthesisError`. Batch preflight can stop all dependent scenarios before their requests run, and the report lists those scenarios as not run.

The runner does not perform business actions, modify Fabric or M365 ACLs, or claim that a prompt file is a connected knowledge base. Only explicit `--provision` mode may add the signed-in user's inference role on the dedicated Foundry account.
