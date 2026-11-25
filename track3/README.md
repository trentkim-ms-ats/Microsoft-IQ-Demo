# Track 3 · WebIQ

Track 3 retrieves public web evidence with the Microsoft Foundry Responses API `web_search` tool. It never reads Fabric rows or Microsoft Graph results, sends internal identifiers, or falls back to saved answers.

| Profile | Scenarios | Source policy |
| --- | --- | --- |
| `workshop` (default) | Original Q1 payment-provider status, Q2 US weather/transport notices, Q3 electronics safety/security | [Workshop-derived catalog](data/source_catalog.json); exact official host allowlists and at least two distinct citations per scenario |
| `demo` | Existing Track 1/4-aligned Q1–Q5 | [Public guidance queries](data/queries.json); at least one cited public HTTPS source per scenario |
| `all` | Both profiles | Runs each profile independently and writes two reports |

The profiles deliberately have different Q3 meanings: workshop Q3 is product safety/security, not the integrated demo’s promotion metrics. The upstream fixture and simulation runner are not part of the live demo. See [source provenance](../SOURCES.md).

## Provision a dedicated Azure deployment

Use an existing, enabled Azure subscription and the [separate Azure CLI login](../docs/SETUP.md#separate-azure-identity-for-tracks-1-3-and-4). The provisioner requires permission to create the resource group, Foundry account, model deployment, and account-scoped role assignment. The default command prints a local plan. Review the target before adding `--apply`.

```bash
python3 -m tools.provision_track3_foundry \
  --subscription "$AZURE_OPENAI_SUBSCRIPTION" \
  --resource-group rg-iq-webiq \
  --account "$WEBIQ_FOUNDRY_ACCOUNT" \
  --location eastus
```

Choose a globally unique `WEBIQ_FOUNDRY_ACCOUNT`. `--apply` creates the tagged group, keyless Foundry account, and `gpt-5.6-sol` (`2026-07-09`, `GlobalStandard`, 400 capacity units by default), subject to the regional catalog and subscription quota. The version is pinned; review and explicitly provision a new version before it retires. The script grants `Cognitive Services OpenAI User` to the verified Azure CLI user on **that account only**. The public HTTPS endpoint requires Entra authentication; local API-key auth is disabled. Model inference and Web Search are billed on usage.

Run the same command and options to resume or reuse a matching provisioned stack. The script refuses untagged groups, unrelated resources, and mismatched accounts or model deployments; it does not resize or delete anything or create a new subscription. The resulting `track3/foundry.provisioned.local.json` contains only target metadata and is ignored by Git. Pass it explicitly to the briefing command so other tracks keep their existing configuration:

```bash
python3 -m tools.run_track3_daily_briefing \
  --provisioned-config track3/foundry.provisioned.local.json --profile all
```

The provisioned-target path bounds response output and can wait up to two minutes per HTTP 429 retry (at most two retries per request). It does not change the citation gates or use a different deployment when throttled.

## Run the briefing

Prerequisites: Python 3.10+, an existing Azure OpenAI model deployment that supports Responses and Web Search, and an approved Azure identity with `Cognitive Services OpenAI User` and read access to the resource. For the demo, use the [separate Azure account and tenant](../docs/SETUP.md#separate-azure-identity-for-tracks-1-3-and-4), not the Track 2 account. Confirm that your organization allows Web Search and its public data processing and usage costs. Run from the repository root.

An `Enabled` subscription and a `Succeeded` deployment are necessary but do not prove inference access. If a plain Responses request (without Web Search) also returns `401 PermissionDenied`, check the signed-in user or federated identity's role on the exact Foundry account. Azure `Owner` has no inference data actions. Assign `Cognitive Services OpenAI User` only on the approved Foundry account, allow time for propagation, and retry. The briefing runner never grants roles or switches credentials.

```bash
python3 -m tools.run_track3_daily_briefing --profile all --check-config

python3 -m tools.run_track3_daily_briefing \
  --profile all \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --account "$AZURE_AI_ACCOUNT_NAME" \
  --subscription "$AZURE_OPENAI_SUBSCRIPTION" \
  --deployment "$AZURE_OPENAI_MODEL"
```

Use the existing dedicated CLI login, or sign in to it if needed using the [separate Azure identity setup](../docs/SETUP.md#separate-azure-identity-for-tracks-1-3-and-4). The script reads the selected resource and checks that the deployment is ready; it does not create resources or modify Azure settings. Supply `--subscription` with the deployment discovery arguments, or set the target in the documented environment variables and omit the arguments.

Track 3 derives `https://<custom-subdomain>.openai.azure.com` by default. To use the same account's Foundry endpoint, set `AZURE_OPENAI_ENDPOINT=https://<custom-subdomain>.services.ai.azure.com` explicitly. This setting is honored with either CLI arguments or environment variables. The runner verifies the custom subdomain against the approved Azure resource and never switches endpoints automatically. It uses only the verified Azure CLI identity, without API-key or bearer overrides. If Python cannot verify TLS, configure an approved CA bundle; do not disable certificate verification.

```bash
python3 -m tools.run_track3_daily_briefing --scenario Q1 --days 14
python3 -m tools.run_track3_daily_briefing --profile demo
```

`--days` sets a public UTC lookback for the workshop profile (default 7, range 1–90). `--scenario` requires a single profile. This script does not execute Track 4; [Track 4](../track4/README.md) independently collects its own current web evidence.

To run both tracks in order while using this track's provisioned target, see the [ordered launcher](../docs/DEMO.md#run-track-3-then-track-4). Track 4 retains its own environment-configured target.

## Output and automation

Each run writes `briefing.json` and `briefing.md` to a new directory under `outputs/track3/`. The runner requires a completed `web_search_call` and valid titled URL annotations. A list of consulted (but uncited) websites does not count. Reports preserve URLs, observation time, scope, and interpretation boundaries. A failed scenario stays failed, produces no publishable answer, and makes the command exit nonzero; the other scenarios still run. The report always requires human review: checking the links does not establish the event date, geographic relevance, independence of sources, or a connection to internal metrics.

[The GitHub Actions workflow](../.github/workflows/track3-webiq-briefing.yml) runs the same command and uploads the briefing, including recorded failures. Configure an approved `webiq` GitHub environment with `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_AI_ACCOUNT_NAME`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_MODEL`, and `IQ_M365_TENANT_ID` as variables. The last value is the Track 2 tenant UUID, used only to enforce separation. Configure Azure OIDC federation for `repo:OWNER/REPO:environment:webiq`, protect that environment, and grant read and inference access only to the approved resource. No API key is required. The workflow can be run manually or called from a separately approved scheduler workflow with `id-token: write`; no recurring schedule is enabled by default.

See [live validation](../docs/VALIDATION.md#live-acceptance-gates) for the latest verified result.
