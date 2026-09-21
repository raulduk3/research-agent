# Paper and passage retrieval

Decision #68. This contract covers full-paper text retrieval alongside the original-title-and-abstract overview representation and their combined prediction-head features under FT-09. The independent Jev input remains RD-17. Retrieval scores are similarities, not probabilities or scientific-value judgments.

## Representations and source coverage

Each paper version has an overview embedding and zero or more passage embeddings in separately named indexes. The overview retains the LEARNING-PROTOCOL.md text contract. Passage input covers successfully extracted body text, appendices, textual captions and textual tables in document order. Exclude the bibliography and repeated page furniture from passage search; retain those in the original artifact and citation-extraction pipeline. Inline mathematical text is retained as extracted, without claiming that text embeddings understand its notation or that image content has been embedded. Figures and unreadable material remain deep-read resources or explicit missing coverage. No OCR is added.

Store extraction identity, source hash, section path, block id and character offsets into the immutable extracted text for every passage. Store page/LaTeX source locations when the extractor provides them; never invent locations. Report extraction coverage as complete, partial or unavailable with reasons and included/omitted block counts. Complete refers to extractable text under this policy, not verified semantic coverage of the PDF. A pipeline failure cannot mark an incomplete passage index complete.

## Chunking

Use the pinned embedding tokenizer. Split within section boundaries into at most 384 content tokens with 64-token overlap; use a 320-token stride and emit the final nonempty remainder only when it contains previously uncovered tokens. Do not overlap across sections. Sections shorter than 384 tokens form one passage. Token offsets map back to stored character spans, and repeated overlap is identifiable from those spans. Section titles are metadata, not silently added input. The representation manifest validates that 384 content tokens plus all model-required prefixes and special tokens fit its supported length. Incompatible models fail qualification rather than truncate.

Preserve one embedding per passage for retrieval. Document and query formatting, pooling, normalization, dimension and precision are fixed in the immutable representation manifest. A model without supported, tested query/document compatibility cannot serve question-to-passage retrieval. Both indexes use compatible vectors from the same adopted model; indexes for different model revisions never mix.

## Combined head representation

For head fitting and inference, use only the first public paper version and its complete extracted-text coverage under this policy. Overview and passage embeddings are unit-L2 float32 vectors of the same dimension d. For each content token t in an included section, let c(t) be the number of passage spans containing that token. Passage weight w(j) is the sum of 1/c(t) over tokens in passage j. This assigns one total unit of weight per token despite overlap. Pool p = sum(w(j) * embedding(j)) / sum(w(j)), using float64 accumulation in section/span order, then normalize p to unit L2 and cast to float32. Concatenate x = [overview, p] / sqrt(2), shape [2d], as the sole head feature vector. No later citation data, metadata counts or Jev fields enter x. The pool is an approximation to full-text representation, not a claim of reasoning over every detail.

Require at least one passage, valid original overview, complete original extraction under the documented policy, and finite nonzero pool. Missing or partial full text makes head inference unavailable; do not substitute zeros, a revised paper or an overview-only model. Retrieval still serves the available overview and passages with their coverage states. The card records head eligibility separately from passage availability. Report the exclusion rate and resulting coverage bias in training/evaluation reports. A future fallback head is a separate model decision.

The pooled vector and feature hash include ordered passage identities, source/extraction identity, chunk policy, weights, overview and representation identity. Changing any of these rebuilds and requalifies affected heads; ordinary outcome-label refresh reuses the same features. Historical training and live inference use this identical construction. New paper revisions can have new retrieval cards but cannot replace original-version head features.

## Search and card evidence

Keep the existing five agent tools. Extend query_cards with a retrieval mode: overview or passages, query text and a result limit from 1 to 5; omitted mode is overview and omitted limit is 5. A paper filter is optional and names one snapshot-visible paper family. Reject extra fields and an empty or over-limit query without truncation. Query text is at most 256 embedding tokens including model-required formatting. Tool outputs still count against AG-12 run budgets.

Passage mode ranks eligible vectors by cosine similarity, ties by paper-family id, paper-version id, section order and passage start offset. Consider only the version selected by the run snapshot; never mix versions or fetch newer artifacts. With no paper filter, the result limit counts distinct paper families; return at most that many families and two non-overlapping matching passages per paper. With a filter, the result limit counts non-overlapping passages from that paper. Both cases therefore return at most five results of their specified unit. Select greedily in rank order, skipping passages overlapping an already selected span in the same version. If fewer eligible results exist, return fewer; no fabricated matches or minimum-similarity claim. An index implementation must reproduce the specified ranking or obtain a separate measured approximation decision.

Return each base card unchanged and attach a separately identified query-evidence envelope: query hash, snapshot id, retrieval-mode and manifest ids, paper/version ids, exact passage text, section/source locations, similarity score and coverage state. This envelope is query-specific, not a mutation of the stored card. A base card lists overview/passage availability, coverage, passage count and the source locator for deep_read. This makes full-paper evidence available with cards without dumping a paper into every default card.

The agent can deep_read the cited surrounding section through existing tools. It receives text and evidence identities, never vector coordinates. Jev assessments remain separately identified; neither retrieval scores nor extracted passages are automatically Jev judgments, quality scores, forecast labels or evolutionary fitness.

## Failure, caching and snapshots

Cache passage embeddings by source/extraction hash, section/span identity, chunk-policy version and representation identity. Index publication is atomic per paper version: unfinished work is pending, not partially complete. Extraction-proven partial text can publish a partial index with its omissions recorded. Reuse unchanged artifacts across runs and head refits. Replacing extraction, chunking or model revision creates new immutable artifacts; old snapshots retain their own index membership and card versions.

Missing full text leaves overview search and source deep reading available with explicit reasons. A passage-mode request without eligible indexed passages returns unavailable for that mode; it does not silently return overview results. Corrupt or incompatible vectors cannot enter a response. A retrieval outage cannot fabricate evidence or remove the original paper identity and abstract.

## Qualification

Before a study uses passage retrieval, preserve an overview-only baseline under SR-17 and preregister a matched comparison under SR-18. Use the same questions, snapshots and reading budgets. Report passage-source fidelity, extraction coverage, relevant-evidence retrieval and agent evidence-support results separately from forecast accuracy and reader usefulness. The benefit criterion and sample size remain the evaluation decision in #32; available infrastructure alone does not establish benefit. No paid inference or hardware purchase is authorized by this protocol.
