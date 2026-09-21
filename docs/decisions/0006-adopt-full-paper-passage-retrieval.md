# 0006. Add source-linked full-paper passage retrieval

- Status: accepted
- Date: 2026-09-20
- Issue: #68
- Spec: SDD-RD-01 to SDD-RD-04, SDD-RD-10, SDD-RD-25 to SDD-RD-28, SDD-MD-06, SDD-FT-08, SDD-FT-09, SDD-FT-17; TDD-1.1.8, TDD-1.1.9, TDD-1.1.12, TDD-1.1.25 to TDD-1.1.28; LEARNING-PROTOCOL.md; RETRIEVAL-PROTOCOL.md
- Pull requests: #63

## Context

Overview embeddings omit detailed methods, results and arguments that full-paper reading can expose. The reader already has cards and deep-read tools, but no passage index with source locations. Full-paper retrieval has been requested alongside the overview representation.

## Decision

Retain original-title-and-abstract overview embeddings and add section-aware embeddings of extracted full-paper passages. Apply RETRIEVAL-PROTOCOL.md for chunking, source coverage, model compatibility, bounded query_cards retrieval, exact evidence attachments, cache reuse and snapshot isolation. Preserve the existing tool names and separate stored cards from query-specific evidence.

Optional-signal provenance failures make that signal unavailable rather than discard a readable card. This resolves the conflicting failure clauses in RD-02, RD-03 and RD-10 against RD-01.

## Consequences

Full-paper text can inform the agent through inspectable matching passages. Storage and embedding work increase; a second encoder is not required, while deterministic passage pooling supplies the full-paper head features. Figures remain separately readable. Head inputs concatenate the normalized original overview and overlap-weighted normalized original full-paper pool with equal block scaling. Incomplete full text leaves head inference unavailable rather than silently substituting overview-only features. This feature expansion was explicitly accepted along with full-paper retrieval. Citation-target reconsideration stays in #64 and benchmark-selection authority in #69. Model capability #25 and measured retrieval benefit #32 remain gates, not claims of successful implementation.
