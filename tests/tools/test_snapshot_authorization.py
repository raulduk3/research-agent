from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.tools.snapshot import authorize_snapshot

RUN_ID = "123e4567-e89b-42d3-a456-426614174000"
SNAPSHOT_HASH = "a" * 64
OTHER_SNAPSHOT_HASH = "b" * 64


class _Lookup:
    def __init__(self, snapshot_hash: str) -> None:
        self._snapshot_hash = snapshot_hash
        self.calls: list[str] = []

    def snapshot_hash_for(self, run_id: str) -> str:
        self.calls.append(run_id)
        return self._snapshot_hash

    def allowed_tools_for(self, run_id: str) -> frozenset[str]:
        return frozenset({"query_cards"})


def test_authorize_snapshot_returns_the_runs_own_bound_hash() -> None:
    lookup = _Lookup(SNAPSHOT_HASH)
    assert authorize_snapshot(lookup, RUN_ID, SNAPSHOT_HASH) == SNAPSHOT_HASH
    assert lookup.calls == [RUN_ID]


def test_authorize_snapshot_rejects_a_newer_snapshot_named_by_the_caller() -> None:
    lookup = _Lookup(SNAPSHOT_HASH)
    with pytest.raises(ContractValidationError):
        authorize_snapshot(lookup, RUN_ID, OTHER_SNAPSHOT_HASH)


def test_authorize_snapshot_resolves_the_bound_hash_before_comparing() -> None:
    # The lookup is always consulted, even though the caller's guess is
    # wrong: authorization compares against the run's own record, never
    # trusts the caller's claim outright.
    lookup = _Lookup(SNAPSHOT_HASH)
    with pytest.raises(ContractValidationError):
        authorize_snapshot(lookup, RUN_ID, OTHER_SNAPSHOT_HASH)
    assert lookup.calls == [RUN_ID]
