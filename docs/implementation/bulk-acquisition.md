# Bulk acquisition from arXiv's requester-pays S3 archive

This implements #146 under #66: a second acquisition path for corpus
releases, alongside the daily API path (`docs/implementation/source-pilot.md`).
Given a selected population, it reads arXiv's monthly source and PDF bundles
from the requester-pays S3 archive confirmed by #145
(`docs/evidence/source-pilot/arxiv-bulk.md`), extracts text for each
family's source member with the same extractor #111 already ships
(`reader/extract.py`), and publishes the same provenance and extraction
contracts the corpus release job (#114) already consumes from the API path:
`SourceAccess`, `PaperVersionRecord`, `ExtractionRecord`. Bundle originals
stay in the archive; only extracted text, hashes and a manifest come home.
It does not select the population (`learning/corpus.py`) or assemble a
chunked `PassageRecord` set (see "Known limits").

## Owners

| Concern | Owner | Tests |
| --- | --- | --- |
| Permission and credential gates, manifest parsing, tar decoding, hand-rolled SigV4 client | `ingest/bulk.py` | `tests/ingest/test_bulk.py` |
| Resumable `capture` job worker, one bundle group per checkpoint | `ingest/bulk.py#BulkWorker` | `tests/integration/corpus/test_pilot_resume.py`-style, real storage |
| Local operator and CLI | `ingest/bulk.py#main`, `bin/extract-in-region` | manual |

## Permission and credentials

The job refuses to start unless `docs/evidence/source-pilot/arxiv-bulk.md`'s
own `## Status` section still confirms `arxiv_bulk_s3` is allowed research
use (`require_permission`). The evidence file's exact bytes are hashed and
carried as `Identity.permission_evidence_hash`, so a corrupted or replaced
evidence file changes the identity every publication is checked against —
`BulkWorker` re-verifies this hash against the identity it is constructed
with, not only at CLI startup.

AWS credentials come from `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (and an
optional `AWS_SESSION_TOKEN`) in the environment only
(`credentials_from_environment`); the job never reads a credential from a
file (PL-11 to PL-16).

## S3 access

No AWS SDK is added to this repository's pinned dependencies
(CONTRIBUTING.md: no speculative abstractions). `RealS3Client` issues a
plain HTTPS GET/HEAD, signed with a hand-rolled AWS Signature Version 4
implementation reviewed against the AWS SigV4 specification, since it cannot
be exercised against real AWS in CI. `verify_region` HEADs the bucket first
and records the region `x-amz-bucket-region` reports; `get_object` refuses
to run before that so no object read is ever misattributed to an unverified
region. Every request carries `x-amz-request-payer: requester`. `bytes_read`
and `request_count` accumulate on the client for the PL-16 demand record.

## Manifests and members

arXiv publishes one manifest per collection, `src/arXiv_src_manifest.xml`
and `pdf/arXiv_pdf_manifest.xml`, each a flat list of `<file>` entries naming
a bundle's key, its `[first_item, last_item]` id range and its `yymm`.
`parse_manifest` reads the entries; `bundle_for_family` finds the bundle
whose range contains a given family id by lexicographic containment, which
matches numeric containment because arXiv ids are fixed-width and
zero-padded within one bundle's month. `_find_member` locates one family's
member inside an opened bundle tar by exact stem or stem-plus-non-digit-suffix,
so a longer id that happens to share a numeric prefix is never mismatched.

A source member is one gzip-compressed stream: plain TeX text, or (for a
multi-file submission) a nested tar. `decode_latex_source` unwraps both
forms and picks the largest `.tex` member of a nested tar; a PDF-only
submission's "source" is the PDF itself and decodes to `None`, so
`extract_source_member` calls `reader.extract.extract_unsupported` instead
of inventing text. This module does not run TeX or OCR (SDD-MD-10, the same
constraint #111 observes).

## The worker

`BulkWorker` claims `capture` jobs the same way `ingest/pilot.py#PilotWorker`
does, over an authenticated `StorageClient` — `pilot_local.local_storage`'s
server capability admits only the `capture` job kind, and that binding is
not edited for this change. One `capture` job carries a `bulk` stage
specification: the target bucket and the selected population (family id,
first-public time, categories, the same shape `learning/corpus.py#PilotCandidate`
enumerates).

Per run: verify the region once, fetch both manifests, then process each
distinct source bundle in turn. For each bundle: fetch it, record its
`SourceAccess`, then for every family whose source lives in that bundle,
extract its source member (required; missing is recorded `not_found`, never
invented) and best-effort fetch its PDF member (provenance only — no text
comes from a PDF). A family's `PaperVersionRecord` is published once its
source member's `SourceAccess` and `ExtractionRecord` exist, carrying
`text_source_kind` of `latex` or `metadata` depending on whether the source
had a supported text layer. A family with no source bundle at all is
counted in the run summary's `families_missing_bundle` and produces no
`PaperVersionRecord`.

## Resumption

Each bundle is one checkpointed unit (`work_key("bundle", filename)`): the
worker records completed bundle keys and output hashes after every bundle,
and a resumed claim restores them before continuing with the next one
(PL-15). A transient S3 failure mid-bundle raises `BundleFetchFailed`
uncaught, the same way a killed process would — the job's lease simply
expires and a later run reclaims it, resuming from its last checkpointed
bundle rather than retrying forever inside one process.

## Operating it

```sh
bin/extract-in-region run --state DIR --dsn DSN \
  --population candidates.json [--bucket arxiv]
bin/extract-in-region report --state DIR --dsn DSN
```

`--population` is a JSON array shaped like `learning/corpus.py#PilotCandidate`:
`{"family_id", "first_public_at", "categories"}` per entry. The DSN must
select a schema dedicated to this job, distinct from the daily API path's;
the state directory holds local mTLS certificates, published artifacts and
one `runs.jsonl` line per run recording wall time, peak RSS, bytes read,
request count and an estimated cost (`ESTIMATED_USD_PER_GET_REQUEST`, an
explicit documented placeholder — see `arxiv-bulk.md`'s own "## Status" on
recording the measured rate at first access).

## Known limits

- No feature or chunking pipeline runs here: `reader/chunk.py` needs a
  pinned tokenizer this job does not wire, so no `PassageRecord` set is
  assembled. A family acquired through this path is text-and-provenance
  only until a later pipeline chunks it, the same disclosed state #114's
  release contract already reports for every unfeatured row.
- The cost estimate is a documented placeholder (`ESTIMATED_USD_PER_GET_REQUEST`,
  AWS S3 Standard's published general-purpose GET pricing at time of
  writing), not a measurement; `arxiv-bulk.md` records the bucket's actual
  region and current per-gigabyte rate at first real access.
- Like the source pilot's local operator, this one runs in a single local
  process with no container image and talks to storage directly through
  `StorageClient` rather than over the deployed mTLS boundary as a service.
- The equal-text-hash acceptance criterion (a family acquired both ways
  yields identical extraction) is exercised against the pilot's 100 once a
  real bulk run against the pinned population executes; no run has done so
  yet, so no measured agreement is recorded here.
