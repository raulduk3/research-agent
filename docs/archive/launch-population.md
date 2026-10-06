# Launch population

`seeds.json` is the population the study starts from: eight procedures, each admitted into all three islands, twenty-four genomes in all (#311).

- The four launch emphases of Appendix A: evidence-first (each island's founder, AG-38), methods and assumptions, earlier related work, and limitations and alternative explanations. Their twelve configurations are the seeded population AG-03 checks.
- Four owner-written variants admitted under AG-03 before the first cycle: base-rate, simulator, skimmer-skeptic-expert and meta-analyzer.

Each procedure holds the four emphasis parts AG-20 lets a mutation change. Every prompt begins with `common_instruction`. The scan policy, read policy and probability assignment rule are written as rules, not as a role. Tools, budgets, sampling and output schema are not in the file: they come from the launch profile's `run` section and the protected output core, so every genome shares one infrastructure hash.

Admit it with:

```sh
bin/seed-population --file docs/launch/seeds.json --state DIR --dsn DSN \
  --profile FILE [--island cs|quant-ph|q-bio] [--corpus-ids FILE]
```

The command checks the whole fixture before writing anything. It prints each configuration hash as `admitted` or `present`, then each island's population. A second run admits nothing. A genome carrying a corpus paper identifier (AG-31), or an island that already has a different founder, stops the run with nothing admitted.

Editing a procedure's wording changes its configuration hash, so a rerun admits it as a new genome beside the old one. Change a running population through the owner app instead.
