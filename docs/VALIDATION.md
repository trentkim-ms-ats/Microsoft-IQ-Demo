# Validation status

## Repository checks

The local test suite validates source data integrity, Fabric deployment helpers, and the live-adapter contracts. These checks do not contact Microsoft services and are not live-demo success evidence.

```bash
python3 -m unittest discover -s tests -v
python3 -m tools.run_track3_daily_briefing --profile all --check-config
# Requires the identity and target variables from SETUP.md; metadata only.
python3 -m tools.run_track4_demo --preflight-only
python3 -m tools.live_demo --help
python3 -m tools.publish_m365 --help
python3 -m tools.verify_m365 --help
```

The publisher's plan mode validates the local 60-item package and target mappings but does not check remote resource existence or modify M365.

The 53 files in the original Track2 `content_definitions/` and `generated/` directories (excluding `.DS_Store`) matched the bundled copies byte-for-byte at the source revision in [SOURCES.md](../SOURCES.md).

## Live acceptance gates

| Track | Required live evidence | Current status |
| --- | --- | --- |
| FabricIQ | Fabric SQL endpoint returns the fixed Q1-Q5 results as the authorized identity | Read-only live check in the existing demo Lakehouse: Q1–Q5 returned 60, 2, 4, 2, and 81 rows, matching the reference counts |
| Fabric Ontology and graph | Direct Lakehouse binding, materialized graph type, and live GQL smoke queries | Verified through REST: 14 node types, 18 edge types, 1,200 Product nodes and 2,003 Order→Customer edges. This does not establish Ontology UI status or validate every graph row |
| WorkIQ publishing | All 27 documents, 15 own-mailbox messages, and 18 Teams threads are published | Verified live: 15 SharePoint and 12 OneDrive files at the configured paths, 15 distinct samples in the publisher's inbox, and 18 Teams threads/55 messages across seven shared channels in the private Team |
| WorkIQ search/ACL | Publisher can find intended content; if testing two accounts, restricted user cannot discover or open protected content | Live Q1–Q5 passed on SharePoint, OneDrive, and Outlook. Direct Teams reads found matching channel content for every scenario. Teams Microsoft Search is still unverified (prior HTTP 403 with `ChannelMessage.Read.All` alone); restricted-account checks were intentionally omitted |
| WebIQ | Foundry returns a completed `web_search_call` and the scenario's minimum of valid, distinct URL citations | Verified live: workshop Q1–Q3 and demo Q1–Q5 all passed on the dedicated `iq-webiq-a9737323` deployment. The cited material still requires review before presentation |
| FoundryIQ | The standalone run pairs live Fabric rows with its own validated WebIQ citations and returns a completed Responses answer for Q1–Q5 | Verified live: 5/5 completed on the dedicated `gpt-6.2-sol` deployment. WorkIQ was skipped as required by tenant separation |

### Current review (2026-11-23 UTC)

The 14 original Track 1 files passed the local manifest checks, the Track 2 publisher-only provision and publishing plans validated without writes, and both WebIQ catalogs passed configuration checks. `materialize_graph.py --verify-only` read the existing Ontology and GraphModel definition and executed both GQL smoke queries without a refresh. It reported the graph type and counts above; nine Decimal properties are represented as source strings in the graph only. Eligibility/UI state and every other graph row were not checked by this command.

The Track 4 metadata preflight passed with the dedicated login, the previously verified target and a trusted CA bundle. An initial invocation without identity settings was blocked as designed; another without the CA bundle failed TLS verification. The existing-target runner now accepts the validated same-account `services.ai.azure.com` endpoint, as the provisioned path already did. Metadata readiness alone does not establish live SQL, inference, or current citation quality.

A fresh ordered run using `--track3-provisioned-config track3/foundry.provisioned.local.json` passed all three workshop and five demo WebIQ scenarios. Its live reports are under `outputs/track3/20261123T150032011814Z-{workshop,demo}/`; human source review is still required. The 53 bundled Track 2 source files were also compared byte-for-byte with the archived source revision with no differences or extra files in those source directories.

The same ordered run subsequently passed all five Track 4 scenarios on the previously provisioned dedicated target using its existing-target path. Fabric returned `60 / 2 / 4 / 2 / 81` rows, each scenario had accepted web evidence and a completed synthesis response, and WorkIQ was skipped. The fresh report is `outputs/track4/20261123T150638052912Z/demo.json`. This rerun did not revalidate Track 2 or prove a native Foundry IQ connector; the earlier Track 2 read-back below remains historical.

### Dedicated Track 4 deployment and demo (2026-11-23 UTC)

`python3 -m tools.run_track4_demo --provision "$AZURE_OPENAI_SUBSCRIPTION"` verified the existing workshop Lakehouse with the selected Azure account before creating a separate, keyless Foundry account in `rg-iq-foundryiq` (East US). ARM confirmed `gpt-6.2-sol` version `2026-11-17` in `Succeeded`, with `GlobalStandard`, 400 capacity units, and no automatic version upgrade. The signed-in user received inference access only at the new account scope. The existing Lakehouse and other deployments were not modified.

The full run exited `0`. The inference smoke test and all five synthesis requests returned completed responses with IDs. Q1–Q5 returned `60 / 2 / 4 / 2 / 81` live Fabric rows and `4 / 6 / 6 / 6 / 5` distinct accepted web citations, respectively. Raw JSON and the Markdown report were saved locally under `outputs/track4/20261123T062117571901Z/`. No prior report or Track 2 data was read. The live checks establish that the pipeline works, not that every generated interpretation or citation is presentation-ready.

A second invocation with `--scenario Q1` also completed live. The deployment ETag, model version, and capacity were unchanged after provisioning was reapplied.

### Dedicated Track 3 deployment (2026-11-23 UTC)

`tools.provision_track3_foundry --apply` created `rg-iq-webiq` and `iq-webiq-a9737323` in `eastus` under the existing Azure subscription, and deployed `gpt-5.6-sol` version `2026-07-09` (`GlobalStandard`). Azure confirmed the account and deployment were `Succeeded`, local key authentication was disabled, and the signed-in user had `Cognitive Services OpenAI User` on the new account. A plain Responses request completed. Live briefings hit HTTP 429 at the initial allocation of 100 capacity units, so only the new deployment was increased to 400, which is now the provisioner default. The previous `trentkim-foundry-resource` deployment kept its 500 units.

Reapplying at 400 capacity units reused the resources and account-scoped role. Running the briefing with `--provisioned-config track3/foundry.provisioned.local.json --profile all` exited `0`; all eight scenarios returned a response ID, a completed live search, and valid citations. Reports are under `outputs/track3/20261123T014006763222Z-workshop/` (Q1–Q3: 4, 4, 4 distinct citations) and `outputs/track3/20261123T014006763222Z-demo/` (Q1–Q5: 8, 9, 7, 7, 5 distinct citations).

### Track 3 live rerun on the shared Foundry account (2026-11-23 UTC)

ARM confirmed the existing subscription was `Enabled` and the approved `gpt-5.6-sol` deployment was `Succeeded`. Plain inference initially returned `401 PermissionDenied`; the selected user only had `Owner`, which has no inference data actions. `Cognitive Services OpenAI User` was assigned at the Foundry account scope. A plain Responses request then completed on the same resource's `services.ai.azure.com` endpoint; the `openai.azure.com` endpoint had still returned 401 at the time of that comparison. The standalone runner now accepts the explicitly configured Foundry endpoint only if its subdomain matches the selected resource.

The first live search returned out-of-policy citations in workshop Q2 and Q3, and those answers were withheld. The runner now includes the exact hostname policy in the workshop prompt in addition to the search filter and validator. The citation gate was not relaxed. A subsequent `--profile all` run completed both profiles in one invocation (exit `0`).

| Profile | Distinct accepted citations by scenario | Successful report directory |
| --- | --- | --- |
| Workshop | Q1: 4, Q2: 2, Q3: 6 | `outputs/track3/20261123T003115277099Z-workshop/` |
| Demo | Q1: 6, Q2: 8, Q3: 7, Q4: 7, Q5: 7 | `outputs/track3/20261123T003115277099Z-demo/` |

Every listed scenario returned a response ID and at least one completed live Web Search call. A successful citation gate confirms retrieval, not that an incident occurred. For example, the workshop payment-provider run cited official status pages but marked the incident check inconclusive. No cached result was used, and Tracks 2 and 4 were not run.

### Ordered Track 3 and Track 4 run (2026-11-22 UTC)

`python3 -m tools.run_tracks_3_4` reused the selected dedicated Azure CLI login. It ran Track 3 before Track 4, and both returned `blocked` without making model requests. Azure Resource Manager confirmed the selected subscription was `Disabled`, with no enabled subscription in the dedicated profile. Track 4 also received HTTP 401 for the previous demo Lakehouse. The same token could list Fabric workspaces, but that workspace was not among the ones visible to this login. No substitute results or access changes were made. Restore the selected subscription and verify read access to the prepared Lakehouse before rerunning.

### Historical combined run (2026-11-22 UTC)

The former `tools.run_track34_demo` command returned `blocked` (exit `1`) and wrote JSON and Markdown reports under `outputs/track34/`. It has been replaced by the [standalone Track 3 and Track 4 commands](DEMO.md#live-commands). The catalogs passed, but the dedicated login profile was not configured, so the batch did not query the services. A separate Azure Resource Manager read confirmed that the prior Foundry subscription was `Disabled`.

An independent read-only check against the existing Fabric demo Lakehouse used the historical Fabric account, distinct from Track 2. It exposed an unsupported `Connection Timeout` connection-string keyword; the SQL adapter now sets its login timeout through the driver's `timeout` argument. With the [macOS OpenSSL setup](SETUP.md#runtime), all five live queries returned the expected row counts. This checks Fabric input only; no live WebIQ citations or Foundry synthesis were produced. Track 2 was not accessed or modified.

### Track2 publisher-only read-back (2026-11-23 KST)

`python3 -m tools.verify_m365 --interactive` matched the following published samples. The Teams columns count keyword matches in the recorded messages retrieved directly from the configured channels, not results from the Teams search index.

| Scenario | SharePoint | OneDrive | Outlook | Teams threads | Teams messages |
| --- | ---: | ---: | ---: | ---: | ---: |
| Q1 | 9 | 7 | 7 | 6 | 6 |
| Q2 | 9 | 7 | 8 | 4 | 4 |
| Q3 | 6 | 3 | 2 | 1 | 2 |
| Q4 | 6 | 5 | 7 | 5 | 7 |
| Q5 | 6 | 4 | 5 | 3 | 4 |

This run did not recreate the tenant deployment, repost samples, or grant new permissions. The registration, consent, provisioning, and publisher plan commands were checked separately without writes.

## Required tests before presentation

1. Run each Q1-Q5 Fabric query against the real Lakehouse SQL endpoint and compare row counts and measures with the intended definitions.
2. Verify Graph token `aud`, `scp`, tenant, and signed-in user; check each source separately. For the two-account workflow, confirm access control by direct source opening as well as Search API results.
3. Verify Outlook send acceptance and delivery in the publisher's mailbox. Verify SharePoint/OneDrive upload URLs and Teams thread/message IDs. Confirm no write landed outside the configured demo locations.
4. Open citations from Web Search and review retrieval time, source scope, geography, and whether it applies to the question.
5. Test each source failure and the integrated identity mismatch: no stale or local results may be substituted; missing Fabric plus missing internal M365 evidence must block the answer.

## Prior environment notes

Previous session notes recorded successful Fabric table loading/query comparison and Graph-token permission/network limitations. They are historical and do not establish current service availability, current content state, or Graph eligibility. The original unsupported-source binding was replaced with direct OneLake bindings, and the Graph API checks above succeeded; the Ontology UI's current eligibility/materialization display has not been independently verified by this review.
