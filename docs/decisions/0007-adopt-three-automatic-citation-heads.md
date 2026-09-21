# 0007. Adopt three automatic citation heads

- Status: accepted
- Date: 2026-09-20
- Issue: #64
- Spec: SDD Scope and Terms, EN-12 to EN-17, EN-39, EN-41, IN-12, AG-26, RD-08, FT-08 to FT-25 and related scoring/acquisition clauses; LEARNING-PROTOCOL.md; paired TDD items
- Pull requests: #63
- Supersedes: the launch targets, human-label corpus and selection objective of 0005; retains original-version provenance, temporal evaluation, calibration and combined features under 0006

## Context

Substantive-use and evaluation labels require reviewing downstream evidence. That workload is not justified for the initial prediction experiment. Three automatically labeled targets were requested, together with a deliberate path to adding more heads later. Their role is supporting evidence about subsequent citation patterns, not a universal paper-quality judgment.

## Decision

Use one frozen representation and three separately fitted binary logistic heads: first-year citation reach (at least five distinct citing families), late-year citation activity (at least one family in each of days 181–270 and 271–365), and cross-subfield citation reach (at least two other primary subfields within 365 days). LEARNING-PROTOCOL.md fixes their exact automatic-citations-v1 definitions, one OpenAlex source, date/taxonomy limitations, missingness, corpus limits, shapes, calibration, promotion and refresh.

Keep original-title-and-abstract plus overlap-weighted full-paper passage features, shape [2d]. Labels, masks and predictions have three named entries. No downstream full-text semantic review, two-reviewer corpus, semantic challenge set or Jev evidence-annotation job is required. Jev's original-paper content assessments and separate qualification remain unchanged. Preserve all three configured targets even when one is unavailable; a complete three-head readiness claim requires all three to qualify.

Future targets require an accepted versioned definition, label feasibility and costs, independent qualification, calibration and useful added information beyond existing targets. Existing artifacts remain compatible through immutable registry and bundle versions. This is an extension boundary, not an added launch service or promise of available semantic labels.

Remove the obsolete semantic-label scoring dependency. Report per-target agent forecast skill, keep automatic performance replacement disabled pending #69/#11, and select digest entries through agent-ranked nominations with deterministic rotation. Do not silently replace scientific usefulness with a citation-weighted fitness function. Conditional evolution mechanisms remain documented for later activation by an explicit policy; this decision does not adopt ForeSci scoring.

## Consequences

One acquisition pipeline supplies all labels and reuses each original paper's features. Head annotation is automatic; source integrity, complete original-text extraction, classification missingness, temporal shifts and sufficient classes still require measurement. These three proxies are correlated and can be uninformative. The protocol tests each independently and reports correlation, coverage and multiple-comparison limits rather than promising three successful models.

Fixed thresholds are implementation policies, not proven optimal choices. Citation dates describe indexed works, not verified citation-passage appearance; reconstructed historical graphs and machine-assigned subfields carry disclosed error. Definitions can generalize beyond software papers, while launch predictive calibration remains limited to cs.AI/cs.LG.

Future semantic or longer-horizon heads remain worth considering because citation records omit correctness, substantive use, reader usefulness and delayed recognition. They return only when credible labels and measured benefit justify their costs. No encoder training, extra data provider, OCR, rental or paid benchmark run is added.

The head design is closed by this amendment. Full-system runtime, operating profiles, scoring activation and remaining TDD coverage are tracked separately in IMPLEMENTATION-READINESS.md; document consistency is not evidence of successful training.
