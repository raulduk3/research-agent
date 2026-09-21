"""Pure overlap-adjusted pooling for original-paper head features."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from research_agent.contracts.primitives import validate_sha256, validate_uuid4

_NORM_TOLERANCE = 1e-5
_WEIGHT_TOLERANCE = 1e-8
_MAX_PASSAGE_TOKENS = 384
_PASSAGE_STRIDE = 320


@dataclass(frozen=True, slots=True)
class PassageEmbedding:
    section_order: int
    token_start: int
    token_end_exclusive: int
    representation_hash: str
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        validate_sha256(self.representation_hash)
        if not isinstance(self.vector, tuple):
            raise TypeError("passage vector must be an immutable tuple")


@dataclass(frozen=True, slots=True)
class AssembledFeature:
    passage_weights: tuple[float, ...]
    pooled_passage: tuple[float, ...]
    combined: tuple[float, ...]


def overlap_adjusted_weights(
    passages: Sequence[PassageEmbedding],
) -> tuple[float, ...]:
    """Assign one total unit of weight to every included section token."""

    _validate_spans(passages)
    coverage: dict[tuple[int, int], int] = {}
    for passage in passages:
        for token in range(passage.token_start, passage.token_end_exclusive):
            key = (passage.section_order, token)
            coverage[key] = coverage.get(key, 0) + 1
    weights = tuple(
        math.fsum(
            1.0 / coverage[(passage.section_order, token)]
            for token in range(passage.token_start, passage.token_end_exclusive)
        )
        for passage in passages
    )
    count = len(coverage)
    if not math.isclose(
        math.fsum(weights),
        float(count),
        rel_tol=_WEIGHT_TOLERANCE,
        abs_tol=_WEIGHT_TOLERANCE * max(1, count),
    ):
        raise ValueError("passage weights do not preserve token coverage")
    return weights


def assemble_features(
    overview: tuple[float, ...],
    passages: tuple[PassageEmbedding, ...],
    *,
    representation_hash: str,
    representation_dimension: int,
    overview_representation_hash: str,
    source_version_id: str,
    original_version_id: str,
    extraction_coverage: str,
) -> AssembledFeature:
    """Build head input after a resolver supplies immutable eligibility fields.

    The storage adapter must resolve these identities from committed records. This
    numeric owner verifies their agreement but does not itself establish lineage.
    """

    validate_sha256(representation_hash)
    validate_sha256(overview_representation_hash)
    validate_uuid4(source_version_id)
    validate_uuid4(original_version_id)
    if type(representation_dimension) is not int or representation_dimension <= 0:
        raise ValueError("representation dimension must be a positive integer")
    if source_version_id != original_version_id:
        raise ValueError("head features require the first public version")
    if extraction_coverage != "complete":
        raise ValueError("head features require complete original extraction")
    if not isinstance(overview, tuple) or not isinstance(passages, tuple):
        raise TypeError("feature inputs must be immutable tuples")
    if not passages:
        raise ValueError("head features require at least one passage")
    dimension = len(overview)
    if dimension != representation_dimension:
        raise ValueError("overview dimension differs from representation")
    if overview_representation_hash != representation_hash or any(
        passage.representation_hash != representation_hash for passage in passages
    ):
        raise ValueError("embedding representation identity differs")
    _require_unit_vector(overview, "overview")
    for passage in passages:
        if len(passage.vector) != dimension:
            raise ValueError("embedding dimensions differ")
        _require_unit_vector(passage.vector, "passage")

    weights = overlap_adjusted_weights(passages)
    total_weight = math.fsum(weights)
    pooled64 = tuple(
        math.fsum(
            weight * float(passage.vector[coordinate])
            for weight, passage in zip(weights, passages, strict=True)
        )
        / total_weight
        for coordinate in range(dimension)
    )
    pooled_norm = _finite_norm(pooled64, "pooled passage")
    pooled = _float32(value / pooled_norm for value in pooled64)
    _require_unit_vector(pooled, "pooled passage")

    scale = math.sqrt(2.0)
    combined = _float32(
        [float(value) / scale for value in overview]
        + [float(value) / scale for value in pooled]
    )
    _require_unit_vector(combined, "combined feature")
    return AssembledFeature(weights, pooled, combined)


def _validate_spans(passages: Sequence[PassageEmbedding]) -> None:
    if not passages:
        raise ValueError("at least one passage is required")
    previous: PassageEmbedding | None = None
    for passage in passages:
        if (
            type(passage.section_order) is not int
            or type(passage.token_start) is not int
            or type(passage.token_end_exclusive) is not int
            or passage.section_order < 0
            or passage.token_start < 0
            or passage.token_end_exclusive <= passage.token_start
            or passage.token_end_exclusive - passage.token_start > _MAX_PASSAGE_TOKENS
        ):
            raise ValueError("passage token span is invalid")
        if previous is None or passage.section_order != previous.section_order:
            if passage.token_start != 0:
                raise ValueError("each section must begin at token zero")
            if previous is not None and passage.section_order <= previous.section_order:
                raise ValueError("passages are not in stable section order")
        else:
            if passage.token_start != previous.token_start + _PASSAGE_STRIDE:
                raise ValueError("passage spans do not use the fixed stride")
            if previous.token_end_exclusive - previous.token_start != 384:
                raise ValueError("only a final passage may be shorter than 384 tokens")
            if passage.token_end_exclusive <= previous.token_end_exclusive:
                raise ValueError("passage must contain a previously uncovered token")
        previous = passage


def _require_unit_vector(vector: Sequence[float], name: str) -> None:
    norm = _finite_norm(vector, name)
    if not math.isclose(norm, 1.0, rel_tol=_NORM_TOLERANCE, abs_tol=_NORM_TOLERANCE):
        raise ValueError(f"{name} vector must have unit L2 norm")


def _finite_norm(vector: Sequence[float], name: str) -> float:
    if any(isinstance(value, bool) for value in vector):
        raise ValueError(f"{name} vector must contain finite numeric values")
    values = tuple(float(value) for value in vector)
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{name} vector must be finite")
    norm = math.sqrt(math.fsum(value * value for value in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError(f"{name} vector must be nonzero")
    return norm


def _float32(values: Iterable[float]) -> tuple[float, ...]:
    return tuple(struct.unpack("<f", struct.pack("<f", value))[0] for value in values)
