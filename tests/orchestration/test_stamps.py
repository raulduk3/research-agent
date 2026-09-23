"""A run stamp in the run record's wire shape (#285)."""

from __future__ import annotations

import pytest

from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.runs import validate_model_identity
from research_agent.orchestration.stamps import RunStamp
from research_agent.storage.errors import UnavailableInput


def _stamp(bundles: dict[str, tuple[str, ...]]) -> RunStamp:
    return RunStamp(
        genome_hash="7" * 64,
        seed=1,
        agent_model_manifest="8" * 64,
        service_image_versions={"reader": "9" * 64},
        snapshot_hash="a" * 64,
        paper_card_manifest="b" * 64,
        prediction_head_bundles=bundles,
    )


def test_model_identity_names_one_bundle_per_target_and_null_for_none() -> None:
    stamp = _stamp(
        {TARGET_IDS[0]: ("1" * 64,), TARGET_IDS[1]: (), TARGET_IDS[2]: ("2" * 64,)}
    )
    identity = stamp.model_identity()
    assert identity == validate_model_identity(identity)
    assert identity["prediction_head_bundles"] == {
        TARGET_IDS[0]: "1" * 64,
        TARGET_IDS[1]: None,
        TARGET_IDS[2]: "2" * 64,
    }
    assert identity["agent_model_manifest"] == "8" * 64
    assert identity["service_image_versions"] == {"reader": "9" * 64}
    assert identity["paper_card_manifest"] == "b" * 64


def test_model_identity_refuses_a_target_scored_by_two_bundles() -> None:
    stamp = _stamp(
        {TARGET_IDS[0]: ("1" * 64, "2" * 64), TARGET_IDS[1]: (), TARGET_IDS[2]: ()}
    )
    with pytest.raises(
        UnavailableInput, match=f"mixed_prediction_head_bundles:{TARGET_IDS[0]}"
    ):
        stamp.model_identity()
