"""Launch model policy: pinned representation, frozen weights, no deferred encoder.

Appendix A: Launch profile fixes the model roles the first deployment serves.
`validate_representation_adoption` (SDD-MD-03) keeps the pinned representation
active whatever a candidate's release date says; `verify_frozen_weights`
(SDD-FT-06) hashes the embedding model's stored files around a weekly cycle
and refuses the cycle's output when they changed; `validate_launch_models`
(SDD-MD-01) and `reject_deferred_encoder` (SDD-MD-04) refuse the trainable
encoder until #51 admits it. None of these checks downloads, loads or
allocates a model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_date,
)

from .backend import resolved_file_hashes
from .manifest import MODEL_ID, REVISION, RepresentationManifest

__all__ = [
    "LAUNCH_MODEL_ROLES",
    "DEFERRED_ENCODER_OFFER_KINDS",
    "AdoptionDecision",
    "EncoderOffer",
    "EncoderOfferDisposition",
    "FrozenWeightsError",
    "LaunchModelError",
    "RepresentationCandidate",
    "reject_deferred_encoder",
    "validate_launch_models",
    "validate_representation_adoption",
    "verify_frozen_weights",
]

_T = TypeVar("_T")

# The only model roles the first deployment serves (SDD-MD-01).
LAUNCH_MODEL_ROLES: frozenset[str] = frozenset(
    {"embedding", "prediction_heads", "agent"}
)

# What SDD-MD-04 refuses for the deferred trainable encoder.
DEFERRED_ENCODER_OFFER_KINDS: frozenset[str] = frozenset(
    {"checkpoint_series", "training_job", "training_interface"}
)

_DISABLED_BY_PROFILE = "disabled_by_profile"


class FrozenWeightsError(ContractValidationError):
    """The embedding model's stored weights differ from the pinned manifest."""


class LaunchModelError(ContractValidationError):
    """An active model manifest names a role the launch profile does not serve."""


@dataclass(frozen=True, slots=True)
class RepresentationCandidate:
    """A representation offered to replace the active one.

    ``published_at`` is carried so the offer is complete, and deliberately
    never read: release recency is not evidence of anything (SDD-MD-03).
    ``activation_manifest_hash`` names an explicit accepted activation, the
    only route by which a different representation could enter.
    """

    model_id: str
    revision: str
    published_at: str
    dimension: int
    tokenizer_hash: str
    weight_hash: str
    qualified: bool
    activation_manifest_hash: str | None

    def __post_init__(self) -> None:
        validate_non_empty_string(self.model_id)
        validate_non_empty_string(self.revision)
        validate_utc_date(self.published_at)
        validate_sha256(self.tokenizer_hash)
        validate_sha256(self.weight_hash)
        if self.activation_manifest_hash is not None:
            validate_sha256(self.activation_manifest_hash)


@dataclass(frozen=True, slots=True)
class AdoptionDecision:
    """The representation that stays active, and why a candidate was refused."""

    active: RepresentationManifest
    admitted: bool
    reasons: tuple[str, ...]


def validate_representation_adoption(
    active: RepresentationManifest, candidate: RepresentationCandidate
) -> AdoptionDecision:
    """Decide a candidate against the pinned representation (SDD-MD-03).

    The active manifest is returned unchanged in every case, so no vector
    identity moves. A candidate is admitted only when it is the pinned
    artifact itself, qualified and explicitly activated; a different revision
    needs a new launch profile and a separately qualified namespace, which no
    offer at run time can supply. Incompatible dimension or tokenizer identity
    is reported alongside, so the refusal names every defect at once.
    """

    reasons: list[str] = []
    if candidate.model_id != MODEL_ID or candidate.revision != REVISION:
        reasons.append("revision_not_pinned")
    if candidate.dimension != active.dimension:
        reasons.append("incompatible_dimension")
    if candidate.tokenizer_hash != active.tokenizer_hash:
        reasons.append("tokenizer_mismatch")
    if candidate.weight_hash != active.weight_hash:
        reasons.append("weight_mismatch")
    if not candidate.qualified:
        reasons.append("unqualified")
    if candidate.activation_manifest_hash is None:
        reasons.append("no_accepted_activation")
    return AdoptionDecision(active, not reasons, tuple(reasons))


def verify_frozen_weights(
    snapshot_dir: Path, manifest: RepresentationManifest, cycle: Callable[[], _T]
) -> _T:
    """Run *cycle* and return its result only if the embedding files are unchanged.

    The stored tokenizer and weight files are hashed before the cycle and
    must match the manifest; they are hashed again after it and must match
    the first reading. A cycle that trains the embedding model, or writes a
    changed copy of its weights beside the pinned ones, raises
    ``FrozenWeightsError`` and its result is discarded (SDD-FT-06).
    """

    pinned = (manifest.tokenizer_hash, manifest.weight_hash)
    if resolved_file_hashes(snapshot_dir) != pinned:
        raise FrozenWeightsError(
            "stored embedding files do not match the pinned manifest"
        )
    result = cycle()
    if resolved_file_hashes(snapshot_dir) != pinned:
        raise FrozenWeightsError("the cycle changed the embedding model's weights")
    return result


@dataclass(frozen=True, slots=True)
class EncoderOffer:
    """A checkpoint series, training job or training interface for the encoder."""

    kind: str
    name: str

    def __post_init__(self) -> None:
        if self.kind not in DEFERRED_ENCODER_OFFER_KINDS:
            raise ContractValidationError(
                "kind must be checkpoint_series, training_job or training_interface"
            )
        validate_non_empty_string(self.name)


@dataclass(frozen=True, slots=True)
class EncoderOfferDisposition:
    """The recorded refusal of one encoder offer."""

    offer: EncoderOffer
    disposition: str
    reason: str


def reject_deferred_encoder(offer: EncoderOffer) -> EncoderOfferDisposition:
    """Refuse *offer* as disabled by profile, before any file, network or model use.

    The trainable encoder enters only through #51 (SDD-MD-04). The refusal
    is a value the caller records; the frozen embedding bundle is untouched.
    """

    return EncoderOfferDisposition(
        offer,
        _DISABLED_BY_PROFILE,
        "the trainable encoder is held out of the launch profile until #51",
    )


def validate_launch_models(roles: Mapping[str, str]) -> None:
    """Check active model manifests, by role, against the launch roles (SDD-MD-01).

    *roles* maps each active role to its manifest identity. Every launch role
    must be present; any other role, a trainable encoder among them, is
    refused. An absent encoder artifact is simply not a role and never
    blocks readiness.
    """

    for identity in roles.values():
        validate_non_empty_string(identity)
    extra = sorted(set(roles) - LAUNCH_MODEL_ROLES)
    if extra:
        raise LaunchModelError(
            f"roles {extra} are {_DISABLED_BY_PROFILE}; the launch profile serves "
            "only the frozen embedding model, prediction heads and agent endpoint"
        )
    missing = sorted(LAUNCH_MODEL_ROLES - set(roles))
    if missing:
        raise LaunchModelError(f"launch roles {missing} have no active manifest")
