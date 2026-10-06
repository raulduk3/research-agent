# 0043. Distinguish unverified and unavailable output

- Status: accepted
- Date: 2026-10-06
- Spec: SDD-IG-03; SDD-CT-02; SDD-UI-02; SDD-UI-03

## Context

Retrieved context does not verify generated claims. Failed paper groups appeared empty, and run totals combined settled charges with uncertain estimates despite a settled-cost label.

## Decision

Deterministic retrieval reports support for its stored-record summary. Model synthesis remains unverified, including when its prose contains numbered citations. Return supported=false and display that limitation beside the answer while retaining source links and paid receipts. This is conservative provenance labeling, not semantic entailment validation.

Run detail and brief cost_micros fields contain settled charges only. The existing settlement-aware run cost summary supplies a separate unsettled amount and receipt count to the browser. Paper per-island cost uses settled charges. Budgets continue reserving uncertain charges.

Paper assignment and run groups consult unavailable before displaying counts or empty-state messages. Readings retain their existing unavailable distinction.

## Consequences

Paid answers remain readable with an explicit verification limitation. Factual validation and refusal of unsupported synthesized prose remain unfinished requirements. The settlement repair does not establish all genome, generation or feedback cost measures.
