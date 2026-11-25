# Live demo runbook

This runbook uses live service calls only. Do not present local CSV calculations, saved responses, or test mocks as demo results.

## Before the session

1. Complete [environment setup](SETUP.md) and [live validation](VALIDATION.md).
2. Verify all 14 Track1 CSVs are loaded into the demo Lakehouse and Q1-Q5 queries execute through its SQL endpoint.
3. Prepare the licensed publisher, register the Entra app, and obtain consent for that publisher only. Review the Track2 provision and publish plans before running their explicitly confirmed apply commands. Prepare a separate restricted account only for the optional two-account checks; see [Track2](../track2/README.md).
4. After indexing, run `python3 -m tools.verify_m365 --interactive` to check publication and Q1–Q5. Verify restricted-user access only if running the two-account checks. With [separate Azure and Microsoft 365 tenants](SETUP.md#separate-azure-identity-for-tracks-1-3-and-4), run Track 2 on its own; Track 4 deliberately excludes it.
5. Set the Graph source KQL restrictions to the approved demo locations. Configure Foundry Web Search and model access, then run [the Track 3 briefing](../track3/README.md) against the approved deployment. Do not place internal record values in public search queries.

For a coherent story, use Q1 throughout: compare campaign payment approval metrics, inspect the Product and Order→Customer graph, show the related Microsoft 365 narrative separately, then review public payment context and the Track 4 answer. The graph and WorkIQ observations are **not inputs** to standalone Track 4. They can provide context for a human presenter, not evidence that the synthesis consumed them. The other scenarios each have their own metric caveats in [Track 1](../track1/README.md#metric-definitions-and-caveats).

## Live commands

```bash
# Direct source checks
python3 -m tools.live_demo --track fabric --scenario Q1
python3 -m tools.live_demo --track work --scenario Q1
python3 -m tools.live_demo --track web --scenario Q1
python3 -m tools.run_track3_daily_briefing --profile demo

# Legacy same-identity flow, or a single scenario with WorkIQ skipped in separate mode
python3 -m tools.live_demo --track all --scenario Q1
```

Use Q1-Q5 as the scenario value. Each call issues new service requests; there is no fixture fallback. Inspect the JSON status, identity, live source IDs/URLs, citations, warnings, and limitations before presenting results.

### Track 3 WebIQ

In the [separate Azure environment](SETUP.md#track-3-and-track-4-settings), run just the public-web briefing:

```bash
python3 -m tools.run_track3_daily_briefing --profile all --check-config
python3 -m tools.run_track3_daily_briefing --profile all
```

`all` collects workshop Q1–Q3 (seven-day UTC lookback by default) and demo Q1–Q5 as separate reports under `outputs/track3/`. Use `--profile workshop` or `--profile demo` to run one profile. This command does not access Fabric or WorkIQ.

### Track 4 FoundryIQ

```bash
# Create or reuse the Track 4 stack, then run all five scenarios.
python3 -m tools.run_track4_demo --provision "$AZURE_OPENAI_SUBSCRIPTION"

# Alternatively, use an explicitly configured existing Foundry deployment.
python3 -m tools.run_track4_demo --preflight-only
python3 -m tools.run_track4_demo
```

The [provision-and-run command](../track4/README.md#provision-and-run-q1q5) checks the selected workshop Lakehouse and reads the required SQL results before it creates any Azure resources. By contrast, `--preflight-only` checks metadata for an existing deployment: `ready` does not prove inference, Web Search, or SQL access. On a live run, Track 4 collects new demo-profile citations for Q1–Q5 and pairs them with live Fabric rows. It requests synthesis only when both sources pass and does not run Track 3, read its reports, or access Track 2. Use `--scenario Q1` to run just one scenario.

Track 4 writes `demo.json` and `demo.md` under `outputs/track4/<UTC-run-id>/` and exits nonzero for `blocked` or `incomplete`. Inference retries HTTP 429/503 at most twice, with a 30-second per-wait ceiling (120 seconds for HTTP 429 in provisioned mode). Provisioned mode also retries selected inference authorization errors during its initial access check, allowing up to 90 seconds of waits for RBAC propagation. Other setup errors must be resolved before rerunning. Present only reviewed, current live evidence.

### Run Track 3, then Track 4

With the Foundry resource and Fabric IDs configured, run `python3 -m tools.run_tracks_3_4` from the repository root. It reuses the already selected login and subscription in the dedicated Azure CLI profile (`$HOME/.azure-iq-demo` by default), without signing in again or selecting a different subscription. If explicit account, tenant, or subscription variables disagree with that profile, the command stops before starting either track.

To use the separately provisioned Track 3 account while retaining Track 4's environment-configured target, run `python3 -m tools.run_tracks_3_4 --track3-provisioned-config track3/foundry.provisioned.local.json`. Without this option both commands use the configured Foundry environment variables. This launcher does not run Track 1 or Track 2 or provision resources.

The launcher runs the two standalone scripts in order. Track 4 still runs its own checks if Track 3 fails, and the launcher exits nonzero if either track fails. It does not change billing or Fabric access. If Fabric REST returns 401 or 403, verify that the signed-in demo account can open the selected workspace and Lakehouse before rerunning Track 4.

## Presentation sequence

1. Show Fabric metrics and their denominator and data-quality caveats.
2. Search M365 for live evidence in the current user's scope; open the cited source links.
3. Show WebIQ public sources separately and explain what they can and cannot establish.
4. Show the Track 4 answer as a synthesis of Fabric SQL and public web evidence only. Do not imply it consumed the graph or the separately presented M365 narrative.
5. If any source is unavailable, show its explicit status. Standalone Track 4 requires both live Fabric and public web evidence for synthesis; the legacy flow blocks if both Fabric and WorkIQ are missing.

Stop on identity mismatch, access-control exposure, unsupported API/source, or an unexplained response. Never perform refunds, campaign changes, customer contact, or other operational actions from the demo.

## After the session

Remove only the demo content and permissions that were created for this event, following retention rules. Revoke test tokens and shut down unused Foundry/Fabric resources.
