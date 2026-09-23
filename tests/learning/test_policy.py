from __future__ import annotations

import pytest

from research_agent.learning.policy import (
    TrainingJobProposal,
    TrainingOriginError,
    validate_training_origin,
)

PUBLISHED = "a" * 64
PARENT = ("b" * 64,)


def test_prediction_head_fitting_is_exempt_and_not_rejected() -> None:
    proposal = TrainingJobProposal("prediction_head_fit", None, ())
    validate_training_origin(proposal)


def test_absent_ancestry_cannot_create_a_checkpoint() -> None:
    proposal = TrainingJobProposal("encoder_finetune", None, ())
    with pytest.raises(TrainingOriginError, match="published-weight artifact"):
        validate_training_origin(proposal)


def test_missing_parent_chain_alone_is_refused() -> None:
    proposal = TrainingJobProposal("encoder_finetune", PUBLISHED, ())
    with pytest.raises(TrainingOriginError, match="published-weight artifact"):
        validate_training_origin(proposal)


def test_verifiable_ancestry_is_still_disabled_at_launch() -> None:
    proposal = TrainingJobProposal("encoder_finetune", PUBLISHED, PARENT)
    with pytest.raises(TrainingOriginError, match="disabled at launch"):
        validate_training_origin(proposal)


def test_non_exempt_proposal_validates_ancestry_hash_shape() -> None:
    with pytest.raises(ValueError):
        TrainingJobProposal("encoder_finetune", "not-a-hash", PARENT)


def test_parent_chain_must_be_an_immutable_tuple() -> None:
    with pytest.raises(TrainingOriginError, match="tuple"):
        TrainingJobProposal("encoder_finetune", PUBLISHED, list(PARENT))  # type: ignore[arg-type]
