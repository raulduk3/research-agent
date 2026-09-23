# Source, model and provider permission registry

Checked 2026-09-22. Maps evidence to every `source_id` in the
`SourcePermission` contract (TDD.md, Operations contracts: Deployment
bindings and permissions) and to SDD IN-25 and IN-27. This is evidence toward
that record, not a submitted `SourcePermission` row: no storage service
exists to assign a `permission_id`, `terms_hash` or `evidence_hashes` as
artifact ids, so the table below links to the evidence documents themselves
instead.

| `source_id` | `decision` | `permits_capture` | `permits_derived_artifacts` | `permits_retained_responses` | `permits_hosted_processing` | evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `arxiv` | allowed for metadata (CC0); e-prints for personal/research use, no redistribution | true | true | true | n/a, no hosted provider service | [source-access.md](source-access.md), [access-rules.md](../source-pilot/access-rules.md) |
| `openalex` | allowed (CC0 metadata); full-text rights not evaluated | true (metadata) | true | true | false | [source-access.md](source-access.md), [access-rules.md](../source-pilot/access-rules.md) |
| `jev` | unknown | false | false | false | false | owned by #59, not yet reviewed |
| `hf_daily_papers` | unknown | false | false | false | false | access/retention validation not yet performed (Appendix A: Retrieval, extraction and graph values requires this before enabling) |
| `arxiv_bulk_s3` | allowed for research use with in-region processing; link back to arXiv; no redistribution of e-prints | true | true | true | true, requester-pays reads inside the bucket's region | [arxiv-bulk.md](../source-pilot/arxiv-bulk.md) |
| `arxiv_gcs_pdf` | allowed under arXiv's e-print terms (research use, no redistribution, link back); rendered PDFs only, byte-identical to arXiv's; an arXiv-sanctioned bulk channel | true | true | true | true, public bucket readable from any host | [arxiv-gcs-pdf.md](../source-pilot/arxiv-gcs-pdf.md) |
| `commoncrawl_index` | allowed; public dataset, no account; attribution to Common Crawl in reports; bounded to feasibility findings until #143 is decided | true | true | true | true, public bucket readable from any host | [web-mentions.md](../source-pilot/web-mentions.md) |
| `embedding_weights` | allowed by license (Apache-2.0, `nomic-ai/modernbert-embed-base`) | true | true | n/a | false, runs locally on the application host | [pinned-sources.md](../models/pinned-sources.md) |
| `agent_weights` | allowed by license (MIT, publisher-declared, `glm-5.3-flash`); the system hosts no agent weights | n/a | n/a | true | true, served per-token by Z.ai's first-party API (decision 0015) | [pinned-sources.md](../models/pinned-sources.md) |

License permission is not the same as deployment or capability readiness.
`embedding_weights` and `agent_weights` above record only that the publisher
license permits the stated uses; the pinned-sources evidence is explicit that
"provider access, limits, retention permission and operating values are not
established by these pages," and tracks that separate readiness gate (SDD
RD-24) under #59 and #100. Retention deadlines are not source-imposed for any
row above; they follow the launch profile's general retention policy (study
duration plus two years, Appendix A: Diagnostics, alerts and data handling),
subject to required-deletion tombstoning under a source's own terms — for
example, the 48 of 100 pilot papers retained under arXiv's non-exclusive
distribution license only, recorded in
[pilot-2026-09-21.md](../source-pilot/pilot-2026-09-21.md).

## Missing permission versus disabled optional sources

`jev` and `hf_daily_papers` above are missing permission: both are required
by launch scope (eight Jev content assessments; the Hugging Face Daily Papers
discovery baseline), and neither has had its access/retention review
completed. They are not part of this registry because they are unwanted —
`hf_daily_papers` failing to become available leaves its baseline
`unavailable` without blocking the research digest (Appendix A), and `jev`
review is `#59`'s explicit scope.

This is distinct from the six diagnostic adapters disabled by design at
launch — provider citation-intent (EN-18), repository-fork (EN-19),
linked-artifact (EN-20), artifact-upvote (EN-21), repository-star (EN-22) and
discussion-mention (EN-23). Each of those SDD requirements states directly
that "this adapter is not a launch dependency; enabling it requires its
source capability and retention review under IN-25." They are not `source_id`
values in the `SourcePermission` enum and carry no row here; their absence is
a launch design choice, not a missing-evidence gap.
