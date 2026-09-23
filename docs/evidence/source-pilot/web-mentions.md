# Web mentions from Common Crawl: feasibility and coverage

Finding for #143, measured 2026-09-22 against snapshot `CC-MAIN-2025-26` (crawled 2025-06-12 to 2025-06-25) for the March 2025 arXiv cohort (`2503.NNNNN`, about 24,000 papers), 90 to 110 days after submission. Raw hits are kept with the working notes; nothing was built.

## What the crawl offers

- Snapshots arrive about every five weeks, each with a public columnar index of crawled URLs (300 partitions, about 10 GB in the `url` column) and 100,000 link files (WAT, about 160 MB each, about 16 TB per snapshot) holding every extracted link with the linking page's URL.
- The index answers "which URLs were crawled", not "which pages link to a URL". A count of linking hosts is only visible in the link files.
- arxiv.org itself is absent from the crawl (no abstract page of the cohort, nor of well-known older papers, was captured).

## Part 1: URLs carrying the arXiv id

Full scan of the index's `url` column (all 300 partitions, from this host over HTTPS, 30 minutes, no account). 918 URLs, 724 distinct ids, 675 in the cohort: about 2.8% of the cohort appears in any URL. 462 of those ids appear only on arxiv.org, export.arxiv.org or www.arxiv.org. Off arXiv, about 260 ids (about 1%), almost all on mirrors and aggregators (fugumt.com 43, pubpeer.com 41, huggingface.co 34, paperdigest.org 23). Hosts per id: 675 on one host, 47 on two, 2 on more.

A target defined on this count has a base rate near 1% at K=1 hosts and near 0 at K=2. It does not discriminate.

## Part 2: pages linking to the paper

200 of the 100,000 link files, drawn uniformly with seed 20260922 (0.2% of the snapshot, about 32 GB read), scanned for links to `arxiv.org/abs/<id>` or `/pdf/<id>`, recording the linking host. 59 links, 21 distinct papers, 13 hosts; every paper on one host within the sample. Aggregators and institutional lists carry most of it: catalyzex.com (5 papers), tootfinder.ch, siplab.org, lib.pusan.ac.kr, kaldir.vc.in.tum.de (2 each), then single pages (a lab site, deepmind.google, quantumcomputingreport.com, a university repository).

Extrapolated with the sampling error of a count of 21 (about ±22%): roughly 10,000 (paper, host) pairs in the full snapshot. Distinct papers with at least one linking host are fewer, because aggregator pages hold many ids; a plausible range is 10% to 40% of the cohort at K=1, with the organic share (not aggregators or lab lists) a fraction of that. The full-scan number is not established by this sample.

## Cost of the real measure

A full link-file scan per snapshot reads 16 TB: in-region compute of roughly USD 20 to 50 per snapshot, monthly for as long as forecasts are open, plus the engineering and an account with billing. The index scan cannot substitute for it.

## Conclusion

Web mentions is not adoptable as a target for the first release. It remains a candidate contingent on one full-snapshot scan to establish its base rate by category and an aggregator denylist. The short-horizon selection signals go to venue publication and early-citation rank (#153), which need no new source.

## Status

`commoncrawl_index` is added to the permission registry as **allowed; public dataset, no account, attribution to Common Crawl in reports**. Its use is bounded to feasibility findings until #143 is decided.
