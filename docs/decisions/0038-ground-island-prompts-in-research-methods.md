# 0038. Ground island prompts in research methods

- Status: accepted
- Date: 2026-10-06
- Issue: #437
- Spec: SDD-IS-03; SDD-IS-05; SDD-RN-01; SDD-EV-01
- Pull requests: #439

## Context

Founders differed in reading posture but used the same generic procedures across islands. Existing and evolved agents need domain methods with visible provenance, without erasing authored behavior or changing historical runs.

## Decision

Keep a data-driven catalog in `beta/methods.py`. Persist a versioned `research_methods` object in each current genome. It holds domain instructions and source metadata in separate fields. Run prompt assembly includes only the instructions, never source names, links, version labels or the origin of evolved instructions. The operator upgrades every existing genome, including inactive agents and archived islands, through one append-only spec revision. Reapplying the same catalog and island context writes nothing. Authored prompt instructions stay intact and keeps the reader, skeptic and builder procedures distinct.

Unversioned runtime composition was considered. It would change behavior without changing the exported genome version and make source provenance harder to audit. Persisted method profiles use the existing revision, lineage and immutable run-snapshot owners; runtime assembly reads only the profile instructions. No new schema or per-reading source requests are required.

The catalog draws its methods from these primary papers and official guidance:

- [Machine learning reproducibility report](https://jmlr.org/papers/volume22/20-303/20-303.pdf), sections 2 and 5: evaluation details, reproducibility and uncertainty.
- [Practical quantum advantage](https://www.nature.com/articles/s41586-022-04940-6): validation and classical comparison at the claimed scale.
- [Preclinical research reporting principles](https://www.grants.nih.gov/policy-and-compliance/policy-topics/reproducibility/principles-guidelines-reporting-preclinical-research): experimental design and bias controls.
- [Statistical inference principles](https://www.amstat.org/asa/files/pdfs/p-valuestatement.pdf): interpret results in context rather than by a significance cutoff.
- [Convex optimization](https://web.stanford.edu/~boyd/cvxbook/), chapters 5 and 9: feasibility, optimality and stopping criteria.
- [Simulation model description protocol](https://www.jasss.org/23/2/7.html): model purpose, design and fitness for purpose.

The role questions and retrieval workflows are this application's adaptation of the sources. The sources do not prescribe these tools. Source metadata and the human agent card identify the adaptation. Prompts separate method checks from evidence for the paper being read. Unknown islands use general methods with their actual focus and categories and record the absence of specialist guidance in profile metadata.

## Consequences

New founders and breeder children receive their island's current methods. Mating replaces inherited method profiles with the destination profile; novelty compares authored behavior independently of method metadata. The child prompt does not identify the donor. Upgrades remove only the exact legacy mating labels naming a donor recorded in genealogy, preserving the following instructions and arbitrary custom text. Invalid oversized children record a refusal without changing the population. The authored prompt limit remains 8,000 characters. The separate method instructions allow up to 4,000 characters. Upgrades preserve existing prompt text without truncation. Content edits preserve evolved ancestry and record the previous version separately; the upgrade repairs ancestry from original creation revisions where older edits replaced it with a self-reference.

`python -m research_agent.beta upgrade-methods --dry-run` previews the proposed spec and changes without preparing or otherwise mutating the database. Omitting `--dry-run` applies the revision to an already prepared store. A service running the methods-aware code reads that revision for subsequent runs without another restart. Stored prompts, past revisions and in-flight runs retain their original evidence and behavior.

The preview's `spec` can also be reviewed and submitted through the existing operator spec-apply endpoint. The target service must run the methods-aware code before applying the structured field; older versions discard it and do not compose its instructions. Applying an upgrade to a deployed store remains an operator action.
