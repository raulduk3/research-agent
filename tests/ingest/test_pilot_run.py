"""Schedule the `openalex` stage ahead of `documents` so labels resolve first (#151).

`_advance` enqueues each family's `openalex` job `ahead` of the queue and
expedites a straggler left over from a build started before this change.
`_openalex_pending` and `_drain` are the run loop's own decision: one job at
a time while a selected family's labels are still unresolved, unbounded once
every family has been observed. `_jobs` caches each spec and report by its
immutable manifest hash so a job's changing state is re-read without
re-reading content that cannot change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest import pilot_run
from research_agent.ingest.arxiv import fetch_bucket_pdf, target_sets
from research_agent.ingest.pilot import Identity, PilotWorker, RunSummary
from research_agent.learning.corpus import (
    DEFAULT_CAP,
    DEFAULT_CATEGORIES,
    DEFAULT_PER_MONTH,
    DEFAULT_POPULATION_RULE,
    SELECTION_SEED,
)

FROZEN_AT = "2025-12-01T00:00:00.000000Z"
EARLY = datetime(2025, 1, 1, tzinfo=timezone.utc)
LATE = EARLY + timedelta(hours=1)


class _RecordingStorage:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self.expedited: list[UUID] = []

    def enqueue(
        self,
        spec: dict[str, Any],
        inputs: tuple[str, ...] = (),
        *,
        ahead: bool = False,
    ) -> UUID:
        job_id = uuid4()
        self.enqueued.append(
            {"spec": spec, "inputs": inputs, "ahead": ahead, "id": job_id}
        )
        return job_id

    def expedite(self, job_id: UUID) -> None:
        self.expedited.append(job_id)


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


def _committed_select(families: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "state": "committed",
        "spec": {"stage": "select", "frozen_at": FROZEN_AT},
        "report_manifest": "manifest-select",
        "report": {"selected": families},
    }


def _committed_openalex(family_id: str, records_received: int = 0) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "state": "committed",
        "spec": {"stage": "openalex", "family": {"family_id": family_id}},
        "report_manifest": f"manifest-openalex-{family_id}",
        "report": {"records_received": records_received},
    }


def _failed_openalex(family_id: str) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "state": "failed",
        "spec": {
            "stage": "openalex",
            "family": {"family_id": family_id},
            "record_budget": 100,
        },
        "report_manifest": None,
        "report": None,
    }


def _queued_openalex(family_id: str) -> dict[str, Any]:
    return dict(_failed_openalex(family_id), state="queued")


def _failed_documents(family_id: str) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "state": "failed",
        "spec": {"stage": "documents", "family": {"family_id": family_id}},
        "report_manifest": None,
        "report": None,
    }


def _families(*ids: str) -> list[dict[str, Any]]:
    return [{"family_id": family_id, "license_url": None} for family_id in ids]


# --- _advance: the next openalex job is scheduled ahead ---------------------


def test_advance_enqueues_the_next_openalex_job_ahead_of_the_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A", "B")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return _committed_listings() + [_committed_select(families)]

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    pilot_run._advance(storage, FROZEN_AT)
    openalex = [e for e in storage.enqueued if e["spec"]["stage"] == "openalex"]
    assert len(openalex) == 1
    assert openalex[0]["ahead"] is True
    assert openalex[0]["spec"]["family"]["family_id"] == "A"


def test_advance_uses_the_given_record_cap_for_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A", "B")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_committed_openalex("A", records_received=40)]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    pilot_run._advance(storage, FROZEN_AT, record_cap=50)
    openalex = [e for e in storage.enqueued if e["spec"]["stage"] == "openalex"]
    assert openalex[0]["spec"]["record_budget"] == 10


# --- _advance: expedite a straggler left over from before #151 -------------


def test_advance_expedites_a_queued_openalex_job_scheduled_behind_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A")
    documents_job = {
        "id": str(uuid4()),
        "state": "queued",
        "scheduled_at": EARLY,
        "spec": {"stage": "documents", "family": {"family_id": "A"}},
        "report_manifest": None,
        "report": None,
    }
    openalex_job = {
        "id": str(uuid4()),
        "state": "queued",
        "scheduled_at": LATE,
        "spec": {"stage": "openalex", "family": {"family_id": "A"}},
        "report_manifest": None,
        "report": None,
    }

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [documents_job, openalex_job]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    pilot_run._advance(storage, FROZEN_AT)
    assert storage.expedited == [UUID(openalex_job["id"])]


def test_advance_does_not_expedite_an_openalex_job_already_ahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A")
    documents_job = {
        "id": str(uuid4()),
        "state": "queued",
        "scheduled_at": LATE,
        "spec": {"stage": "documents", "family": {"family_id": "A"}},
        "report_manifest": None,
        "report": None,
    }
    openalex_job = {
        "id": str(uuid4()),
        "state": "queued",
        "scheduled_at": EARLY,
        "spec": {"stage": "openalex", "family": {"family_id": "A"}},
        "report_manifest": None,
        "report": None,
    }

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [documents_job, openalex_job]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    pilot_run._advance(storage, FROZEN_AT)
    assert storage.expedited == []


# --- _openalex_pending -------------------------------------------------------


def test_openalex_pending_is_false_before_a_selection_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pilot_run, "_jobs", lambda storage: _committed_listings())
    assert pilot_run._openalex_pending(object()) is False


def test_openalex_pending_is_true_until_every_family_is_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A", "B")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_committed_openalex("A")]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    assert pilot_run._openalex_pending(object()) is True


def test_openalex_pending_is_false_once_every_family_is_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A", "B")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_committed_openalex("A"), _committed_openalex("B")]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    assert pilot_run._openalex_pending(object()) is False


# --- _jobs: cache specs and reports by manifest hash -------------------------


class _FakeConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def execute(self, *_args: object, **_kwargs: object) -> "_FakeConnection":
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeDatabase:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def transaction(self, operation: Any) -> Any:
        return operation(_FakeConnection(self._rows))


class _FakeStorage:
    def __init__(self, rows: list[tuple[Any, ...]], reports: dict[str, Any]) -> None:
        self.database = _FakeDatabase(rows)
        self._reports = reports
        self.report_calls: list[str] = []

    def report(self, manifest: str) -> dict[str, Any]:
        self.report_calls.append(manifest)
        return self._reports[manifest]


def test_jobs_reflects_a_state_change_without_re_reading_a_cached_spec() -> None:
    job_id = uuid4()
    now = datetime.now(timezone.utc)
    manifest = f"manifest-{uuid4().hex}"
    reports = {manifest: {"stage": "listing", "set_spec": "cs:cs:AI"}}
    storage = _FakeStorage([(job_id, "queued", now, manifest, None)], reports)

    first = pilot_run._jobs(storage)
    assert first[0]["state"] == "queued"
    assert storage.report_calls == [manifest]

    storage.database = _FakeDatabase([(job_id, "running", now, manifest, None)])
    second = pilot_run._jobs(storage)
    assert second[0]["state"] == "running"
    assert second[0]["spec"] == reports[manifest]
    assert storage.report_calls == [manifest]


# --- _drain: one job at a time while labels are unresolved -------------------


class _FakeWorker:
    def __init__(self, summaries: list[RunSummary]) -> None:
        self._summaries = list(summaries)
        self.calls: list[int | None] = []

    def run(self, *, maximum_jobs: int | None = None) -> RunSummary:
        self.calls.append(maximum_jobs)
        return self._summaries.pop(0)


def test_drain_claims_one_job_at_a_time_while_openalex_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = [True, True, False]
    monkeypatch.setattr(pilot_run, "_openalex_pending", lambda storage: pending.pop(0))
    monkeypatch.setattr(pilot_run, "_advance", lambda *args, **kwargs: False)
    worker = _FakeWorker(
        [RunSummary(1, False), RunSummary(1, False), RunSummary(0, False)]
    )
    summary = pilot_run._drain(
        object(),
        worker,
        FROZEN_AT,
        population_rule=DEFAULT_POPULATION_RULE,
        cap=DEFAULT_CAP,
        seed=SELECTION_SEED,
        per_month=DEFAULT_PER_MONTH,
        categories=DEFAULT_CATEGORIES,
        gate_on_labels=False,
        record_cap=pilot_run.RECORD_CAP,
    )
    # Old behavior (a regression this guards against) would call worker.run()
    # unbounded every iteration: [None, None, None].
    assert worker.calls == [1, 1, None]
    assert summary == RunSummary(2, False)


def test_drain_stops_on_a_budget_exhausted_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pilot_run, "_openalex_pending", lambda storage: False)
    monkeypatch.setattr(pilot_run, "_advance", lambda *args, **kwargs: True)
    worker = _FakeWorker([RunSummary(3, True)])
    summary = pilot_run._drain(
        object(),
        worker,
        FROZEN_AT,
        population_rule=DEFAULT_POPULATION_RULE,
        cap=DEFAULT_CAP,
        seed=SELECTION_SEED,
        per_month=DEFAULT_PER_MONTH,
        categories=DEFAULT_CATEGORIES,
        gate_on_labels=False,
        record_cap=pilot_run.RECORD_CAP,
    )
    assert worker.calls == [None]
    assert summary == RunSummary(3, True)


# --- failed families are passed over, recorded, and requeued on demand ------


def test_advance_moves_past_a_failed_openalex_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A family whose openalex job failed does not hold the stage: the next
    family is enqueued and the failed one is not retried on its own."""
    families = _families("A", "B", "C")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_failed_openalex("A"), _committed_openalex("B", 7)]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    assert pilot_run._advance(storage, FROZEN_AT, record_cap=100) is True
    openalex = [e for e in storage.enqueued if e["spec"]["stage"] == "openalex"]
    assert [e["spec"]["family"]["family_id"] for e in openalex] == ["C"]
    # Only committed reports count against the record cap.
    assert openalex[0]["spec"]["record_budget"] == 93


def test_advance_waits_on_a_requeued_family(monkeypatch: pytest.MonkeyPatch) -> None:
    families = _families("A", "B")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_failed_openalex("A"), _queued_openalex("A")]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    pilot_run._advance(storage, FROZEN_AT)
    assert [e for e in storage.enqueued if e["spec"]["stage"] == "openalex"] == []
    assert pilot_run._openalex_pending(object()) is True


def test_openalex_pending_is_false_once_every_family_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A", "B")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_failed_openalex("A"), _committed_openalex("B")]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    assert pilot_run._openalex_pending(object()) is False


def test_requeue_enqueues_a_fresh_job_for_each_failed_family_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A", "B", "C")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [
                _failed_openalex("A"),
                _committed_openalex("B", 7),
                _committed_openalex("C"),
                _failed_documents("B"),
            ]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    enqueued = pilot_run.requeue(storage, record_cap=100)
    assert [(e["stage"], e["family_id"]) for e in enqueued] == [
        ("openalex", "A"),
        ("documents", "B"),
    ]
    by_stage = {e["spec"]["stage"]: e for e in storage.enqueued}
    assert by_stage["openalex"]["spec"]["family"]["family_id"] == "A"
    assert by_stage["openalex"]["spec"]["record_budget"] == 93
    assert by_stage["openalex"]["ahead"] is True
    assert by_stage["openalex"]["inputs"] == ("manifest-select",)
    assert by_stage["documents"]["spec"] == {
        "stage": "documents",
        "family": {"family_id": "B"},
    }
    assert by_stage["documents"]["inputs"] == ("manifest-select",)


def test_requeue_narrows_to_the_named_stage_and_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A", "B")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_failed_openalex("A"), _failed_openalex("B"), _failed_documents("A")]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    enqueued = pilot_run.requeue(storage, stages=("openalex",), families=("B",))
    assert [(e["stage"], e["family_id"]) for e in enqueued] == [("openalex", "B")]


def test_requeue_does_not_repeat_a_family_already_requeued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_failed_openalex("A"), _queued_openalex("A")]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    assert pilot_run.requeue(storage) == []
    assert storage.enqueued == []


def test_requeue_lists_a_failed_set_as_its_next_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def jobs(storage: object) -> list[dict[str, Any]]:
        listings = _committed_listings()
        listings[0] = dict(
            listings[0],
            state="failed",
            spec=dict(listings[0]["spec"], attempt=1),
            report=None,
            report_manifest=None,
        )
        return listings

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    enqueued = pilot_run.requeue(storage, stages=("listing",))
    assert len(enqueued) == 1 and enqueued[0]["stage"] == "listing"
    assert storage.enqueued[0]["spec"]["attempt"] == 2


def test_worker_takes_the_operating_budget_over_a_stale_spec() -> None:
    """A job queued under an exhausted budget must not keep that zero for ever.

    Release 1b queued 528 openalex jobs while its budget was spent, so each
    carried `record_budget: 0`. A spec is an immutable artifact, so raising
    the operator's budget could not reach them: the worker claimed one, found
    the budget spent, stopped, and the job was re-leased without end.
    """
    worker = PilotWorker(
        cast(Any, object()),
        worker_id=uuid4(),
        identity=cast(Any, object()),
        sources=cast(Any, object()),
        record_budget=31_000_000,
    )
    assert worker._record_budget == 31_000_000

    unset = PilotWorker(
        cast(Any, object()),
        worker_id=uuid4(),
        identity=cast(Any, object()),
        sources=cast(Any, object()),
    )
    assert unset._record_budget is None


def test_sources_wires_the_bucket_as_the_pilot_s_pdf_source() -> None:
    identity = Identity(
        ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, "d" * 64, "e" * 64
    )
    sources = pilot_run._sources(identity)
    assert sources.pdf_bucket is fetch_bucket_pdf
