from __future__ import annotations

from research_agent.web.projections import RatedEntryDetail, RatingDisclosure

DETAIL = RatedEntryDetail(
    probability=0.73,
    rationale="cites three independent replications",
    popularity_count=12,
    jev={"status": "available"},
    reading="a sourced summary",
)


def test_an_unrated_entry_omits_every_gated_field_entirely() -> None:
    projection = RatingDisclosure().project(DETAIL, rated=False)
    assert projection == {}


def test_a_rated_entry_discloses_all_five_gated_fields() -> None:
    projection = RatingDisclosure().project(DETAIL, rated=True)
    assert projection == {
        "probability": 0.73,
        "rationale": "cites three independent replications",
        "popularity_count": 12,
        "jev": {"status": "available"},
        "reading": "a sourced summary",
    }


def test_the_projection_never_carries_an_origin_field_rated_or_not() -> None:
    unrated = RatingDisclosure().project(DETAIL, rated=False)
    rated = RatingDisclosure().project(DETAIL, rated=True)
    assert "origin" not in unrated
    assert "origin" not in rated
