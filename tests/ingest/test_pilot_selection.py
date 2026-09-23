"""The pilot operator threads selection parameters into the select stage.

`_advance` enqueues the `select` stage once both listing sets have committed.
These tests exercise that decision and the job specification it builds
without a real storage service: `_jobs` is replaced with a fixed committed
listing state, and enqueue calls are recorded rather than published.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest import pilot_run
from research_agent.ingest.arxiv import parse_listing_page, target_sets
from research_agent.ingest.pilot import (
    Identity,
    PilotWorker,
    _Lease,
    derived_uuid,
)
from research_agent.learning.corpus import (
    DEFAULT_CAP,
    DEFAULT_CATEGORIES,
    DEFAULT_PER_MONTH,
    DEFAULT_POPULATION_RULE,
    SELECTION_SEED,
)

FROZEN_AT = "2025-12-01T00:00:00.000000Z"


class _RecordingStorage:
    def __init__(self) -> None:
        self.enqueued: list[tuple[dict[str, Any], tuple[str, ...]]] = []

    def enqueue(
        self,
        spec: dict[str, Any],
        inputs: tuple[str, ...] = (),
        *,
        ahead: bool = False,
    ) -> UUID:
        self.enqueued.append((spec, inputs))
        return uuid4()


def _committed_listings(
    categories: tuple[str, ...] = DEFAULT_CATEGORIES,
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(uuid4()),
            "state": "committed",
            "spec": {"stage": "listing", "set_spec": set_spec},
            "report_manifest": f"manifest-{set_spec}",
            "report": {"pages": 1},
        }
        for set_spec in target_sets(categories)
    ]


def test_advance_enqueues_select_with_default_selection_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pilot_run, "_jobs", lambda storage: _committed_listings())
    storage = _RecordingStorage()
    assert pilot_run._advance(storage, FROZEN_AT) is True
    ((spec, inputs),) = storage.enqueued
    assert spec["stage"] == "select"
    assert spec["frozen_at"] == FROZEN_AT
    assert spec["population_rule"] == DEFAULT_POPULATION_RULE
    assert spec["cap"] == DEFAULT_CAP
    assert spec["seed"] == SELECTION_SEED
    assert spec["per_month"] == DEFAULT_PER_MONTH
    assert spec["categories"] == list(DEFAULT_CATEGORIES)
    assert inputs == tuple(f"manifest-{s}" for s in target_sets(DEFAULT_CATEGORIES))


def test_advance_threads_explicit_selection_parameters_into_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pilot_run, "_jobs", lambda storage: _committed_listings())
    storage = _RecordingStorage()
    rule = "every cs.AI or cs.LG family, uniform, seeded, capped at 10000"
    assert (
        pilot_run._advance(
            storage,
            FROZEN_AT,
            population_rule=rule,
            cap=10000,
            seed=1,
            per_month=0,
        )
        is True
    )
    ((spec, _inputs),) = storage.enqueued
    assert spec["population_rule"] == rule
    assert spec["cap"] == 10000
    assert spec["seed"] == 1
    assert spec["per_month"] == 0


def test_advance_derives_sets_from_explicit_categories_and_reproduces_the_original_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: --categories cs.AI,cs.LG must enqueue exactly the two
    # listing sets the committed pilot used before categories were
    # configurable.
    categories = ("cs.AI", "cs.LG")
    monkeypatch.setattr(
        pilot_run, "_jobs", lambda storage: _committed_listings(categories)
    )
    storage = _RecordingStorage()
    assert pilot_run._advance(storage, FROZEN_AT, categories=categories) is True
    ((spec, inputs),) = storage.enqueued
    assert spec["categories"] == ["cs.AI", "cs.LG"]
    assert inputs == ("manifest-cs:cs:AI", "manifest-cs:cs:LG")


def test_advance_does_not_enqueue_select_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def jobs_with_select(storage: object) -> list[dict[str, Any]]:
        return _committed_listings() + [
            {
                "id": str(uuid4()),
                "state": "running",
                "spec": {"stage": "select", "frozen_at": FROZEN_AT},
                "report_manifest": None,
                "report": None,
            }
        ]

    monkeypatch.setattr(pilot_run, "_jobs", jobs_with_select)
    storage = _RecordingStorage()
    assert pilot_run._advance(storage, FROZEN_AT) is False
    assert storage.enqueued == []


_SAMPLE = Path(__file__).parents[1] / "fixtures" / "sources" / "arxiv-oai-sample.xml"


def _select(spec: dict[str, Any]) -> dict[str, Any]:
    """The select stage over the committed sample listing page; only the
    storage-backed page reader is replaced."""

    worker = PilotWorker(
        cast(Any, None),
        worker_id=uuid4(),
        identity=Identity(
            ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
        ),
        sources=cast(Any, None),
    )

    def pages(lease: _Lease) -> Iterator[bytes]:
        yield _SAMPLE.read_bytes()

    worker._listing_pages = pages  # type: ignore[method-assign]
    return worker._select(_Lease(uuid4(), 1, "f" * 64, spec))


def test_select_never_draws_a_family_an_agent_requested() -> None:
    spec = {
        "stage": "select",
        "frozen_at": "2024-01-01T00:00:00.000000Z",
        "per_month": 0,
        "cap": 10,
    }
    listed = {r.family_id for r in parse_listing_page(_SAMPLE.read_bytes()).records}
    drawn = _select(spec)
    selected = [f["family_id"] for f in drawn["selected"]]
    assert len(selected) >= 2 and set(selected) <= listed
    assert drawn["requested_skipped"] == 0

    requested = selected[0]
    paper_family_id = str(derived_uuid("gate-paper-family", requested))
    again = _select({**spec, "requested": {paper_family_id: str(uuid4())}})
    assert [f["family_id"] for f in again["selected"]] == selected[1:]
    assert again["requested_skipped"] == 1
    assert again["population_hash"] != drawn["population_hash"]
