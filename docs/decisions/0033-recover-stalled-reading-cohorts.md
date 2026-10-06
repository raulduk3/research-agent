# 0033. Recover stalled reading cohorts

- Status: accepted
- Date: 2026-10-05
- Issue: #404
- Spec: IG-01, IG-02, RN-03 and CT-03; implementation corrections, requirement text unchanged
- Pull requests: #403, #409

## Context

The public swarm had 31 runs, nine failures, two quant papers, one bio paper and no general papers. Ingestion repeatedly consumed its admission cap on the first category and unchanged feed heads. Failed reads could never retry and counted as negative votes, automatically releasing papers. Fixed reader order left new agents without turns; evolution changed the population used to decide existing papers. The public globe stopped polling after an initial failure and kept its initial snapshots indefinitely.

The requested correction is recorded in #404. Selected-paper terminology, explicit selected-paper context, general-island supply and higher live pacing are recorded separately in #405.

## Decision

Rotate the first ingestion category durably across passes, scan at least twenty feed entries per category, and admit changed papers within each category's share of the pass cap. Unchanged records do not consume admission slots.

Give less-used readers and islands turns, finish partly read cohorts before untouched arrivals, and freeze the reader count when a cohort starts. A failed run is a missing vote, not a rejection. A paper is decided only after its cohort submits complete readings.

Retry failed readings after fifteen minutes, with at most three automatic attempts per paper and genome version in a UTC day. Renew the allowance on the next day so a prolonged provider outage cannot permanently strand a reader. Every attempt must fit existing budget admission and run caps; completed readings are not automatically repeated.

On startup, reopen automatic rejections that depended on failed readings. Preserve human releases and historical runs, readings and receipts. Enforce the daily run cap inside each island's scheduling loop.

Retry the public activity feed after an initial failure and refresh island, paper and budget snapshots every fifteen seconds. Globe motion continues to come from recorded events.

## Consequences

Provider outages leave inspectable failed traces and undecided papers, with bounded automatic recovery. Cohorts can complete despite arrivals and evolution. Source rotation allows quant and bio to receive papers without changing monthly spending authorization. General-island supply and higher live pacing still require the #405 implementation and live verification.

Deployment needs a database backup: reverting the code does not restore assignment decisions or automatic releases reopened at startup. Runtime and browser regression tests cover these corrections. No active specification requirement is amended.
