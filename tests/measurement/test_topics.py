"""SDD-IN-31: nominated-topic dispersion over known primary subfields."""

import math
from uuid import uuid4

import pytest

from research_agent.measurement.topics import topic_entropy


def _families(labels: list[str | None]) -> tuple[list[str], dict[str, str | None]]:
    ids = [str(uuid4()) for _ in labels]
    return ids, dict(zip(ids, labels, strict=True))


def test_one_topic_is_zero_and_equal_three_topics_is_ln_three() -> None:
    one, subfields = _families(["a", "a", "a"])
    even_ids, even_labels = _families(["a", "b", "c"])
    subfields.update(even_labels)
    result = topic_entropy(one, even_ids, subfields)
    assert result.nominated.entropy == 0.0
    assert result.nominated.distinct_subfields == 1
    assert result.pool.entropy == pytest.approx(math.log(3))


def test_unknown_only_has_null_entropy_and_full_unknown_fraction() -> None:
    ids, subfields = _families([None, None])
    result = topic_entropy(ids, ids, subfields)
    assert result.nominated.entropy is None
    assert result.nominated.unknown_fraction == 1.0
    assert result.nominated.distinct_subfields == 0


def test_duplicates_deduplicate_and_unknowns_do_not_enter_the_distribution() -> None:
    ids, subfields = _families(["a", "b", None])
    result = topic_entropy(ids + ids, ids, subfields)
    assert result.nominated.family_count == 3
    assert result.nominated.unknown_fraction == 1 / 3
    assert result.nominated.entropy == math.log(2)


def test_an_empty_nomination_set_has_no_figures() -> None:
    result = topic_entropy([], [], {})
    assert result.nominated.entropy is None
    assert result.nominated.unknown_fraction is None
