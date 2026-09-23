# Implementation records

What has been built and what it was verified against, dated and cited to issues. The [SDD](../spec/SDD.md) and [TDD](../spec/TDD.md) state the design; these records state progress against it. Implementation order, evidence gates and TDD ownership per work issue are tracked in #100. Provider and source facts checked for the work are under [`docs/evidence/`](../evidence).

- [Durable storage foundation](storage-foundation.md): transaction, provenance, job and checkpoint owners and their tests (#72).
- [Local acquisition and learning prerequisites](local-learning-prerequisites.md): source, outcome, feature and fitting owners (#65, #66, #67, #70).
- [Numerical fitting smoke](numerical-smoke.md): synthetic three-head fitting run.
- [Disposable Linux boundary evidence](linux-boundary-evidence.md): container, network and role observations (#81).
- [Boundary guest definition](lima-collection-boundary.yaml): the Lima Linux VM those observations were made in (#81).
- [Storage configuration example](storage-config.example.json).
- [Private rating frontend](rating-frontend.md): sign-in and blinded digest presentation, with the remaining integration boundaries (#73).
