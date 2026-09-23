import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.versions import SupersessionChain, SupersessionRecord

OLD = "a" * 64
NEW = "b" * 64
NEWER = "c" * 64


def _record(old: str, new: str, decision: str = "0001") -> SupersessionRecord:
    return SupersessionRecord(
        old_hash=old,
        new_hash=new,
        reason="replaced by a later profile",
        decision_id=decision,
        effective_at="2026-09-22T00:00:00.000000Z",
    )


def test_supersession_record_rejects_a_self_loop() -> None:
    with pytest.raises(ContractValidationError):
        _record(OLD, OLD)


def test_supersession_chain_preserves_the_old_choice_after_activation() -> None:
    chain = SupersessionChain()
    chain.add(_record(OLD, NEW))
    assert chain.is_superseded(OLD)
    assert not chain.is_superseded(NEW)
    assert chain.resolve_current(OLD) == NEW


def test_supersession_chain_resolves_through_a_multi_step_lineage() -> None:
    chain = SupersessionChain()
    chain.add(_record(OLD, NEW))
    chain.add(_record(NEW, NEWER))
    assert chain.resolve_current(OLD) == NEWER
    assert [record.new_hash for record in chain.history_of(OLD)] == [NEW, NEWER]


def test_supersession_chain_rejects_a_second_edge_from_the_same_old_hash() -> None:
    chain = SupersessionChain()
    chain.add(_record(OLD, NEW))
    with pytest.raises(ContractValidationError):
        chain.add(_record(OLD, NEWER))


def test_supersession_chain_rejects_a_cycle() -> None:
    chain = SupersessionChain()
    chain.add(_record(OLD, NEW))
    with pytest.raises(ContractValidationError):
        chain.add(_record(NEW, OLD))


def test_resolve_current_is_a_no_op_for_an_unsuperseded_choice() -> None:
    chain = SupersessionChain()
    assert chain.resolve_current(OLD) == OLD
