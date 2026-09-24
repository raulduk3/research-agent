# Mock alignment to the specification

Head of `origin/develop` at the start: `30109ad5b96c8b1aa3ad560cc940159d7a9ffcc9` (Merge pull request #176).
Head of `origin/develop` at the end: `30109ad5b96c8b1aa3ad560cc940159d7a9ffcc9`, unchanged.
Pull request #175 (AG-39, AG-40, decisions 0019 and 0020) was open at both fetches and is not depicted.

An eighth page, `overview.html`, was added afterwards on the owner's request. It carries the end-to-end layered
picture drawn in the spec-integration session of 2026-09-22 (layers from sources up to the pages, tagged control,
watch and data) into the mock, corrected to the same head: twelve genomes, one head per target, the host's graphics
processor, a daily digest, no selection switch, Jev held out. It is a map of the other pages, not a contract of its own.

A ninth page, `swarm.html`, is the owner's swarm replay panel from the brief handed off by the agent-tools session on
2026-09-22 at 23:40: one canvas, a synthetic ordered event list for the 2026-10-01 batch, a scrubber, play, pause,
click a paper for its genomes' forecasts and a row for that run's events. It is the one mock page with JavaScript, because a
scrubber cannot be static; the script is inline, uses no framework and loads nothing external. It follows the head,
not the brief, where they differ: a run covers a 20-paper shard, so its line follows the paper of its latest tool call
and its submit places one arrow per shard paper (citation_reach_365d); no forecast matures in the window, so the event
list holds no resolution and the panel says so. Not built, per the brief: live mode, lineage threads, migration, read
paths, easing.

The mock is a demo of what the pages will show, not the specification. Every visible field traces to a
requirement id, a TDD contract field or an Appendix A value in `docs/spec/SDD.md` and `docs/spec/TDD.md` at that
commit. Example data is fictional, dated 2026-09-24 to 2026-10-04, and one dataset feeds every page
(the generator is `~/Dev/.research-agent-pr/mock-gen/gen.py` with its dataset in `data.py`; `python3 gen.py` rewrites the seven pages; the pages are the deliverable).

Fixed example calendar: activation and qualification 2026-09-24; first study batch 2026-09-25; digest shown for
publication day 2026-10-01 (cs island); run shown from the 2026-10-01 batch, shard 7; weekly report for ISO week
2026-W40 (2026-09-28 to 2026-10-04), frozen Monday 2026-10-05 00:00 UTC (FT-16); first forecasts mature
2027-12-24 (365 days plus the 90-day grace after 2026-09-25).

## Presentation revision of 2026-09-22 (evening)

On the owner's instruction the mock became the base for the real front end, so its presentation changed without
changing what it shows:

- Agents are named by island and reading style ("cs · evidence-first"), which is unique among the twelve seeds. The
  lineage code (`C.1.0.1`: island, founder line, generation, ordinal) sits in a small tag with the config hash as its
  title, and the config hash is listed under Identifiers. A child would be named "{parent} › {n}"; none exists.
  Nothing in the specification names agents, so this is presentation over AgentConfig.config_id and the lineage records.
- Every page ends with a collapsed Identifiers table holding the hashes and record ids that used to be inline
  (paper ids, view ids, batch, snapshot, profile, bundle, registration, run, submission, slot, quote). Papers appear as
  title plus arXiv id. Tables carry plain-language headers.
- Owner actions (#139), step controls, the run's contract, budgets, first message and cost accounting, and the system
  layers sit under "Advanced" disclosures. Skill columns read "not yet" with the maturity date in the note below.
- The home page (`overview.html`) opens on today's runs, spend, alerts (IN-21, IN-22), digests (EN-40), the papers
  the cs agents back most (mean sealed citation_reach_365d probability and agreement over the four runs of the shard
  on run.html, AG-26; a drawn summary, not a contract field), a moderation queue (IN-11 spot check, agents, kill switch
  IN-19/IN-20) and links to the reports. The layered picture is collapsed below it.
- Style, settled after three passes the same evening: a light tan ground with white and off-white panels, no rules or
  borders anywhere and tables that sit directly on the page with spaced rows and small uppercase headers, gentle 6 to
  8 px corners, generous line height, monospace throughout in the
  early-Macintosh spirit, plain blue links, and bright system colors (blue, green, red, yellow, orange, purple) only as
  thin card accents, tag fills and the swarm's lineage hues. The rating app stays plain HTML forms with no script;
  `swarm.html` remains the one page with an inline script.
- The swarm page draws one arrow per paper (mean and agreement) and shows each agent's own arrow only for the clicked
  paper; its step controls, legend and identifiers are under Advanced.

Every field listed in Table 1 is still present; the checks in the Checks section were rerun after the revision
(no visible hash or UUID outside Identifiers on any page except the recorded first message inside the run page's
Advanced block; no script outside swarm.html; no external asset; forbidden terms zero; no horizontal scroll at 375 px).

## Product pass of 2026-09-22 (late evening)

- Hierarchy: `index.html` is now **Today**, the front door for both raters, phone first: a one-line count of what needs
  attention, the open forecast question as a card in the feed (HumanForecastArgs: a slider for the probability, a free-text
  box for the rationale, the evidence view carried as a hidden value), then the twelve papers as cards with like, dislike
  and skip; after a rating, "what the agents thought" opens under the card with the entry's reading (EN-43) and a link to
  the detail. The owner strip at the top links to the owner's home. The forecast sheet page remains as the record behind
  the card. Navigation is five words plus settings: today, swarm, agents, report, models, settings.
- `overview.html` is the owner's home in three sections: what the agents are thinking (mean sealed reach probability and
  agreement per paper from the run trace), what's new, needs attention. The layered system picture is gone from the product.
- `paper.html` reads as a story: the reading first, then the four readings in one table with first to fourth reader,
  agreement wording derived from the recorded numbers, the evidence they pointed at with how many cited it, the baselines,
  and each reader's step-by-step, the authors and the content assessment under "More". A line says the rater's own forecast
  appears beside the readers' when one exists (HumanQuestionView), judged against the same outcome.
- `settings.html` is new: every lever with its current value and how it changes ("now" for owner actions such as pausing
  paid execution, admit/retire/seed and acknowledging alerts; "new profile version" for every numerical limit, per
  Appendix A; "deployment" for raters, sources and the allowlist), and each island's configuration (categories, rater,
  agents and floor and affordable count, budget share, founder, selection proxy, whether it accepts agents from elsewhere).
- Probabilities: every 0-to-1 value is drawn as a short bar plus the number (`pbar`), faint at 0 and deep orange at 1, on
  the paper, run, agents, report, home, questions and swarm pages.
- Units: every visible number carries a unit in its cell or its column header (runs, forecasts, papers, agents, USD,
  tokens, calls, reads, images, minutes, seconds, weeks, credit, entries, Brier, nats, "chance, 0 to 1"). Recorded agent
  notes and paper titles are shown as recorded.
- Vocabulary: requirement codes and plumbing words (shard, snapshot, ledger, hash, manifest, schema, sealed) are off every
  visible surface outside the collapsed Advanced and Identifiers sections and outside recorded text; "paper group",
  "locked in", "the record" stand in. The codes remain in each page's HTML comment and in this file.
- Report: a "You and the agents" table lists the rater's answered questions beside the agents' average on the same papers,
  with the note that a formal comparison must be preregistered first (SR-18, IN-17); until then it is a record, not a verdict.
- Reading guide (Today): under the open forecast question, a written guide of at most 120 words: two sentences on what
  the paper is and does, then up to four pointers into the paper (section title, or figure or table caption with page),
  each with one clause on what to look for there, labeled automated output like the summarizer's reading, shown only on an entry that carries a human forecasting question (an entry with only like, dislike or skip shows no guide and triggers no call), ordered by how many of the island's agents cited that place in a sealed claim, with no count, no
  agent number, no probability, rationale or summary shown (the count orders only; showing it would be a popularity
  count under SR-25 and "of 4" would reveal the island's size). Owner direction of 2026-09-22 relayed by the loop session; the draft decision issue describes it as a pinned
  guide call whose input is the paper and the cited spans, never a claim. Not in the specification at the head: it discloses agent-derived evidence locators before any rating,
  which SR-25 does not cover for the human-question view, so it stays marked pending until the decision lands.
- Cover (Today): the page opens with the swarm, an inline SVG of the cs island at the end of the day built from the same
  synthetic run trace as swarm.html (dots darker with the agents' mean chance, one arrow per paper for agreement, the four
  agents' nests), captioned "Your swarm · 12 agents · 350 papers read overnight · 124 runs, 121 answered", tapping through
  to the replay; the heading reads "Your swarm picked 12". Presentation over the same recorded values.
- Copy (Today): the page greets ("Good evening."), one sentence of counts, the container board, then the cards. The skip
  button is labeled "pass" (the stored value is still skip, IN-10). The question card shows the guide's two sentences and
  folds the four pointers under "where to look"; its submit reads "that's my call".
- Swipe (Today): swipe right = accept (like), swipe left = push away (dislike) (IN-10); pass (skip) is a button. A small inline script does the gesture and, in production, submits the
  same rating form; the buttons remain the action without it. This makes Today the second page with a script; the rating
  app is still ordinary forms, not an application (#121). On a question card a swipe either way, or "pass", dismisses
  the question: no forecast is recorded and nothing is scored. "Dismissed" is not a HumanQuestionView state at the head
  (open, answered, expired), so it is a pending decision; until it lands a dismissed question is an unanswered one,
  recorded as absent and never scored (EN-34, TDD-3.1.33).
- Lingering entries (Today): entries still unrated from earlier digests are listed under "Still waiting from earlier
  days" with their digest day; a rating has no deadline (EN-34 Observable: both raters can read the digest after close).
  Rated entries collapse under "Rated today". Abstracts clamp to two lines on the card.
- Open for a decision: a rater comment without a probability has no field in the specification; the free-text box on Today
  is the forecast rationale (String[0..2000]). A comment-only input, and the you-versus-agents comparison as a registered
  measure, are candidates for issues.

## Entity pages (2026-09-23, early)

Every major entity now has an index and a detail page, and the navigation lists the indexes: today (papers of the day,
detail paper.html), swarm, agents (agents.html → agent.html), runs (runs.html → run.html), islands (islands.html →
island.html), reports (reports.html → report.html), models (models.html index → head.html for a prediction head; the
embedding model, agent model and summarizer sections sit on the index page), accepted (liked.html → paper.html), settings.
The mock carries one detail page per entity: the cs founder, its group-7 run, the cs island, the cs W40 report, the reach
head. Detail pages open with a back link to their index.

- agents.html is ordered by island, founder first, then reading style; the stored parts and the owner actions moved to
  agent.html, which adds today's runs from the same synthetic schedule as swarm.html.
- runs.html groups the day's runs by island, then by agent: one summary row per agent (runs, void, first to last start,
  minutes in a container, settled cost) that unfolds to its runs in time order with paper group, duration and outcome
  (IN-18: void runs included; AG-05).
- islands.html and island.html show stream, rater, agents, budget share, proxy, today's digest, selection state and
  recent weeks (AG-36 to AG-38, EN-40 to EN-42, FT-13, FT-14, IN-43).
- reports.html lists one row per island per week with the headline verdict (FT-16, FT-26, IN-16).
- head.html shows one head's held-out loss, interval, fit date, refit records, calibration per category and fitting
  details (FT-08, FT-10, FT-11, FT-23, Appendix B).
- Accepted groups by month with a count per month, newest first, older months folded, and a one-line tally.
- Entry detail: a "this reasoning is off" flag under each reader's reason with a short reason list, posted to a review
  queue the owner sees on the home page. Not in the specification: the only human inputs at the head are ratings,
  human forecasts and the owner's spot-check verdicts (IN-10, EN-34, IN-11). Pending decision. A flag never changes a
  score (SR-03, EN-16).

## Style and cover revision (forked session, 2026-09-22 late)

- Style: cards, panels, inputs and buttons are flat with a 1 px hairline border in a warm grey and square corners, no
  shadows; tables carry a hairline between rows and a darker rule under the header; the page itself stays flat on the
  light tan ground. Owner's words: "more brutalist and less mac, lines in between tables, keep the page mostly flat".
- Cover (Today): a small rotating graph, no text, not a link. Nodes are the twelve agents in their lineage colors, larger
  for founders, placed on the outside of their island's lobe and pointing in; the papers form the body, one lobe per island near the middle, up to 28 papers per island. The view is scaled uniformly and tilted slightly so the rotation reads as depth. An edge is one agent's
  deep read of one paper today, taken from the run trace (ToolReceipt of deep_read, AG-30), so a paper between two agents is
  one they both read, and islands never link because a genome runs only its island's papers (AG-36). It animates only while
  on screen (IntersectionObserver, visibilitychange) and pauses on tap. Presentation over recorded reads; nothing simulated.
- The two-container board with the twelve agent tiles moved to the owner home under "What's new".

## Decision issues filed 2026-09-23

The pending items above are now open decisions on GitHub: #196 reading guide under a human forecast question, #197 a
dismissed state for human forecast questions, #198 a rater note on a digest entry without a probability, #199 a shared
accepted view across the two rated islands, #200 a rater flag on a run's recorded rationale. Each mock feature stays
marked pending until its issue is accepted and the amendment lands on develop.

## Cover globe (2026-09-23)

The Today cover is a slowly turning globe drawn for beauty over literalness, on the owner's instruction: the papers agents
read deeply today on an even lattice over the sphere, the twelve agents at evenly spaced points on the surface in their
lineage colors with a soft glow (founders larger), and every edge one recorded deep read (AG-30) bowed outward in the
agent's color and fading toward the back; a faint graticule and a radial shade give depth; orthographic projection keeps
the silhouette a circle. Positions carry no meaning; edges and colors are the recorded data. No text, no identifiers.

The globe reacts to the rater's actions at the level SR-21 allows. The rater's own papers (today's digest, entries still
waiting from earlier days, the open question) sit on the lattice as hollow rings. Accept fills the ring and sends a green
pulse through the island's four agents (credit goes to the nominating agents, IN-43, but which ones stays hidden, so the
whole island glows); push away fades the ring and pulses red; pass shrinks it and sends nothing (a skip credits nobody).
Locking in a forecast marks the question's paper with a blue ring and touches no agent (a human forecast is the rater's
alone, EN-34); passing on the question leaves a grey mark. An agent's halo grows or shrinks slightly with the island's
credit over the session, a visual only. Rated entries from earlier are drawn in their current state on load.
The canvas skips a frame while it measures under 40 px (before layout or mid-resize) and clamps the sphere radius to at
least 1 px, so a zero-sized canvas no longer raises a negative-radius gradient error; checked at 375 px and desktop widths.

## Table 1. Visible fields and what they trace to

| Page | Visible field | Traces to |
| --- | --- | --- |
| index | rater's island in the heading and header line | EN-32 (each rater receives their island's digest); DeploymentBindings.rater_islands; DigestManifest.island |
| index | publication day | DigestView.publication_day |
| index | entry count (12) | DigestView.entries[0..12]; EN-41 seven population places, EN-33 up to three controls, EN-42 up to two service picks |
| index | digest view id | DigestView.digest_view_id (route GET /digests/{digest_view_id}) |
| index | automated-output label | IN-28; TDD-4.1.36 |
| index | blinding disclosure ("Publication dates are shown for every entry. Residual age and content cues can weaken blinding.") | EN-42 Limits |
| index | per entry: title | DigestEntryView.title |
| index | per entry: abstract | DigestEntryView.abstract |
| index | per entry: paper id (UUID) | DigestEntryView.paper_id (PaperFamilyId is a storage-issued UUID) |
| index | per entry: published date | DigestEntryView.publication_date; EN-42 "show publication dates consistently" |
| index | per entry: source link | DigestEntryView.source_link |
| index | per entry: like, dislike, skip buttons | IN-10; RatingArgs.value; POST /v1/ratings |
| index | per entry: rating state (unrated, or value with time) | DigestEntryView.rating: RatingState {unrated} or {rated, value, created_at} |
| index | per entry: details link only when rated or skipped | DigestEntryView.details_available; TDD digest projections "like, dislike and explicit skip unlock details" |
| index | hidden form field entry_view_id | RatingArgs.entry_view_id (DigestEntryView.entry_view_id) |
| index | identical fields for all 12 entries, blind order | SR-22; TDD-2.1.27; EN-40 seeded shuffle (seed itself not shown) |
| paper | title, published date, source link, paper id | DigestEntryView fields of the rated entry |
| paper | the rater's rating and its time | RatingState {rated, value, created_at} |
| paper | "opens only after you have rated or skipped" | SR-25; TDD-2.1.28; GET /v1/entries/{entry_view_id}/details 403 until rated |
| paper | automated-output label | IN-28 |
| paper | reader labels A to D, fresh per paper | AnonymousRunView.label; SR-21; TDD-2.1.26 |
| paper | per run: three answers in fixed target order | AnonymousRunView.answers[0..3]; target order from Agent contracts ("reach, late activity, cross-subfield reach") |
| paper | per answer: target id, probability | AnonymousAnswer.target_id, probability; IN-36 |
| paper | per answer: rationale | AnonymousAnswer.rationale[0..2000]; SR-24 (shown only after rating) |
| paper | per answer: evidence items as text with paper id and location, up to five, opaque link | AnonymousAnswer.evidence[0..5]; VisibleEvidence {evidence_view_id, text, paper_id, location}; GET /v1/evidence/{evidence_view_id} |
| paper | per answer: verdict "unresolved" | AnonymousAnswer.verdict; IN-37; EN-13 (no horizon has passed in 2026) |
| paper | per answer: baselines (popularity unavailable, base rate, paper-card regression, nearest neighbors) | AnonymousAnswer.baselines; AnonymousBaseline {name, probability, verdict}; IN-37 naming IN-07, IN-08, IN-09, IN-33 |
| paper | per run: turns with note and intent (11 to 14 shown, at most 16) | AnonymousRunView.turns[0..16]; ProtectedTurn {note[0..1000], intent}; AG-33; IN-36 |
| paper | reading text under the label "automated output" | DetailView.reading; ReadingView {text, label: "automated output"}; EN-43 (at most 200 words); IN-36 |
| paper | reading introduced as the summarizer's reading of the recorded claims, rationales and run notes | EN-43 Behavior; SR-26 |
| paper | author citation rows: author id, count, captured time, or typed unavailable reason | DetailView.author_citations; HumanAuthorCitation {author_id, count, captured_at, unavailable_reason}; RD-12 |
| paper | assessment: unavailable, source label "Jev paper-content assessment" | DetailView.assessment; HumanAssessment {status: "unavailable", source_label}; #123; decision 0015 |
| questions | heading "batch of 2026-10-01"; "up to three questions"; "citation_reach_365d"; "batch-hash sampling"; "opens when the batch is issued, independently of the digest" | EN-34 and its Limits; TDD-3.1.33; HumanQuestionsView.questions[0..3] |
| questions | per question: paper id, question view id | HumanQuestionView.paper_id, question_view_id |
| questions | per question: target citation_reach_365d | HumanQuestionView.target_id |
| questions | per question: prompt text (registry display question plus the paper title) | HumanQuestionView.prompt; Appendix B target registry display question |
| questions | per question: deadline | HumanQuestionView.deadline; EN-09 Limits (24 hours after first public availability) |
| questions | per question: state open, answered, expired | HumanQuestionView.state |
| questions | answered question: probability, sealed time, forecast id, "immutable" | HumanQuestionView.probability; HumanForecastResult {forecast_id, sealed_at, state}; TDD digest projections "an answered question is immutable" |
| questions | expired question: refused write, 409, digest unaffected | EN-34; Private rating application ("Human forecast expiry returns a 409 deadline error; it never blocks digest reading") |
| questions | form: probability, rationale (2000), up to five evidence view ids | HumanForecastArgs {probability, rationale[0..2000], evidence_view_ids[0..5]}; POST /v1/human-forecasts |
| questions | evidence views listed for a question, recorded in the view receipt | HumanViewReceipt.visible_evidence_ids; SR-07 (human forecasts cite the view receipt) |
| questions | "missed question recorded as absent, never as a forecast" | EN-34 ("Do not impute omitted answers"); TDD-3.1.33 |
| agents | 12 genomes, 3 islands, four per island, one founder each | Appendix A Seeded evolution; AG-36; AG-38; decision 0017 |
| agents | floor four, ceiling from the island's share of the USD 200 monthly cap | FT-14 Limits; Appendix A Seeded evolution |
| agents | per genome: config hash prefix | AgentConfig.config_id |
| agents | per genome: island (cs, quant-ph, q-bio) | AgentConfigBody.island; Island enum |
| agents | per genome: founder marker | AgentConfigBody.founder; AG-38 |
| agents | per genome: emphasis | AgentConfigBody.emphasis enum |
| agents | per genome: lineage ("seed, no parent") | TDD-3.1.66 (child names its parent), TDD-3.1.73 Migration record; AG-37 |
| agents | per genome: admission record (owner id, time) | #139 acceptance criteria; AG-03 (operator-admitted artifact) |
| agents | per genome: runs made, submitted, void | AG-05; AG-15; IN-18 |
| agents | per genome: claims sealed | SR-07 to SR-10; Forecast record |
| agents | per genome: skill reach, late, cross, each "unavailable" with the maturity reason | FT-12 (per target, no average); TDD-4.1.75; EN-13 maturity 365 + 90 days |
| agents | per genome: preference credit and rated entries credited, separate columns | FT-26; IN-43; TDD-4.1.80 |
| agents | q-bio rows: zero credit with the reason "island never rated" | FT-26 Limits |
| agents | per genome: agreement with calibrated heads, labeled as the q-bio island's registered proxy | Appendix A Seeded evolution (proxy names); AG-19 |
| agents | per genome: cost per run in USD | FT-12 skill per dollar term; Appendix A ("measured per-run cost"); CostClass agent_inference |
| agents | island ceilings table: papers this month, share, monthly share, runs per genome per month, ceiling, floor, active | Appendix A Seeded evolution ("shares in proportion to each island's paper count in the month so far"); TDD-4.1.77 admitted count; FT-14 |
| agents | selection dispositions: cycles 1 and 2 "selection-disabled, population unchanged", with policy reason, ranked support, tie-breaks, resulting size | FT-13; FT-14 Observable; AG-18; TDD-4.1.76; TDD-4.1.77 |
| agents | registration reference and date | SR-18; Appendix A ("One canonical preregistration under SR-18 precedes the first select stage") |
| agents | minimum resolved-claim count "not yet set, #130" | AG-19 Limits; FT-14 Limits |
| agents | diversity archive, empty, columns archived genome hash, skill, support ids | FT-15; TDD-4.1.78 |
| agents | genome detail: schema_version, island, founder, emphasis, model_manifest_id, system_prompt, scan_policy, read_policy, probability_policy, tools, samples_per_question, extension {}, profile_id | AgentConfigBody, every field; AG-16; AG-34 (empty extension); bounds 16000 and 4000 from Appendix A |
| agents | prompt opening sentence about evidence, support, preference and missing evidence | Appendix A Agent batches ("Each prompt begins with the same instruction ...") |
| agents | "admission refused any paper identifier" | AG-31 |
| agents | owner action: edit and admit as a new genome (new hash, lineage link, admission record, source untouched) | #139; AG-16; AG-20; SR-19 |
| agents | owner action: retire (takes effect next cycle; founder cannot be retired) | #139; AG-22, AG-23; AG-38 |
| agents | owner action: seed a variant into a named island (floor and ceiling enforced, refusal with reason; no migration into q-bio) | #139; AG-03; FT-14; AG-37 |
| agents | "refused for an identity that is not the owner" | #139 |
| run | run id, state, started, terminated, termination reason | Run {spec, state, started_at, terminated_at, submission_id, termination_reason} |
| run | slot: batch id, island, shard_index, config id, arm population, attempt 0, slot id | SlotIdentity; RunSlot.slot_id; AG-17 Limits |
| run | mode study | RunSpec.mode |
| run | snapshot id, profile id | RunSpec.snapshot_id, profile_id; AG-10; SR-28 |
| run | paper ids (20, listed with source ids and first-public times) | RunSpec.paper_ids[1..20]; Appendix A shards of at most 20 sorted by first_public_at then id |
| run | questions 60 in paper then target order | RunSpec.questions[0..60]; Agent contracts question order rule |
| run | specification seed | RunSpec.specification_seed; TDD-3.1.61 |
| run | deadline = earliest question seal deadline | RunSpec.deadline; Agent contracts ("The run deadline is no later than its earliest question seal deadline") |
| run | submission id | Run.submission_id; SubmitArgs.submission_id |
| run | stamp: bundle, representation, service images, card manifest | SR-15 |
| run | agent model: provider-returned identity glm-5.3-flash, Z.ai first-party API, alias recorded as unpinned | AG-01; Appendix A Pinned model choices; TDD-3.1.37 |
| run | budgets: 16 model calls, 40 tool calls including rejected, 8 deep reads, 12 images, 65536 context, 16384 generated, 8192 per response, 20 minutes, 120 s timeout, with used | Appendix A "Per run"; BudgetLimits; BudgetUsage; AG-12 |
| run | measured input tokens with cached share | BudgetUsage.measured_input_tokens; Appendix A ("Resent input counts toward measured usage"); ModelReceipt token counts |
| run | first message: paper and question ids, targets, budgets, snapshot description, tools; no paper card | AG-25; TDD-3.1.56 |
| run | per turn: request hash, response hash, in and out tokens, disposition accepted | AG-29; ModelReceipt; TDD-3.1.62 |
| run | per turn: intent and note | ProtectedTurn; AG-33; intents from the fixed list |
| run | per tool call: name (one of the five), arguments, response size, remaining budgets | AG-09; ToolCall; ToolReceipt.usage_after; AG-27; TDD-3.1.58; exact tool argument schemas |
| run | submission: 60 answers (question id, target, probability, rationale, evidence id count up to five) | SubmitArgs.answers[0..60]; Answer {question_id, probability, rationale[0..2000], evidence_ids[0..5]}; AG-26 |
| run | submission: 7 nominations (paper id, rationale) | SubmitArgs.nominations[0..7]; Nomination {paper_id, rationale} |
| run | "sealed atomically at ledger sequence" | AG-26; SubmitData.ledger_sequence; SR-11 |
| run | cost: quote, reserved worst case per request, settled charge, released, daily and monthly counters against 8,000,000 and 200,000,000 microdollars | Spending authorization contracts (CostQuote, SpendReservation, reservation rule "resent input at the pinned context limit, the reserved output allowance"); Appendix A ceilings USD 8 and USD 200 |
| report | island, ISO week, span, freeze time | FT-16 (Monday 00:00 UTC); TDD-4.1.80 |
| report | preregistration reference | SR-18; StudyRegistration.registration_id |
| report | "every number rebuilt from the ledger" | IN-01; FT-26 Observable |
| report | automated-output label | IN-28 |
| report | like rate on system picks, random controls, service picks (rated, liked, rate) | FT-26; TDD-4.1.80; IN-10 |
| report | differences with 95% interval, verdict inconclusive, support, method | IN-15 (10000 resamples, publication weeks, seed 20260920); IN-16 ("inconclusive", never "tie"); IN-14 (support counts); TDD-4.1.19; TDD-4.1.20 |
| report | per genome: skill reach, late, cross, skill per dollar (unavailable with reason), preference credit, rated entries credited, agreement with heads; founder marked | FT-26; FT-12; IN-43; TDD-4.1.80; Appendix A proxy names |
| report | migrations admitted this week: none | FT-26; TDD-3.1.73 |
| report | runs this week: issued, submitted, void, missed deadline, quarantined | IN-18; TDD-4.1.22 |
| report | selection disposition for the week | FT-13; FT-14 Observable |
| report | diagnostic: pick-set non-overlap per genome against Hugging Face Daily Papers, with nomination count and shared count | IN-04 and its Limits; EN-38; TDD-4.1.4 |
| report | diagnostic: lead time over the discovery service at 0.75, days ahead, no crossing, history unavailable | IN-41 and its Limits; TDD-4.1.25 |
| report | diagnostic: Shannon entropy, distinct subfields, unknown fraction, same-day pool entropy | IN-31; Appendix A Diagnostics; TDD-4.1.39 |
| report | diagnostic: reliability diagram unavailable with resolved and unresolved counts | IN-30; IN-06 On failure; TDD-4.1.38 |
| report | diagnostic: spot check sampled 5, checked, supported, unsupported, unassessable, unchecked, share | IN-32; IN-11 Limits; TDD-4.1.40; Appendix A ("Rationale-support audits record supported/unsupported/unassessable") |
| report | q-bio report note: zero preference columns and why | FT-26 Limits |
| models | representation hash and manifest fields: model_repository, model_revision, weight and tokenizer files, runtime_manifest_hash, dimension 768, dtype float32_le, pooling, normalization, max_tokens 8192, overview_format, prefixes, chunk_policy, publisher_license, known_pretraining_cutoff null | RepresentationManifest record; MD-06; Appendix A Pinned model choices |
| models | compute platform: the host's graphics processor, one namespace per platform | MD-06; Appendix A Hosts; TDD-4.1.67 (see disagreement note below) |
| models | prediction-head input 1536, feature_policy overview_passage_sqrt2_v1 | FT-09; CombinedFeatureRecord; ModelBundle.dimension |
| models | corpus release: hash, purpose, population rule, build date and window, categories, seed 20260920, counts, temporal split | Appendix B population rule; CorpusRelease {selection_seed: 20260920}; EN-01; TemporalSplit 60/15/10/15; FT-18 |
| models | bundle hash, target registry hash, three heads | ModelBundle; FT-08; TargetRegistry |
| models | per head: status, head hash, target definition hash, fit date and cutoff, lambda from the fixed set, labels' end date, held-out skill with 98.333% interval, calibration a and b per primary category, promotion record, weekly refit records | TargetBundleEntry; LinearHead; FitDiagnostics; SigmoidCalibrator; Appendix B Validation and promotion; FT-10 ("completed, skipped-insufficient-data, unchanged-data or failed"); FT-11; FT-23 |
| models | agent model: glm-5.3-flash, Z.ai first-party API, no weights hosted, returned identity per call, alias unpinned, sampling 0.7 / 0.9 / 1.0, one route, no fallback | Appendix A Pinned model choices; AG-01; SR-13; TDD-3.1.37 |
| models | qualification gate agent_capability: 100 conversations with at least 99 valid, 50 figure questions with at least 80%, 100 evidence-location questions with at least 90% at 16k, 32k, 64k | Appendix A Pinned model choices and Activation gates; GateResult |
| models | paid_execution_enabled true after the gate; authorization id | Appendix A ("authorized spend stays zero until it passes"); SpendAuthorization |
| models | summarizer: model identity, prompt hash, tools disabled, one call per entry, 16384 context, 512 generated, 60 s, USD 1 per day, at most 200 words, input list | EN-43; Appendix A Summarizer paragraph; Reading record |
| models | spend ceilings: USD 8 per day, USD 200 per month, scholarly USD 2 per day, Jev USD 2 per day retained unused, summarizer USD 1 per day, in microdollars | Appendix A Hosts; Spending authorization ("8,000,000 daily and 200,000,000 monthly microdollars, 2,000,000 Jev and 2,000,000 scholarly") |
| models | Jev held out, RD-15 to RD-24 unchanged, unavailable on every card, allowlist closed, smoke test not a gate | Appendix A Scope and deferred behavior; #123; decision 0015 |
| overview | eleven layers, 0 Sources to 10 Pages, read bottom to top | SR-01 (layering); the session widget's order, corrected |
| overview | per layer: owning requirement ids in the text | the cited ids, each present at the head |
| overview | tags "control", "watch", "data" | a reading aid: control = an owner-set value or action (#139, Appendix A ceilings, IN-19, IN-25, SR-18, EN-01 configured list, FT-23 gate); watch = a recorded measurement (IN-21, IN-22, IN-06, IN-11, IN-42, IN-29, EN-37, FT-13, FT-26, IN-18); data = accumulating records (EN-03, EN-04, EN-07, IN-10, IN-43, EN-43, AG-29, AG-37, FT-15, FT-10) |
| overview | Pages layer: links to the seven other pages with one-line purposes | #121, #128, PL-22 and the ids listed on each page |
| overview | numbers: 15 minutes or 100 records, 30 minutes, seven daily and four weekly backups, monthly restore, 50 picks a day, 20 papers per shard, 24 hours, 10,000, seed 20260920, USD 8 and USD 200, 365 plus 90 days, five spot checks, three controls, two service picks, seven places, 60 answers, 7 nominations, 768 dimensions, twelve genomes | SR-16 Limits; Appendix A Hosts, Retrieval and Agent batches; EN-09; EN-13; Appendix B; CorpusRelease; IN-11; EN-33; EN-42; EN-41; SubmitArgs; MD-06; Appendix A Seeded evolution (each grepped, see Checks) |
| overview | first maturity date 2027-12-24 | the example calendar: first study batch 2026-09-25 plus 455 days (EN-13, Appendix B) |
| swarm | three regions labeled cs, quant-ph, q-bio | AG-36 islands; Appendix A routing by primary category |
| swarm | grey points, one per paper of the batch (350, 113, 131) | EN-09 daily batch; positions are a 2D projection of overview vectors (RD-06), a presentation choice |
| swarm | nests, one per genome, twelve, colored by lineage hue, labeled island.line.generation.ordinal with the config hash prefix | AgentConfig.config_id (identity); AG-36 to AG-38; the label and hue scheme are the presentation proposal of 2026-09-22, not a contract |
| swarm | line from nest to a paper while a run is in flight; at most two lines at once | Run.started_at; ToolReceipt per tool call (AG-29); Appendix A "at most two configurations concurrently" |
| swarm | ticks above a paper for deep reads | AG-30; DeepReadArgs |
| swarm | one arrow per paper: direction is the mean sealed citation_reach_365d probability (0 left, 1 right), length is the genomes' agreement (the resultant of their unit arrows); dot darkens and grows with the mean | Answer.probability; SubmitArgs.answers[0..60]; AG-26. The mean and resultant are drawn summaries of recorded probabilities; no requirement defines them and they enter nothing |
| swarm | the clicked paper shows each genome's own arrow in its hue | Answer.probability per run |
| swarm | void run leaves no arrow | AG-15 |
| swarm | resolution snaps a point to black or white; none in the window | EN-04; EN-13 (first maturity 2027-12-24) |
| swarm | scrubber, play at a fixed rate, +1 and −1 | the brief; play redraws once per event |
| swarm | readout: event index, UTC time, runs submitted, void, in flight, arrows, resolutions | counts over the event list; IN-18 (void runs counted) |
| swarm | paper panel: source id and title for the 20 known shard-7 papers, deep reads, arrows with genome label, hash prefix and probability, resultant length | the run on run.html shares these papers; other papers are labeled synthetic |
| swarm | run panel: run_started, tool_call with tool name and paper, submit with answer count, void | the event kinds of AG-29, AG-26, AG-15; the founder's shard-7 run links to run.html |
| today | attention line (to rate, questions open, rated) | counts over DigestEntryView.rating and HumanQuestionView.state |
| today | question card: slider, free text, lock-in button | HumanForecastArgs {probability, rationale[0..2000], evidence_view_ids}; POST /v1/human-forecasts |
| today | "what the agents thought" under a rated card | ReadingView (EN-43, after rating); link to DetailView |
| settings | every lever, value and how it changes | Appendix A launch-v2, SpendAuthorization, DeploymentBindings, BudgetLimits, FT-13 to FT-15, IN-19 to IN-22, #139 |
| settings | island table | AG-36 to AG-38, EN-32, EN-40 to EN-42, IN-43, Appendix A Seeded evolution, DeploymentBindings.rater_islands |
| all | probability bar beside every 0-to-1 value | presentation of Answer.probability and the other recorded probabilities |
| all | navigation: today, swarm, agents, report, models, settings | #121 (rating app), #128 (owner inspector); a mock convenience, not a field |

## Table 2. Removed from the previous mock and the rule that forbade it

| Removed | Page | Rule |
| --- | --- | --- |
| "sheet answered" note in the digest header | index | EN-34: the human-forecast view is separate from the digest; it is now its own page |
| seed, digest hash, "built from sealed claims" line | index | SR-21 and SR-22 (nothing that carries provenance); TDD-2.1.27 (origin and selection reason are storage-only); the prompt's rule against a seed, digest hash, watermark or "built from" line |
| "Entries are unmarked: some are random controls, some are discovery-service picks" | index | SR-22: no field or label sets a control or service pick apart; the disclosure EN-42 requires is about age and content cues, not origin |
| entry numbers 1 to 12 | index | SR-21 ("papers are not grouped or ordered by genome"); position after the seeded shuffle carries no meaning and is not a DigestEntryView field |
| "Other islands" line naming another rater and q-bio counts | index | EN-32: each rater receives the digest of their island and no other; nothing on a page names a person |
| "Why it was surfaced": pooled confidence, disagreement, rank 1 of 12, "not a control", "not a service pick" | paper | SR-21, SR-22, SR-25; TDD-2.1.28 ("continuing permanent genome/control/service-origin blinding"); DetailView has no such fields |
| summarizer model id and prompt hash shown to the rater | paper | ReadingView is {text, label} only; EN-43 stores model identity, prompt hash and input hashes with the Reading record, not in the rater view |
| "Card the agents saw" table: head probabilities with model stamps, neighbors, novelty distance, graph counts | paper | DetailView carries no PaperCard; TDD digest projections: "Never serialize a general PaperCard or manifest into public detail" |
| reader labels linking to run.html | paper | TDD digest projections: "no underlying run ids in URL, DOM, downloadable JSON or error"; SR-21 |
| reader labels reused as A to D in a fixed table with base-rate, popularity, regression as a footnote | paper | AnonymousAnswer.baselines is per answer with verdicts (IN-37); labels are drawn fresh per paper (SR-21) |
| "Verdict: resolves 2027-09-24, observations so far: 2 citing families" | paper | AnonymousAnswer.verdict is one of four states; EN-13 and Appendix B: no early positives before maturity; IN-03 |
| "9 genomes", generation numbers, "admitted by selection", "survived selection (rank 1 of 4)", "parent of" history rows | agents | Appendix A: twelve seeded genomes, four per island; AG-18, FT-13, FT-14: no selection before the third weekly cycle |
| "(control)" and "(exempt)" name suffixes, human-readable genome names | agents | AgentConfig.config_id is the identity; founder is a boolean field; q-bio is an island, not a marker on a genome |
| preference credit shown with skill and heads agreement as "weekly proxies" without counts | agents | FT-26: credit and the count of rated entries it came from are separate columns |
| genome JSON with "domain", "confidence_rule", "budgets", "working_format" fields | agents | AgentConfigBody has exactly the listed parts; budgets are BudgetLimits on the run specification (AG-17), not a genome part on the head |
| budget "max_tokens_per_run: 320000" and "320,000 tokens" | agents, run | Appendix A "Per run": 65536 context tokens and 16384 generated tokens |
| "Lifetime claims" table with Brier column and "pending 2027-09-24" | agents | #177 (forecast pages over resolution records are not yet stored); IN-03 (no loss before the horizon); the prompt did not ask for it |
| intents "read" and "decide" | run | AG-33 Limits: intents are scan, compare, inspect, forecast, nominate, submit, stop |
| "… turns 6–13" elision | run | AG-28 and AG-29: every request and response in order, none dropped |
| "submitted 20 claims", "Submitted claim (one of 20)" with "family", "horizon", "confidence" fields | run | SubmitArgs: up to 60 answers (20 papers times three targets) plus up to 7 nominations; Answer {question_id, probability, rationale, evidence_ids}; horizons come from the question (SR-09) |
| "Schemas rendered from the code" block with "enum[4]" intents and "evidence ≤20" | run | AG-33 (seven intents); Answer.evidence_ids[0..5]; #128 asks for schemas rendered from code, which a static mock cannot do without inventing them |
| "cost $0.019 · 14 calls · 11m 40s" as a one-line outcome | run | replaced by BudgetUsage against BudgetLimits and the SpendReservation record in microdollars |
| "Lead time over services" table (service picks the system had nominated earlier, median days ahead) | report | IN-41 defines lead time as a genome's sealed citation_reach_365d probability above the preregistered 0.75 threshold before the pick's capture, in days; the removed table measured nominations, which no requirement defines. Replaced by an IN-41 diagnostic in the defined form |
| "Disagreement" table (mean spread of confidences, papers with spread > 0.4) | report | no requirement defines it; TDD-4.1.4 "Selection disagreement diagnostic" is the IN-04 pick-set non-overlap |
| "→ tie" on a comparison whose interval contains zero | report | IN-16: reported as inconclusive, never tied |
| "1000 resamples" | report | IN-15 Limits and Appendix A: 10000 resamples, seed 20260920 |
| "drift from seed" column ("1 field", "migrant") | report | not a TDD-4.1.80 column; migrations are listed per island as admitted records (FT-26), and none exist |
| "Spend" section with "$56 cap" this week and "reserved next week" | report | Appendix A ceilings are USD 8 per UTC day and USD 200 per UTC month; no weekly cap exists |
| "Citation skill: empty until 2027-09" line and "null control (shuffled labels) scheduled monthly" | report | replaced by per-column unavailable with the maturity reason (FT-26 On failure); the null control is Appendix A's label-permutation test on prediction heads, not a weekly agent report item |
| "Modal L4 (cuda 12.4, torch 2.6)" platform row | models | Appendix A Hosts: the representation platform is the host's graphics processor; the specification names no rented compute |
| "equivalence check 500 papers, min cosine 0.99993, gate 0.9999" | models | no requirement defines a cross-platform equivalence gate; MD-06 forbids mixing platforms in one namespace |
| "corpus release-1 · seed 20260922 · hash 7ac0…" | models | CorpusRelease.selection_seed is 20260920; the population rule and categories are Appendix B |
| head versions v3 and v4 by category with "refused: not better than v3 by threshold", "ECE", "AUC" | models | FT-08: one head per target fitted across all categories; calibration and base rates per primary category (decision 0016); reported measures are Brier against the fitting base rate with the paired 98.333% interval (Appendix B), average precision and ten-bin reliability, not AUC or ECE |
| "forward skill (from 2027-09)" column | models | prospective evaluation is IN-38 and TDD-1.1.23, reported when eligible predictions resolve; not a bundle field |
| "Held out: weekly encoder training (#51), web-mentions target (#143, labels being computed), rating head, attention diagnostics" | models | #143 is an open decision and is not depicted; #51 is a reserved id block, not a model page row; "rating head" and "attention diagnostics" name nothing in the specification. Jev remains, as unavailable |

## Where the specification was silent and a choice was made

- The swarm panel is the one page with JavaScript (inline, no framework, nothing external). Its event list, paper positions, label scheme and hues are synthetic presentation, generated from the shared dataset so the founder's shard-7 run matches run.html.
- The overview page's layer order and its three tags are a presentation choice carried over from the session widget; the specification's own layering (SR-01) is infrastructure, environment, agents, reader, models, fitting, and the page cites it while ordering by data flow.

- The rater's island appears in the digest header. DigestView has no island field; EN-32 binds each rater to one island's digest, and showing the rater's own island reveals nothing about any entry's origin.
- The detail page shows a `source` link and publication date in its header from the rated DigestEntryView, since DetailView itself carries only runs, author citations, assessment and reading.
- The forecast sheet's prompt text is the registry display question followed by the paper title, because HumanQuestionView has no title or source-link field and a rater cannot act on a bare UUID. Two evidence views per question are listed so the form's evidence view ids refer to something the rater saw (HumanViewReceipt).
- The value of "agreement with the calibrated heads" is shown as a number with no formula. The specification names the proxy and places its definition in the SR-18 registration; the page cites the registration.
- Run notes on the detail page cover the whole 20-paper shard, so they mention other papers by description. AnonymousRunView.turns is the run's turns; they carry no identity.
- The mock has one detail page, so every rated entry's details link opens the same page.
- One navigation bar links rater pages and owner pages together for the demo. In the application the owner inspector (#128) and the rating app (#121) are separate roles; the rater pages themselves link to no owner page content.
- The rating form carries only `entry_view_id` and `value`; the real RatingArgs also carries `request_id`, `digest_id` and `expected_previous_event_id` as hidden fields. `digest_id` is a hash and was left out so no digest hash appears on the page.

## Where the specification and the prompt disagree (the specification wins)

- Lead time over the discovery service. The prompt says no requirement defines it. IN-41 does ("how many days earlier", threshold 0.75 on citation_reach_365d, Limits), Appendix A says it is "reported beside" the proxies, and TDD-4.1.25 gives the formula. The old table (nominations, median days) is removed as the prompt asks; an IN-41 diagnostic in the defined form is shown, labeled as not entering fitness.
- Prediction heads. The prompt says "fitted per primary category (cs, quant-ph, q-bio)". Decision 0016 and Appendix B fit one head per target across all categories and calibrate per primary category, and TargetRegistry.calibrated_domains lists four: cs.AI, cs.LG, quant-ph, q-bio. The page shows three heads with four calibrators each.
- Population page column "founder flag (one per island, the evidence-first configuration)" and "genome ... nine parts": AgentConfigBody on the head has thirteen fields including schema_version, model_manifest_id and profile_id; the page renders all of them.

## Internal inconsistencies noticed in the specification at this head (not changed here; the repository is read-only for this task)

- The RepresentationManifest record row in the TDD literally says `device: "cpu"`, while MD-06, Appendix A Hosts and TDD-4.1.67 say the host's graphics processor and MD-06 carries `deviation:#158`. The page follows MD-06 and says so.
- Appendix B's first-release population rule ("twelve months ending thirteen months before the build date, so that every family is mature at the build") cannot make every family mature: maturity is 365 plus 90 days, about fifteen months, so families from the last two months of the window carry immature (unknown, masked) labels at the build. The page renders the rule as written and gives the window dates.
- Appendix A Scope and deferred behavior still says "a seeded population of eight agent configurations"; Seeded evolution and decision 0017 say twelve. The page shows twelve.

## Checks run

1. Numbers. A script grepped `docs/spec/SDD.md` and `docs/spec/TDD.md` at `30109ad` for every profile-derived number, bound and label shown on the pages (83 checks on the seven pages, plus 21 on the overview: entry caps, budgets, caps, seeds, resample count, maturity, tool and intent lists, model identities, summarizer budget, corpus rule, split fractions, lambda set, interval coverage, qualification floors, the IN-28 and EN-42 sentences). Every check found at least one match; zero missing.
2. Rater pages field by field. A script parsed the 12 digest entries and found exactly the DigestEntryView fields (title, abstract, paper_id, publication_date, source_link, rating, details_available) plus the RatingArgs form; nothing extra. On the detail page it found the DetailView sections only: four AnonymousRunView labels, twelve AnonymousAnswer blocks with target, probability, rationale, evidence, verdict and baselines, four turn lists, one ReadingView text with its label, author citations and the unavailable HumanAssessment. A leak grep for genome, slot, run id, config, hash, seed, shuffle, control, service pick, nomination, rank, pooled, confidence, watermark, origin, founder and island over the visible text of the three rater pages found hits only inside fictional paper titles and abstracts, in recorded run notes about other papers, or in the rater's own island name.
3. Forbidden items. Greps over all seventeen files for: pooled confidence, disagreement, rank N, "not a control", "not a service pick", lead time over services, why surfaced, sheet answered, 320000, Modal, L4, nine genomes, generation columns, venue, web mention, grounding, stability, short-horizon, fine-tuning, scan-and-read, one-paper run, a person's name, a conference name, Jev shown as available, "tie", "heads agreement" as a column name, external `src=` or `<link`: zero hits each; `<script` appears only in swarm.html, by design. "watermark" appears once, on the report page, in the required "rebuilt from the ledger" line.
4. Phone width. Served on port 8766 and viewed each page in a 375 by 812 viewport. No page scrolls horizontally (document width 375 on all nine; the swarm canvas stacks its three regions vertically below 640 px; the overview stacks its layers and its page grid collapses to one column). Key/value tables wrap long identifiers; the per-run answers on the detail page are stacked blocks. Wide data tables (population, turns, submission answers, report comparisons) keep a 640 px minimum width and scroll inside their own wrapper, which is intended for the owner pages.

## Rating gestures (forked session, 2026-09-23)

Owner direction: the daily gesture is accept or pass; anything that rewards or punishes an agent is deliberate.

- Today: swipe right = like ("accept"), swipe left = skip ("pass"). The card offers those two buttons; the dislike button appears on a card only when dislike is already its current rating. The left-swipe edge is neutral, not red.
- Dislike ("push away") is the one rating that costs the nominating agents credit (IN-43: minus one shared in proportion to each agent's sealed citation_reach_365d probability), so it is not a gesture. It is a button in a "Your call" box on the entry detail (the RatingArgs form with `entry_view_id`, `value` and `expected_previous_event_id` = the current rating id, superseding under Rating.supersedes_event_id) and on the accepted list.
- After a rating, Today, the entry detail and the accepted list state what the rating did in words: "credit to the agents that picked it", "the agents that picked it lose credit", "no credit either way". No agent is named on a rater page (SR-21, SR-22, SR-24); the per-agent weekly credit stays on the owner's agents page.
- Not added, by the specification: rewarding or punishing a single agent, a model or the whole swarm from the trace. AG-07 and SR-24 allow no rating, reading or cost figure to reach selection except the preregistered measure; the models are pinned. The per-reader flag on the entry detail stays a note to the owner (#200), never a score.
- Checks: regenerated 17 pages; at 375 px Today's unrated cards show accept/pass only, one done card shows push away as current, document width 375 on today, entry detail and accepted; a left swipe or pass tap records "passed"; push away on the detail switches the state and the credit sentence. The mock's in-page script only records state in place; the forms post RatingArgs unchanged without it.

## About, impact, header, footer and cost graphs (forked session, 2026-09-23)

Owner direction, in order: an about page a newcomer can read, with bold terms linking to pages; the rater should feel the impact of each call, game-like but with the real technical consequence; the header was overwhelming; the footer should carry system diagnostics and health; settings should carry accurate cost graphs, tight and in line with the specification; the about page must not fix counts that a profile can change, and must read as product, not a diary; forecasting is the discipline, not the purpose: the purpose is contextual awareness, claims and notes that prompt thinking, gaps, loose ends and possible research.

New visible fields and what they trace to:

| Page | Field | Traces to |
|---|---|---|
| about.html | purpose, notes as the product | EN-32/EN-40 digest, AG-26 nominations with rationale and evidence, EN-43 reading |
| about.html | why the agents forecast, sealed and scored later, can fail | AG-01, IN-01, EN-13, FT-12; the "can fail" sentence is the owner's framing, not a requirement |
| about.html | islands, runs, pinned model, your part, random controls, questions | AG-16, AG-17, MD pinned model, IN-10, IN-43, FT-14, SR-22, EN-34 |
| impact.html | calls this week (accepted, pushed away, passed) | IN-10; WEEK_CALLS in data.py |
| impact.html | credit that reached agents (+7 of +9 signed) | IN-43; sum of CREDIT for cs, whole by construction; the difference landed on controls or service picks (SR-22) |
| impact.html | agents' picks vs random controls, difference and interval, "not yet a verdict" | IN-15 and the weekly report; LIKE_RATE in data.py, same values as report.html |
| impact.html | forecasts sealed this week, judged from 2027-12-24 | EN-34, EN-13; WEEK_FORECASTS matches report.html's You-and-the-agents table |
| impact.html | the five-step chain | IN-43, FT-14 (rank by proxy, spend share, floor four, founder stays), EN-13 |
| index.html | "Your week" strip; +1 / −1 / 0 chip after a rating | same sources; the chip is the IN-43 sign |
| every page | footer: runs today, workers, spend, papers and ingest lag, digests, model, record anchor and backup, host, next ranking and first maturity, alerts and checks | Appendix A hosts and alerts (thresholds on settings.html), TDD timing report (publication-to-ingest quantiles), FT-14, EN-13; DIAG in data.py |
| settings.html | settled spend per UTC day by kind, outstanding reservations on today, cap and 80% alert line | TDD-3.x spend reservation (settled charges plus outstanding reservations against combined and subcategory caps, UTC buckets), Appendix A caps (USD 8 a day, USD 200 a month, summarizer 1, scholarly APIs 2, content assessment 2), alert at 80% |
| settings.html | each island's share of the month | Appendix A spend shares; FT-14 (share bounds population) |
| settings.html | cost per run by agent | COST_USD, the measured model cost that divides skill for skill per dollar (TDD-4.1.75) |

Choices and checks:

- Header: four items (today, impact, accepted, about) and a "more" disclosure holding swarm, agents, runs, islands, reports, models, owner home and settings. A details element, no script; the current page's name shows on the summary when it is inside. The menu opens to the right edge so it fits a 375 px screen (measured: right edge 313 px, document width 375 px); the row is baseline-aligned.
- Credit data: CREDIT per agent was adjusted so each island's column sums to a whole number (cs +7, quant-ph +2), because every rated population entry credits exactly ±1 in total. Same constant feeds agents.html, agent.html, island.html and report.html.
- No projection on the cost graphs: the specification defines none. Outstanding reservations are shown because caps are checked on settled charges plus reservations. Horizontal bars are HTML so their text stays readable on a phone; only the daily chart is SVG.
- About page names no population, island or per-run count. It leads with purpose and treats forecasting as the discipline that can fail; the notes stand on their own.
- Checks: 19 pages regenerated; no requirement codes in the visible text of about.html or impact.html (0 matches at 375 px); document width 375 px on today, about, impact, settings, agents; footer present on all 19 pages; a fresh tab loads today with no console errors (the earlier radial-gradient error was a stale entry from before the other session's fix).

## Drift pass (forked session, 2026-09-23)

Owner: "drift across the system, finalize". One pass over every page, checked by a script that strips comments, styles and scripts and scans the visible text.

- Time. Today is 2026-10-01 12:00 UTC on every page. Week 40 (2026-09-28 to 10-04) was shown as frozen on 2026-10-05; it is now "in progress, as it stands at 2026-10-01 12:00 UTC", on report.html, reports.html and island.html, with its counts scaled to Monday through Thursday noon: 288 cs runs issued, 281 finished, 2 in flight, 5 void; 16,298 forecasts made; 12 questions offered, 4 answered; 7 discovery-service picks, 2 called early; accept rates 0.61 on agents' picks (11 of 18), 0.29 on random controls (2 of 7), 0.33 on service picks (1 of 3), and these 28 rated entries are the 28 calls on impact.html (14 accepted, 5 pushed away, 9 passed; 11 minus 4 on agents' picks is the +7 credit). Week 39 stays frozen 2026-09-28. No visible date after 2026-10-04 except the ranking date 2026-10-05 and the first maturity 2027-12-24.
- Runs. RUNS covered "10 days" ending 2026-10-04; it now covers the last 7 daily batches (2026-09-25 to 2026-10-01) at the same per-agent daily rates (cs 18, quant-ph 6, q-bio 7), with forecasts made scaled by the same per-run rate; "(10 days)" reads "(7 days)" on agents, agent, island and settings. NONOVERLAP is week 40 so far. Cost per run, credit and agreement are rates or weekly sums and did not change.
- Vocabulary. No "like", "liked" or "dislike" remains in visible text: island, overview, report, reports and settings now say accept, accepted, push away, pass. The accept rate counts a pass as not accepted (the report says so), which is what makes the report's rates and the impact page's calls the same numbers.
- Rating controls, after the owner's note that the choices are simplified: Today offers accept and pass (push away appears only as the current state of an already pushed-away card); the entry detail offers all three deliberately; the accepted list shows the paper as accepted and offers push away or pass only. Forms still post RatingArgs values like, dislike, skip.
- Checks: audit script over 19 pages finds no future date, no like/dislike wording, no "10 days"; buttons per page as listed above; document width 375 px on report, accepted, island at phone width.

## Reconciliation after the drift pass (2026-09-23)

- The shared Accepted list now holds every paper accepted this week: 14 by the cs rater (1 today, then 4, 4 and 5 on
  2026-09-28 to 09-30, matching the week's 28 calls on impact.html and the W40 report's 11 + 2 + 1 accepted) and 2 by the
  quant-ph rater, 16 in all; Today's progress line counts the same list. The eleven added papers are fictional, with arXiv
  ids from a stretch no other page uses.
- Developer words removed from visible text: "ledger" and "hash-chained" on run.html (a check description) and settings.html
  (Storage and Sources levers) now read "recorded paper", "tamper-evident record" and "fingerprinted"; the requirement code
  on the Accepted list's lead line is gone. Ids and codes remain under Identifiers.
- Checks after regeneration: 19 pages serve 200; no dangling links; no like/dislike wording; no requirement codes or
  developer words outside collapsed Identifiers blocks; dates within 2026-09-24 to 2026-10-01 except models.html's
  pre-launch fit dates (09-22, 09-23), left as plausible; the console is clean on a fresh tab (the one 404 in the long-lived
  tab's log predates the Accepted page).
- Accepted page, later the same day: the inline push away and pass buttons were removed on the owner's word ("old decision
  choices"). Push away is a deliberate step on the paper page after reading what was recorded, and pass has no meaning for
  an accepted paper. Each of the rater's entries now shows its credit sentence and a "change your mind" link to the paper
  page's Your call form; the list reflects the current rating. This supersedes the "push away or pass" line in the drift-pass
  section above.
- Paper page, same pass: the Your call box no longer offers accept, push away and pass as three equal buttons. It states the
  current call and offers only what is still open, by rule: accepted → push away (the deliberate step, taking the credit
  back); pushed away → accept (taking it back); passed → either. The form is still RatingArgs with
  expected_previous_event_id set to the current rating id, so a new event supersedes the old one (Rating.supersedes_event_id,
  IN-43). The mock's one detail page is an accepted paper, so only the first case renders; the rule sits in the generator as
  NEXT_CALL and in the page script.

## Whole-mock review (2026-09-23, owner: "the about page feels off now")

Fixed across the 19 pages, all presentation over the same recorded values:

- about.html: islands have "their own rater" (not "reader", which names the four passes over a paper); the target is
  "at least five papers cite it within a year" as on every other page; "Your part" now says how a call is made (swipe
  right accepts, left passes; push away is deliberate, on the paper page after reading what was recorded; any call can
  be changed later the same way).
- index.html "Done today": rated cards follow the paper page's rule (NEXT_CALL): an accepted card offers no button and a
  "change your mind" link to the paper page; a pushed-away or passed card offers accept; the swipe script removes the
  buttons the same way after a call. impact.html's "Change your mind" no longer names the accepted list as a place to
  change a call.
- settings.html: the Ratings lever states the gestures; "the second rater" is "the quant-ph rater" as elsewhere; a
  literal anchor tag in the Selection table is plain text now.
- models.html and head.html: only the 2026-09-28 refit is reported skipped; 2026-10-05 is "next", not past.
- overview.html: the control period "ends Monday 2026-10-05", as island.html and settings.html say.
- Clock: the snapshot is 13:30 UTC (08:30 in Chicago), after the day's last run ended at 13:24 UTC, so the runs listed on
  runs, agent and overview all exist at the snapshot; the footer reads 124 issued · 121 finished · 0 in flight · 3 void
  (it summed to 122 before) and "2 idle · today's runs done"; nothing is reserved; the record anchor is 13:15 UTC; the
  greeting is "Good morning". Report W40 runs so far: 288 issued, 283 finished, 5 void.
- RUNS: cs · evidence-first has 2 void over 7 days (it showed 1 while agent.html showed 2 today alone); the cs 7-day
  voids now sum to W39's 2 plus W40's 5.
- The forecast question reads "Will at least five papers cite this one within a year?" on every page.
- Left as is: models.html's fit dates (2026-09-22/23, before launch day); rating timestamps in the small hours UTC.
- Clock, corrected on the owner's word ("it's like 9:27 at night"): the snapshot is 2026-10-01 21:30 in Chicago, which is
  2026-10-02 02:30 UTC, and the greeting follows the rater's clock ("Good evening"). Record timestamps stay UTC. Today's
  batch (2026-10-01 UTC, 124 runs, ended 13:24 UTC) is complete and is what runs, agent, swarm and overview show; tonight's
  batch (2026-10-02 UTC) began at 01:03 UTC, 20:03 in Chicago, and is the live part: 16 issued, 14 finished, 2 in flight,
  USD 0.26 settled and USD 0.18 reserved, workers 2 of 2 busy. Footer, overview, models, settings (a partial 10-02 bucket,
  cap bars for the UTC day) and the report lead say which batch each figure belongs to. The open question's paper appeared
  02:47 UTC on 10-01, so it closes 02:47 UTC on 10-02, 17 minutes after the snapshot. This supersedes the 13:30 UTC bullet
  above.

## Evil by Design pass (2026-09-22, late)

`REVIEW-evil-by-design.md` in this directory records the review; this is what changed in `mock-gen/gen.py`. Nothing was
added: every change is a removal, a reorder or a change of words, and every field in Table 1 is still present.

- Today: the "Your week" credit strip and the owner's spend line are gone from the rater's page (impact and the owner home
  hold them). Under the globe each block now carries a heading and one line saying what it is and why: "A question for
  you", "Today's picks", "From earlier days". Abstracts are no longer clamped. The lead says what accept means and that
  the agents' notes open after the call so their view cannot steer it (SR-25 in the reader's words). "9 left" replaces
  "9 still want a look".
- Question card: no gesture (a swipe that dismissed a question is gone; the buttons remain). The slider carries no answer
  until it is moved: the number appears beside it and the submit wakes on the first touch. The close time is shown in the
  reader's zone with UTC in brackets (the mock fixes America/Chicago through `lt()`; the live pages use the browser's zone).
- Settled cards stay in place with their state line and the one cheap change of mind still open (accepted → pass, passed
  or pushed away → accept); nothing folds into a collapsed section. "Rated earlier today" holds ratings from before
  this visit. Push away is still only on the paper page.
- Credit words are neutral everywhere: "+1 to the agents that picked it", "−1 to the agents that picked it", "no credit
  moves"; the card state reads "+1 accepted · change your mind" and nothing else, so the same line is true on a control
  (IN-43, SR-22). The loss framing ("lose credit", "takes the credit back", "a deliberate step" on every accepted row) is
  gone; the rule is stated once on impact and linked from Today and the paper page.
- Globe: one ink-coloured ring for accept, push away and pass alike; no island pulse, no halo growth. A locked forecast
  still marks blue, a passed question grey.
- Impact: four plain sentences replace the numeral tiles; the day-by-day list is gone; the tab moved under "more".
- Owner home: a digest entry still waiting for the owner's own call (today's or lingering) is left out of the "back most"
  table and the note says how many were held, because the owner is the cs rater (SR-25).
- Footer: one line, the grid under a disclosure. EN-42 disclosure in plain words. Chips no longer animate.

## Teach-by-cue pass (2026-09-22, later)

Owner's direction: less prose, small arrows with a few words beside the controls that teach the page every time; the
acknowledgement of a call outside the card and pleasant; Today's sections clearly labelled; the globe floating left on
wide screens and small on a phone; and no pile-up: the system stores what a rater did not do but never queues it back.

- Today is a two-column grid from 900 px (globe and progress on the left, sticky; the feed on the right, 620 px at most);
  on a phone the globe is 150 px tall above the feed. Sections carry a small uppercase label with a count or a close time
  on the right ("Today's picks · 9 of 12 left"), and one cue line each: "← swipe left to pass / swipe right to accept →",
  "↓ the agents' notes open under a paper after your call", "↓ your own forecast, locked when sent, judged in a year like
  the agents'", and "↑ drag to set your chance · then send, or pass" under the slider. The paragraphs are gone.
- The acknowledgement of a call is outside the card: a small bordered word ("accepted ✓", "passed", "pushed away") rises
  from the card's top edge on the side of the call and fades, and the card nudges once that way. Same size, colour and
  motion for every call; the word is the only difference.
- "From earlier days" is gone from Today. An entry not called by the next digest is recorded as uncalled (RatingState
  unrated, EN-34 Observable) and does not come back; the impact page says so. The globe still draws those entries as
  hollow rings because they are recorded reads, and the data stays in `LINGER` for the owner pages.

## Your questions page (2026-09-22, later)

`questions.html` was rebuilt as the record behind Today's question card, under the same rules as the rest: "Your
questions", a back link, one lead line, a day label with counts on the right ("2026-10-02 · 1 asked · 0 answered · 1
open"), one cue line, then the open question as the same card as Today (the card is now one function, `question_card`,
used by both pages: one input for one act; the number field and the "what you looked at" checkboxes are gone, the
evidence view travels as the hidden value it already was). Answered and closed questions are one line each: the chance
bar, "locked in", the local time and the judgement date; or "closed", the local time, "not answered · nothing is
affected". Older days fold. The page carries the same inline script as Today for the slider readout and the pass button,
so it is the third page with a script (Today, swarm, questions). EN-34, HumanQuestionView states unchanged.

## Name (2026-09-22, last)

The product is called **Atoll**, marked with one emoji, the island, at the left of the header on every page and in every
page title. An atoll is a ring of islands round one lagoon: the agents' islands, and the day's papers they all read from.
Nothing else is tropical. The name lives in one constant (`NAME`, with `MARK`) in `mock-gen/gen.py`. The last line of
every page carries "© 2026 Rick Álvarez · all rights reserved · licensing to be decided" (`RIGHTS`): protective by
default until the owner decides between journals, open source and an organisation. Presentation only; the repository
is still `research-agent`.

## Home-screen app (2026-09-22, close)

The pages are built to be added to an iPhone home screen and used as an app. Every page's head carries
`apple-mobile-web-app-capable`, the title "Atoll", the default status bar, `theme-color` in the band colour, the
180 px `apple-touch-icon.png` (the island on the tan ground, drawn by `mock-gen` from the system emoji; 192 and 512 px
copies for the manifest) and `manifest.webmanifest` (standalone, start on Today, scope `./`), which the generator writes
with the pages. The viewport is `viewport-fit=cover` and the header and body pad for the notch and home bar with the
safe-area insets. The header is the app's only chrome, so it sticks to the top. Every button is at least 44 px tall and
15 px, the slider track is 44 px, text fields are 16 px so iOS does not zoom on focus, tap flashes and double-tap zoom are
off. Detail pages keep their "← today" or "← index" link because standalone mode has no browser back button. Nothing
else changed; no service worker and no offline copy, by design: the record is on the server.

## Globe layout (2026-09-22, close)

Paper positions on the cover globe are now placed by connection: each paper starts at the mean position of the agents
that read it deeply (AG-30), then relaxes on the sphere for 160 steps, pulled gently toward each of its readers and
pushed apart from every other point, with the twelve agents fixed where they were. The rater's own papers (no agent
link, SR-21) join the relaxation with repulsion only, so they take the gaps. Twenty-two papers per island instead of
thirty. Result: papers sit between their readers, arcs are short, nearest-neighbour spacing is even (0.28 to 0.45 chord
on the unit sphere for 82 points), and the globe reads balanced at 150 px and at 300 px. Marks and line widths scale
with the globe's radius (down to 0.55 at phone size). Positions still carry no meaning; edges and colours are recorded
data.

## Full globe and the floating widget (2026-09-22, last)

- The globe now holds every paper an agent touched today (549 of 594; 389 read deeply, the rest only looked up), placed
  inside the sphere, not on it. Each paper starts on the line from the centre toward the mean position of its agents, at
  a depth set by rank: a paper read from one side sits outermost, one read from several sides innermost, papers only
  looked up inside the deep-read ones, radii growing with the cube root of rank so the volume fills evenly. A short
  relaxation (numpy, 120 steps) pushes papers apart, pulls each gently toward its deep readers and holds it at its depth.
  Measured radii: tenth percentile 0.43, median 0.73, ninetieth 0.89 of the sphere, which is an even fill. The twelve
  agents stay on the surface where they were. Deep-read papers are full dots and carry the 537 read edges (thinner and
  fainter than before); looked-up papers are smaller, fainter dots. The rater's own papers sit inside too.
- When the cover scrolls out of view the same canvas moves into a 96 px box, top right, with a 1 px black border on the
  tan ground, and keeps turning and reacting to calls; it moves back when the cover returns. One canvas, no second
  animation. Tapping the box scrolls to the top. Docking follows the cover's position on scroll (the app's browser pane
  reports the page hidden, so it cannot depend on visibility). On wide screens the sidebar is sticky below the header
  (64 px), so the globe never slides under it; the widget never appears there because the cover stays in view.
- Wide-screen clipping fix: the two-column grid was 300 + 620 px fixed and overflowed sideways between 900 and about
  1000 px, and the sticky sidebar's offset was a guessed 64 px, so the globe slid under the header on some screens. The
  columns are now fluid (200 to 300 px for the globe, the rest for the feed up to 620 px) and the sidebar's offset is
  the header's measured height plus 10 px, set as `--navh` by the globe script on load and resize.
- Fuller, more even globe: every paper of the day is now a node (594: deep-read full, looked-up fainter, untouched
  faintest), depth by rank with radius growing as rank to the power 1/3.5 rather than 1/3, so the projected disc reads
  even from centre to rim (about 25 dots per unit area in each ring, measured over eight rotation angles) instead of
  centre-heavy; 220 relaxation steps. Nearest-neighbour spacing stays even.
- Globe layout, final: the iterative relaxation is gone. Paper positions are a blue-noise sampling of the ball
  (Bridson's fast Poisson-disk sampling in three dimensions: grid cells of r/√3, up to 30 candidates in the annulus r
  to 2r around each active point, a point retires after 30 failures), with the minimum distance shrinking 30% toward
  the rim so the projected ball reads even rather than centre-heavy, and the base distance found by bisection so the
  count matches the papers. Each paper then takes the free sample nearest where it wants to be (the direction of its
  readers at a depth from `radial_norm`), most-read papers first. Measured: nearest-neighbour spacing 0.14 to 0.20 with
  mean 0.16 (before: 0.09 to 0.45), ring density centre to rim 28, 28, 27, 25, 19 dots per unit area, and read edges
  average 0.54 long against about 1.2 for random pairs, so papers still sit by their readers. The sample set is cached
  in `mock-gen/.poisson-*.npy` (deterministic per size and seed) so regeneration stays at a couple of seconds.

## Replay at every level, the PDF in the page, a page per pick and per question (2026-09-23)

Owner direction, 2026-09-22 late: replay should exist at every level; a run should be watchable in real time with the
paper's parts and what the agent is doing, at no added cost; the PDF in the page; a click on a question or a pick opens
a page; click exploration is normal, make it easy to explore and learn. Filed as decision issue #208 in the repository;
the specification amendment (IN-44 to IN-47, TDD-4.1.81 to 4.1.84, decision 0023) waits on the owner's accepting comment.

- One player script (`mock-gen/replay.py`, `PLAYER_JS`) drives every panel: play, pause, a speed menu, a scrubber, one
  event at a time under Advanced, autoplay on load, and no dead air (between events the clock never makes the viewer wait
  more than about 1.5 s of real time). Every drawn element is one recorded event of the one dataset; no panel calls a model.
- Levels and pages: a run (`run.html`, owner, agent named; `reading-<key>-<n>.html`, rater, reader label only, SR-21): the
  group's papers on the left with each part (section, page, table, figure) lighting when a recorded call returned it
  (ToolReceipt, AG-29, AG-30), budgets remaining after each call (AG-27), the agent's notes labeled as its own account
  (SR-02, AG-39) beside the recorded calls, the PDF below at the page the call named; "watch as if live" replays at real
  speed with the future hidden, which is what the live view of a run in flight is. A paper's day (`paper-<key>.html`, one
  page per digest paper; `paper.html` stays as P1): appeared, ingested, carded, sealed, the readers' runs and sealed
  forecasts, the digest, sent, the rater's call and its credit; before the call only the public part shows (SR-21, SR-22,
  SR-25). A question (`question-<key>.html`, one per sheet question): issued, forecasts arriving as runs seal on a 0-to-1
  line, the rater's own call, the close; the agents' chances and the baselines are hidden while the question is open so
  they cannot anchor the rater (EN-34, IN-37). An agent's day (`agent.html`): its runs as blocks across 24 h with tool
  calls and submits counting up. The island's day (`island.html`): the swarm panel filtered to cs (`swarm.filter_island`).
  The island's week (`report.html`): each day's batch, digest and the rater's calls landing, dashed when a hidden control
  credited nobody, with each agent's preference credit building to the report's totals (IN-43; the per-call shares are a
  choice consistent with those totals: +3.10, +2.45, −0.40, +1.85 = +7 over 17 landing signed calls).
- The PDF: the mock's arXiv ids do not exist, so `mock-gen/pdfgen.py` writes a fictional PDF per paper (`mock/pdf/`,
  32 files, standard library only) laid out from the same part map the replay lights up (P1 fixed so Table 3 is on page
  4, Section 5.1 on page 5, Section 3.1 on page 2, the code release on page 9, as the evidence on the paper page says).
  Pages embed it in an iframe with `#page=N`; every page number, evidence line and deep-read step opens it there. On a
  phone's home-screen app the iframe shows the first page and "open the PDF" opens the viewer.
- Links: pick titles on Today open the paper's page; question titles open the question's page; the accepted list links
  the papers that have pages; readers on a paper page open their run; explore lines on the owner pages point up and
  down the hierarchy (run → agent → island → week → swarm).
- Shape: the run replays keep the 20-paper group of this head (`30109ad`); decision 0022 (one paper per run, merged
  since) is a separate realignment pass, after which the group collapses to one paper and the panel gets simpler.
  Readers for P3 and P6, their evidence lines and the question papers' agent forecasts are synthetic, consistent with the
  readings and the report's numbers; P1's readers are the recorded ones.

## Styles and sessions, 2026-09-23

Every page now links one built stylesheet, `dist/atoll.css`, built from `styles/tokens.css`, `styles/components.css` and
`styles/atoll.css` with Tailwind v4 (no preflight); the rules are the ones the pages carried inline, moved verbatim, and
`styles/README.md` is the component inventory. Two pages were added, `login.html` and `owner-login.html`, one credential
each (PL-22), and `log out` closes every page's menu. `settings.html` became `costs.html`, owner-only. The data behind
each page is `CONTRACTS.md`; the fixed front-end contract is `CONTRACT-v1.md`.

The rating app serves a byte copy of `dist/atoll.css` as `src/research_agent/web/static/atoll.css`; the repository's
copy of the built sheet is `front-end/src/styles/atoll.css` (#341, `docs/implementation/rating-frontend.md`).
