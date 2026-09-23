from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.resolutions import validate_resolver_identity

SEALED = {
    "resolver_id": "citation-reach-v1",
    "resolver_build_digest": "a" * 64,
    "target_definition_hash": "b" * 64,
    "observation_protocol_version": 1,
}


def test_first_resolution_pins_a_complete_valid_tuple() -> None:
    identity = validate_resolver_identity(None, SEALED)
    assert identity == SEALED


def test_a_later_resolution_reproducing_the_pinned_tuple_is_accepted() -> None:
    validate_resolver_identity(SEALED, dict(SEALED))


def test_omitted_build_digest_is_rejected() -> None:
    supplied = dict(SEALED)
    del supplied["resolver_build_digest"]
    with pytest.raises(ContractValidationError):
        validate_resolver_identity(None, supplied)


def test_a_semantic_version_alone_without_its_build_digest_is_insufficient() -> None:
    supplied = dict(SEALED)
    supplied["resolver_build_digest"] = None
    with pytest.raises(ContractValidationError):
        validate_resolver_identity(None, supplied)


def test_a_changed_build_under_the_same_resolver_name_is_rejected() -> None:
    drifted = dict(SEALED, resolver_build_digest="c" * 64)
    with pytest.raises(ContractValidationError, match="differs from the identity"):
        validate_resolver_identity(SEALED, drifted)
