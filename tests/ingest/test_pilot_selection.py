"""The pilot operator threads selection parameters into the select stage.

`_advance` enqueues the `select` stage once both listing sets have committed.
These tests exercise that decision and the job specification it builds
without a real storage service: `_jobs` is replaced with a fixed committed
listing state, and enqueue calls are recorded rather than published.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.ingest import pilot_run
from research_agent.ingest.arxiv import TARGET_SETS
from research_agent.learning.corpus import (
    DEFAULT_CAP,
    DEFAULT_PER_MONTH,
    DEFAULT_POPULATION_RULE,
    SELECTION_SEED,
)

FROZEN_AT = "2025-12-01T00:00:00.000000Z"


class _RecordingStorage:
    def __init__(self) -> None:
        self.enqueued: list[tuple[dict[str, Any], tuple[str, ...]]] = []

    def enqueue(self, spec: dict[str, Any], inputs: tuple[str, ...] = ()) -> UUID:
        self.enqueued.append((spec, inputs))
        return uuid4()


def _committed_listings() -> list[dict[str, Any]]:
    return [
        {
            "id": str(uuid4()),
            "state": "committed",
            "spec": {"stage": "listing", "set_spec": set_spec},
            "report_manifest": f"manifest-{set_spec}",
            "report": {"pages": 1},
        }
        for set_spec in TARGET_SETS
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
    assert inputs == ("manifest-cs:cs:AI", "manifest-cs:cs:LG")


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
