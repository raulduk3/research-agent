# LaTeX source share of the release 1b corpus

Dated 2026-09-23, interim. Measured over the 2,857 families whose
`documents` job had committed when the measurement ran, of the 10,000 the
release selects (cs.AI, cs.LG, quant-ph, q-bio; seed 20260922). The
selection is a uniform draw and the documents stage claims families in
enqueue order, so this sample is not biased by category or by date, but it
is 28.6% of the corpus, and the figures below are to be re-run on the
finished release. It answers #31: how much of the corpus carries the paper
source the reader depends on.

## Method

A family's retained "source" is whatever arXiv served for its e-print, and
arXiv serves a PDF-only submission as its source. So a retained source is
not evidence of LaTeX. Each retained source payload was classified by its
own bytes, never by its declared media type:

| Class | Meaning |
| --- | --- |
| `tar-tex` | gzip tar with at least one `.tex` member |
| `single-tex` | one gzipped file whose text carries `\documentclass`, `\begin{document}`, `\input` or `\section` |
| `tar-no-tex` | gzip tar with no `.tex` member |
| `pdf-only` | the source came back as the PDF's own bytes, or no source was retained |

Usable LaTeX is `tar-tex` plus `single-tex`.

## Result

| Category | n | Usable LaTeX | `tar-tex` | `single-tex` | `tar-no-tex` | `pdf-only` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 2,857 | 2,654 (92.9%) | 2,632 | 22 | 4 | 199 (7.0%) |
| cs.AI | 1,322 | 1,190 (90.0%) | 1,189 | 1 | 1 | 131 (9.9%) |
| cs.LG | 1,584 | 1,493 (94.3%) | 1,491 | 2 | 3 | 88 (5.6%) |
| quant-ph | 553 | 532 (96.2%) | 513 | 19 | 0 | 21 (3.8%) |
| q-bio | 48 | 37 (77.1%) | 37 | 0 | 0 | 11 (22.9%) |

A family can carry more than one category, so category rows overlap and do
not sum to the total.

Retention itself was near total: 2,855 of 2,857 sources and 2,856 of 2,857
PDFs retained, the rest `invalid_payload`. The 7.0% gap between "retained"
and "usable LaTeX" is entirely PDF-only submissions, which is the figure a
reader that depends on source has to plan around. q-bio is the outlier at
77.1%, on a small n of 48; the finished release will say whether that
holds.

## What this establishes

- For the reader's source-dependent paths, about 93% of this corpus has
  LaTeX to read, and about 90% in cs.AI, the category with the most PDF-only
  submissions.
- A source-feasibility gate set at the category level has one category,
  q-bio, materially below the others on the current sample.

## What this does not establish

- Not that the LaTeX compiles or is complete: `tar-tex` means a `.tex`
  member exists, not that the tarball builds.
- Not the final number: 28.6% of the release, re-run at completion.
- Not the bibliography match rate, which is #26 and measured separately
  over the `tar-tex` and `single-tex` families here.
