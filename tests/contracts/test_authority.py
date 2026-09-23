import pytest

from research_agent.contracts.authority import AuthorityPolicy
from research_agent.contracts.primitives import ContractValidationError


def test_only_the_resolver_or_operator_may_write_a_resolution() -> None:
    policy = AuthorityPolicy()
    for denied_role in ("agent", "jev", "scorer", "ingest"):
        assert not policy.permitted(record_kind="resolution", writer_role=denied_role)
    for allowed_role in ("resolver", "operator"):
        assert policy.permitted(record_kind="resolution", writer_role=allowed_role)


def test_only_the_scorer_or_operator_may_write_a_score() -> None:
    policy = AuthorityPolicy()
    for denied_role in ("agent", "jev", "resolver", "ingest"):
        assert not policy.permitted(record_kind="score", writer_role=denied_role)
    for allowed_role in ("scorer", "operator"):
        assert policy.permitted(record_kind="score", writer_role=allowed_role)


def test_a_resolution_with_an_agent_token_is_refused_before_append() -> None:
    policy = AuthorityPolicy()
    assert not policy.permitted(record_kind="resolution", writer_role="agent")


def test_a_jev_answer_routed_into_a_resolver_is_refused() -> None:
    policy = AuthorityPolicy()
    assert not policy.permitted(record_kind="resolution", writer_role="jev")
    assert not policy.permitted(record_kind="score", writer_role="jev")


def test_an_agent_may_write_a_proposal_but_no_other_authoritative_kind() -> None:
    policy = AuthorityPolicy()
    assert policy.permitted(record_kind="proposal", writer_role="agent")
    for restricted_kind in (
        "source_observation",
        "resolution",
        "score",
        "exclusion_record",
    ):
        assert not policy.permitted(record_kind=restricted_kind, writer_role="agent")


def test_source_observation_is_ingest_and_operator_only() -> None:
    policy = AuthorityPolicy()
    assert policy.permitted(record_kind="source_observation", writer_role="ingest")
    assert not policy.permitted(record_kind="source_observation", writer_role="agent")
    assert not policy.permitted(
        record_kind="source_observation", writer_role="resolver"
    )


def test_an_unrecognized_record_kind_is_refused() -> None:
    policy = AuthorityPolicy()
    with pytest.raises(ContractValidationError):
        policy.permitted(record_kind="not_a_kind", writer_role="operator")
