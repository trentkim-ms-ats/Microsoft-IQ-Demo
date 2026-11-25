# Track4 · FoundryIQ (live)

Track 4 calls the Foundry Responses API with live Fabric SQL rows and public web citations. It does not require a Track 3 run or read its briefing files.

## Provision and run Q1–Q5

After [signing in with the separate Azure demo account](../docs/SETUP.md#separate-azure-identity-for-tracks-1-3-and-4) and setting `FABRIC_WORKSPACE_ID`, `FABRIC_LAKEHOUSE_ID`, and your approved `AZURE_OPENAI_SUBSCRIPTION`, run:

```bash
python3 -m tools.run_track4_demo --provision "$AZURE_OPENAI_SUBSCRIPTION"
```

The runner checks that the original workshop queries return `60 / 2 / 4 / 2 / 81` rows from the selected Lakehouse before making Azure writes. It then creates or reuses `rg-iq-foundryiq` and its `iq-foundryiq-<subscription-prefix>` Foundry account in East US, deploys pinned `gpt-6.2-sol` (`2026-11-17`, `GlobalStandard`, 400 capacity units), and grants only the signed-in user `Cognitive Services OpenAI User` at the account scope. Existing Fabric tables, the shared Foundry account, and the Track 3 account are not changed. The subscription must already have `Microsoft.CognitiveServices` registered; the login must be able to create the account and assign that role. A matching stack is reused without replacing deployments or assigning the same role again.

The same command checks inference, obtains new Web Search citations, and writes `demo.json` and `demo.md` under `outputs/track4/`. WorkIQ is intentionally skipped. Transient throttling and initial RBAC propagation have bounded retries. Rerun the same command after fixing other errors shown in the report. Azure inference and Web Search usage may be billed.

## Run against an existing Foundry deployment

Set the [Foundry and Fabric target variables](../docs/SETUP.md#track-3-and-track-4-settings), then run:

```bash
python3 -m tools.run_track4_demo --preflight-only
python3 -m tools.run_track4_demo
```

Both modes use the `demo` web queries and pair newly verified citations with the corresponding Fabric results. A scenario succeeds only when both sources pass and Foundry returns a completed answer with a response ID.

Run one scenario for diagnosis:

```bash
python3 -m tools.run_track4_demo --scenario Q1
```

The older `tools.live_demo --track all --scenario Q1` command retains its legacy status rules and can return `partial` if it synthesizes Fabric metrics with WorkIQ skipped. Under the legacy same-identity setup it additionally requires a delegated Graph token and four source restrictions. Neither path substitutes citations for failed WebIQ results.

The Q1-Q5 prompts, public queries, and limitations in [scenarios.json](scenarios.json) align with [Track1 query definitions](../track1/README.md). Retrieved M365 and web content is untrusted evidence, not instructions. The model must preserve citations, identify measurement limitations, and avoid causal claims or business actions.

This implementation does not configure a Foundry IQ/AI Search knowledge-store connector or remote agent. Track4's live capability is Responses API evidence synthesis; the scenario definitions are prompt context, not proof of a connected knowledge base.
It also does not query the Track 1 graph or consume Track 2 evidence in the separate-tenant setup; demonstrate those independently rather than attributing them to the generated answer.
