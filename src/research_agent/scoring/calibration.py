"""Agent forecast calibration diagnostics: concentration and reliability (SDD-IN-05, IN-06).

Both read only sealed forecast probabilities and, for reliability, the explicit
true/false outcomes of resolved questions. They are descriptive diagnostics: the
concentration flag is reported apart from measured calibration, and neither
enters fitness or selection.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_probability,
    validate_sha256,
    validate_uuid4,
)

BIN_COUNT = 10
CONCENTRATION_WINDOW = 200
CONCENTRATION_THRESHOLD = 180
CONCENTRATION_DISPOSITIONS: frozenset[str] = frozenset(
    {"flagged", "not_flagged", "insufficient_support"}
)


def probability_bin(probability: float) -> int:
    """Return the fixed tenth a probability falls in; 1.0 belongs to the last."""

    validate_probability(probability)
    return min(math.floor(BIN_COUNT * probability), BIN_COUNT - 1)


@dataclass(frozen=True, slots=True)
class SealedProbability:
    """One sealed forecast probability of a configuration, in seal order."""

    configuration_id: str
    target_definition_hash: str
    seal_sequence: int
    probability: float

    def __post_init__(self) -> None:
        validate_non_empty_string(self.configuration_id)
        validate_sha256(self.target_definition_hash)
        if (
            not isinstance(self.seal_sequence, int)
            or isinstance(self.seal_sequence, bool)
            or self.seal_sequence < 1
        ):
            raise ContractValidationError("seal_sequence must be a positive integer")
        validate_probability(self.probability)


@dataclass(frozen=True, slots=True)
class ConcentrationReport:
    """The clustering diagnostic for one configuration and target definition."""

    configuration_id: str
    target_definition_hash: str
    profile_id: str
    observation_count: int
    bin_counts: tuple[int, ...]
    support_hash: str
    disposition: str

    def __post_init__(self) -> None:
        if self.disposition not in CONCENTRATION_DISPOSITIONS:
            raise ContractValidationError("disposition is not a recognized value")

    @property
    def flagged(self) -> bool:
        return self.disposition == "flagged"


def concentration_flag(
    forecasts: Sequence[SealedProbability], *, profile_id: str
) -> tuple[ConcentrationReport, ...]:
    """Flag each configuration/target whose latest 200 probabilities share one bin.

    Unresolved probabilities take part, and a flag is never a statement that the
    configuration is miscalibrated. A partition with fewer than 200 sealed
    probabilities reports insufficient support and no flag.
    """

    validate_non_empty_string(profile_id)
    partitions: dict[tuple[str, str], list[SealedProbability]] = defaultdict(list)
    for forecast in forecasts:
        key = (forecast.configuration_id, forecast.target_definition_hash)
        partitions[key].append(forecast)
    reports: list[ConcentrationReport] = []
    for (configuration_id, target_hash), members in sorted(partitions.items()):
        sequences = [member.seal_sequence for member in members]
        if len(set(sequences)) != len(sequences):
            raise ContractValidationError(
                "a seal sequence repeats within one partition"
            )
        latest = sorted(members, key=lambda member: member.seal_sequence)[
            -CONCENTRATION_WINDOW:
        ]
        counts = [0] * BIN_COUNT
        for member in latest:
            counts[probability_bin(member.probability)] += 1
        support_hash = sha256_hex(
            canonical_json(
                [[m.seal_sequence, m.probability] for m in latest],
            )
        )
        if len(latest) < CONCENTRATION_WINDOW:
            disposition = "insufficient_support"
        elif max(counts) >= CONCENTRATION_THRESHOLD:
            disposition = "flagged"
        else:
            disposition = "not_flagged"
        reports.append(
            ConcentrationReport(
                configuration_id=configuration_id,
                target_definition_hash=target_hash,
                profile_id=profile_id,
                observation_count=len(latest),
                bin_counts=tuple(counts),
                support_hash=support_hash,
                disposition=disposition,
            )
        )
    return tuple(reports)


@dataclass(frozen=True, slots=True)
class ResolvedProbability:
    """One resolved forecast: its stated probability and its true/false outcome."""

    question_id: str
    probability: float
    outcome: bool

    def __post_init__(self) -> None:
        validate_uuid4(self.question_id)
        validate_probability(self.probability)
        if not isinstance(self.outcome, bool):
            raise ContractValidationError("outcome must be a boolean")


@dataclass(frozen=True, slots=True)
class AgentReliabilityBin:
    """One fixed tenth of the probability range with its resolved members."""

    lower: float
    upper: float
    count: int
    mean_probability: float | None
    observed_fraction: float | None
    question_ids: tuple[str, ...]


def reliability_table(
    rows: Sequence[ResolvedProbability],
) -> tuple[AgentReliabilityBin, ...]:
    """Bin resolved probabilities into ten fixed tenths of one configuration/target.

    Each bin carries the mean of its stated probabilities, never its center, and
    the share of its questions that settled true. An empty bin carries no means.
    """

    members: list[list[ResolvedProbability]] = [[] for _ in range(BIN_COUNT)]
    for row in rows:
        members[probability_bin(row.probability)].append(row)
    table: list[AgentReliabilityBin] = []
    for index, group in enumerate(members):
        lower, upper = index / BIN_COUNT, (index + 1) / BIN_COUNT
        if not group:
            table.append(AgentReliabilityBin(lower, upper, 0, None, None, ()))
            continue
        table.append(
            AgentReliabilityBin(
                lower,
                upper,
                len(group),
                math.fsum(member.probability for member in group) / len(group),
                sum(member.outcome for member in group) / len(group),
                tuple(sorted(member.question_id for member in group)),
            )
        )
    return tuple(table)
