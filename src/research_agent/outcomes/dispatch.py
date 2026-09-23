"""Route a sealed question's settlement to its pinned resolver build (EN-11)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from research_agent.contracts import sha256_hex
from research_agent.contracts.learning import (
    CitationFamilyRecord,
    CitationObservation,
    TargetDefinition,
    TargetRegistry,
)
from research_agent.contracts.papers import PaperVersionRecord
from research_agent.contracts.primitives import RecordMeta
from research_agent.outcomes.resolve import Resolver
from research_agent.outcomes.results import ResolutionResult

RESOLVER_UNAVAILABLE = "resolver_unavailable"
RESOLVED = "resolved"
SUPPORTED_PROTOCOLS = frozenset({"automatic-citations-v1"})


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    status: str
    result: ResolutionResult | None


def resolve_pinned_question(
    *,
    pinned_registry_hash: str,
    load_pinned_registry: Callable[[str], TargetRegistry | None],
    read_family: Callable[[str], CitationFamilyRecord],
    meta: RecordMeta,
    target: TargetDefinition,
    paper: PaperVersionRecord,
    observation: CitationObservation,
    as_of: str,
    record_finding: Callable[[str], None],
) -> DispatchOutcome:
    """Resolve *observation* through the resolver build the sealed question actually pinned.

    A question's ``pinned_registry_hash`` freezes which resolver build
    settles it; dispatch never substitutes the currently active target
    registry for it, so a build published after sealing can never reach
    back and settle an older question. An absent or unsupported build is
    reported through *record_finding* and leaves the question pending
    rather than guessing with a newer build.
    """
    registry = load_pinned_registry(pinned_registry_hash)
    if (
        registry is None
        or sha256_hex(registry.to_canonical_json()) != pinned_registry_hash
    ):
        record_finding(
            f"resolver build unavailable for registry {pinned_registry_hash}"
        )
        return DispatchOutcome(RESOLVER_UNAVAILABLE, None)
    if registry.protocol not in SUPPORTED_PROTOCOLS:
        record_finding(
            f"unsupported resolver protocol {registry.protocol!r}"
            f" for registry {pinned_registry_hash}"
        )
        return DispatchOutcome(RESOLVER_UNAVAILABLE, None)
    resolver = Resolver(read_family, meta, registry=registry)
    label = resolver.resolve_target(target, paper, observation, as_of)
    return DispatchOutcome(RESOLVED, ResolutionResult.from_label(label))
