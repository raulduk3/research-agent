"""``bin/publish-digest``: a day's committed runs become the stored digest the
rating app serves (#370)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import sha256_hex
from research_agent.digest.cli import main
from research_agent.orchestration.daily import record_runs
from research_agent.platform.services.web import build_rating_app
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.queries import InspectorQueries
from research_agent.storage.resolutions import ResolutionRepository
from research_agent.storage.runs import RunRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository
from research_agent.storage.submissions import SubmissionRepository
from research_agent.evolution.population import PopulationStore
from research_agent.web.digest import load_digest
from tests.platform.test_launchers import (
    RATING_SCOPES,
    Layout,
    _capability,
    _storage,
    _storage_secrets,
    _storage_values,
    _free_port,
    _tls_secrets,
)
from tests.storage.test_http import _tls_material
from tests.storage.test_queries import (
    PRODUCER,
    QUESTION_A,
    QUESTION_B,
    Storage,
    genome,
    identity,
)

DAY = "2026-09-23"


@pytest.fixture
def tls(tmp_path: Path) -> tuple[Path, tuple[Any, ...]]:
    directory = tmp_path / "tls"
    directory.mkdir()
    return directory, _tls_material(directory)


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> Storage:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    kwargs: dict[str, Any] = {
        "producer": PRODUCER,
        "config_hash": "c" * 64,
        "retention_policy_hash": "d" * 64,
    }
    return Storage(
        database,
        store,
        ArtifactRepository(database, store),
        SheetRepository(database, store, **kwargs),
        SnapshotRepository(database, store, **kwargs),
        RunRepository(database, store, **kwargs),
        SubmissionRepository(database, store, **kwargs),
        ResolutionRepository(database, store, **kwargs),
        PopulationStore(database, store, **kwargs),
        InspectorQueries(database, store),
    )


def _issue_day(storage: Storage, state: Path, *, commit: bool) -> dict[str, str]:
    """One cs genome reads two papers; the first run commits when *commit*."""

    configuration_id = uuid4()
    storage.population.record_seed(
        configuration_id=configuration_id,
        genome=genome("lineage-1"),
        profile_hash="9" * 64,
        command_id=uuid4(),
    )
    sheet_hash, snapshot_hash = storage.seal_sheet(), storage.seal_snapshot()
    nominated, read = str(uuid4()), str(uuid4())
    runs = [
        storage.create_run(
            sheet_hash=sheet_hash,
            snapshot_hash=snapshot_hash,
            configuration_id=configuration_id,
            paper_id=paper_id,
            issued_question_ids=(QUESTION_A, QUESTION_B),
        )["run_id"]
        for paper_id in (nominated, read)
    ]
    if commit:
        evidence = storage.artifact(b'{"evidence":1}', kind="study_evidence")
        storage.submissions.accept_submission(
            identity=identity(),
            payload={
                "run_id": runs[0],
                "submission_id": str(uuid4()),
                "answers": [
                    {
                        "question_id": question,
                        "probability": 0.25,
                        "rationale": "the method section supports this",
                        "evidence_ids": [evidence],
                    }
                    for question in (QUESTION_A, QUESTION_B)
                ],
                "nomination": {
                    "paper_id": nominated,
                    "recommend": True,
                    "preference": 0.7,
                    "rationale": "worth reading",
                },
            },
        )
    (state / "days").mkdir(parents=True)
    (state / "days" / f"{DAY}.json").write_text(
        json.dumps({"from_date": DAY, "until_date": DAY}) + "\n"
    )
    record_runs(state, DAY, runs)
    return {"snapshot": snapshot_hash, "nominated": nominated, "read": read}


def _arguments(state: Path, dsn: str) -> list[str]:
    return ["--island", "cs", "--day", DAY, "--state", str(state), "--dsn", dsn]


def _digests(dsn: str) -> int:
    count = Database(dsn).transaction(
        lambda connection: connection.execute("SELECT count(*) FROM digests").fetchone()
    )
    assert count is not None
    return int(count[0])


@pytest.mark.integration
def test_a_committed_day_publishes_one_digest_the_rating_app_starts_on(
    storage: Storage,
    postgres_dsn: str,
    artifact_root: Path,
    tmp_path: Path,
    tls: tuple[Path, tuple[Any, ...]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = tmp_path / "state"
    day = _issue_day(storage, state, commit=True)

    assert main(_arguments(state, postgres_dsn)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert main(_arguments(state, postgres_dsn)) == 0
    assert json.loads(capsys.readouterr().out) == printed
    assert _digests(postgres_dsn) == 1

    digest = {"island": "cs", "batch_id": day["snapshot"]}
    assert printed["values"] == {"app": {"digest": digest}}
    directory, (_server, _client, fingerprint, *_rest) = tls
    layout = Layout(tmp_path)
    port = _free_port()
    with _storage(
        postgres_dsn,
        artifact_root,
        _server,
        _capability(fingerprint, "rating_app", RATING_SCOPES),
    ) as address:
        config = layout.load(
            layout.config(
                "rating",
                {
                    **_tls_secrets(layout, directory, client_ca=False),
                    **_storage_secrets(layout, directory),
                },
                host="127.0.0.1",
                port=port,
                public_origin=f"https://127.0.0.1:{port}",
                storage=_storage_values(address, RATING_SCOPES),
                **printed["values"]["app"],
            ),
            "rating",
        )
        build_rating_app(config)
        loaded = load_digest(config.storage_client(), **digest)

    # The nominated paper is the population entry, the paper read but never
    # nominated its control; each keeps its content-derived id on replay.
    assert {entry.paper_hash for entry in loaded.entries} == {
        sha256_hex(day[paper].encode()) for paper in ("nominated", "read")
    }
    assert all(isinstance(entry.digest_entry_id, UUID) for entry in loaded.entries)
    assert printed["entries"] == len(loaded.entries) == 2


@pytest.mark.integration
def test_a_day_without_a_committed_run_refuses_and_stores_nothing(
    storage: Storage,
    postgres_dsn: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = tmp_path / "state"
    _issue_day(storage, state, commit=False)

    assert main(_arguments(state, postgres_dsn)) == 2
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "no_committed_runs\n")
    assert _digests(postgres_dsn) == 0
