# Live environment setup

The demo has no offline-simulation mode. All presented results must come from the current Fabric, Microsoft 365 Graph, or Foundry service invocation. Prepare an isolated demo tenant and never commit tokens, tenant IDs, database names, or endpoint secrets.

## Runtime

```bash
python3 -m pip install -r requirements-live.txt
```

The SQL endpoint account needs read access to the Lakehouse tables. Standalone legacy setup can use `Authentication=ActiveDirectoryDefault`; the separate demo setup below binds SQL authentication to the selected Azure CLI account. Local CSV tests do not require the live dependencies.

On macOS, if `mssql-python` reports that it cannot load OpenSSL even though it is installed, expose the installed library directory to the Python process. This example was verified with Homebrew's `openssl@3.5`:

```bash
DYLD_LIBRARY_PATH="$(brew --prefix openssl@3.5)/lib" python3 -m tools.run_track4_demo
```

Apply this only to the command that needs it. Keep TLS certificate verification enabled.
If Python's HTTPS client separately reports `CERTIFICATE_VERIFY_FAILED`, use a trusted CA bundle for that invocation (for example, `SSL_CERT_FILE="$(python3 -m certifi)"` when `certifi` is installed and public roots suffice).

## Separate Azure identity for Tracks 1, 3, and 4

Track 2 remains in its Microsoft 365 tenant. Run FabricIQ, WebIQ, and FoundryIQ with a different Azure account and Entra tenant. Set `IQ_AZURE_TENANT_ID` to that tenant UUID and `IQ_AZURE_ACCOUNT` to its sign-in UPN (or its federated application client ID for CI). Set `AZURE_CONFIG_DIR` to a dedicated directory outside the repository, distinct from your normal Azure CLI and Track 2 caches.

This separation prevents the standalone Track 4 runner from reading Track 2; it is not an end-to-end four-source integration. Sign-in, tenant consent, licenses, and access grants are prerequisites requiring authorized human action, even though the remaining deployment and validation steps have scripts.

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-iq-demo"
# Set IQ_AZURE_TENANT_ID and IQ_AZURE_ACCOUNT to your approved Azure demo identity first.
az login --tenant "$IQ_AZURE_TENANT_ID"
```

The scripts compare the target against `track2/provision-config.local.json`. Where that file is absent, set `IQ_M365_TENANT_ID` and (for a user sign-in) `IQ_M365_ACCOUNT` to the Track 2 tenant UUID and publisher UPN. Keep these values out of Git. The checks reject the same tenant or publisher, a mismatched Azure login or token, and an inactive Foundry subscription.

Set the Fabric target variables to the Lakehouse in the selected Azure demo tenant. When using an existing Foundry deployment, set `AZURE_OPENAI_SUBSCRIPTION`, `AZURE_RESOURCE_GROUP`, and `AZURE_AI_ACCOUNT_NAME`; the configured Azure OpenAI endpoint must match that resource in the enabled subscription. Do not supply a Foundry API key or bearer override in this mode. When running Track 4, the runner skips Microsoft Graph entirely and uses only Fabric and public web evidence. A new, authorized cross-tenant configuration would be needed to include Track 2 evidence.

### Track 3 and Track 4 settings

To create an isolated Azure resource group and model for WebIQ, use the [Track 3 Foundry provisioner](../track3/README.md#provision-a-dedicated-azure-deployment). Its optional local target file is read only when passed to the standalone Track 3 briefing; it does not change the Track 4 target.

After the separate login, set these values in the same shell:

| Setting | Target and access |
| --- | --- |
| `AZURE_OPENAI_SUBSCRIPTION`, `AZURE_RESOURCE_GROUP`, `AZURE_AI_ACCOUNT_NAME` | Explicitly selected, enabled Azure subscription and approved Foundry account. The identity needs Azure read access to the account and deployment metadata. |
| `AZURE_OPENAI_MODEL`, optional `AZURE_OPENAI_ENDPOINT` | A ready deployment with Responses and Web Search support. The standalone Track 3 and Track 4 runners derive the endpoint from the configured account if omitted; an explicitly configured URL must match that account. The identity needs Entra inference access. |
| `FABRIC_WORKSPACE_ID`, `FABRIC_LAKEHOUSE_ID` (Track 4 only) | IDs of the Lakehouse loaded with the 14 original Track 1 CSVs. The identity needs Fabric REST read access to the Lakehouse and `SELECT` access through its SQL analytics endpoint. |

Track 3 needs only the Foundry configuration; it does not connect to Fabric. Track 4 resolves its SQL target from the selected Lakehouse metadata. `FABRIC_SQL_SERVER` and `FABRIC_SQL_DATABASE` remain inputs to the standalone SQL CLI, not the Track 4 runner. For a new Foundry deployment, [Track 4's explicit `--provision SUBSCRIPTION_ID` mode](../track4/README.md#provision-and-run-q1q5) needs only the Fabric IDs and a user login with provisioning and account-scope role assignment rights. It ignores the shared Foundry target variables and does not create, load, or change permissions on Fabric. Without `--provision`, the runner does not create deployments or change roles. No mode selects a replacement subscription: the owner must [reactivate a disabled subscription](https://learn.microsoft.com/azure/cost-management-billing/manage/subscription-disabled) or approve a replacement.

## Service settings

| Track | Environment/config | Required access |
| --- | --- | --- |
| FabricIQ | `FABRIC_SQL_SERVER`, `FABRIC_SQL_DATABASE` | Entra identity with SQL endpoint read access |
| WorkIQ search | `GRAPH_ACCESS_TOKEN`; `TRACK2_SHAREPOINT_SCOPE`, `TRACK2_ONEDRIVE_SCOPE`, `TRACK2_OUTLOOK_SCOPE`, `TRACK2_TEAMS_SCOPE` | Short-lived delegated token; source-specific Graph read permission and source ACL |
| WorkIQ provisioning | `--interactive` (publisher-only) or `GRAPH_ACCESS_TOKEN`; local `track2/provision-config.local.json` | Delegated `User.Read`, `Team.Create`, `Team.ReadBasic.All`, `TeamMember.Read.All`, `Channel.Create`, `Channel.ReadBasic.All`, `ChannelMember.ReadWrite.All`, `Files.ReadWrite.All`, `Sites.ReadWrite.All`; two-account setup also needs `User.ReadBasic.All` |
| WorkIQ publishing | `--interactive` or `GRAPH_ACCESS_TOKEN`; generated `track2/publish-config.provisioned.local.json` | Delegated `User.Read`, `Files.ReadWrite.All`, `Sites.ReadWrite.All`, `Mail.Send`, `ChannelMessage.Send`; publisher-only consent |
| WorkIQ verification | `--interactive` or `GRAPH_ACCESS_TOKEN`; generated publishing config and publication receipts | Delegated `User.Read`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Read.All`, `Sites.Read.All`, `Files.Read.All`, `Mail.Read` |
| WebIQ / FoundryIQ | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_MODEL`; Azure CLI sign-in or explicit `AZURE_OPENAI_AUTH_TOKEN`/`AZURE_OPENAI_API_KEY` | Access to the approved deployment, Responses API, and Web Search tool availability |

Use the minimum needed Graph search scopes: SharePoint `Sites.Read.All`, OneDrive `Files.Read.All`, and Outlook `Mail.Read`. Teams `chatMessage` search needs `ChannelMessage.Read.All` plus `Chat.Read` (or `Chat.ReadWrite`). The Track2 verifier's direct channel reads need `ChannelMessage.Read.All`, not chat-read permission. The search adapter marks a source unavailable if its delegated permission or query scope is absent. The user token is not elevated to application access.

## Track2 prerequisites

In the isolated demo tenant, verify that `publisherUpn` has active Teams, SharePoint Online (including working OneDrive access), and Exchange Online service plans and an accessible mailbox. Register the single-tenant `IQ Workshop Provisioner` public client and have an authorized Entra administrator grant Microsoft Graph delegated consent **to `publisherUpn` only**, not tenant-wide. The verified run used a `Global Administrator` for consent; the publisher does not require that role when a separate administrator grants consent. See the [Track2 prerequisites](../track2/README.md#prerequisites) and the registration and consent commands in the Track2 guide.

## M365 target safety

Preserve ignored local state by tenant, and inspect any existing app before explicitly reusing its object ID. Create and license a separate restricted test account only if running the two-account checks; account creation and license assignment are intentionally outside the script. `python3 -m tools.provision_m365 --config track2/provision-config.local.json` prints a plan without network calls. Live creation requires `--apply` and an exact `--confirm-tenant` match. The script creates a private Team containing only the publisher, uses its default SharePoint Documents library, provisions the publisher's OneDrive, creates ACL folders, and sets read access only for the restricted user's Participants folders. It creates seven shared channels and adds that user only to the five non-leadership/non-data-quality channels. Progress is stored locally to resume asynchronous Team/channel creation.

The provisioner does not change tenant-wide sharing policies, remove existing permissions, create or license accounts, or prove effective access. Verify direct folder access and channel visibility as both users before publishing; inherited SharePoint permissions and tenant policies must be checked in the target service. The generated publisher config is `track2/publish-config.provisioned.local.json`; the publisher then uploads content to those configured targets.

For an explicitly selected publisher-only demonstration, `--publisher-only` skips the restricted account, sharing, and denial checks. Review effective permissions before uploading; this mode cannot establish or claim restricted-user isolation. Its saved provisioning state cannot be resumed using the two-account mode.

The publisher sends all 15 workshop emails to the signed-in publisher's own mailbox; sample role names are displayed as text, never impersonated. It posts Teams threads as the signed-in user to configured channels. Review the write plan and pass both `--apply` and the exact `--confirm-tenant` value to publish. Do not use production or shared mailboxes.

## Operational controls

- Assign a tenant owner, demo operator, budget owner, and cleanup owner.
- Use synthetic workshop content only; do not add customer data or internal records.
- Keep the publisher's ignored `.local.json` config and `publish_state.local.json` state file out of Git and backups shared outside the team.
- If demonstrating two-account access controls, verify library/folder/channel ACLs with both identities before connecting Foundry.
- Stop if a source is unsupported, the token user does not match the Fabric identity, or source restrictions cannot be applied.
- Retire short-lived tokens after the demo. Check email retention and remove only resources created for this demo.

## Official references

- [Fabric Lakehouse SQL analytics endpoint](https://learn.microsoft.com/fabric/data-warehouse/sql/overview)
- [Microsoft Graph Search API](https://learn.microsoft.com/graph/search-concept-overview)
- [Microsoft Graph permissions reference](https://learn.microsoft.com/graph/permissions-reference)
- [Microsoft Graph create Team](https://learn.microsoft.com/graph/api/team-post?view=graph-rest-1.0)
- [Microsoft Graph register an application](https://learn.microsoft.com/graph/api/application-post-applications?view=graph-rest-1.0)
- [Microsoft Graph grant delegated permissions for a specific user](https://learn.microsoft.com/graph/api/oauth2permissiongrant-post?view=graph-rest-1.0)
- [Microsoft Graph create channel](https://learn.microsoft.com/graph/api/channel-post?view=graph-rest-1.0)
- [Microsoft Graph get channel filesFolder](https://learn.microsoft.com/graph/api/channel-get-filesfolder?view=graph-rest-1.0)
- [Microsoft Graph create folder](https://learn.microsoft.com/graph/api/driveitem-post-children?view=graph-rest-1.0)
- [Microsoft Graph share a drive item](https://learn.microsoft.com/graph/api/driveitem-invite?view=graph-rest-1.0)
- [mssql-python Entra authentication](https://learn.microsoft.com/sql/connect/python/mssql-python/entra-authentication?view=sql-server-ver17)
- [Foundry Responses API Web Search](https://learn.microsoft.com/azure/foundry/openai/how-to/web-search)
