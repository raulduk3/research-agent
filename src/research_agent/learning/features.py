"""Pure overlap-adjusted pooling and declared metadata block for head features."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from research_agent.contracts.canonical import canonical_json, canonical_loads
from research_agent.contracts.cards import PaperCardBody
from research_agent.contracts.learning import (
    EMBEDDING_FEATURE_DIMENSION,
    METADATA_DIMENSION,
    PRIMARY_CATEGORY_IDS,
)
from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_uuid4,
)

_NORM_TOLERANCE = 1e-5
_WEIGHT_TOLERANCE = 1e-8
_MAX_PASSAGE_TOKENS = 384
_PASSAGE_STRIDE = 320
_MIN_STANDARD_DEVIATION = 1e-12
# The closed metadata block order (#149 Appendix B): True where a column is
# standardized from the fitting partition, False where it keeps a fixed
# identity transform (one-hot columns and the code-link flag).
_STANDARDIZED_MASK: tuple[bool, ...] = (
    (True, True)
    + (False,) * len(PRIMARY_CATEGORY_IDS)
    + (True, True)
    + (False,) * 7
    + (False,)
    + (True,)
)


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


@dataclass(frozen=True, slots=True)
class CardMetadata:
    """The eight card-derived fields the declared metadata block is built from.

    Every field is available at seal time from the paper card and nothing
    else (#149 Appendix B); a caller that cannot resolve one of these must
    refuse the row rather than construct a partial ``CardMetadata`` (the
    dataclass admits no missing field). ``categories`` is ordered, primary
    first; the listed-category count is its length, not a stored field.
    """

    author_count: int
    categories: tuple[str, ...]
    abstract_tokens: int
    title_tokens: int
    first_available_weekday: int
    code_link: bool
    version_count: int

    def __post_init__(self) -> None:
        validate_non_negative_int(self.author_count)
        validate_non_negative_int(self.abstract_tokens)
        validate_non_negative_int(self.title_tokens)
        validate_positive_int(self.version_count)
        if not isinstance(self.categories, tuple) or not self.categories:
            raise ValueError("card metadata categories must be a nonempty tuple")
        for category in self.categories:
            validate_non_empty_string(category)
        if self.categories[0] not in PRIMARY_CATEGORY_IDS:
            raise ValueError("card metadata primary category is not admitted")
        if (
            type(self.first_available_weekday) is not int
            or not 0 <= self.first_available_weekday <= 6
        ):
            raise ValueError("card metadata weekday must be 0 to 6")
        if not isinstance(self.code_link, bool):
            raise ValueError("card metadata code_link must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "author_count": self.author_count,
            "categories": list(self.categories),
            "abstract_tokens": self.abstract_tokens,
            "title_tokens": self.title_tokens,
            "first_available_weekday": self.first_available_weekday,
            "code_link": self.code_link,
            "version_count": self.version_count,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())


def assemble_metadata_block(metadata: CardMetadata) -> tuple[float, ...]:
    """Build the closed-order metadata block (#149 Appendix B) from one card.

    Order: author count (log1p), listed-category count, primary-category
    one-hot over ``PRIMARY_CATEGORY_IDS``, abstract token count (log1p),
    title token count, first-availability weekday one-hot, a code-link
    flag, and the version count at seal. The list is closed; adding a
    feature is an amendment.
    """

    if not isinstance(metadata, CardMetadata):
        raise TypeError("metadata block requires a CardMetadata")
    primary_one_hot = tuple(
        1.0 if metadata.categories[0] == category else 0.0
        for category in PRIMARY_CATEGORY_IDS
    )
    weekday_one_hot = tuple(
        1.0 if metadata.first_available_weekday == day else 0.0 for day in range(7)
    )
    block = (
        math.log1p(metadata.author_count),
        float(len(metadata.categories)),
        *primary_one_hot,
        math.log1p(metadata.abstract_tokens),
        float(metadata.title_tokens),
        *weekday_one_hot,
        1.0 if metadata.code_link else 0.0,
        float(metadata.version_count),
    )
    if len(block) != METADATA_DIMENSION:
        raise ValueError("assembled metadata block width differs from the closed order")
    return _float32(block)


@dataclass(frozen=True, slots=True)
class Standardization:
    """Per-column mean and standard deviation for the metadata block.

    Fit once from the fitting partition and stored on the head bundle so
    calibration and promotion score the same input the fit saw (#149); a
    bundle without a stored standardization is refused. One-hot and flag
    columns carry the fixed identity transform (mean 0, standard
    deviation 1), never a fitted one.
    """

    mean: tuple[float, ...]
    std: tuple[float, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.mean, tuple)
            or not isinstance(self.std, tuple)
            or len(self.mean) != METADATA_DIMENSION
            or len(self.std) != METADATA_DIMENSION
        ):
            raise ValueError("standardization must cover the metadata block")
        for mean_value, std_value, standardize in zip(
            self.mean, self.std, _STANDARDIZED_MASK, strict=True
        ):
            if (
                not math.isfinite(mean_value)
                or not math.isfinite(std_value)
                or std_value <= 0
            ):
                raise ValueError(
                    "standardization values must be finite with a positive scale"
                )
            if not standardize and (mean_value != 0.0 or std_value != 1.0):
                raise ValueError(
                    "a fixed metadata column must carry the identity transform"
                )

    def to_dict(self) -> dict[str, Any]:
        return {"mean": list(self.mean), "std": list(self.std)}

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "Standardization":
        value = canonical_loads(raw)
        if not isinstance(value, dict) or set(value) != {"mean", "std"}:
            raise ValueError("standardization fields do not match schema")
        mean, std = value["mean"], value["std"]
        if not isinstance(mean, list) or not isinstance(std, list):
            raise ValueError("standardization arrays must be lists")
        return cls(
            tuple(float(cast(Any, item)) for item in mean),
            tuple(float(cast(Any, item)) for item in std),
        )


def fit_standardization(metadata_rows: Sequence[Sequence[float]]) -> Standardization:
    """Fit per-column mean/standard deviation over raw fitting-partition rows.

    One-hot and flag columns keep the fixed identity transform; a column
    with no fitting-partition variance keeps a unit scale rather than
    dividing by zero.
    """

    rows = [tuple(float(value) for value in row) for row in metadata_rows]
    if not rows:
        raise ValueError("standardization requires at least one fitting row")
    if any(len(row) != METADATA_DIMENSION for row in rows):
        raise ValueError("standardization rows must match the metadata block width")
    mean: list[float] = []
    std: list[float] = []
    for index, standardize in enumerate(_STANDARDIZED_MASK):
        if not standardize:
            mean.append(0.0)
            std.append(1.0)
            continue
        column = [row[index] for row in rows]
        column_mean = math.fsum(column) / len(column)
        variance = math.fsum((value - column_mean) ** 2 for value in column) / len(
            column
        )
        column_std = math.sqrt(variance)
        mean.append(column_mean)
        std.append(column_std if column_std > _MIN_STANDARD_DEVIATION else 1.0)
    return Standardization(tuple(mean), tuple(std))


def apply_head_input(
    embedding_block: Sequence[float],
    metadata_block: Sequence[float],
    standardization: Standardization,
) -> tuple[float, ...]:
    """Build one fitted head's input row: the single function every consumer uses.

    The embedding block passes through unchanged (its unit-L2 invariant is
    the caller's, not this function's); the metadata block is standardized
    under the bundle's stored transform. Fitting, calibration and
    promotion all call this with the same ``standardization`` so they score
    the identical input (#149).
    """

    if not isinstance(standardization, Standardization):
        raise TypeError("apply_head_input requires a Standardization")
    if len(embedding_block) != EMBEDDING_FEATURE_DIMENSION:
        raise ValueError("embedding block must match the embedding-only width")
    if len(metadata_block) != METADATA_DIMENSION:
        raise ValueError("metadata block must match the closed metadata width")
    standardized = (
        (float(value) - mean) / std
        for value, mean, std in zip(
            metadata_block, standardization.mean, standardization.std, strict=True
        )
    )
    return _float32([float(value) for value in embedding_block] + list(standardized))


# The fixed, versioned code-repository-link rule (#149 Appendix B): a host
# from this closed list named in the abstract or comments. Adding a host is
# an amendment, not a configuration change.
_CODE_HOSTS = ("github.com", "gitlab.com", "huggingface.co", "codeberg.org")


def detect_code_link(abstract: str | None, comments: str | None) -> bool:
    """Whether the abstract or comments name a code-repository host (#149)."""

    for text in (abstract, comments):
        if text is None:
            continue
        lowered = text.lower()
        if any(host in lowered for host in _CODE_HOSTS):
            return True
    return False


def card_metadata(card: PaperCardBody) -> CardMetadata:
    """Build the declared metadata block's source record from one paper card.

    Every feature is available at seal time from the card and nothing else
    (#149 Appendix B); a card whose first-availability weekday is unknown
    cannot supply one and this refuses rather than guessing a zero.
    """

    if not isinstance(card, PaperCardBody):
        raise TypeError("card_metadata requires a PaperCardBody")
    if card.first_available_weekday is None:
        raise ValueError("card metadata requires a known first-availability weekday")
    return CardMetadata(
        author_count=card.author_count,
        categories=card.categories,
        abstract_tokens=card.abstract_tokens,
        title_tokens=card.title_tokens,
        first_available_weekday=card.first_available_weekday,
        code_link=card.code_link,
        version_count=card.version_count,
    )
