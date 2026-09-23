from dataclasses import replace

from research_agent.contracts import sha256_hex
from research_agent.outcomes.dispatch import (
    RESOLVED,
    RESOLVER_UNAVAILABLE,
    resolve_pinned_question,
)
from research_agent.outcomes.targets import definitions, registry
from test_resolution import AS_OF, META, scenario


def _dispatch(**overrides):  # type: ignore[no-untyped-def]
    paper, observation, stored = scenario()
    current_registry = registry(META)
    findings: list[str] = []
    kwargs = {
        "pinned_registry_hash": sha256_hex(current_registry.to_canonical_json()),
        "load_pinned_registry": lambda registry_hash: current_registry
        if registry_hash == sha256_hex(current_registry.to_canonical_json())
        else None,
        "read_family": stored.__getitem__,
        "meta": META,
        "target": definitions(META)[0],
        "paper": paper,
        "observation": observation,
        "as_of": AS_OF,
        "record_finding": findings.append,
    }
    kwargs.update(overrides)
    return kwargs, findings


def test_resolves_through_the_pinned_registry_not_a_newer_one() -> None:
    old_registry = registry(META)
    newer_meta = replace(META, created_at="2027-01-01T00:00:00.000000Z")
    newer_registry = registry(newer_meta)
    old_hash = sha256_hex(old_registry.to_canonical_json())

    def load(registry_hash: str):  # type: ignore[no-untyped-def]
        return {old_hash: old_registry}.get(registry_hash)

    kwargs, findings = _dispatch(
        pinned_registry_hash=old_hash, load_pinned_registry=load
    )
    outcome = resolve_pinned_question(**kwargs)
    assert outcome.status == RESOLVED
    assert outcome.result is not None
    assert not findings
    assert sha256_hex(newer_registry.to_canonical_json()) != old_hash


def test_missing_historical_resolver_image_reports_unavailable_and_pends() -> None:
    kwargs, findings = _dispatch(load_pinned_registry=lambda registry_hash: None)
    outcome = resolve_pinned_question(**kwargs)
    assert outcome.status == RESOLVER_UNAVAILABLE
    assert outcome.result is None
    assert len(findings) == 1
    assert kwargs["pinned_registry_hash"] in findings[0]


def test_a_registry_returned_under_the_wrong_hash_is_treated_as_unavailable() -> None:
    kwargs, findings = _dispatch(
        load_pinned_registry=lambda registry_hash: registry(
            replace(META, created_at="2028-01-01T00:00:00.000000Z")
        )
    )
    outcome = resolve_pinned_question(**kwargs)
    assert outcome.status == RESOLVER_UNAVAILABLE
    assert findings
