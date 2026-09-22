# 0018. Add a pinned summarizer reading to each digest entry

- Status: accepted
- Date: 2026-09-22
- Issue: #142, on the owner's direction of 2026-09-22
- Spec: SDD Terms; SDD-SR-04, SR-13, SR-25, SR-26, IN-36, EN-16 amended; SDD-EN-43 added; Appendix A agent batches and egress; TDD-2.1.4, 2.1.7, 2.1.15, 2.1.28, 4.1.16 amended; TDD-3.1.75 added; the DetailView, ReadingView and Reading records
- Pull requests: #176
- Supersedes: the absolute bar on model text for raters in decision 0002's SR-26 and IN-36; preserves recorded fields as the only other thing a rater sees, the scorer's model-free inputs and the blinding rules

## Context

Agent output evolves, so its shape is not a stable thing to read. A rater who has rated an entry sees every run's probabilities, rationales and notes verbatim, which is complete and hard to read. The owner asked for one reviewer layer: a pinned configuration of the same hosted model that writes a short reading of the agents' claims for each digest entry. SR-26 and IN-36 forbade any model text for a rater, so the work issue #142 could not be built against the specification as written.

## Decision

Each digest entry carries one reading written by the summarizer, a pinned non-evolving configuration of the agent model with the tools disabled, from the entry's paper card and the sealed probabilities, rationales and run notes of every genome of the island for that paper. It never sees the paper's text, the nominations, the entry's origin or any genome or run identity, so controls and service picks read like every other entry. The reading is bounded, labeled as automated output, stored with model identity, prompt hash and ordered input hashes, shown only after the rater has rated the entry, and enters no score, fitness or agent input. SR-04, SR-26 and IN-36 admit exactly this text and nothing else; SR-13 gives the summarizer the same one route a run has; SR-25 hides the reading until rating.

## Consequences

A second model call per digest entry, budgeted under a USD 1 daily sublimit inside the existing caps. Every input the summarizer reads exists in the ledger, so a reading is reproducible from its hashes. What becomes impossible: any other model text on a rater's screen, a reading that mentions a genome or an origin, and a reading before rating. Left open: showing the reading before rating, a measured layer under SR-17; the prompt text itself, a configured version recorded by hash.
