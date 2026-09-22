# Recurring audit operations

Prepared 2026-09-22, ahead of the audits' implementing issues (#56, #64,
#77). This schedules the recurring human and automated audit duties the
specification already fixes, so the operating calendar and evidence-location
convention are ready before the code that runs them exists. No audit has
run; this is the operating plan, not a completed audit.

## Duties covered

| Requirement | Duty | Cadence | Sample |
| --- | --- | --- | --- |
| SDD-IN-11 | Spot-check sealed forecasts: does the cited evidence support the forecast | Weekly (ISO week) | 5 hash-seeded forecasts, or all if fewer |
| SDD-IN-39 | Report confirmed resolver defects separately from evidence-support judgments | Weekly | All investigated source/resolver cases that week, per resolver version |
| SDD-IN-42 | Walk a random sample of scores back to raw inputs through recorded provenance | Weekly | Up to 50 hash-sampled score records; separately, up to 50 captured source records; plus the latest completed batch and one hash-selected older batch replayed |
| SDD-EN-37 | Daily acquisition coverage report, linked to the latest applicable audit | Daily | Every acquired family that day (automatic; not a sampled human duty) |

Each duty's sample size, schedule and denominator come from Appendix A:
Launch profile ("Evaluation, leakage and provider qualification" and
"Diagnostics, alerts and data handling" in `docs/spec/SDD.md`) and are not
set independently here.

## IN-11: forecast evidence spot check

- A human does not choose which forecasts are sampled; the system draws five
  hash-seeded sealed forecasts per ISO week (all if fewer than five exist)
  and shows each with its cited evidence in a review view.
- The reviewer records a verdict: the cited evidence supports the forecast,
  or it does not. A sampled forecast left without a verdict stays recorded
  as unchecked and is not swapped for another forecast.
- This verdict is the sole input to the supported-evidence share IN-32
  reports; it is not a resolver-defect finding and does not feed IN-39.

## IN-39: resolver defect reporting

- The weekly report covers investigated source/resolver cases, confirmed
  defects and open cases, broken out per resolver version.
- Confirmed-defect counts carry their investigated-case denominator and are
  reported as a selected audit sample, not a population error estimate. A
  week with no investigated cases reports an unavailable audit rate, not a
  zero error rate.
- IN-11's rationale-support verdicts are kept out of this report; a rater's
  or reviewer's disagreement about whether evidence supports a forecast is
  not, by itself, a resolver defect.

## IN-42: provenance walk

- Each ISO week, hash-sample up to 50 recorded scores and, for each, follow
  its recorded provenance stamps through the ledger's hash chain back to the
  raw inputs it was computed from.
- Separately, audit up to 50 captured source records that week, and replay
  the latest completed batch plus one hash-selected older batch.
- The check only reports; it does not correct anything it finds. When a
  walk cannot be completed, the break is recorded in the report and the
  score stays as recorded, unchanged.
- Use all records if fewer than the sample ceiling exist; every snapshot is
  boundary-checked before sealing, ahead of this weekly sample.

## EN-37: daily acquisition coverage

- Ingest computes, for each daily cohort, source, readable-text, figure and
  parsed-bibliography shares over every family acquired that day. This is
  automatic per-day reporting, not a sampled human duty.
- The report attaches the most recent applicable dated audit (the fixed
  100-paper source audit in Appendix A) and its sample/version, or an
  explicit not-yet-audited state when none applies yet.
- A missing audit does not suppress the day's automatic counts, and a
  failed automatic measurement is recorded as a coverage-report failure; it
  never substitutes the previous day's numbers or fabricates a review.

## Preserving sample ids, denominators and not-reviewed states

Every duty above draws a named, seeded sample and reports its own
denominator; none of the four is allowed to convert a missed or unresolved
review into a fabricated label, and none suppresses automatic coverage
reporting when a human audit is late or absent. Where a sampled item has no
recorded verdict (IN-11) or a walk did not complete (IN-42), the report
carries that item as unchecked or broken, not as a favorable default. The
four duties stay separate from each other in what they report, per the
distinctions the requirement text draws: IN-11 measures evidence support,
IN-39 measures confirmed resolver defects, IN-42 measures provenance
integrity, and EN-37 measures acquisition completeness.

## Keeping evaluator identity separate from rater blinding

IN-11's evidence reviewer reads a sealed forecast's rationale and cited
evidence unblinded; a digest rater under SDD-SR-21 and SDD-SR-22 never sees
that. The two roles stay separate: an IN-11 reviewer session grants no
access to a rater's detail-view unlock (TDD-4.1.16, tied to that rater's own
stored rating), and a rater's own-rating unlock grants no access to IN-11's
review view or to IN-42's provenance walk. Neither role is a path to the
other's hidden genome, configuration or control-source provenance.

## Assignment and evidence location

Actual staffing (named reviewers for IN-11's evidence-support verdicts and
IN-42's provenance walks, and named operators for IN-39's defect
investigation) is not authorized by this document; #78 says explicitly not
to contact reviewers or promise availability without separate authorization.
Reviewer identity, when assigned, is recorded as a pseudonymous local id
under the access restriction in Appendix A ("restrict access to the two
raters and operator roles"), never a name or contact detail.

Missing coverage on any of these four duties blocks that duty's own report
for the period it was due, per its "On failure" rule above; it does not
block the implementing issues' TDD drafting or collection engineering, which
can proceed while reviewer assignment remains open.

Once these audits run, their reports are stored with the ledger and
measurement artifacts the implementing issues persist, referenced from a
future evidence note in this directory naming the run date, sample and
denominator for each duty. This document records the schedule only.
