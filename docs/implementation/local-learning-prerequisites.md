# Local acquisition and learning prerequisites

These local owners implement bounded parts of #82/#65, #87/#66, #88/#70/#83 and #91–#93.
They merged with the storage foundation in #95. They do not close those
parents or create a source, representation or forecasting qualification.

## Retained source and deterministic outcomes

`contracts/papers.py` and `contracts/learning.py` define closed immutable source
and citation records. `ingest/replay.py` checks exact retained source identity
and explicit license metadata without a network fallback. No fabricated fixture
is counted as an acquired source document. `ingest/openalex.py` validates exact
retained Works-query identity, identifiers, day intervals, taxonomy and explicit
continuation state. Its real one-record metadata fixture is accompanied by
[limited capture evidence](../evidence/source-pilot/parser-fixture.md); missing
production capture provenance remains unavailable, not manufactured.

`outcomes/windows.py` uses elapsed UTC days and conservative half-open provider
intervals. `outcomes/bounds.py` collapses exact identities and possible identity
components for lower counts, retains distinct possibilities for upper counts,
excludes target-family self-links, and limits each possible family to one
possible subfield. Its iterative matching avoids recursion limits. Incomplete
pagination preserves unbounded upper counts.

`outcomes/resolve.py` binds a read-only immutable-family resolver and producer
identity outside the caller payload. It checks maturity, original version and
source identity before reading citation families. Sufficient positive witnesses
can survive later incomplete capture; negatives need complete capture. Missing
target taxonomy masks breadth alone. These numerical/domain owners still need
the storage job, immutable availability and typed Result service adapters before
acceptance of the complete normative interface.

`ingest/fetch.py` performs one anonymous OpenAlex incoming-citation page
request (#91). Its query is built only from canonical work ids, a page size and
an opaque cursor; it cannot carry an API key or an arbitrary URL. It verifies
TLS, follows no redirect, never retries, and bounds bytes and every network read
by one absolute deadline. It records actual capture start and completion times,
the raw body hash and observed rate-limit headers. Two limits remain. Name
resolution in `socket.create_connection` is not covered by the deadline, so a
stalled resolver can exceed it. Pacing, the daily request budget and persistence
belong to the acquisition worker's durable rate gate, which does not exist yet.
One fetched page does not run the 100-paper pilot.

## Frozen selection and coverage

`learning/corpus.py` selects the latest 25 fully mature UTC months, ranks eligible
original arXiv families independently of outcomes, takes at most four per month
and keeps the intended denominator at 100. The hash preimage is canonical JSON
with integer `seed=20260920` and `paper_family_id`; missing sources/features do
not trigger replacement. The caller must supply an already reconciled, frozen
eligible enumeration. The pure week splitter refuses fewer than 40 weeks.

`learning/coverage.py` reports source, feature, label and joint eligibility
separately. The 70-of-100 pilot arithmetic uses complete features AND each
known target label. It is not a source-feasibility disposition: conformance,
permission, actual source and immutable publication evidence are also required.

`contracts/corpus.py` defines the closed `CorpusRow`, `CorpusRelease` and
`TemporalSplit` wire records (#92). They check identifiers, ISO weeks derived
from `t0`, fixed pilot/initial/expansion denominators, shortfall arithmetic and
the fixed 60/15/10/remainder chronological boundaries. They do not admit a
release: receipt-cutoff admission and the authoritative family-partition
mapping remain parent work, and no `family_partition_hash` preimage is defined.
`storage/verification.py` can now verify an artifact graph against a frozen
storage publication cutoff, checking publication time and committed ledger
sequence for every raw artifact and producing manifest (#93).

## Numerical prerequisites

NumPy 2.3.3 and SciPy 1.16.2 are exact locked dependencies. The feature, fit and
calibration cores live in the normative `learning/` owners. The materialized
numerical values are internal objects, not alternate wire schemas. Hash-verified
TensorRef and immutable record adapters, actual frozen model execution and
qualification remain necessary. See `numerical-smoke.md` for synthetic solver
measurements. No synthetic row is called a real pilot paper, and a 100-paper
engineering run cannot satisfy the release class counts or chronological gates.

The original source pilot has not run. No live model or source qualification,
serving activation, paid execution or workload expansion is claimed.

`TrainingArrays` and `CombinedFeatureRecord` now have closed immutable wire
contracts (#90). `learning/arrays.py` verifies all referenced tensor bytes and
binds every feature row to its family, representation and exact combined tensor,
and every label cell to its family, ordered target definition and label state.
Missing readers fail closed; unknown labels remain masked zero. This is an
internal consistency adapter, not a release-admission gate. Authoritative
original extraction/embedding lineage, frozen corpus membership, committed
receipt cutoffs and representation qualification are still required before
real training or activation can be accepted.
