"""Dispersion of primary subfields among nominated papers (SDD-IN-31).

Shannon entropy in natural logs over the known labels of deduplicated nominated
families, beside the same figure for the same-day eligible pool. Unknown labels
are reported as a fraction and never counted as a topic; with no known label the
entropy is absent, not zero. Nothing here enters selection.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from research_agent.contracts.primitives import validate_uuid4


@dataclass(frozen=True, slots=True)
class TopicSpread:
    """Entropy, distinct known subfields and unknown coverage of one family set."""

    family_count: int
    distinct_subfields: int
    unknown_fraction: float | None
    entropy: float | None


@dataclass(frozen=True, slots=True)
class TopicDispersion:
    """The nominated set's spread with its same-day eligible-pool comparator."""

    nominated: TopicSpread
    pool: TopicSpread


def _spread(
    family_ids: Iterable[str], subfields: Mapping[str, str | None]
) -> TopicSpread:
    unique = frozenset(family_ids)
    for family_id in unique:
        validate_uuid4(family_id)
    labels = [subfields.get(family_id) for family_id in sorted(unique)]
    known = Counter(label for label in labels if label)
    total = sum(known.values())
    entropy = (
        -math.fsum((n / total) * math.log(n / total) for n in known.values())
        if total
        else None
    )
    return TopicSpread(
        family_count=len(unique),
        distinct_subfields=len(known),
        unknown_fraction=(len(unique) - total) / len(unique) if unique else None,
        entropy=None if entropy is None else abs(entropy),
    )


def topic_entropy(
    nominated_family_ids: Iterable[str],
    pool_family_ids: Iterable[str],
    subfields: Mapping[str, str | None],
) -> TopicDispersion:
    """Compare the nominated set's topic entropy with the eligible pool's.

    `subfields` maps a family id to its snapshot-valid primary subfield, or to
    None (or is missing the family) when unknown.
    """

    return TopicDispersion(
        nominated=_spread(nominated_family_ids, subfields),
        pool=_spread(pool_family_ids, subfields),
    )
