import pytest

from research_agent.contracts.cards import AuthorCitationCapture
from research_agent.contracts.primitives import ContractValidationError
from research_agent.reader.counts import author_counts

AS_OF = "2026-06-01T00:00:00.000000Z"
EARLY = "2026-05-01T00:00:00.000000Z"
LATE = "2026-06-15T00:00:00.000000Z"


def _capture(author_id: str, count: int, captured_at: str) -> AuthorCitationCapture:
    return AuthorCitationCapture(author_id, count, "a" * 64, captured_at)


def test_available_capture_carries_its_source_and_time() -> None:
    (value,) = author_counts(
        author_ids=("alice",),
        captures=(_capture("alice", 12, EARLY),),
        as_of=AS_OF,
    )
    assert value.author_id == "alice"
    assert value.count == 12
    assert value.source_capture_hash == "a" * 64
    assert value.captured_at == EARLY
    assert value.reason is None


def test_missing_author_is_unavailable_with_no_fabricated_zero() -> None:
    (value,) = author_counts(author_ids=("bob",), captures=(), as_of=AS_OF)
    assert value.count is None
    assert value.reason == "missing_source"
    assert value.source_capture_hash is None
    assert value.captured_at is None


def test_capture_after_snapshot_is_unavailable_not_a_stale_number() -> None:
    (value,) = author_counts(
        author_ids=("carol",), captures=(_capture("carol", 99, LATE),), as_of=AS_OF
    )
    assert value.count is None
    assert value.reason == "not_available_as_of"


def test_a_later_replacement_cannot_mutate_a_pinned_snapshot() -> None:
    pinned = author_counts(
        author_ids=("dana",), captures=(_capture("dana", 5, EARLY),), as_of=AS_OF
    )
    with_late_replacement = author_counts(
        author_ids=("dana",), captures=(_capture("dana", 500, LATE),), as_of=AS_OF
    )
    assert pinned[0].count == 5
    assert with_late_replacement[0].reason == "not_available_as_of"
    assert with_late_replacement[0].count is None


def test_duplicate_author_ids_are_deduplicated_in_first_occurrence_order() -> None:
    result = author_counts(
        author_ids=("alice", "bob", "alice"),
        captures=(_capture("alice", 1, EARLY),),
        as_of=AS_OF,
    )
    assert [value.author_id for value in result] == ["alice", "bob"]


def test_captures_cannot_name_the_same_author_twice() -> None:
    with pytest.raises(ContractValidationError):
        author_counts(
            author_ids=("alice",),
            captures=(_capture("alice", 1, EARLY), _capture("alice", 2, EARLY)),
            as_of=AS_OF,
        )
