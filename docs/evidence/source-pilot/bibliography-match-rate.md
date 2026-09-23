# Bibliography match rate on the release 1b corpus

Dated 2026-09-23, interim. Answers #26: how many parsed LaTeX bibliography
entries the exact-identifier parser (`ingest/bibliography.py`, MD-07,
TDD-4.1.69) resolves to a corpus family. Measured over the 2,654 committed
families whose retained source holds LaTeX (see
`latex-source-share.md`), against an identity index built from the 10,000
selected families: every version of each family's arXiv id, plus its DOI
where the listing carried one (most did not).

## Method

For each family, the `.bbl` members and any `.tex` member holding a
`thebibliography` environment were concatenated and given to the real
parser unchanged. The parser accepts only an explicitly versioned arXiv id
or a DOI; everything else is preserved as an unmatched entry with a reason.
One further count was taken outside the parser and never fed to it:
unmatched entries whose text names a selected family by an *unversioned*
arXiv id, the form most bibliographies actually use.

## Result

| Category | Families with `\bibitem` | Entries | Matched edges | `unresolved_identifier` | `no_identifier` | Unversioned arXiv id naming a selected family |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 2,418 | 122,371 | 25 (0.02%) | 22,297 (18.2%) | 99,872 (81.6%) | 456 (0.37%) |
| cs.AI | 1,065 | 55,180 | 3 (0.01%) | 4,711 (8.5%) | 50,392 (91.3%) | 279 (0.51%) |
| cs.LG | 1,356 | 66,915 | 3 (0.00%) | 5,240 (7.8%) | 61,584 (92.0%) | 248 (0.37%) |
| quant-ph | 511 | 28,812 | 21 (0.07%) | 14,455 (50.2%) | 14,288 (49.6%) | 63 (0.22%) |
| q-bio | 34 | 2,217 | 0 | 284 (12.8%) | 1,930 (87.1%) | 4 (0.18%) |

236 LaTeX families carry no `\bibitem` at all (a `.bib` with no compiled
`.bbl` in the tarball, or biblatex); they contribute no entries. Category
rows overlap.

## What this establishes

- **As a source of intra-corpus edges, bibliography parsing is
  negligible at this corpus size: 25 edges from 122,371 entries.** The
  selection is a uniform 10,000-paper draw from a window of roughly a
  million, so the chance that a cited paper is itself a selected family is
  small by construction; and 81.6% of entries carry no identifier the
  contract may match, only a title and authors, which it forbids matching
  by design. The snapshot channel found 6,766,342 edges into 704,034 arXiv
  works over the same corpus (`snapshot-label-coverage.md`); that is the
  edge source. The parser's product here is the preserved unmatched
  entries, not edges.
- **The versioned-only rule costs more edges than it admits.** 456
  entries name a selected family by an unversioned arXiv id, against 25
  matched in total. The contract's reason (never a fuzzy match) does not
  apply to an unversioned id: it names the family exactly, and a family is
  the unversioned id. Accepting it would multiply the parser's edges by
  about eighteen, to roughly 0.4% of entries -- still negligible as an
  edge source, but no longer refusing exact evidence. Decision issue #231.
- **Physics bibliographies carry identifiers; CS ones do not.** quant-ph
  entries are 50.2% identifier-bearing (journal DOIs, revtex style) against
  8% in cs.AI and cs.LG. Those DOIs resolve to papers outside the
  selection, so they are correctly unresolved here, but a DOI index over
  the full arXiv map would resolve many of them.

## What this does not establish

- Not the match rate against all of arXiv. The index holds the 10,000
  selected families only; an entry citing an arXiv paper outside the
  selection is `unresolved_identifier`, which is correct for the corpus
  graph and says nothing about the parser.
- Not a DOI match rate. The selection carried a DOI for few families, so
  DOI resolution was barely exercised; the OpenAlex identity pass holds
  DOIs for 2,984,041 arXiv works and would change that.
- Not final: 2,654 of an expected ~9,200 LaTeX families; re-run at
  completion.
