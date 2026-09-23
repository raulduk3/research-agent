# Snapshot label coverage for release 1b

Dated 2026-09-23. Measured against the release 1b selection (10,000
families; cs.AI, cs.LG, quant-ph, q-bio; seed 20260922) and a complete pass
over the OpenAlex works table. It records what the snapshot can and cannot
label, so the choice between the snapshot and the per-request API rests on
numbers rather than on the API's convenience.

## What was measured

Two passes over the works table, reading only the columns each needed
through HTTP range requests against the object store.

| Pass | Columns | Wall time | Pulled | Rows | Output |
| --- | --- | --- | --- | --- | --- |
| Identity | `id`, `doi` | 39.5 min | 39.9 GB | 510,372,821 | 2,984,041 arXiv works |
| Citations | `id`, `referenced_works` | 112.0 min | 80.2 GB | 510,372,821 | 6,766,342 edges into 704,034 arXiv works |

The table is 2,447 objects and 725 GB in full. The two columns the citation
pass needs are 7.62% of it; the measured pull is consistent with that share
plus parquet footers. Throughput was 10 to 11 MB/s across sixteen streams.

## Coverage of the selected corpus

| Quantity | Count | Share |
| --- | --- | --- |
| Selected families | 10,000 | |
| Resolved to an OpenAlex work by arXiv DOI | 9,699 | 97.0% |
| Families with at least one citing work in the snapshot | 2,779 | 27.8% |

The 27.8% is not a coverage failure. The population rule draws from the
mature window, and most of a recent window's papers have no incoming
citation yet; for a citation-count target that is an observed zero, which
is a label, not a gap. The number that bounds the channel is the 97.0%:
those families can be labelled from one pass.

The 301 families that do not resolve carry no arXiv DOI in the snapshot.
They need a different identity path, per-request matching or a title match,
and until one exists they are unlabelled rather than labelled zero. Nothing
here licenses recording a zero for a family whose identity was never
resolved.

## What this establishes

One pass labels 97.0% of the corpus in under two hours. The per-request API
channel, under the keyless daily limit this build actually hit, resolves the
same 10,000 families in roughly sixteen days, and stops the whole run when
it refuses (fixed in #221). The snapshot is therefore the channel for bulk
citation labels, and the API is for the identity paths the snapshot cannot
resolve.

## What this does not establish

- Not a per-family observation. These counts come from a scratch pass, not
  from the pilot's own stage, and no artifact in the corpus is derived from
  them. The scheduler that would make the pass produce committed
  observations is #223.
- Not a timestamped observation. A snapshot read carries its release as
  provenance, not a per-request instant, so an observation built from it
  must record the release, as `docs/evidence/source-pilot/openalex-snapshot.md`
  already sets out.
- Not a target-label mapping. Edges are the input to the registered
  citation targets, not the labels themselves; horizons, grace periods and
  base rates apply on top.
