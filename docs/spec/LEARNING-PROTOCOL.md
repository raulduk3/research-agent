# Historical learning protocol

Version: evidence-v1. Decision: #64. Required by SDD EN-12, EN-13 and FT-18 to FT-25. This document fixes the target semantics and corpus release procedure; it does not assert that data or models have passed qualification. Changes to semantics create a new version. Numerical gates below are initial operating policy, not empirical estimates or power guarantees.

## Target registry

| Target id | Binary event in the first 365 elapsed days | Role |
| --- | --- | --- |
| substantive_use_365d | At least one external downstream scholarly work explicitly uses an identifiable contribution of the target work in developing its own contribution | Primary forecast, digest ordering and fitness |
| substantive_evaluation_365d | At least one external downstream scholarly work explicitly evaluates an identifiable contribution using stated evidence or a substantive chain of reasoning | Separate diagnostic forecast |

These are project-specific operational labels grounded in citation-function analysis. They are not standardized universal measures of scientific value. A citation alone, an endorsement, publication prestige, a repository, downloads, stars and model confidence satisfy neither event. A relationship can satisfy both events. One qualifying work establishes existence; repeated passages, versions and multiple indexes never create multiple events. Successful use does not establish correctness. Evaluation can corroborate, challenge, delimit or yield mixed/inconclusive findings; none of those directions is rewarded over another.

The contribution object is separately annotated as finding, theory/proposition, argument/concept, synthesis/framework, method/procedure, dataset/material, or software/instrument. Multiple objects can apply. Unknown object identity prevents a positive verdict. This avoids defining every paper as a software or empirical-method paper. Merely listing a study in a review is background; using its result in a new synthesis is substantive use. A theorem explicitly used in a proof, a conceptual framework used to structure an analysis and a historical finding used to support a new argument can qualify. An explicit counterexample or documented source-based challenge can qualify as evaluation. Praise and unsupported disagreement cannot.

External means no overlapping authors after identity reconciliation; it does not mean independent institutions, social networks, funding or laboratories. Known overlap disqualifies that downstream work. Unresolved potential overlap makes that edge unknown. Name strings alone do not prove independence. The reviewer records identifiers or documented identity reconciliation.

The eligible downstream object is a scholarly work with a retrievable dated version and attributable passages, not a social post. Every target remains a claim about documented events within the named sources and observation process. Undocumented industrial use and unindexed scholarship remain outside observation. A first-year negative is not permanent lack of value or evidence against delayed recognition.

## Time and evidence

The target paper's earliest verified public version supplies first_public_at, not its journal acceptance date, later arXiv revision or ingestion date. Known preprints are reconciled with journal versions. The event interval is open at that instant and closed at first_public_at plus 365 times 86400 seconds. A later work's earliest preserved version actually containing the qualifying passage supplies event time; an older paper date cannot backdate a passage added by revision. If the only available timestamp is a date, use a UTC day interval. A possible interval straddling the event boundary is unknown.

Prospective collection closes 90 elapsed days after the event interval ends. Both positive and negative labels enter the binary training cohort only after this grace period, avoiding earlier admission of positives. At the collection deadline, resolve reviewed positives and fully observed negatives; all remaining cases are unknown. Later corrections append new label versions and update identified reports without erasing the original cutoff result. Missing review never becomes a negative.

Historical acquisition performed today records today's actual capture and review times. It cannot establish what an index returned at an old deadline without a preserved snapshot. Mark such evidence historical_reconstructed; report acquisition lag and indexing limitations separately from prospective records. The target event definition and review rubric remain identical, but historical collection availability is not claimed identical. Reconstructed labels can train a deployment model and support a disclosed retrospective benchmark; they cannot establish leakage-free historical deployment performance or prospective agent fitness.

## Sources and artifact contract

1. Obtain the complete eligible arXiv identifier population independently of citations and outcomes. Preserve cross-list deduplication and first-version metadata. Obtain authorized original source/PDF bytes and title/abstract; record unavailable versions rather than using the newest document.
2. Discover candidate citing works through the union of OpenAlex and Semantic Scholar records, with complete pagination, query/version metadata, capture times and source errors. Index overlap is not independent confirmation. A source not indexing the target is a coverage gap, not an empty complete search.
3. Reconcile work identities using arXiv identifiers and DOIs plus reviewed ambiguous matches. Group journal/preprint revisions into paper families. Candidate citing works can be outside launch categories; they supply outcome evidence rather than new live recommendation candidates.
4. Retrieve licensed dated full text through arXiv, publisher/repository locations, or permitted scholarly full-text datasets such as S2ORC. Indexes discover evidence; publisher version metadata and preserved passages establish it. Full-text availability and redistribution permission are separate fields. No source purchase or redistribution is implied.
5. Locate every citation context and inspect surrounding sections when a short passage is ambiguous. Preserve document hash, exact page/section or text offsets and provided passage ids. Extraction never fabricates quotations. OCR remains outside launch scope; unreadable scans are missing evidence.

Raw acquisition, extracted text, reference matching, annotation proposals, human reviews, labels, embeddings and model bundles are distinct immutable artifacts. Each has a schema version, content hash, producing configuration and actual timestamp. Source licenses and retention terms are release metadata. Credential headers are never retained as evidence.

Minimum records:

| Record | Required fields |
| --- | --- |
| Paper version | canonical paper id, family id, version id, original bytes hash, first-public time/uncertainty, version time, capture time, source and license |
| Evidence edge | target id, downstream family/version, citation linkage, contribution object, numbered passages and offsets, event-time interval, author relation and provenance |
| Review | rubric version, reviewer id, independent verdict per relationship, evidence ids, reason, review time, adjudication and superseded record |
| Label | paper id, target version, true/false/unknown, unknown reason, evidence and completion-manifest ids, maturity time, label-available time, historical/prospective acquisition kind |
| Embedding | paper version, input hash, model/tokenizer/package revisions, preprocessing id, dimension, dtype, normalization, computed_at and vector hash |
| Corpus release | eligible population, selection seed, inclusion/exclusion ids, all labels, family grouping, split ids, source watermarks, qualification report and artifact hashes |
| Model bundle | target order, representation manifest, fitted weights, calibrator, training cutoff, corpus/split hashes, evaluation disposition and per-target availability |

## Annotation and negative labels

Jev evidence annotation is a separate job from original-paper content assessment. It reads target-contribution context and numbered downstream passages. Separate categorical questions record relationship (use, evaluation, background-only or uncertain, allowing use and evaluation simultaneously), contribution object and evaluation direction. Freeze rubric, complete class distributions and provider identity. Do not turn a probability threshold into ground truth. Reviewers establishing reference labels see original evidence without the Jev answer, forecast, reputation or popularity fields.

Two reviewers independently label evidence. Their agreement establishes the initial verdict; disagreements require recorded joint adjudication, and unresolved disputes stay unknown. Positive evidence links a specific contribution, qualifying relationship, external work and dated passage. A reviewer can request more context. The same rule governs eventual live settlement. Jev unavailability leaves manual review possible; no automatic fallback judge is introduced.

For each target, one verified qualifying edge establishes true once mature. False requires both discovery adapters to complete and every returned potentially eligible edge to be ruled out or reviewed with usable dated evidence. Edges proved outside the window or sharing authors do not require semantic review. Unknown dates, inaccessible text, unresolved identity, incomplete pagination and exhausted review budgets block false when they could hide a qualifying event. A complete search with no candidate works is false under the observation protocol. Record the residual possibility of undiscovered use; do not describe these negatives as exhaustive real-world truth.

No automated relevance filter discards candidate edges before establishing a negative. Jev can prioritize the review queue but cannot make an unreviewed edge disappear. Diagnostic citation-intent data is a retrieval aid, not proof. Positive enrichment is allowed only in rubric-development/challenge sets and never in representative prevalence, calibration or final evaluation estimates.

## Corpus stages and qualification

Initial feasibility sample: 300 launch-domain target papers whose event window and grace period have elapsed, drawn uniformly across the most recent 24 complete eligible publication months, seed 20260920. Allocate 12 papers per month and the remaining 12 to the earliest months; if a month lacks eligible papers, preserve the shortfall rather than silently change the sample. Select by sorted hash of seed and canonical id within month. Preserve every drawn paper, including failed acquisitions, in the coverage denominator.

Within each month, take the first two sampled papers for rubric development, plus the third sampled paper in each of the earliest twelve months. This gives 60 development papers; the remaining 240 are locked label qualification papers. Freeze the rubric before annotating qualification. The pilot is a feasibility workload, not enough by definition to train qualified heads. Before increasing workload, report elapsed review minutes, bytes, source requests, per-paper citation-edge counts, token usage, estimated next-stage cost and unknown causes. Stop each pilot after 300 target papers or 5,000 candidate evidence edges, whichever limit is reached. Unfinished target papers are unknown. Paid calls require a separately authorized budget. Report how the edge cap biases coverage by citation volume.

Qualification requires at least 70% known labels over the locked representative sample, at least 50% known labels in each adequately sampled contribution-type stratum, and at least 20 reviewed positives and 20 negatives per target. A stratum needs 30 target papers to be reported as adequately sampled; other strata are explicitly unqualified, not pooled into a passing claim. Require pre-adjudication Cohen's kappa at least 0.60 for each binary relationship, plus positive and negative agreement each at least 0.80. Report uncertainty intervals and disagreements; these floors do not prove annotation truth. A failed target remains unqualified; a rubric revision requires a new held-out qualification sample.

The Jev annotation study reports its confusion matrix, per-class precision/recall, multiclass Brier score, abstentions and coverage against the independent human verdicts. Jev quality affects annotation efficiency, not the authority of labels. No minimum confidence bypasses human adjudication.

For cross-disciplinary semantics, maintain a separate challenge set of 90 licensed evidence cases: 30 mathematical/theoretical, 30 empirical natural/life-science and 30 qualitative/conceptual or synthesis cases, including use, evaluation and background examples. Two subject-competent reviewers annotate them. This checks rubric applicability only; it is neither a prevalence sample nor a cross-domain forecasting benchmark. A missing competent reviewer or failed relationship agreement leaves that domain unqualified. Launch-domain data alone never authorizes all-domain forecast claims. Adding a live domain requires a representative domain corpus and the same coverage, calibration and forecasting gates.

After a passing feasibility result, expand by publication-month blocks to 2,000 then 5,000 candidate target papers, stopping at either size if partition gates and prediction qualification pass. Beyond 5,000, create a cost/learning-curve finding before changing the workload cap. Do not change inclusion based on outcome success. Use cached evidence and annotation versions across releases. Effective known labels per head, class counts, periods and coverage determine feasibility, not the raw download total.

## Representation and fitting

The frozen embedder is selected and pinned under MD-06 and #25; no unverified model alias is an executable artifact identity. Its manifest fixes the vector dimension, tokenizer, dense pooling, weights hash, supported length and numerical precision. A missing qualified manifest blocks embedding production, not data collection. Head implementation accepts the declared dimension and fails on a mismatch.

The overview input is original-version title, one newline, and original abstract, UTF-8 NFC, with line breaks normalized to LF. An empty abstract or input exceeding the selected model's token limit is unavailable; do not silently truncate. Encode the overview and original full-text passages using RETRIEVAL-PROTOCOL.md. Concatenate the normalized overview and overlap-weighted normalized passage pool, divided by sqrt(2), to obtain one float32 vector of shape [2d]. Reject missing complete original-text coverage, zero/nonfinite vectors or incompatible representations. Exclude separately supplied author metadata, citation counts, downstream evidence and Jev fields. Author or result cues embedded in the original text are not claimed to be removed. Fitting and inference share exactly this construction. Record retrieval availability separately: partial text can be retrieved even when head features are unavailable.

Freeze the eligible population and group related versions before splitting. Order complete ISO publication weeks by first_public_at. Assign oldest 60% of weeks to fitting, next 15% to development, next 10% to calibration and final 15% to locked evaluation, rounding the first three counts down. Require at least 40 distinct weeks overall, at least four in each partition, and retain whole weeks. Families crossing boundaries go to their earliest partition; later copies supply no new rows. Record the exact week boundaries and family resolution before examining labels.

For every target require fitting >=100 positives and >=100 negatives; development >=25 of each; calibration >=25 of each; locked evaluation >=50 of each. These are operating floors, not statistical sufficiency claims. All labels used by a fit exist by its recorded cutoff. A true historical backtest additionally refits at each simulated cutoff with only labels actually available then; absent old availability records prevent that claim. The initial retrospective benchmark does not pretend a contemporary embedder existed before its release.

Fit one binary logistic regression per target using mean binary cross-entropy plus lambda/2 times squared L2 weight norm; intercept is unpenalized. Search lambda in {0.0001, 0.001, 0.01, 0.1, 1}, choose lowest development Brier score, breaking ties toward larger lambda. Use deterministic L-BFGS, zero initialization, gradient infinity-norm stopping tolerance 0.000001 and maximum 2,000 iterations. Nonconvergence fails that candidate. Record solver/library revision and actual objective convention rather than confusing inverse regularization C with lambda. No class rebalancing, oversampling or synthetic negatives; unknown labels are masked per target. Freeze the chosen head without refitting on development or calibration.

Fit sigmoid calibration on raw logits using calibration data only: p = sigmoid(a*z+b), with a constrained nonnegative and a 0.000001 L2 penalty on a,b; use bound-constrained L-BFGS-B with the same tolerance and iteration limit. Record the exact implementation and parameters. Final output is two named scalar probabilities with independent availability, not a softmax; use and evaluation are not mutually exclusive. One input has shape [2d], a batch [N,2d], known labels and masks [N,2].

## Validation, promotion and retraining

The baseline probability is the fitting-partition positive fraction for that target, fixed before evaluating later partitions. Initial head qualification requires calibration and locked-evaluation Brier scores below that baseline; on locked evaluation require the upper bound of a paired 95% bootstrap interval for head-minus-baseline Brier loss to be below zero. Use 2,000 resamples of whole publication weeks, seed 20260920, with paper families inseparable. Report average precision, fixed ten-bin reliability with counts, coverage and contribution-type slices. Sparse slices are unqualified; do not hide them in a global metric. Qualification can fail even with many papers.

Consume a locked release evaluation set once. Model changes after inspecting it require a fresh chronological holdout; previous evaluation data is thereafter labeled development history. Preserve all attempts and comparisons. Repeated weekly checks on an already-seen monitoring set are development monitoring, not new independent evidence. Weekly promotion uses the frozen family and lambda choice, a chronological recalibration partition, baseline improvement and no higher Brier loss than the incumbent on the same monitoring support. Corpus/annotation version changes and changed model selection require fresh release qualification. If the manifest has not changed, skip refitting. If class-count gates fail, retain the prior compatible model.

Before each live batch, pin the entire bundle and compute probabilities only from snapshot-eligible vectors. Store prediction time, target, horizon and bundle identity before later evidence is observed. Prospective evaluation uses those persisted predictions, never probabilities recomputed after the event. Report coverage-conditioned performance and unknown-outcome rates; complete-case metrics do not remove missingness bias. No head probability acts as an admission filter for agent retrieval.

Weekly refitting uses mature labels available at the freeze and retained eligible historical data. Head updates do not train the embedder, Jev or agent model. Label corrections create new immutable releases and invalidate affected reports. Changing embedding models rebuilds embeddings and heads in a separate namespace before atomic promotion. Old snapshots retain old vectors and probabilities. Missing or invalid qualified models are explicit unavailable states.

## Readiness and build order

1. Build identities, artifact capture, source manifests and resumable acquisition. Begin prospective observation capture immediately after those engineering checks pass.
2. Build the review interface and label resolver against preserved real cases. Run the bounded feasibility and cross-disciplinary rubric studies.
3. Build corpus releases, splits and frozen embeddings; train one use head end to end. Add the second head through the same implementation only when its own gates pass.
4. Integrate qualified probabilities and separate original-paper Jev assessments with cards and sealed agent forecasts. Demonstrate unavailable states and retry recovery.
5. Run scoring, digest and rating integration; retain population configurations until genuinely prospective fitness matures. A historical corpus supplies head supervision, not historical performance for new agents.

Collection and engineering integration can proceed before a head qualifies. Qualified forecasting requires the use-head gate. Mature benefit claims require actual future observations. The full-system TDD, provider qualification and operational readiness remain separately tracked in #56; this protocol alone does not claim to close them.

## Research basis and limits

- [SciCite, Cohan et al. 2019](https://aclanthology.org/N19-1361/) establishes citation-intent classification as a research task; its existing categories are not the target labels adopted here.
- [SOFT, 2026 preprint](https://arxiv.org/abs/2601.05103) motivates separating citation intent from the object cited. Its reported results do not validate this project's rubric.
- [DORA indicator guidance](https://sfdora.org/wp-content/uploads/2024/05/DORA_indicators_guidance.pdf) discusses limitations of research indicators and the importance of their interpretation. It does not endorse these operational targets.
- [S2ORC](https://github.com/allenai/s2orc) provides scholarly full-text resources through Semantic Scholar datasets; access, licenses, dated versions and coverage still require qualification.
- [Probability calibration](https://scikit-learn.org/stable/modules/calibration.html) describes separate calibration data and probability assessment. The split percentages and gates above are project policy.

No accessible dataset is asserted to contain all required labels. No Jev benchmark is asserted to prove these labels. The corpus and qualification work are mandatory precisely because those claims remain unmeasured.
