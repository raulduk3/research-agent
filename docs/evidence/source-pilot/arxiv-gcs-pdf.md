# arXiv PDFs from the public Google Cloud Storage bucket

Finding for #146 and the release-1 document stage, measured 2026-09-22 from this host. No account, key or billing was used; every request was anonymous HTTPS.

## What the bucket is

arXiv's bulk-data page (`https://info.arxiv.org/help/bulk_data.html`) names two full-text bulk channels: "Kaggle - Full Text" and "Amazon S3 - Full Text". The Kaggle dataset (`https://www.kaggle.com/datasets/Cornell-University/arxiv`, Cornell University) states: "The full set of PDFs is available for free in the GCS bucket `gs://arxiv-dataset` or through Google API (`https://storage.googleapis.com/arxiv-dataset`)", updated "on a weekly basis". It is an arXiv-sanctioned channel, not a third-party mirror.

## Layout

- Objects: `arxiv/arxiv/pdf/<YYMM>/<id>v<n>.pdf`, one object per paper version; listing by prefix through the JSON API works anonymously. Prefixes `arxiv/arxiv/ps/` and `arxiv/arxiv/html/` also exist; legacy archives (`arxiv/cs/`, `arxiv/quant-ph/`, ...) hold the pre-2007 identifiers.
- No LaTeX source: the bucket carries rendered PDFs only. Source stays on arXiv's own channel (API at the three-second rule, or the S3 archive).

## Measurements

- Anonymous access: HTTP 200/206 with `Content-Type: application/pdf`; range requests honored.
- Coverage: 40 of 40 families sampled from the release-1 selection (queued document jobs) exist at their listed version; the months 2306, 2409, 2412, 2503 and 2508 each list more than 1,000 objects.
- Byte identity: three PDFs already fetched from `export.arxiv.org` by the build were compared by SHA-256 with the bucket's object of the same version: `2404.02990v1` (21,415,969 bytes), `2404.12493v1` (807,887 bytes) and `2409.08916v1` (4,971,015 bytes) are identical; `2409.08916v2` differs from the v1 copy, as a different version must. The bucket holds arXiv's own bytes, so an artifact fetched from it has the same content identity as one fetched from arXiv.
- Throughput: 24 PDFs, 137.5 MB, in about 6 s with eight parallel downloads, about 20 MB/s from this host, against about 1 MB/s from `export.arxiv.org` under its one-connection rule. The release-1 PDFs (10,000 families, about 4.3 MB each) are about 45 GB, under an hour.

## Terms

The Kaggle page applies CC0 to the metadata and refers to `https://arxiv.org/help/license` for the papers, the same terms as every other arXiv channel: personal and research use, no redistribution of e-prints, link back to arXiv. No rate limit is stated for the bucket; Google Cloud's public-bucket egress is borne by the bucket's owner. Retention follows the study's policy as for `arxiv`.

## What this permits for the project

- The documents stage may fetch each family's PDF from the bucket in parallel and its LaTeX source from arXiv at the three-second rule, halving the arXiv requests per family. The access record names the bucket URL as the source; the artifact's identity is its bytes, and a sampled hash comparison against arXiv's copy is the ongoing equivalence check.
- For the historical corpus, PDFs for all 10,000 families can be present within an hour of the label stage ending; source follows at about nine seconds a family.

## Status

`arxiv_gcs_pdf` is added to the permission registry as **allowed under arXiv's e-print terms for personal and research use; no redistribution; link back to arXiv; PDFs only**.
