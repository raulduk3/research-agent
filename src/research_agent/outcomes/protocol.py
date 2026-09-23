"""One immutable protocol object shared by historical and prospective resolution (FT-19)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from research_agent.contracts import sha256_hex
from research_agent.contracts.learning import CitationObservation, TargetRegistry
from research_agent.outcomes.windows import (
    capture_timing_failure,
    instant,
    maturity_at,
    utc,
)


@dataclass(frozen=True, slots=True)
class ObservationProtocol:
    """The fixed source adapter, family/taxonomy policy and capture deadline.

    Both execution paths (a historical reconstruction and a prospective
    maturity capture) bind the same immutable object: provider publication
    date is not citation-passage event time, so neither path may read one
    for the other. Acquisition kind (``observation.kind``) changes reporting
    eligibility only -- it never changes which predicate a stored observation
    satisfies.
    """

    protocol: str
    source: str
    family_policy: str
    taxonomy_policy: str
    self_author_citations: str
    self_family_links: str
    indexing_allowance_seconds: int
    prospective_capture_allowance_seconds: int
    registry_hash: str

    @classmethod
    def from_registry(cls, registry: TargetRegistry) -> "ObservationProtocol":
        first = registry.definitions[0]
        return cls(
            registry.protocol,
            first.source,
            first.family_policy,
            first.taxonomy_policy,
            first.self_author_citations,
            first.self_family_links,
            first.indexing_allowance_seconds,
            first.prospective_capture_allowance_seconds,
            sha256_hex(registry.to_canonical_json()),
        )

    def capture_deadline(self, t0: str) -> str:
        """The latest instant a prospective capture may complete for *t0*."""
        return utc(
            instant(maturity_at(t0))
            + timedelta(seconds=self.prospective_capture_allowance_seconds)
        )

    def admit(self, observation: CitationObservation, *, as_of: str) -> str | None:
        """Return a failure reason if *observation* cannot bind to this protocol.

        Checks provenance (protocol id, source and the exact bound registry)
        and capture timing only; predicate evaluation over the preserved
        evidence is the resolver's own job (``outcomes/resolve.py``), not
        this admission gate's.
        """
        if (
            observation.protocol != self.protocol
            or observation.provider != self.source
            or observation.target_registry_hash != self.registry_hash
        ):
            return "invalid_source"
        return capture_timing_failure(
            t0=observation.t0,
            kind=observation.kind,
            started_at=observation.capture_started_at,
            completed_at=observation.capture_completed_at,
            as_of=as_of,
        )
