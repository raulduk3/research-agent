"""One fictional dataset shared by every mock page. Dates 2026-09-24 to 2026-10-04.

Ids are derived from labels so every page shows the same value for the same thing.
Nothing here names a person, a tool, a session or a model other than the pinned ones.
"""
import hashlib
import random

HEAD = "30109ad5b96c8b1aa3ad560cc940159d7a9ffcc9"


def h(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def u(label: str) -> str:
    """Deterministic canonical UUIDv4 string from a label."""
    r = random.Random(label)
    b = bytearray(r.getrandbits(8) for _ in range(16))
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    x = b.hex()
    return f"{x[:8]}-{x[8:12]}-{x[12:16]}-{x[16:20]}-{x[20:]}"


def short(x: str, n: int = 12) -> str:
    return x[:n] + "…"


# ---------------------------------------------------------------- profile, registry
PROFILE = h("launch-profile-v2")
TARGET_REGISTRY = h("target-registry-automatic-citations-v1")
TARGETS = [
    ("citation_reach_365d", "Will at least five papers cite this one within a year?"),
    ("late_citation_activity_365d", "Will indexed citations continue in both final parts of the first year?"),
    ("cross_subfield_reach_365d", "Will it receive indexed citations from at least two other research subfields in its first year?"),
]
TARGET_VERSION = {t: h("target-definition-" + t) for t, _ in TARGETS}
REGISTRATION = h("preregistration-island-selection-2026-09-24")
REGISTRATION_AT = "2026-09-24T18:00:00.000000Z"

# ---------------------------------------------------------------- islands and genomes
ISLANDS = ["cs", "quant_ph", "q_bio"]
ISLAND_LABEL = {"cs": "cs", "quant_ph": "quant-ph", "q_bio": "q-bio"}
EMPHASES = ["evidence_first", "methods_assumptions", "earlier_work", "limitations"]

GENOMES = []
for isl in ISLANDS:
    for emp in EMPHASES:
        GENOMES.append({
            "island": isl,
            "emphasis": emp,
            "founder": emp == "evidence_first",
            "hash": h(f"genome-{isl}-{emp}-seed-v2"),
        })
G = {(g["island"], g["emphasis"]): g for g in GENOMES}
CS_F = G[("cs", "evidence_first")]

# runs over the last 7 daily batches, 2026-09-25 .. 2026-10-01 (today's counted as issued); per agent per day: cs 18, quant_ph 6, q_bio 7
# (issued, finished, forecasts made)
SHARDS = {"cs": 18, "quant_ph": 6, "q_bio": 7}
RUNS = {
    ("cs", "evidence_first"): (126, 124, 7190),
    ("cs", "methods_assumptions"): (126, 124, 7194),
    ("cs", "earlier_work"): (126, 125, 7251),
    ("cs", "limitations"): (126, 124, 7192),
    ("quant_ph", "evidence_first"): (42, 41, 2325),
    ("quant_ph", "methods_assumptions"): (42, 40, 2268),
    ("quant_ph", "earlier_work"): (42, 41, 2325),
    ("quant_ph", "limitations"): (42, 40, 2268),
    ("q_bio", "evidence_first"): (49, 48, 2750),
    ("q_bio", "methods_assumptions"): (49, 47, 2693),
    ("q_bio", "earlier_work"): (49, 48, 2750),
    ("q_bio", "limitations"): (49, 47, 2694),
}
COST_USD = {  # measured mean settled agent_inference cost per run, USD
    ("cs", "evidence_first"): 0.0181, ("cs", "methods_assumptions"): 0.0194,
    ("cs", "earlier_work"): 0.0176, ("cs", "limitations"): 0.0203,
    ("quant_ph", "evidence_first"): 0.0172, ("quant_ph", "methods_assumptions"): 0.0188,
    ("quant_ph", "earlier_work"): 0.0169, ("quant_ph", "limitations"): 0.0197,
    ("q_bio", "evidence_first"): 0.0178, ("q_bio", "methods_assumptions"): 0.0191,
    ("q_bio", "earlier_work"): 0.0174, ("q_bio", "limitations"): 0.0199,
}
# preference credit (summed IN-43 credit over ISO week 2026-W40) and credited-entry count. Each rated population entry
# credits exactly +1 or −1 in total, so an island's column sums to a whole number: cs +7, quant-ph +2.
# The cs rater's week so far (2026-09-28 to 2026-10-01): 28 calls; the signed ones that landed on agents' picks net +7,
# the rest landed on random controls or service picks and credited nobody (IN-43). Like rate as report.html: 0.61 vs 0.29.
WEEK_CALLS = {"like": 14, "dislike": 5, "skip": 9}
WEEK_DAYS = [("2026-09-28", 8), ("2026-09-29", 8), ("2026-09-30", 9), ("2026-10-01", 3)]
LIKE_RATE = {"cs": (0.61, 0.29, "+0.32", "−0.04 to +0.58")}
WEEK_FORECASTS = 4  # sealed human forecasts this week, as the report's You-and-the-agents table
CREDIT = {
    ("cs", "evidence_first"): ("+3.10", 9), ("cs", "methods_assumptions"): ("+2.45", 7),
    ("cs", "earlier_work"): ("−0.40", 6), ("cs", "limitations"): ("+1.85", 8),
    ("quant_ph", "evidence_first"): ("+0.96", 6), ("quant_ph", "methods_assumptions"): ("+0.41", 5),
    ("quant_ph", "earlier_work"): ("+0.58", 5), ("quant_ph", "limitations"): ("+0.05", 4),
    ("q_bio", "evidence_first"): ("0", 0), ("q_bio", "methods_assumptions"): ("0", 0),
    ("q_bio", "earlier_work"): ("0", 0), ("q_bio", "limitations"): ("0", 0),
}
HEADS_AGREEMENT = {
    ("cs", "evidence_first"): "0.74", ("cs", "methods_assumptions"): "0.69",
    ("cs", "earlier_work"): "0.71", ("cs", "limitations"): "0.66",
    ("quant_ph", "evidence_first"): "0.70", ("quant_ph", "methods_assumptions"): "0.65",
    ("quant_ph", "earlier_work"): "0.72", ("quant_ph", "limitations"): "0.63",
    ("q_bio", "evidence_first"): "0.68", ("q_bio", "methods_assumptions"): "0.71",
    ("q_bio", "earlier_work"): "0.64", ("q_bio", "limitations"): "0.67",
}
NONOVERLAP = {  # IN-04 pick-set non-overlap, week 2026-W40 so far (through Thursday's batch), cs island: (1 - overlap, nominations, shared)
    "evidence_first": ("0.990", 504, 5), "methods_assumptions": ("0.994", 498, 3),
    "earlier_work": ("0.988", 502, 6), "limitations": ("0.994", 495, 3),
}
OWNER_ID = u("operator-id")
ADMITTED_AT = "2026-09-24T09:00:00.000000Z"
MATURITY_FIRST = "2027-12-24"  # first study batch 2026-09-25 + 365 + 90 days

# ---------------------------------------------------------------- papers
# (key, arxiv id, title, abstract, publication date, first public instant)
PAPERS = [
    ("P1", "2609.24817", "Sparse routing for long-context retrieval under a fixed token budget",
     "We route passages through a learned sparsity mask and cut resent tokens by 63% at equal recall on three long-document benchmarks. The mask is trained once per corpus and needs no query-time tuning.",
     "2026-09-30", "2026-09-30T15:40:12.000000Z"),
    ("P2", "2609.24390", "Calibrated citation forecasting from full-text embeddings",
     "Regularized logistic heads over pooled passage vectors reach a Brier skill of 0.18 against a base-rate baseline at one year, with calibration that holds across three arXiv categories.",
     "2026-09-30", "2026-09-30T16:02:55.000000Z"),
    ("P3", "2609.25102", "A negative result on synthetic pretraining for tabular foundation models",
     "Across 41 public tabular datasets, synthetic pretraining does not beat a tuned gradient-boosted baseline. We release the tuning budget and every failed configuration.",
     "2026-09-30", "2026-09-30T21:11:08.000000Z"),
    ("P4", "2609.23958", "Do judge models agree with citation outcomes? A preregistered replication",
     "Judge scores explain 4% of the variance in one-year citation counts after controlling for author counts. The preregistration and the deviations from it are reported in full.",
     "2026-09-29", "2026-09-29T19:30:41.000000Z"),
    ("P5", "2609.24655", "Island-model evolution of reading policies for scientific triage",
     "Migration between domain islands transfers reading strategies with measurable gains in the receiving domain, at the cost of a slower approach to each island's own optimum.",
     "2026-09-30", "2026-09-30T17:48:19.000000Z"),
    ("P6", "2609.23711", "Reproducibility of reported ablations in 2025 machine-learning submissions",
     "Of 120 sampled ablations, 71 reproduce within the reported variance. Missing seeds explain most failures; missing hyperparameters explain most of the rest.",
     "2026-09-29", "2026-09-29T18:05:30.000000Z"),
    ("P7", "2609.25040", "Hash-chained ledgers for forward-only evaluation of forecasting agents",
     "A protocol for sealing predictions before outcomes exist, with deterministic resolvers, anchored chain heads and a replay procedure that consumes recorded model replies.",
     "2026-09-30", "2026-09-30T20:27:03.000000Z"),
    ("P8", "2609.24221", "Vision-language agents read figures: a 50-question audit",
     "Rendered page images recover 82% of figure-grounded answers without optical character recognition. Errors concentrate in multi-panel figures with shared axes.",
     "2026-09-30", "2026-09-30T15:12:47.000000Z"),
    ("P9", "2609.23877", "Prefix caching makes agent loops cheaper: a cost study",
     "Append-only conversations with cached prefixes reduce per-run cost by a factor of eight on a hosted mixture-of-experts model, measured over 2,000 tool-using runs.",
     "2026-09-29", "2026-09-29T22:40:16.000000Z"),
    ("P10", "2609.24980", "Rater preference is not impact: a one-year comparison",
     "Blind human ratings of surfaced papers correlate 0.21 with one-year citation reach. Preference tracks readability and topic familiarity more than it tracks later citation.",
     "2026-09-30", "2026-09-30T19:55:38.000000Z"),
    ("P11", "2609.24533", "Token budgets as a genome field",
     "Letting selection mutate the reading budget yields agents that read 40% less at equal forecast skill, and agents that read nothing when cost enters the objective.",
     "2026-09-30", "2026-09-30T17:03:22.000000Z"),
    ("P12", "2609.23604", "Curriculum effects in masked-word pretraining on arXiv",
     "Ordering pretraining by submission date changes downstream retrieval quality by under 1%. The effect is within the variance across seeds.",
     "2026-09-29", "2026-09-29T17:31:09.000000Z"),
]
P = {}
for key, arx, title, abstract, pub, first in PAPERS:
    P[key] = {"key": key, "arxiv": arx, "title": title, "abstract": abstract, "pub": pub,
              "first_public": first, "id": u("paper-family-" + arx),
              "link": f"https://arxiv.org/abs/{arx}"}

# ratings recorded by the cs rater on 2026-10-01 (like, dislike, skip unlock details)
RATINGS = {
    "P1": ("like", "2026-10-01T08:12:40.000000Z"),
    "P3": ("skip", "2026-10-01T08:14:03.000000Z"),
    "P6": ("dislike", "2026-10-01T08:15:21.000000Z"),
}
# blind display order after the recorded shuffle (positions 0..11)
DIGEST_ORDER = ["P4", "P1", "P9", "P6", "P11", "P2", "P12", "P7", "P3", "P10", "P5", "P8"]
DIGEST_VIEW_ID = u("digest-view-cs-2026-10-01")
DIGEST_ID = h("digest-manifest-cs-2026-10-01")
PUBLICATION_DAY = "2026-10-01"
ENTRY_VIEW = {k: u("entry-view-" + k) for k in P}
RATING_ID = {k: u("rating-" + k) for k in RATINGS}

# the human question sheet: three citation_reach_365d questions of the batch, batch-hash sampled
SHEET = [
    {"key": "Q1", "arxiv": "2609.24102", "title": "Contrastive pretraining for spectral graph coarsening",
     "first_public": "2026-10-01T02:47:12.000000Z", "deadline": "2026-10-02T02:47:12.000000Z",
     "state": "open", "probability": None, "answered_at": None},
    {"key": "Q2", "arxiv": "2609.23790", "title": "Adaptive step sizes for stochastic bilevel optimization",
     "first_public": "2026-09-30T06:48:31.000000Z", "deadline": "2026-10-01T06:48:31.000000Z",
     "state": "answered", "probability": "0.30", "answered_at": "2026-10-01T05:52:17.000000Z"},
    {"key": "Q3", "arxiv": "2609.23655", "title": "Sample-efficient identification of switched linear systems",
     "first_public": "2026-09-30T02:15:44.000000Z", "deadline": "2026-10-01T02:15:44.000000Z",
     "state": "expired", "probability": None, "answered_at": None},
]
for q in SHEET:
    q["id"] = u("paper-family-" + q["arxiv"])
    q["view_id"] = u("question-view-" + q["key"])
    q["link"] = f"https://arxiv.org/abs/{q['arxiv']}"
SHEET_FORECAST_ID = u("human-forecast-Q2")

# ---------------------------------------------------------------- batch, snapshot, run
BATCH_ID = h("daily-batch-2026-10-01")
SNAPSHOT_ID = h("snapshot-2026-10-01")
RUN_ID = u("run-cs-founder-shard7-2026-10-01")
SLOT_ID = h("slot-" + BATCH_ID + "-cs-7-" + CS_F["hash"] + "-population-0")
SUBMISSION_ID = u("submission-" + RUN_ID)
SPEC_SEED = 13970426384012208517
REQUEST_SEED = 2914407731
MODEL_MANIFEST = h("agent-model-manifest-glm-5.3-flash-zai")
SUMMARIZER_PROMPT_HASH = h("summarizer-prompt-v1")
SUMMARIZER_MODEL_IDENTITY = "glm-5.3-flash"
RUN_STARTED = "2026-10-01T03:29:44.000000Z"
RUN_ENDED = "2026-10-01T03:41:07.000000Z"
RUN_DEADLINE = "2026-10-01T15:12:47.000000Z"  # earliest question seal deadline in the shard (P8)

# shard 7: 20 papers of the cs island, sorted by first_public_at then family id
SHARD_EXTRA = [
    ("2609.24188", "Gradient-free adapters for retrieval re-ranking", "2026-09-30T15:03:10.000000Z"),
    ("2609.24240", "Sparse mixture routing with learned capacity", "2026-09-30T15:20:33.000000Z"),
    ("2609.24301", "Benchmarking uncertainty heads on tabular shift", "2026-09-30T15:31:02.000000Z"),
    ("2609.24350", "A unified view of citation-graph baselines", "2026-09-30T15:44:58.000000Z"),
    ("2609.24361", "Deterministic replay for tool-using language agents", "2026-09-30T15:49:20.000000Z"),
    ("2609.24377", "Bounded rationales improve human audit of forecasts", "2026-09-30T15:52:07.000000Z"),
    ("2609.24412", "Passage pooling weights under overlapping chunks", "2026-09-30T16:09:45.000000Z"),
    ("2609.24433", "Cheap negatives for dense retrieval on preprints", "2026-09-30T16:14:11.000000Z"),
    ("2609.24459", "Failure modes of self-consistency decoding at scale", "2026-09-30T16:20:38.000000Z"),
    ("2609.24486", "Curriculum sharding for streaming corpora", "2026-09-30T16:27:59.000000Z"),
    ("2609.24510", "Reference-centroid distance as a descriptive signal", "2026-09-30T16:35:14.000000Z"),
    ("2609.24548", "Estimating first-year reach from early neighbors", "2026-09-30T16:41:50.000000Z"),
    ("2609.24577", "Tool-call schemas that refuse coercion", "2026-09-30T16:50:29.000000Z"),
    ("2609.24601", "A seeded control protocol for private digests", "2026-09-30T16:58:03.000000Z"),
    ("2609.24629", "Weekly refits with mature labels only", "2026-09-30T17:01:40.000000Z"),
    ("2609.24640", "Per-token inference under a fixed monthly cap", "2026-09-30T17:02:55.000000Z"),
]
SHARD = [
    dict(arxiv=P["P8"]["arxiv"], title=P["P8"]["title"], first_public=P["P8"]["first_public"], id=P["P8"]["id"], key="P8"),
    dict(arxiv=P["P1"]["arxiv"], title=P["P1"]["title"], first_public=P["P1"]["first_public"], id=P["P1"]["id"], key="P1"),
]
for arx, title, fp in SHARD_EXTRA:
    SHARD.append(dict(arxiv=arx, title=title, first_public=fp, id=u("paper-family-" + arx), key=arx))
SHARD.append(dict(arxiv=P["P2"]["arxiv"], title=P["P2"]["title"], first_public=P["P2"]["first_public"], id=P["P2"]["id"], key="P2"))
SHARD.append(dict(arxiv=P["P5"]["arxiv"], title=P["P5"]["title"], first_public=P["P5"]["first_public"], id=P["P5"]["id"], key="P5"))
SHARD.sort(key=lambda s: (s["first_public"], s["id"]))
assert len(SHARD) == 20


def question_id(paper_id: str, target: str) -> str:
    return h("question-" + paper_id + "-" + target + "-" + SNAPSHOT_ID)


# per-paper answers of the founder's run (probabilities for reach, late, cross) and a one-line rationale
FOUNDER_ANSWERS = {
    "2609.24817": ((0.72, 0.55, 0.10), "Table 3 shows the 63% cut at equal recall; code released; the three benchmarks share a source corpus."),
    "2609.24390": ((0.44, 0.31, 0.12), "Skill of 0.18 over base rate is modest; calibration section supports the claim across categories."),
    "2609.24221": ((0.51, 0.34, 0.15), "Fifty questions is small, but the audit method is reusable and the error analysis is specific."),
    "2609.24655": ((0.38, 0.29, 0.21), "Migration gains are shown on two islands only; the slower convergence cost is measured."),
    "2609.24188": ((0.19, 0.12, 0.06), "Adapters match a tuned baseline; no improvement over it is reported."),
    "2609.24240": ((0.27, 0.16, 0.05), "Capacity routing helps at one scale; the ablation at other scales is missing."),
    "2609.24301": ((0.22, 0.14, 0.09), "Benchmark paper with released splits; adoption depends on the shift suite being used."),
    "2609.24350": ((0.15, 0.09, 0.04), "Survey of known baselines with no new measurement."),
    "2609.24361": ((0.41, 0.30, 0.13), "Replay procedure is exact and the recorded-reply protocol is simple enough to adopt."),
    "2609.24377": ((0.33, 0.24, 0.17), "Human audit result on 400 forecasts; the rationale bound is a chosen constant."),
    "2609.24412": ((0.12, 0.08, 0.03), "Weighting derivation is correct but the effect on retrieval is under 1%."),
    "2609.24433": ((0.29, 0.18, 0.06), "Negative sampling recipe is cheap; gains hold on two of three retrieval sets."),
    "2609.24459": ((0.36, 0.27, 0.11), "Failure taxonomy is specific and reproduced at three model sizes."),
    "2609.24486": ((0.17, 0.10, 0.05), "Sharding change affects engineering cost, not quality; narrow audience."),
    "2609.24510": ((0.14, 0.11, 0.08), "Descriptive signal with no downstream evaluation."),
    "2609.24548": ((0.31, 0.22, 0.07), "Neighbor-outcome estimator is close to the base rate on the held-out weeks."),
    "2609.24577": ((0.24, 0.15, 0.09), "Schema refusal is measured on a synthetic suite only."),
    "2609.24601": ((0.20, 0.13, 0.10), "Protocol paper; the seeded draw is well specified but untested against raters."),
    "2609.24629": ((0.18, 0.12, 0.05), "Refit policy is sound; the paper reports no comparison against refitting with immature labels."),
    "2609.24640": ((0.26, 0.19, 0.08), "Cost study with dated quotes; relevance depends on provider pricing staying stable."),
}
FOUNDER_NOMINATIONS = [
    ("2609.24817", "Direct improvement on a metric people track, released code, one clear table."),
    ("2609.24221", "A small but reusable audit; the error analysis on shared axes is useful to anyone rendering pages."),
    ("2609.24361", "Exact replay from recorded replies is what forward-only evaluation needs."),
    ("2609.24390", "The calibration section across categories is the strongest part."),
    ("2609.24459", "Failure taxonomy reproduced at three sizes."),
    ("2609.24655", "Migration result is narrow but measured honestly, including its cost."),
    ("2609.24377", "Human audit on 400 forecasts with a preregistered bound."),
]

# readers shown on the paper page for P1, in the order the per-paper labels were drawn
READERS = [
    {"label": "reader A", "genome": ("cs", "earlier_work"),
     "answers": [(0.58, "Close to an earlier routing paper that reached five citations; this version is cleaner and released code.", 2),
                 (0.31, "Late activity would need adoption by one retrieval framework; nothing in the paper shows uptake yet.", 1),
                 (0.12, "Retrieval subfield only; no cross-subfield audience is addressed.", 1)],
     "turn_count": 12},
    {"label": "reader B", "genome": ("cs", "evidence_first"),
     "answers": [(0.72, "Table 3 shows the 63% cut at equal recall; code released; the three benchmarks share a source corpus.", 3),
                 (0.55, "Cheap method with a direct metric improvement; late activity plausible if adopted by one framework.", 2),
                 (0.10, "Method is specific to long-document retrieval.", 1)],
     "turn_count": 14},
    {"label": "reader C", "genome": ("cs", "limitations"),
     "answers": [(0.49, "Ablation on mask sparsity is convincing; the shared corpus behind the three benchmarks limits generality.", 2),
                 (0.28, "Unsure about uptake outside retrieval; the paper claims no generality it does not test.", 1),
                 (0.06, "No evidence for use outside the subfield.", 1)],
     "turn_count": 11},
    {"label": "reader D", "genome": ("cs", "methods_assumptions"),
     "answers": [(0.65, "Result holds under the stated setup; the equal-recall comparison is fair and the token accounting is explicit.", 2),
                 (0.40, "Assumes a fixed mask per corpus; drift over time is not tested, which bounds late activity.", 2),
                 (0.08, "Assumptions are retrieval-specific.", 1)],
     "turn_count": 13},
]
BASELINES = [  # name, probability or None, verdict; same question, IN-37
    ("popularity", None, "unavailable"),
    ("base rate", "0.11", "unresolved"),
    ("paper-card regression", "0.37", "unresolved"),
    ("nearest neighbors", "0.43", "unresolved"),
]
READING_TEXT = (
    "All four readers put this paper above the base rate on first-year citation reach, with chances from 0.49 to 0.72, "
    "and all four cited the same table: the 63% reduction in resent tokens at equal recall. They agreed less on late activity, "
    "from 0.28 to 0.55, where the higher readings rest on adoption by a retrieval framework and the lower ones on the absence of "
    "any uptake evidence in the paper. Every reader put cross-subfield reach low. Two of the four flagged that the three benchmarks "
    "share a source corpus, which bounds the generality claim. One flagged that the fixed per-corpus mask is not tested for drift. "
    "None of the rationales cites evidence outside the paper except one comparison to an earlier routing paper that reached five citations."
)
assert len(READING_TEXT.split()) <= 200

# author citation counts shown after rating (HumanAuthorCitation)
AUTHOR_CITATIONS = [
    ("A5013847710", 312, "2026-09-30T23:41:08.000000Z", None),
    ("A5090233114", 1284, "2026-09-30T23:41:08.000000Z", None),
    ("A5044120987", None, None, "not_available_as_of"),
]

# ---------------------------------------------------------------- models page
REPRESENTATION_HASH = h("representation-manifest-modernbert-embed-base-d556a88e-gpu-float32")
RUNTIME_MANIFEST = h("runtime-manifest-linux-vm-2026-09-24")
CORPUS_RELEASE = h("corpus-release-1-2026-09-22")
BUNDLE_HASH = h("model-bundle-release-1")
BUNDLE_PREVIOUS = None
QUAL_REPORT = {t: h("head-qualification-" + t) for t, _ in TARGETS}
HEAD_HASH = {t: h("linear-head-" + t) for t, _ in TARGETS}
CALIBRATED_DOMAINS = ["cs.AI", "cs.LG", "quant-ph", "q-bio"]
AUTH_ID = u("spend-authorization-2026-09-24")
QUOTE_ID = u("cost-quote-zai-glm-5.3-flash-2026-09-24")

# ---------------------------------------------------------------- spend and diagnostics (settings graphs, footer)
# Spend per day in USD, settled from provider token counts: (day, cs, quant-ph, q-bio, summarizer, scholarly APIs).
# 2026-09-24 is partial: paid execution was enabled at 18:30 UTC. 2026-10-01 is a full day (USD 2.28: cs 1.32 as
# island.html, summarizer 0.03). The snapshot is 2026-10-02 02:30 UTC = 2026-10-01 21:30 in Chicago, so the 10-02 UTC
# bucket is partial. Caps from Appendix A: USD 8 a day, USD 200 a month.
DAILY_SPEND = [
    ("2026-09-24", 0.38, 0.13, 0.15, 0.01, 0.00),
    ("2026-09-25", 1.29, 0.43, 0.50, 0.03, 0.00),
    ("2026-09-26", 1.34, 0.42, 0.51, 0.03, 0.00),
    ("2026-09-27", 1.27, 0.45, 0.48, 0.03, 0.00),
    ("2026-09-28", 1.36, 0.44, 0.52, 0.03, 0.00),
    ("2026-09-29", 1.31, 0.41, 0.50, 0.03, 0.00),
    ("2026-09-30", 1.33, 0.46, 0.49, 0.03, 0.00),
    ("2026-10-01", 1.32, 0.44, 0.49, 0.03, 0.00),
    ("2026-10-02", 0.15, 0.04, 0.07, 0.00, 0.00),  # tonight's batch so far: 14 finished runs to 02:30 UTC, no digest yet
]
CAP_DAY_USD, CAP_MONTH_USD = 8.0, 200.0
CAP_SUMMARIZER_DAY_USD, CAP_APIS_DAY_USD, CAP_ASSESS_DAY_USD = 1.0, 2.0, 2.0
SHARE_MONTH_USD = {"cs": 118.0, "quant_ph": 38.0, "q_bio": 44.0}
# Footer diagnostics at 2026-10-01 12:00 UTC. Every value sits inside the alert thresholds on settings.html
# (disk under 20% free, backup older than 26 h, anchor older than 30 min, spend at 80% of a cap, >10% void or missed).
DIAG = {
    "checked_at": "2026-10-02 02:30 UTC · 21:30 in Chicago",
    "runs_today": (16, 14, 0, 0, 0, 2),  # tonight's batch (2026-10-02 UTC, began 01:03 UTC): issued, finished, void, missed, quarantined, in flight
    "last_batch": ("2026-10-01", 124, 121, 3),  # today's batch, complete at 13:24 UTC: date, issued, finished, void
    "workers": (2, 2),  # busy, total
    "papers_today": 594,
    "ingest_lag": ("41 min", "3 h 10 min"),  # first public to ingested, p50 and p95
    "digest_sent": "06:00 UTC to 2 raters",
    "backup_at": "02:10 UTC · 7 daily and 4 weekly kept",
    "anchor_at": "02:15 UTC",
    "disk_free_pct": 61,
    "service_misses_24h": 0,
    "provider": "glm-5.3-flash · Z.ai · responding, 1.9 s median per call",
    "next_ranking": "Monday 2026-10-05 00:00 UTC",
    "first_maturity": MATURITY_FIRST,
    "alerts_open": 0,
    "checks_waiting": 1,
}
# Outstanding reservations at 12:00 UTC: the 2 runs in flight, each reserved at worst case before its calls
# (caps are checked on settled charges plus outstanding reservations; a reservation is released only for proven unused remainder).
OUTSTANDING_USD = 0.18
ALERT_FRACTION = 0.8  # alert when settled plus outstanding reaches 80% of any cap
