# 0026. Ask Jev in choice, score and noul questions

- Status: accepted
- Date: 2026-09-23
- Issue: #267
- Spec: SDD 6.3 rubric table, SDD-RD-16, SDD-RD-18, SDD-RD-22; TDD-4.1.54, TDD-4.1.56, TDD-4.1.60; TDD Jev eight-field records
- Pull requests: pending

## Context

The first rubric asked eight `choice` questions, and most came back "reported" or "not reported". The provider serves two more primitives, `score` for an ordered judgement and `noul` for a calibrated probability on a claim, and their wire shapes were checked live against `jev-1.13.0` on 2026-09-23. The owner directed that the rubric use them, keep eight fields, and that cards carry only what an agent needs to read each value.

## Decision

`jev-rubric-v2` is the launch rubric: `primary_contribution` stays a `choice` with v1's categories; `evaluation_rigor` (0 to 4), `limitations_candor` (0 to 3) and `novelty_as_claimed` (0 to 3) are `score` questions whose points describe what is reported; `claims_supported_by_evidence`, `reproducible_from_materials`, `generalizes_beyond_main_setting` and `open_problems_stated` are `noul` questions, the probability that the paper's own text supports the statement. Every question still asks what the paper reports.

`jev-rubric-v1` stays admitted under its own version and hash; assessments stored under it keep loading and rendering under v1.

The rendered card shows per field the value and only what makes it readable: a choice's option and distribution, a score's legend line and distribution over scale points, a noul's probability and statement, with provider confidence. Hashes, instants, identity kinds and report ids stay on the stored record.

## Consequences

A v2 response is decoded all-or-nothing; a `score` legend that differs from the question's criteria or a `noul` outside [0, 1] is refused. A field id names one primitive and scale in every version, so a changed scale needs a new field id. The smoke report counts a `score` field by scale point and a `noul` field by ten decile buckets, beside the categories a `choice` field counts; a v1 report keeps its shape. v2 needs its own smoke test before it is activated (RD-22). The v2 response fixture is built from the recorded wire shapes; a response recorded from the live service replaces it when the owner runs one.
