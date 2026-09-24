# 0021. Add a declared metadata block to the prediction-head input

- Status: accepted
- Date: 2026-09-22
- Issue: #148
- Spec: SDD Appendix A: Launch profile, Pinned model choices and representation; Appendix B: Learning protocol, Representation and fitting, Inference contract and paper-card shape; SDD-FT-08; SDD-MD-06
- Pull requests: pending
- Supersedes: the embedder-alone premise of decision 0002 in part (the embedding-only head remains the comparison arm of the #25 run)

## Context

Decision 0002 fixed the launch heads as logistic regression on the frozen embedding vector alone (overview plus pooled passages, [1536]). Citation outcomes are also predicted by cheap metadata the paper card already holds: author count, primary and cross-listed categories, abstract and title length, day of week of first availability, presence of a code link, and the version count at seal. These are known predictors in the bibliometric literature and are available at seal time with no leakage. The heads are the agents' prior and the baseline the agents are measured against; a weaker head than necessary weakens both.

## Decision

Two constants replace the one embedding width. `EMBEDDING_FEATURE_DIMENSION` (1536) stays the width of `CombinedFeatureRecord.combined_vector`: embedding-only, unit-L2, `overview_passage_sqrt2_v1`, built exactly as before by `models/embedding.py` and `models/batch.py`. `HEAD_INPUT_DIMENSION` (1553) is the width of `TrainingArrays.features` and of the fitted head: the embedding block followed by a fixed, declared metadata block of width 17, appended by `learning/fit.py` and every other consumer of a fitted head's input.

The metadata block's closed order (Appendix B, source basis): author count (log1p), the count of listed categories, a one-hot of the primary category set, abstract token count (log1p), title token count, a one-hot of the first-availability weekday, whether the abstract or comments name a code repository (a fixed, versioned rule over github.com, gitlab.com, huggingface.co and codeberg.org), and the version count at seal. The list is closed; adding a feature is an amendment. Every feature is available at seal time from the paper card and nothing else; a card missing one refuses the row rather than substituting a zero or falling back to the embedding alone.

The embedding block's unit-L2 invariant applies to its own [1536] prefix only. The metadata block is standardized per target and category from the fitting partition's mean and standard deviation (`learning/features.py#fit_standardization`), stored on the head bundle (`FitResult.standardization`) and applied identically at fitting, calibration, promotion and inference through the one function every consumer calls, `apply_head_input`. A bundle without a stored standardization is refused. One-hot and flag columns keep the fixed identity transform (mean 0, standard deviation 1) rather than a fitted one.

The fields originate end to end, not just at the contract layer: `ingest/arxiv.py#ArxivListing` parses the `<authors>` list and exposes `author_count`; `contracts/papers.py#PaperVersionRecord` gains `author_count`, `categories` (ordered, primary first) and `version_count` from the arXiv listing record as of the row's t0; `contracts/cards.py#CardBuildInput` and `PaperCardBody` carry those three through to the card alongside `title_tokens`, `abstract_tokens` and `code_link` (declared, caller-resolved, the same pattern as the existing `card_token_count`) and a `first_available_weekday` `reader/cards.py#assemble_card` derives from `first_public_at`, a pure calendar computation. `learning/features.py#card_metadata` builds the closed `CardMetadata` record a card supplies; `assemble_metadata_block` builds the block itself. `learning/corpus.py#CorpusRow` carries the same three ingest-sourced fields, null exactly when no paper resolved for the row, so a historical family's release row is not missing what a live card would have.

The #25 preregistration compares embedding-only against embedding plus metadata on the same splits; this decision does not settle that comparison, only that the metadata-widened head is the one release 1 fits and the embedding-only head remains its comparison arm.

## Consequences

`TrainingArrays.features`, `LinearHead.weights` and `ModelBundle.dimension` are 1553 wide, not 1536; `CombinedFeatureRecord.combined_vector` is unchanged at 1536. Fitting, calibration and promotion all route through `apply_head_input` and therefore through the stored standardization; a bundle fit before this decision has no standardization and is refused rather than silently reinterpreted. `learning/arrays.py#materialize_training_arrays` takes a `read_metadata` reader beside `read_feature` and checks the metadata tail against the row's card the same way it already checked the embedding prefix. Card assembly gains six declared inputs and one derived field; nothing yet in the application wires a production card-building or fitting pipeline end to end, so `read_metadata`, `card_metadata` and the ingest fields are exercised directly by tests, the same state the equivalent embedding-assembly and label-reader interfaces were already in.

Clarification (#375). The category one-hot is over the admitted category, not the recorded primary. The release admits cross-listed families, which keep their own primary (a `cs.CV` paper cross-listed into `cs.LG`), and arXiv's `q-bio` is an archive whose primaries are `q-bio.NC`, `q-bio.QM` and so on, so the literal first category is often outside `PRIMARY_CATEGORY_IDS`. `contracts/learning.py#admitted_category` names the first of a row's ordered categories in the registry, reading any `q-bio.*` as `q-bio`; `CardMetadata` keeps the recorded categories unchanged and refuses only a row with none admitted, and the one-hot, the per-category calibration and the category/month coverage slices all key on the admitted category. The block stays 17 wide. The alternative, a fifth `other` bucket for any primary outside the four, widens the pinned head input and is a contract change left to the owner.

What is deliberately left open: whether the metadata block improves over embedding-only, which is the #25 comparison's question, not this decision's; and FT-11's per-category calibration split, which stays with #67 and is not widened by this change.
