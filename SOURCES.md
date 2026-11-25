# Sources and redistribution

## Workshop data

- Original repository: <https://github.com/trentkim-ms-ats/microsoft-iq-workshop>
- Track1 data reference commit: `b16d5fd8ed481f86eb47d5d4625268ef65a7793b`
- Track2 content package reference commit: `b16d5fd8ed481f86eb47d5d4625268ef65a7793b`
- Track3 source catalog and briefing design reference commit: `b16d5fd8ed481f86eb47d5d4625268ef65a7793b`
- The repository did not contain a `LICENSE`, `COPYING`, or `NOTICE` file at the referenced revision. Public visibility is not permission to redistribute. The requested copies are included here, but the upstream rights have not been independently granted or confirmed. Check authorization before redistributing this repository or its source package.

Track1 includes the original 14 CSV files. Track2 includes the original content definitions and generated 60-item package: 15 SharePoint documents, 12 OneDrive documents, 15 Outlook messages, and 18 Teams threads/55 messages. They are source content for publishing to the configured demo tenant, not local demo results. Track2's uploader sends emails only to the publisher and posts as that account; it does not impersonate source roles or establish M365 ACLs.

## Live-demo implementation

Track3 independently implements the factual scenario topics and official source hostnames from upstream `track3/data/source_catalog.json` and the automation pattern from `tools/run_track3_daily_briefing.py`. The original templates, scripts, and `web_evidence_fixture.json` are not copied into the live demo. The separate integrated profile retains its five generic public queries aligned to Track1. Track4 stores scenario questions, metric limitations, and synthesis guidance; no tenant result or simulated response is stored.

External sites are referenced only at runtime by Foundry Web Search. Their pages, results, brands, or content are not included in this repository. Verify service terms and content rights before recording or redistributing live results.
