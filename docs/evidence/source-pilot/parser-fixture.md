# OpenAlex retained-page parser fixture

Checked 2026-09-21. This is engineering evidence for the offline parser. It is
not the 100-paper source pilot, source qualification, a bulk acquisition, or
permission to retrieve full text.

## Provider contract checked

- The official [API reference](https://help.openalex.org/api/) documents the
  Works list envelope as `meta`, `results`, and `group_by`, permits anonymous
  basic queries, and says OpenAlex data is CC0.
- The official [citation recipe](https://help.openalex.org/how-to/api-recipes/)
  documents incoming-work queries with `filter=cites:W…` and directs callers to
  cursor pagination.
- The official [paging contract](https://help.openalex.org/api/paging/) starts
  with `cursor=*`, follows `meta.next_cursor`, and ends when that value is null.
- The official [Work attributes](https://help.openalex.org/data/works/attributes/)
  define `id`, `ids`, DOI, day-precision `publication_date`, primary topic, and
  referenced works. The parser consumes only these selected metadata fields.
- The official [dataset description](https://help.openalex.org/data/how-its-built/)
  states that OpenAlex data is released under CC0. This does not grant rights to
  article full text, which this fixture did not request.

## One anonymous metadata capture

One request was made without an API key, account, paid tier, or content API:

```text
GET https://api.openalex.org/works
filter=cites:W2741809807
select=id,ids,doi,publication_date,primary_topic,referenced_works
per_page=1
cursor=*
```

The response is
`tests/fixtures/sources/openalex-live-one.json`: 10,453 bytes, SHA-256
`ebacdbf0dfe2aa8db198a875ffbac7b9335198708c8deaaaf215a39ae9d7a632`.
It contains one Work and a nonnull continuation cursor. The manual command did
not preserve an admitted execution-image identity or request-start clock, so no
production `SourceAccess` artifact is asserted for this response. The test
constructs a secret-free, explicitly synthetic `SourceAccess` value to exercise
hash, license, URL and cursor enforcement. The raw bytes and their filesystem
write time are retained evidence, not a substitute for the unavailable capture
provenance. A later real pilot must capture the request clocks and admitted
producer manifest at execution time.

The parsed Work is `W3137875885`. Its exact reference list includes requested
target `W2741809807`; its DOI normalizes to
`10.3390/publications9010012`; its provider publication day becomes the
half-open UTC interval `[2021-03-12T00:00:00Z,
2021-03-13T00:00:00Z)`; and its captured primary subfield id is
`https://openalex.org/subfields/1804`.

## Offline and measured evidence

The parser accepts only bytes matching the retained payload hash and an
admitted `CC0-1.0` access record. It performs no HTTP requests. It rejects the
entire page for malformed work ids, inconsistent DOI/id aliases, a missing
exact target reference, invalid dates or taxonomy ids, cursor mismatch, or
omitted response provenance. Exact shared DOI values may join provider works;
identical titles never do. Conflicting exact aliases retain all date intervals
and subfield ids.

On the local Python 3.12.12 runtime, 1,000 parses of the 10,453-byte retained
fixture measured a median 1,654,250 ns and p95 1,890,833 ns. These figures are
an engineering smoke measurement, not a throughput or qualification claim.
