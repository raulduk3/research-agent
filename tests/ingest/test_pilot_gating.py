"""Label-first gating (#144): resolve a family's labels before its documents.

`resolve_citation_gate` is the pure function the `openalex` stage calls to
decide, from already-retained citation pages alone, whether a family's three
automatic-citations-v1 targets are all known (`acquire`) or not (`skip`).
`_advance` is the operator decision that only enqueues `documents` for a
family once its own committed `openalex` report carries an `acquire`
decision, when `--gate-on-labels` is on; off (the default), it enqueues
`documents` unconditionally, exactly as before #144, so the committed
100-family pilot still reproduces.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.contracts import ProducerVersion, canonical_json, sha256_hex
from research_agent.contracts.learning import CitationFamilyRecord, PaginationPage
from research_agent.contracts.papers import SourceAccess, SourceInterval
from research_agent.ingest import pilot_run
from research_agent.ingest.arxiv import target_sets
from research_agent.ingest.fetch import FetchedOpenAlexPage, _match_request, _request
from research_agent.ingest.pilot import (
    OPENALEX_ADAPTER,
    Identity,
    PilotWorker,
    RateGate,
    Sources,
    resolve_citation_gate,
)
from research_agent.ingest.pilot_local import local_storage, worker_principal
from research_agent.learning.corpus import DEFAULT_CATEGORIES
from research_agent.outcomes.windows import instant, utc

FROZEN_AT = "2025-12-01T00:00:00.000000Z"
T0 = "2020-01-01T12:00:00.000000Z"
AS_OF = "2022-01-01T00:00:00.000000Z"
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
CONFIG_HASH = "c" * 64


def _family(number: int, day: int, field: str = "A") -> CitationFamilyRecord:
    return CitationFamilyRecord(
        schema_version=1,
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash=CONFIG_HASH,
        created_at=AS_OF,
        canonical_family_id=f"family-{number}",
        provider_work_ids=(f"W{number}",),
        external_ids=(),
        identity_evidence_hashes=("d" * 64,),
        representative_work_id=f"W{number}",
        representative_rule="lowest_provider_id",
        identity_state="resolved",
        possible_identity_cluster=None,
        target_link_work_ids=("W1000",),
        publication_interval=SourceInterval(
            utc(instant(T0) + timedelta(days=day)),
            utc(instant(T0) + timedelta(days=day + 1)),
        ),
        alternative_publication_intervals=(),
        date_state="known",
        primary_subfield_id=field,
        alternative_subfield_ids=(),
        subfield_state="known",
        raw_response_hashes=("e" * 64,),
        is_target_family_self_link=False,
    )


def _page(*, returned_count: int, complete: bool) -> PaginationPage:
    return PaginationPage(
        page_index=0,
        request_hash="a" * 64,
        response_hash="b" * 64,
        cursor_in=None,
        cursor_out=None if complete else "next",
        returned_count=returned_count,
        capture_started_at=AS_OF,
        capture_completed_at=AS_OF,
        status="completed",
        failure=None,
    )


def _family_spec(family_id: str = "2306.00001") -> dict[str, Any]:
    return {
        "family_id": family_id,
        "first_public_at": T0,
        "categories": ["cs.AI"],
        "author_count": 1,
        "version_count": 1,
    }


# --- resolve_citation_gate (pure) -----------------------------------------


def test_gate_acquires_when_every_target_resolves_to_a_known_state() -> None:
    families = tuple(_family(index + 1, 10) for index in range(5))
    citation_families = {sha256_hex(f.to_canonical_json()): f for f in families}
    gate = resolve_citation_gate(
        _family_spec(),
        target_match_state="matched",
        matched_work_id="W1000",
        pages=(_page(returned_count=5, complete=True),),
        citation_families=citation_families,
        match_started_at=AS_OF,
        match_completed_at=AS_OF,
        target_subfield=("A", "known"),
        as_of=AS_OF,
        producer=PRODUCER,
        config_hash=CONFIG_HASH,
    )
    assert gate["decision"] == "acquire"
    labels = gate["labels"]
    assert labels["citation_reach_365d"]["state"] == "true"
    assert labels["late_citation_activity_365d"]["state"] == "false"
    assert labels["cross_subfield_reach_365d"]["state"] == "false"
    assert all(v["state"] != "unknown" for v in labels.values())


def test_gate_skips_when_the_target_subfield_is_missing() -> None:
    gate = resolve_citation_gate(
        _family_spec(),
        target_match_state="matched",
        matched_work_id="W1000",
        pages=(_page(returned_count=0, complete=True),),
        citation_families={},
        match_started_at=AS_OF,
        match_completed_at=AS_OF,
        target_subfield=(None, "missing"),
        as_of=AS_OF,
        producer=PRODUCER,
        config_hash=CONFIG_HASH,
    )
    assert gate["decision"] == "skip"
    labels = gate["labels"]
    assert labels["citation_reach_365d"]["state"] == "false"
    assert labels["late_citation_activity_365d"]["state"] == "false"
    assert labels["cross_subfield_reach_365d"] == {
        "state": "unknown",
        "reason": "missing_target_subfield",
    }


def test_gate_skips_an_unmatched_target_without_reading_any_page() -> None:
    gate = resolve_citation_gate(
        _family_spec(),
        target_match_state="unmatched",
        matched_work_id=None,
        pages=(),
        citation_families={},
        match_started_at=AS_OF,
        match_completed_at=AS_OF,
        target_subfield=(None, "missing"),
        as_of=AS_OF,
        producer=PRODUCER,
        config_hash=CONFIG_HASH,
    )
    assert gate["decision"] == "skip"
    assert all(v["state"] == "unknown" for v in gate["labels"].values())


def test_gate_skips_an_incomplete_capture() -> None:
    gate = resolve_citation_gate(
        _family_spec(),
        target_match_state="matched",
        matched_work_id="W1000",
        pages=(_page(returned_count=0, complete=False),),
        citation_families={},
        match_started_at=AS_OF,
        match_completed_at=AS_OF,
        target_subfield=(None, "missing"),
        as_of=AS_OF,
        producer=PRODUCER,
        config_hash=CONFIG_HASH,
    )
    assert gate["decision"] == "skip"
    assert gate["labels"]["citation_reach_365d"]["state"] == "unknown"


# --- _advance: documents wait on the gate ----------------------------------


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


def _committed_select(families: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "state": "committed",
        "spec": {"stage": "select", "frozen_at": FROZEN_AT},
        "report_manifest": "manifest-select",
        "report": {"selected": families},
    }


def _committed_openalex(family_id: str, decision: str) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "state": "committed",
        "spec": {"stage": "openalex", "family": {"family_id": family_id}},
        "report_manifest": f"manifest-openalex-{family_id}",
        "report": {
            "stage": "openalex",
            "family_id": family_id,
            "state": "complete",
            "work": "W1",
            "records_received": 5,
            "gate": {
                "family_id": family_id,
                "labels": {},
                "decision": decision,
            },
        },
    }


def _families(*ids: str) -> list[dict[str, Any]]:
    return [{"family_id": family_id, "license_url": None} for family_id in ids]


def test_advance_enqueues_documents_only_for_families_the_gate_acquired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A", "B", "C")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_committed_openalex("A", "acquire"), _committed_openalex("B", "skip")]
            # C has no openalex report yet.
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    pilot_run._advance(storage, FROZEN_AT, gate_on_labels=True)
    documents = [spec for spec, _ in storage.enqueued if spec["stage"] == "documents"]
    assert {d["family"]["family_id"] for d in documents} == {"A"}


def test_advance_does_not_reenqueue_documents_already_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [_committed_openalex("A", "acquire")]
            + [
                {
                    "id": str(uuid4()),
                    "state": "running",
                    "spec": {"stage": "documents", "family": {"family_id": "A"}},
                    "report_manifest": None,
                    "report": None,
                }
            ]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    pilot_run._advance(storage, FROZEN_AT, gate_on_labels=True)
    documents = [spec for spec, _ in storage.enqueued if spec["stage"] == "documents"]
    assert documents == []


def test_advance_enqueues_documents_unconditionally_when_gate_on_labels_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    families = _families("A", "B")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return _committed_listings() + [_committed_select(families)]

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    pilot_run._advance(storage, FROZEN_AT)
    documents = [spec for spec, _ in storage.enqueued if spec["stage"] == "documents"]
    assert {d["family"]["family_id"] for d in documents} == {"A", "B"}


# --- _gate_counts (pure) ----------------------------------------------------


def test_gate_counts_tallies_selected_labeled_gated_out_acquired_embedded() -> None:
    selection = {
        "selected": [{"family_id": "A"}, {"family_id": "B"}, {"family_id": "C"}]
    }
    openalex = [
        {"gate": {"decision": "acquire"}},
        {"gate": {"decision": "skip"}},
        {},  # not yet resolved (gate_on_labels off, or the job hasn't committed)
    ]
    documents = [{"family_id": "A"}]
    assert pilot_run._gate_counts(selection, openalex, documents) == {
        "selected": 3,
        "labeled": 2,
        "gated_out": 1,
        "acquired": 1,
        "embedded": 0,
    }


def test_gate_counts_before_any_selection_report_exists() -> None:
    assert pilot_run._gate_counts(None, [], []) == {
        "selected": 0,
        "labeled": 0,
        "gated_out": 0,
        "acquired": 0,
        "embedded": 0,
    }


def test_ungated_advance_enqueues_families_a_running_build_has_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A build with some documents jobs must still queue the rest (release 1b).

    Lifting the gate on a build that already ran under it left documents
    frozen: the stage existed, so an all-or-nothing check skipped the bulk
    enqueue and the remaining families were never queued at all.
    """
    families = _families("A", "B", "C")

    def jobs(storage: object) -> list[dict[str, Any]]:
        return (
            _committed_listings()
            + [_committed_select(families)]
            + [
                {
                    "id": str(uuid4()),
                    "state": "committed",
                    "spec": {"stage": "documents", "family": {"family_id": "A"}},
                    "report_manifest": None,
                    "report": None,
                }
            ]
        )

    monkeypatch.setattr(pilot_run, "_jobs", jobs)
    storage = _RecordingStorage()
    assert pilot_run._advance(storage, FROZEN_AT) is True
    documents = [spec for spec, _ in storage.enqueued if spec["stage"] == "documents"]
    assert {d["family"]["family_id"] for d in documents} == {"B", "C"}


# --- the API path publishes its observation (#332) -------------------------


def _unreachable(*_: object) -> Any:
    raise AssertionError("the openalex stage never reaches this source")


def _openalex_page(
    request: tuple[str, bytes], body: dict[str, Any], at: str
) -> FetchedOpenAlexPage:
    path, parameters = request
    payload = canonical_json(body)
    access = SourceAccess(
        schema_version=1,
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash=CONFIG_HASH,
        created_at=at,
        source="openalex",
        requested_url="https://api.openalex.org" + path,
        request_parameters_hash=sha256_hex(parameters),
        adapter_version=OPENALEX_ADAPTER,
        capture_started_at=at,
        capture_completed_at=at,
        http_status=200,
        retained_payload_hash=sha256_hex(payload),
        retention_policy_hash="e" * 64,
        license_expression="CC0-1.0",
        permission_evidence_hash="d" * 64,
        failure=None,
    )
    return FetchedOpenAlexPage(access, payload, parameters, (), 0.0)


@pytest.mark.integration
@pytest.mark.parametrize("gate_on_labels", [False, True])
def test_a_committed_openalex_report_names_a_readable_observation(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path, gate_on_labels: bool
) -> None:
    """The prohibited alternative is the API path building the observation
    only to resolve its gate and dropping it, leaving a release nothing to
    read, with or without label gating."""
    identity = Identity(PRODUCER, CONFIG_HASH, "d" * 64, "e" * 64)
    matched = {
        "meta": {"next_cursor": None},
        "results": [{"id": "https://openalex.org/W7"}],
    }
    nothing = {"meta": {"next_cursor": None}, "results": []}
    sources = Sources(
        listing=_unreachable,
        document=_unreachable,
        openalex_match=lambda family, meta: _openalex_page(
            _match_request(family),
            matched,
            "2025-11-01T00:00:00.000000Z",
        ),
        openalex_cites=lambda work, cursor, meta: _openalex_page(
            _request((work,), cursor, 100), nothing, "2025-11-01T00:00:01.000000Z"
        ),
        arxiv_gate=RateGate(0.001),
        openalex_gate=RateGate(0.001),
    )
    family = {
        "family_id": "2306.00001",
        "first_public_at": T0,
        "author_count": 1,
        "categories": ["cs.AI"],
        "version_count": 1,
    }
    tls = tmp_path / "tls"
    with local_storage(
        dsn=postgres_dsn,
        artifact_root=artifact_root,
        tls_directory=tls,
        identity=identity,
    ) as storage:
        storage.enqueue({"stage": "openalex", "family": family, "record_budget": 10})
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=identity,
            sources=sources,
            gate_on_labels=gate_on_labels,
        )
        assert worker.run().jobs_completed == 1
        _, state, manifest = storage.job_rows()[-1]
        assert state == "committed" and manifest is not None
        report = storage.report(manifest)
        observation = storage.report(report["observation"])
    assert report["state"] == "complete"
    assert report["citation_families"] == 0
    assert report["pagination_complete"] is True
    assert ("gate" in report) is gate_on_labels
    assert observation["target_match_state"] == "matched"
    assert observation["target_provider_ids"] == ["W7"]
    assert observation["pagination_complete"] is True
    assert observation["citation_family_hashes"] == []
    assert len(observation["pages"]) == 1
