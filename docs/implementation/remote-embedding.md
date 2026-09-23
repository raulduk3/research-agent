# Remote-GPU batch embedding and platform-equivalence import

This implements #135 under #70: an off-host embedding path for the
historical corpus (#66) and a measured platform-equivalence gate that guards
importing its vectors into the host's representation namespace. It does not
implement passage search or paper-card evidence attachment (`search_passages`,
`attach_evidence`); those remain unowned stubs (RD-26, RD-27).

## Owners

| Concern | Owner | Tests |
| --- | --- | --- |
| Batch manifest, paper batch files, resumable batch loop, device backend | `models/batch.py`, `bin/embed-batch` | `tests/models/test_batch.py` |
| Cosine equivalence report, threshold gate, import orchestration | `models/equivalence.py`, `bin/import-embeddings` | `tests/models/test_equivalence.py` |
| Atomic per-paper-version index publication | `retrieval/passages.py#publish_index` | `tests/retrieval/test_publish_index.py` |
| Export of a corpus release's extracted text into `--text` (#237) | `learning/text_export.py`, `bin/export-text` | `tests/learning/test_text_export.py` |

`embed_paper_batch` chunks through `retrieval.passages.build_passages` and
pools through `models.embedding.FrozenEmbedder`, the same owners #112 shipped
for the host's graphics-device path; this slice adds no second implementation
of either.

## Commands

```sh
# On the application host, from a corpus release's pilot state (#237):
bin/export-text --state ./pilot --dsn "$DSN" --out ./text

# On the rented GPU host, after syncing extracted text out (see Sync below):
bin/embed-batch --text ./text --out ./vectors --device cuda

# Back on the application host, after syncing ./vectors back. The host side
# always re-embeds on this host's own graphics device (#158); there is no
# --device flag here to choose otherwise.
bin/import-embeddings --in ./vectors --namespace ./index \
  --text ./text --check 25
```

`--text` holds one JSON file per paper version (`<paper_version_id>.json`),
each a `models.batch.PaperText`: `paper_version_id`, `title`, `abstract`,
`extraction_hash`, `canonical_text` and the paper's `ExtractionRecord`.
`bin/embed-batch` writes one vector file per paper version plus
`manifest.json` into `--out`; it makes no storage or network call beyond
resolving the pinned model files, and it is resumable — a paper version whose
output file already exists is not re-embedded, so a killed batch continues
from `--out`'s contents.

`bin/import-embeddings` verifies every file named in the manifest against its
recorded SHA-256 (`models.batch.verify_batch_manifest`), refuses a manifest
whose model identity or chunk policy is not the pinned one (`BatchManifest`
rejects that on construction), then re-embeds `--check N` paper versions from
`--text` on the host's own graphics device (`models.backend.load_frozen_embedder`,
auto-detected and never a CLI choice) and compares them against the imported
vectors (`models.equivalence.check_equivalence`). Import is refused, and
nothing is published, when the measured minimum cosine similarity is below
the manifest's `min_cosine_threshold` (default 0.9999, the #105 initial
configured value). Otherwise every paper version in the batch is published
into `--namespace` through `retrieval.passages.publish_index`, with the
batch's platform and the measured `EquivalenceReport` recorded on each
published entry.

## Sync

1. On the application host, run `bin/export-text` against the corpus
   release's pilot state (#237), then copy `--out` to the rented host over
   an operator-controlled channel (for example `rsync` over SSH); the copy
   is a deployment step. The export reads the pilot's state directory and
   DSN the way `bin/corpus-pilot report` does and makes no network request.
   For each family with a committed `documents` job it takes the title and
   abstract from the committed selection record, finds the payloads that
   job retained through its own request records, and extracts them with
   `reader.extract`: `extract_latex` for a source that decodes to LaTeX
   (`ingest.bulk.decode_latex_source`, a gzip tar with a `.tex` member or
   one gzipped `.tex`), otherwise `extract_pdf` over the PDF's text layer
   read by poppler's `pdftotext`, otherwise `extract_unsupported`. The paper
   version id is `derived_uuid("gate-paper-version", family_id)`, the id
   `ingest.pilot` publishes. A version whose file exists is skipped; a
   version whose coverage is `unavailable`, or whose extraction failed, is
   not written and is listed in `export-manifest.canonical` with the
   reader's coverage or the failure, and is tried again on the next run.
   That manifest names the resolved pilot state, its `config_hash`, the
   count of versions in `--out` and the count per coverage, so an embed
   batch can say which corpus it embedded. It is not a `*.json` file, so
   `bin/embed-batch` does not read it as a paper version.
2. On the rented host, run `bin/embed-batch` against that directory.
3. Copy `--out` (the vector files and `manifest.json`) back to the
   application host.
4. Run `bin/import-embeddings` on the application host, pointing `--text` at
   the same directory used in step 1 so the `--check` sample can be
   re-embedded locally for comparison.

## Recorded agreement

No real run has executed against rented GPU capacity yet. The measured
`min_cosine`, `mean_cosine` and `max_absolute_difference` from the first real
`bin/import-embeddings --check` run belong here once that run happens,
alongside the actual device, driver and library identity it measured
against.

## Known limits

- The representation namespace is a local, file-based `--namespace`
  directory, not the storage service's job-fenced index-publication endpoint;
  `storage/` is a separate owner and out of this change's scope.
  `publish_index` is an engineering index (RD-28): it never marks an entry
  study-qualified, and the Appendix A shared retrieval qualification protocol
  is unrelated, later work.
- `--check N` re-embeds only a sample, not the whole batch; a divergence
  outside that sample is not detected by this gate.
- `bin/export-text` needs poppler's `pdftotext` on `PATH` for a PDF-only
  source; without it each such version is listed as failed, not written.
  `pdftotext` cannot tell an image page from a blank one, so every page
  without text is recorded unreadable, and a PDF with some such pages gets
  `partial` coverage.
- `search_passages` and `attach_evidence` are unimplemented; nothing here
  makes published vectors searchable by the agent tools.
