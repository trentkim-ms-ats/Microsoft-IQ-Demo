# Track2 · WorkIQ (live)

WorkIQ uses live Microsoft 365 with a delegated Graph token. The [original workshop package](data/workshop/README.md) contains 60 content items: 15 SharePoint DOCX files, 12 OneDrive DOCX files, 15 Outlook EML messages, and 18 Teams threads containing 55 messages.

## Prerequisites

Use an isolated Microsoft 365 demo tenant. Before running provisioning, confirm that:

- **Entra administrator:** An account in the target tenant can grant the requested Microsoft Graph delegated permissions. The verified run used a `Global Administrator` for this step. If the administrator and publisher are separate, the publisher does not need that role.
- **Licensed publisher:** The account configured as `publisherUpn` has active **Teams, SharePoint Online, and Exchange Online** service plans. Confirm that the account can use Teams, access the SharePoint document library and its own OneDrive, and open its Exchange Online mailbox for the Outlook samples. A tenant subscription alone does not activate these services for the publisher.
- **App registration and consent:** Register `IQ Workshop Provisioner` as a single-tenant public client in Microsoft Entra ID. An authorized administrator must approve the required Microsoft Graph **delegated permissions for `publisherUpn` only** (`Principal` consent), not for all users in the tenant. App registration alone does not grant consent. After approval, sign in to this app as the publisher to obtain a delegated Graph token.

A separate licensed restricted test account is required only for the two-account access checks. Omit it when following the [publisher-only option](#publisher-only-option). The provisioner does not create accounts, assign licenses, or change tenant-wide policies.

In the verified publisher-only run, the account in `track2/provision-config.local.json` served as both administrator and publisher. Its `Global Administrator` role and all three service plans were confirmed, and the app's delegated consent was verified for that account only.

Install the live Python dependencies (`python3 -m pip install -r requirements-live.txt`). App registration and administrator consent also require Azure CLI. The provisioning, publishing, and verification commands can sign in with `--interactive` against the registered app; the resulting tokens stay in memory. No tenant IDs, credentials, generated configs, or live receipts are shipped with the demo.

## 1. Provision isolated M365 targets

Copy `track2/provision-config.example.json` to the ignored local path and set the exact tenant ID, `publisherUpn`, and Team name. Set `restrictedUpn` only if running the two-account checks:

```bash
cp track2/provision-config.example.json track2/provision-config.local.json
```

### Register a delegated Graph app for publisher-only setup

After signing in to Azure CLI as the configured publisher, the following commands first show a local plan and then register a single-tenant public client and its service principal using Microsoft Graph:

```bash
python3 -m tools.register_m365_app --config track2/provision-config.local.json --full-demo
python3 -m tools.register_m365_app --config track2/provision-config.local.json \
  --full-demo --apply --confirm-tenant <exact-tenant-id>
```

The commands use `--full-demo` to add publishing and search scopes to the publisher-only provisioning scopes and register the `http://localhost` redirect for interactive browser sign-in. IDs are saved in the ignored `track2/entra-app-state.local.json`. Registration does **not** grant consent or create a secret. If an app with the same name already exists, it stops rather than adopting it. To reuse an explicitly identified app, pass `--existing-app-object-id <application-object-id>`; its settings and permissions must exactly match. If a write times out, inspect the tenant before retrying.

Use the following commands for publisher-only consent. Do not use the Entra portal's **Grant admin consent for [tenant]** action, which grants consent tenant-wide. Use a separate Azure CLI config directory outside the repository:

```bash
python3 -m tools.grant_m365_consent --full-demo \
  --admin-upn <administrator-upn> --azure-config-dir <private-azure-cli-directory>
python3 -m tools.grant_m365_consent --full-demo \
  --admin-upn <administrator-upn> --azure-config-dir <private-azure-cli-directory> \
  --login --apply --confirm-tenant <exact-tenant-id>
```

Omit `--full-demo` from both commands if it was not used for registration. The admin token must have delegated `DelegatedPermissionGrant.ReadWrite.All` (or `Directory.ReadWrite.All`) and the signed-in administrator must have a supported Entra role. The publisher then uses the registered client ID with an interactive public-client flow to obtain a short-lived token for the required operation. For a tenant switch, preserve the old ignored config and local app/provisioning/publishing state separately, including any generated publishing config. Never use another tenant's state or copy its resource IDs into the new config.

For the two-account workflow, supply a short-lived delegated `GRAPH_ACCESS_TOKEN` from an approved app and authorize the restricted user separately for search. Provisioning requires `User.Read`, `User.ReadBasic.All`, `Team.Create`, `Team.ReadBasic.All` (to poll Teams asynchronous operations), `TeamMember.Read.All`, `Channel.Create`, `Channel.ReadBasic.All`, `ChannelMember.ReadWrite.All`, `Files.ReadWrite.All`, and `Sites.ReadWrite.All`. Do not use an application token or a production tenant.

Review the plan first. This makes no Graph calls:

```bash
python3 -m tools.provision_m365 --config track2/provision-config.local.json
```

Then provision by explicitly confirming the exact tenant ID:

```bash
python3 -m tools.provision_m365 \
  --config track2/provision-config.local.json \
  --apply \
  --confirm-tenant <exact-tenant-id>
```

The script creates a private Team with only the publisher, relies on the Team's default SharePoint Documents library, and creates the three ACL folders in that library and the publisher's OneDrive. It creates seven shared channels; the restricted user is added only to `cs-tier2`, `logistics`, `inventory`, `payments`, and `campaign-ops`. It receives read-only folder shares for `Participants`, not `Leaders` or `Data-Stewards`. The script saves resumable progress in an ignored local state file and writes `track2/publish-config.provisioned.local.json` for the publisher. If replacing an already generated config, add `--overwrite-output`.

If Team/SharePoint provisioning is still in progress, wait a few minutes and rerun the same command; do not delete the state file. For the two-account checks, sign in as both accounts before publishing and verify direct folder access and channel visibility. SharePoint inheritance or tenant sharing policy can affect effective access, so the script's successful writes alone are not proof of isolation.

### Publisher-only option

When a restricted account is unavailable and access-denial verification is intentionally out of scope, add `--publisher-only` to both the plan and apply commands. The `restrictedUpn` value is ignored; no restricted user is added or shared with, and no denial is tested. The Team and channels are created for the publisher only. Folder names do not enforce security: check effective permissions and inheritance before uploading content, and do not claim access isolation was validated. State created in this mode cannot be resumed in two-account mode.

Publisher-only mode does not require `User.ReadBasic.All`; all other provisioning scopes above are still required.

```bash
python3 -m tools.provision_m365 --config track2/provision-config.local.json --publisher-only
python3 -m tools.provision_m365 --config track2/provision-config.local.json \
  --publisher-only --interactive --apply --confirm-tenant <exact-tenant-id>
```

## 2. Publish the live corpus

Use `--interactive` with the `--full-demo` app, or supply a short-lived delegated `GRAPH_ACCESS_TOKEN` for `publisherUpn`. Publishing requires `User.Read`, `Files.ReadWrite.All`, `Sites.ReadWrite.All`, `Mail.Send`, and `ChannelMessage.Send`.

```bash
python3 -m tools.publish_m365 --config track2/publish-config.provisioned.local.json
```

The no-`--apply` command validates the local package and displays the planned writes without contacting Microsoft 365. After reviewing tenant, targets, folder permissions, and counts, explicitly authorize writes:

```bash
python3 -m tools.publish_m365 \
  --config track2/publish-config.provisioned.local.json \
  --interactive --apply \
  --confirm-tenant <exact-tenant-id>
```

The publisher uploads documents to their pre-authorized ACL folders, sends all 15 sample emails only to the signed-in publisher's mailbox, and posts each Teams thread in its mapped channel as that publisher. It does not impersonate the sample role names or send mail to the sample recipients. Its ignored state file records publication receipts for the exact tenant, publisher, and targets so an interrupted run can resume. Preserve older receipts without target context; they can be verified read-only, but the publisher refuses to resume writes from them. The publisher backs off on explicit HTTP `429` responses; for an ambiguous failure, check the remote item before retrying to avoid duplicate posts or mail. Email `202 Accepted` means accepted for sending, not delivered or indexed.

## 3. Verify live publication and search

After indexing, run the publisher's read-only verification against the saved receipts:

```bash
python3 -m tools.verify_m365 --interactive
```

The verifier checks the private Team and shared channels, resolves the SharePoint and OneDrive files at their configured paths, checks exact workshop subjects in the publisher's Outlook inbox, and reads recorded Teams threads and replies. It runs Q1–Q5 against the SharePoint, OneDrive, and Outlook Microsoft Search indexes and counts only hits matched to verified samples. Teams keyword matches are computed from the live channel read-back, **not** the Teams Microsoft Search index. The command exits nonzero if a read-back check fails, a search request fails, or a scenario has no matching published hit across the three tested indexes. A single source can legitimately return no hits. No restricted-user checks are run by this command.

For the separate Graph Search demo, the live Teams `chatMessage` query returned HTTP `403` with `ChannelMessage.Read.All` alone. The adapter requires that scope plus `Chat.Read` or `Chat.ReadWrite`. If Teams Microsoft Search is required, review the additional delegated `Chat.Read` approval separately; the publisher and verifier do not request it. Set:

- `TRACK2_SHAREPOINT_SCOPE` and `TRACK2_ONEDRIVE_SCOPE`: KQL restrictions to the approved demo library/folders.
- `TRACK2_OUTLOOK_SCOPE`: a KQL restriction to the demo mail scope.
- `TRACK2_TEAMS_SCOPE`: a KQL restriction to the approved demo channels.

Run a source search with the test user's delegated token:

```bash
python3 -m tools.live_demo --track work --scenario Q1
```

The Graph Search API runs as the token user. Verify the publisher can open expected source URLs. Only for the two-account checks, verify that restricted items are absent from both search and direct access for the restricted user. The query restriction is an additional search filter, not an ACL.

## 4. Search the real content in the integrated demo

The Q1-Q5 search terms are aligned to the Track1 metrics in [Track4 scenarios](../track4/scenarios.json). Present these search results separately in the current two-tenant setup: standalone Track 4 and the legacy `--track all` command in separate mode skip Graph and do not consume WorkIQ. The legacy same-identity flow can collect Fabric, Graph, and public-web evidence, subject to its identity and permission checks, but that is not the verified two-tenant deployment. A source outage is reported; local corpus content is never substituted for live results.

Do not treat M365 narrative as a measurement or proof of causality. Preserve the source link and state its limitations alongside the Track1 metric.

## Current status

The read-only publisher check verified all 60 published items, including 55 Teams messages across 18 threads in seven shared channels. Q1–Q5 returned published items on SharePoint, OneDrive, and Outlook, and each scenario matched live Teams channel messages. The Teams Microsoft Search index was not verified, and second-user denial testing was intentionally omitted. See the [live results by scenario](../docs/VALIDATION.md#track2-publisher-only-read-back-2026-11-23-kst).
