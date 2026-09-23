"""The next snapshot keeps every prior item and adds the acquired (decision 0025)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.snapshots.compose import compose_next_snapshot


def _item(card: str = "a") -> dict[str, Any]:
    return {
        "paper_family_id": str(uuid4()),
        "paper_version_id": str(uuid4()),
        "card_hash": card * 64,
        "overview_hash": None,
        "passage_index_hash": None,
        "graph_hash": None,
    }


def test_the_next_snapshot_keeps_the_prior_items_and_adds_the_acquired() -> None:
    prior = [_item(), _item()]
    acquired = [_item("b")]
    manifest = compose_next_snapshot(prior, acquired)
    versions = [item["paper_version_id"] for item in manifest["items"]]
    assert versions == sorted(v["paper_version_id"] for v in (*prior, *acquired))
    # Order of the inputs never changes the manifest.
    assert compose_next_snapshot(prior[::-1], acquired) == manifest
    # Re-adding an identical, already pinned item changes nothing.
    assert compose_next_snapshot(prior, [*acquired, prior[0]]) == manifest


def test_an_acquired_paper_never_rewrites_a_pinned_version() -> None:
    prior = [_item()]
    rewritten = {**prior[0], "card_hash": "c" * 64}
    with pytest.raises(ContractValidationError, match="rewrite"):
        compose_next_snapshot(prior, [rewritten])


def test_an_empty_snapshot_is_refused() -> None:
    with pytest.raises(ContractValidationError, match="at least one paper"):
        compose_next_snapshot([], [])
