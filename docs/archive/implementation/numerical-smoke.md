# Numerical fitting smoke

On 2026-09-21, the real NumPy 2.3.3/SciPy 1.16.2 L-BFGS implementation ran on
synthetic engineering-only arrays: 240 fit, 60 development and 60 calibration
rows, each unit-L2 float32 `[N,2048]`, with all three heads balanced and fixed
synthetic release, split, registry, representation and solver-runtime identities. This is not a
100-paper pilot, a model release, or qualification evidence.

These measurements used the previous 2048-wide feature. The representation is now
768-dimensional modernbert-embed-base (#96), so features are `[N,1536]`; the
smoke has not been rerun at that width.

| Target | Lambda | Fit iterations | Gradient infinity norm | Development Brier | Calibration iterations | Projected gradient infinity norm |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| citation_reach_365d | 0.001 | 8 | 3.9275e-7 | 0.10645 | 7 | 1.8446e-7 |
| late_citation_activity_365d | 0.001 | 8 | 3.9275e-7 | 0.10645 | 7 | 1.8446e-7 |
| cross_subfield_reach_365d | 0.001 | 8 | 3.9275e-7 | 0.10645 | 7 | 1.8446e-7 |

The three-head run took 0.0490 seconds locally. Its synthetic labels are
artificially generated, so these Brier values have no scientific or
operational meaning.
