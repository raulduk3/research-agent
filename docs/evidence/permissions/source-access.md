# Source-access evidence for a 100-paper pilot

Checked 2026-09-21. This records provider access facts. The owner has authorized
local implementation and bounded free acquisition; per-source retention and
actual capture provenance still need to be represented in the acquisition
artifacts before a pilot can claim acceptance.

## arXiv

- The [official API manual](https://info.arxiv.org/help/api/user-manual.html)
  documents an unauthenticated Atom metadata API, with `search_query`,
  `id_list`, `start`, and `max_results`. A query plus id list is an
  intersection; `start` is zero based.
- The manual requests a three-second delay between repeated calls, limits a
  query to 30,000 results and slices to at most 2,000. It recommends refining
  queries above 1,000 results and caching: identical daily queries need not be
  repeated. A 100-record metadata candidate set fits this access limit.
- The API manual directs callers to the [API terms](https://info.arxiv.org/help/api/tou.html)
  before use. Metadata access is not evidence that every paper's PDF, source,
  abstract, or derived artifact can be retained. Each selected record's stated
  [arXiv license](https://info.arxiv.org/help/license/index.html), version, and
  any applicable reuse condition must be preserved and evaluated before capture.
- No arXiv-named credential is documented for this metadata API. The local
  environment contained no variable whose name begins `ARXIV`.

## OpenAlex

- The [official API reference](https://help.openalex.org/api/) permits anonymous
  basic metadata queries and identifies the returned dataset as CC0. This is
  sufficient access for the one-record engineering fixture described in
  [parser evidence](../source-pilot/parser-fixture.md), not full-text rights.
- [Authentication](https://help.openalex.org/api/authentication/) documents a
  free keyless daily allowance, a tenfold larger free keyed allowance and a
  100-request/second limit. Responses expose remaining budget, request credit
  use and reset headers. The capture worker must preserve those observations,
  stop when its free allowance is exhausted, and never enable paid billing.
  No OpenAlex-named environment credential was present; no key was created.
- Incoming citations use `filter=cites:W…`. The [filter contract](https://help.openalex.org/api/filtering/)
  allows up to 100 OR values within a filter. Query narrowing must not be
  mistaken for complete citation coverage.
- [Cursor paging](https://help.openalex.org/api/paging/) starts with `cursor=*`
  and follows `meta.next_cursor` to null, with at most 100 works per page.
  The parser binds exact query/target/cursor identity and preserves incomplete
  capture. The default provider corpus is part of the captured query semantics;
  no alternate corpus is silently unioned into labels.

## Remaining pilot evidence

One anonymous metadata request has run; no bulk download, paid content request,
account creation or credential change was performed. The 100-paper pilot still
needs a frozen eligible enumeration, per-original arXiv license records,
rate-limited resumable capture through storage, bounded resource accounting and
complete permission/retention provenance. These are implementation and evidence
requirements, not a request for a new blanket approval. Downstream citing full
text is not needed and OpenAlex paid content is not a pilot dependency.
