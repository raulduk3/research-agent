# OpenAlex snapshot as a bulk citation channel

Checked 2026-09-23, before any acquisition from it. The paged Works API is not
the only way to obtain citation observations: OpenAlex publishes its complete
database as files in Amazon S3, and the citation graph can be read from those
files without the API, without an account and without a daily budget.

## Terms

The snapshot lives in the `openalex` bucket under the `data/` prefix. It is
free to download and needs no AWS account; anonymous requests are accepted, and
the AWS Open Data program covers the transfer fees. OpenAlex data is CC0, the
same basis on which the `openalex` row of the permission registry already
allows capture, derived artifacts and retention. The snapshot is the same data
as the API, so it adds no rights question the existing row has not answered.

What it does change is the request pattern. The API's keyless daily budget and
its 100-requests-per-second ceiling do not apply to S3 reads, and the pacing
rule this file fixes for `help.openalex.org` does not transfer to
`openalex.s3.amazonaws.com`. The rule for the bucket is below.

## Shape

Two formats hold the same data, `data/jsonl/` and `data/parquet/`. The works
table is 2,447 objects: 666 GB as JSONL, 725 GB as Parquet. Neither fits the
595 GB free on the corpus volume, and neither needs to be downloaded.

Parquet is columnar and the bucket honours HTTP range requests, so a reader
takes only the columns it needs. Measured on
`data/parquet/works/updated_date=2026-05-21/part_0080.parquet`, 400,000 rows
across 13 row groups and 189 columns, 1,307 MB compressed:

| column | share |
| --- | --- |
| `abstract_inverted_index` | 38.2% |
| `referenced_works` | 7.3% |
| everything else | 54.5% |

`id`, `referenced_works` and `referenced_works_count` together are 7.62% of the
file. Reading exactly those columns from that part pulled 99.6 MB of 1,307 MB
in 28 range requests and yielded 9,158,083 citation edges. Across the works
table that projects to about 55 GB of transfer for the complete citation graph.

## Pacing and cost

Measured from this host on 2026-09-23: a single stream sustains about 30 Mbps;
eight concurrent streams sustain 167 Mbps. At the eight-stream rate the 55 GB
of citation columns transfers in roughly 45 minutes. Peak local storage is one
part file, since each is read and discarded.

The bucket publishes no rate limit. The rule this file fixes for it: at most
sixteen concurrent streams, each a ranged read of a part file, with retry on
`429`, `503` and `500` under exponential backoff. This is an object store
serving a dataset published for bulk reading, not a metadata API, and the
three-second arXiv rule and the OpenAlex API budget rule do not apply to it.

## What this does not establish

- No prediction, forecast or label quality claim follows from the channel. It
  changes where citation observations come from, not what they mean.
- A snapshot carries a release date, not a per-request observation time. Any
  requirement that reads "weekly OpenAlex observation" and assumes a paged API
  read needs amending before this channel serves it, and the release the
  observation came from must be recorded as its provenance.
- The API remains the channel for incremental daily observation. This is a
  bulk backfill channel, in the same relation to the API as `arxiv_bulk_s3` and
  `arxiv_gcs_pdf` are to `export.arxiv.org`.

## Sources

- OpenAlex snapshot documentation, <https://help.openalex.org/access/snapshot/>, checked 2026-09-23.
- The bucket's own anonymous listing and a ranged column read, run on 2026-09-23.
