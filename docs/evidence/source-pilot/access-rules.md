# Source access rules for the acquisition pilot

Checked 2026-09-21, before any pilot acquisition. The runner hashes this file
into every request record as its permission evidence. A change to these rules
means editing this file, which changes that hash.

## arXiv

Source: [arXiv API terms of use](https://info.arxiv.org/help/api/tou.html).

- At most one request every three seconds, on a single connection, counted
  across all machines. The pilot spaces every arXiv request, listing and
  document alike, by at least three seconds. A new process waits a full
  interval before its first request.
- Descriptive metadata (titles, abstracts, authors, identifiers, categories) is
  CC0 1.0. Listing records carry `CC0-1.0`.
- E-prints (PDF and source) may be retrieved for personal or research use.
  Storing and serving them to others requires the copyright holder's
  permission or a suitable license. The pilot retains originals privately for
  this research, records each paper's own license URL with its documents, and
  does not redistribute them.
- Bulk metadata comes from the OAI-PMH interface (`oaipmh.arxiv.org`), whose
  per-category sets `cs:cs:AI` and `cs:cs:LG` include cross-listed records.
  Record datestamps are last-modified dates. Documents come from the
  programmatic host `export.arxiv.org`: `/src/<id>v1` and `/pdf/<id>v1`.

## OpenAlex

Sources: [API overview](https://help.openalex.org/api/),
[authentication](https://help.openalex.org/api/authentication),
[pricing](https://help.openalex.org/access/pricing/).

- Basic use needs no key. Each response reports its own `cost_usd`; a filtered
  Works list request cost USD 0.0001 on 2026-09-21.
- An account gets USD 1 of API use per day, resetting at midnight UTC; a free
  key gives ten times the keyless budget. The keyless daily budget is inferred
  from those two statements (about USD 0.10, or about 1,000 list requests) and
  is not stated as a number.
- Exceeding the daily budget or 100 requests per second returns `429 Too Many
  Requests`. The pilot runs keyless, with no account and no payment method, so
  a request cannot incur a charge. A 429 stops the run; the job resumes at the
  same cursor after the budget resets.
- OpenAlex data is CC0. Request records carry `CC0-1.0`.

## OpenAlex snapshot

Source: [snapshot documentation](https://help.openalex.org/access/snapshot/),
and the bucket's own anonymous listing, checked 2026-09-23. Full review in
[openalex-snapshot.md](openalex-snapshot.md).

- Host `openalex.s3.amazonaws.com`, bucket `openalex`, prefix `data/`. Free,
  anonymous, no account and no key. AWS Open Data covers the transfer fee.
- The data is CC0, the same basis as the OpenAlex API rows above.
- At most sixteen concurrent streams, each a ranged read of one part file.
  Retry `429`, `503` and `500` with exponential backoff. The API's daily budget
  and its three-second arXiv sibling rule do not apply to this host.
- Readers take only the columns they need. The citation graph needs `id`,
  `referenced_works` and `referenced_works_count`, which are 7.62% of the works
  table; no reader downloads a whole part file's columns without cause.
- A snapshot read records the release it came from as its observation
  provenance, not a per-request timestamp.

## Not used

No API key, account, paid tier, content or PDF service, or credential is used
or stored by the pilot.
