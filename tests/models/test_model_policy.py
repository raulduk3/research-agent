"""Launch model policy: SDD-MD-03, SDD-FT-06, SDD-MD-01 and SDD-MD-04."""

from __future__ import annotations

import dataclasses
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID

import numpy as np
import pytest

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import (
    EMBEDDING_DIMENSION,
    EMBEDDING_FEATURE_DIMENSION,
    TargetDefinition,
)
from research_agent.learning.fit import DIMENSION, MaterializedPartition, fit_head
from research_agent.models.backend import resolved_file_hashes
from research_agent.models.manifest import (
    ADOPTED_CHECKPOINT_DATE,
    DOCUMENT_PREFIX,
    DTYPE,
    MAX_MODEL_TOKENS,
    MODEL_ID,
    POOLING,
    QUERY_PREFIX,
    REVISION,
    RepresentationManifest,
)
from research_agent.models.policy import (
    DEFERRED_ENCODER_OFFER_KINDS,
    EncoderOffer,
    FrozenWeightsError,
    LaunchModelError,
    RepresentationCandidate,
    reject_deferred_encoder,
    validate_launch_models,
    validate_representation_adoption,
    verify_frozen_weights,
)
from research_agent.outcomes.targets import definitions

TOKENIZER_HASH = "a" * 64
WEIGHT_HASH = "b" * 64
LATER_REVISION = "0" * 40


def _manifest(
    tokenizer_hash: str = TOKENIZER_HASH, weight_hash: str = WEIGHT_HASH
) -> RepresentationManifest:
    return RepresentationManifest(
        model_id=MODEL_ID,
        revision=REVISION,
        checkpoint_date=ADOPTED_CHECKPOINT_DATE,
        dtype=DTYPE,
        device="cuda",
        deterministic_algorithms=True,
        dimension=EMBEDDING_DIMENSION,
        pooling=POOLING,
        document_prefix=DOCUMENT_PREFIX,
        query_prefix=QUERY_PREFIX,
        max_model_tokens=MAX_MODEL_TOKENS,
        tokenizer_hash=tokenizer_hash,
        weight_hash=weight_hash,
        qualified=True,
    )


def _candidate(**changes: object) -> RepresentationCandidate:
    pinned = RepresentationCandidate(
        model_id=MODEL_ID,
        revision=REVISION,
        published_at=ADOPTED_CHECKPOINT_DATE,
        dimension=EMBEDDING_DIMENSION,
        tokenizer_hash=TOKENIZER_HASH,
        weight_hash=WEIGHT_HASH,
        qualified=True,
        activation_manifest_hash="c" * 64,
    )
    return dataclasses.replace(pinned, **changes)  # type: ignore[arg-type]


# SDD-MD-03


def test_a_newer_unqualified_revision_leaves_the_active_identity_unchanged() -> None:
    active = _manifest()
    identity = active.representation_hash
    decision = validate_representation_adoption(
        active,
        _candidate(
            revision=LATER_REVISION,
            published_at="2027-01-01",
            weight_hash="d" * 64,
            qualified=False,
            activation_manifest_hash=None,
        ),
    )
    assert decision.admitted is False
    assert decision.active is active
    assert decision.active.representation_hash == identity
    assert decision.reasons == (
        "revision_not_pinned",
        "weight_mismatch",
        "unqualified",
        "no_accepted_activation",
    )


def test_a_qualified_activated_newer_revision_is_still_refused() -> None:
    decision = validate_representation_adoption(
        _manifest(),
        _candidate(
            revision=LATER_REVISION, published_at="2027-01-01", weight_hash="d" * 64
        ),
    )
    assert decision.admitted is False
    assert "revision_not_pinned" in decision.reasons


def test_release_date_never_changes_the_decision() -> None:
    active = _manifest()
    older = validate_representation_adoption(
        active, _candidate(revision=LATER_REVISION, published_at="2020-01-01")
    )
    newer = validate_representation_adoption(
        active, _candidate(revision=LATER_REVISION, published_at="2030-01-01")
    )
    assert older == newer


def test_incompatible_dimension_or_tokenizer_prevents_admission() -> None:
    active = _manifest()
    wide = validate_representation_adoption(active, _candidate(dimension=1024))
    retokenized = validate_representation_adoption(
        active, _candidate(tokenizer_hash="e" * 64)
    )
    assert wide.reasons == ("incompatible_dimension",)
    assert retokenized.reasons == ("tokenizer_mismatch",)
    assert not wide.admitted and not retokenized.admitted


def test_the_pinned_qualified_activated_artifact_is_admitted() -> None:
    active = _manifest()
    decision = validate_representation_adoption(active, _candidate())
    assert decision.admitted is True
    assert decision.reasons == ()
    assert decision.active is active


# SDD-FT-06


def _snapshot(directory: Path) -> RepresentationManifest:
    (directory / "config.json").write_bytes(b'{"hidden_size": 768}')
    (directory / "tokenizer.json").write_bytes(b'{"model": "pinned"}')
    (directory / "model.safetensors").write_bytes(b"pinned-weights" * 64)
    tokenizer_hash, weight_hash = resolved_file_hashes(directory)
    return _manifest(tokenizer_hash, weight_hash)


def _ids(name: str, count: int) -> tuple[str, ...]:
    return tuple(
        str(UUID(bytes=sha256(f"{name}-{index}".encode()).digest()[:16], version=4))
        for index in range(count)
    )


def _partition(name: str, count: int, seed: int) -> MaterializedPartition:
    rng = np.random.default_rng(seed)
    x = np.zeros((count, DIMENSION), dtype=np.float32)
    x[:, :2] = rng.normal(size=(count, 2)).astype(np.float32)
    labels = np.zeros((count, 3), dtype=np.uint8)
    labels[:, :] = (np.arange(count) % 2).astype(np.uint8)[:, None]
    x[:, 0] += labels[:, 0].astype(np.int8) * 2 - 1
    embedding = x[:, :EMBEDDING_FEATURE_DIMENSION]
    norms = np.linalg.norm(embedding.astype(np.float64), axis=1)
    x[:, :EMBEDDING_FEATURE_DIMENSION] = embedding / norms[:, None].astype(np.float32)
    target_hashes = cast(
        tuple[str, str, str],
        tuple(sha256(row.to_canonical_json()).hexdigest() for row in _targets()),
    )
    return MaterializedPartition(
        x,
        labels,
        np.ones_like(labels),
        _ids(name, count),
        name,
        *("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64),
        target_hashes,
    )


def _targets() -> tuple[TargetDefinition, ...]:
    meta = RecordMeta(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        "2026-01-01T00:00:00.000000Z",
    )
    return tuple(definitions(meta))


def _fit_heads() -> float:
    """A weekly refresh: fit a real prediction head over saved features."""

    result = fit_head(
        _targets()[0], _partition("fit", 220, 1), _partition("development", 60, 2)
    )
    return result.selected_lambda


def test_a_real_head_fit_over_saved_features_passes(tmp_path: Path) -> None:
    manifest = _snapshot(tmp_path)
    selected = verify_frozen_weights(tmp_path, manifest, _fit_heads)
    assert selected > 0
    assert resolved_file_hashes(tmp_path) == (
        manifest.tokenizer_hash,
        manifest.weight_hash,
    )


def test_a_cycle_that_trains_both_models_together_is_refused(tmp_path: Path) -> None:
    manifest = _snapshot(tmp_path)

    def train_both() -> float:
        selected = _fit_heads()
        with (tmp_path / "model.safetensors").open("ab") as weights:
            weights.write(b"gradient-step")
        return selected

    with pytest.raises(FrozenWeightsError, match="changed"):
        verify_frozen_weights(tmp_path, manifest, train_both)


def test_a_cycle_that_writes_a_changed_copy_is_refused(tmp_path: Path) -> None:
    manifest = _snapshot(tmp_path)

    def write_copy() -> None:
        (tmp_path / "model-tuned.safetensors").write_bytes(b"tuned-weights")

    with pytest.raises(FrozenWeightsError):
        verify_frozen_weights(tmp_path, manifest, write_copy)


def test_stored_weights_that_drifted_before_the_cycle_are_refused(
    tmp_path: Path,
) -> None:
    manifest = _snapshot(tmp_path)
    (tmp_path / "model.safetensors").write_bytes(b"swapped")
    ran: list[bool] = []
    with pytest.raises(FrozenWeightsError, match="pinned manifest"):
        verify_frozen_weights(tmp_path, manifest, lambda: ran.append(True))
    assert ran == []


# SDD-MD-01 and SDD-MD-04


LAUNCH_ROLES = {
    "embedding": "f" * 64,
    "prediction_heads": "1" * 64,
    "agent": "agent-endpoint",
}


def test_the_launch_roles_pass_with_no_encoder_artifact() -> None:
    validate_launch_models(LAUNCH_ROLES)


def test_an_injected_trainable_encoder_role_is_refused() -> None:
    with pytest.raises(LaunchModelError, match="disabled_by_profile"):
        validate_launch_models({**LAUNCH_ROLES, "trainable_encoder": "2" * 64})


def test_a_missing_launch_role_is_refused() -> None:
    roles = dict(LAUNCH_ROLES)
    del roles["prediction_heads"]
    with pytest.raises(LaunchModelError, match="prediction_heads"):
        validate_launch_models(roles)


@pytest.mark.parametrize("kind", sorted(DEFERRED_ENCODER_OFFER_KINDS))
def test_every_encoder_offer_is_disabled_by_profile(kind: str) -> None:
    offer = EncoderOffer(kind, "answerdotai/ModernBERT-base")
    disposition = reject_deferred_encoder(offer)
    assert disposition.offer is offer
    assert disposition.disposition == "disabled_by_profile"
    assert "#51" in disposition.reason
    validate_launch_models(LAUNCH_ROLES)
