# Microsoft IQ live demo

Four live tracks connect the original Track1 data in Fabric, the original 60-item Track2 package in Microsoft 365, public Web Search, and Foundry Responses synthesis. The demo has no offline-simulation mode or canned live results.

| Track | Live responsibility | Current implementation |
| --- | --- | --- |
| [FabricIQ](track1/README.md) | Demonstrate a business ontology, graph and Q1–Q5 metrics | Fabric Lakehouse, Ontology and GraphModel REST automation; SQL metrics |
| [WorkIQ](track2/README.md) | Find workshop narratives in Microsoft 365 | Delegated Graph Search and channel read-back; not a native Work IQ connector |
| [WebIQ](track3/README.md) | Retrieve public sources without sending internal content | Foundry Responses API `web_search`; not a separate Web IQ connector |
| [FoundryIQ](track4/README.md) | Synthesize live evidence with caveats | Responses API using Fabric SQL and web evidence, not a configured Foundry IQ knowledge base or agent |

## Live setup

Use Python 3.10+, an approved demo tenant, a Fabric Lakehouse SQL endpoint, a delegated Microsoft Graph token, and an Azure AI Foundry deployment with Responses API and Web Search enabled. Keep credentials and tenant IDs outside source control.

```bash
python3 -m pip install -r requirements-live.txt
python3 track1/workshop.py download
python3 -m unittest discover -s tests -v
```

Track1's local `workshop.py analyze` is a data-integrity check only; it is not a demo mode. For the live demo, use the commands and gates in [docs/DEMO.md](docs/DEMO.md). The Track2 package contains 15 SharePoint documents, 12 OneDrive documents, 15 Outlook messages, and 18 Teams threads (55 messages), sourced from the original workshop. Its source and redistribution status are documented in [SOURCES.md](SOURCES.md).

Run [Track 3](docs/DEMO.md#track-3-webiq) with `python3 -m tools.run_track3_daily_briefing --profile all`. [Track 4](track4/README.md#provision-and-run-q1q5) can create or reuse its own Foundry deployment and run all five scenarios with `python3 -m tools.run_track4_demo --provision "$AZURE_OPENAI_SUBSCRIPTION"`. The tracks run independently in the separate Azure environment and do not call Track 2.

## Important boundaries

The tracks illustrate the value of connecting structured business context, workplace narratives, and public evidence, but they are **not one four-source integrated IQ agent**. Track 4 excludes WorkIQ because the tenants are separated; it uses SQL rather than querying the Ontology graph. Show WorkIQ and the graph separately, and do not present their evidence as included in Track 4's answer. Administrator consent, interactive sign-in, licensing, data access, and human review remain necessary; there is no unattended one-command setup for all four tracks.

For Microsoft's product definitions, see [Microsoft IQ documentation](https://learn.microsoft.com/microsoft-iq/) and [Fabric IQ documentation](https://learn.microsoft.com/fabric/iq/). This repository demonstrates selected concepts using the mechanisms in the table, not the complete native product capabilities.

The Track2 provisioner creates a private Team, folders, and shared channels. Direct read-only Participants grants and restricted-user access checks apply only to the two-account workflow. Account creation, licensing, tenant-wide policies, and effective inherited-access verification remain administrator/operator tasks. The publisher writes only to the generated targets: Outlook samples go to the signed-in publisher's own mailbox, and Teams messages are posted as that user. `--apply` plus the exact tenant confirmation is required for live writes. Use [`tools.verify_m365`](track2/README.md#3-verify-live-publication-and-search) to check publication and Q1–Q5 without republishing.

The live CLI is not a claim that external services have been exercised in this workspace. Fabric SQL, Graph scopes, M365 indexing and ACLs, Foundry deployment access, and Web Search availability must pass the live checks in [docs/VALIDATION.md](docs/VALIDATION.md).
