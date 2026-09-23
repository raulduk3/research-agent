from dataclasses import replace

from research_agent.contracts import sha256_hex
from research_agent.contracts.outcomes import OperationalFinding
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
    findings: list[OperationalFinding] = []
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
    finding = findings[0]
    assert finding.kind == RESOLVER_UNAVAILABLE
    assert finding.pinned_registry_hash == kwargs["pinned_registry_hash"]
    assert kwargs["pinned_registry_hash"] in finding.detail
    assert finding.detected_at == kwargs["as_of"]


def test_a_registry_returned_under_the_wrong_hash_is_treated_as_unavailable() -> None:
    kwargs, findings = _dispatch(
        load_pinned_registry=lambda registry_hash: registry(
            replace(META, created_at="2028-01-01T00:00:00.000000Z")
        )
    )
    outcome = resolve_pinned_question(**kwargs)
    assert outcome.status == RESOLVER_UNAVAILABLE
    assert findings
    assert findings[0].kind == RESOLVER_UNAVAILABLE


class _UnsupportedProtocolRegistry:
    """A stand-in for a resolver build under a protocol the dispatcher never admits.

    ``TargetRegistry`` itself refuses any protocol but
    ``automatic-citations-v1``, so an unsupported build can only ever reach
    dispatch through a historical artifact that predates that policy; this
    duck-typed stub exercises that branch without bypassing the contract.
    """

    protocol = "another-protocol-v1"

    def to_canonical_json(self) -> bytes:
        return b'{"protocol":"another-protocol-v1"}'


def test_an_unsupported_resolver_protocol_reports_unavailable() -> None:
    unsupported_registry = _UnsupportedProtocolRegistry()
    unsupported_hash = sha256_hex(unsupported_registry.to_canonical_json())
    kwargs, findings = _dispatch(
        pinned_registry_hash=unsupported_hash,
        load_pinned_registry=lambda registry_hash: unsupported_registry
        if registry_hash == unsupported_hash
        else None,
    )
    outcome = resolve_pinned_question(**kwargs)
    assert outcome.status == RESOLVER_UNAVAILABLE
    assert len(findings) == 1
    assert findings[0].kind == RESOLVER_UNAVAILABLE
    assert "another-protocol-v1" in findings[0].detail
