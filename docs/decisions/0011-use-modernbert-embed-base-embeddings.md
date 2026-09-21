# 0011. Use modernbert-embed-base as the frozen embedder

- Status: accepted
- Date: 2026-09-21
- Issue: #96
- Spec: SDD MD-06; launch profile, pinned model choices and representation; retrieval qualification; TDD-4.1.67 and the representation, embedding, feature, training-array, head and bundle contracts
- Pull requests: #99
- Supersedes: the Qwen3-Embedding-0.6B selection in decision 0008; preserves the feature policy, head mathematics and all qualification gates

## Context

Decision 0008 pinned `Qwen/Qwen3-Embedding-0.6B`: 1024 dimensions, last-token pooling, an instruction-style query prefix, a 32768-token limit and a [2048] head input. The owner chose `nomic-ai/modernbert-embed-base` instead. No application code loads either model yet; the learning contracts and fitting code hard-coded the Qwen widths.

## Decision

The frozen launch representation is `nomic-ai/modernbert-embed-base` at revision `d556a88e332558790b210f7bdbe87da2fa94a8d8`, Apache-2.0 as declared by its publisher. Facts are read from its public model metadata and configuration, not from local execution:

- 768 dimensions, used in full without Matryoshka truncation.
- Attention-masked mean pooling over all input tokens including the prefix, then unit-L2 normalization, as its sentence-transformers modules specify.
- An 8192-token limit including specials and the prefix.
- Stored overview and passage text uses the exact prefix `search_document: `; queries use `search_query: `.

The combined head input becomes [1536]: the overview and pooled passage vectors, each 768. `contracts/learning.py` holds `EMBEDDING_DIMENSION` and `FEATURE_DIMENSION`; the fitting code uses them rather than repeating the width.

## Consequences

Passage chunks (384 tokens), title-and-abstract overviews and queries (at most 256 tokens) fit the 8192-token limit, so no chunking rule changes. Retrieval qualification, head qualification, the no-truncation rule and the full-rebuild rule for any later replacement are unchanged. Features or heads built at the old width are refused. The pretraining cutoff stays unknown until #24 is answered. The numerical smoke in `docs/implementation/numerical-smoke.md` was measured at the old width and has not been rerun.
