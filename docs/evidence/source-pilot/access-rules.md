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

## Not used

No API key, account, paid tier, content or PDF service, or credential is used
or stored by the pilot.
