from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import (
    ContractValidationError,
    ProducerVersion,
    canonical_loads,
    sha256_hex,
)
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict
from research_agent.storage.forecasts import seal_forecasts
from research_agent.storage.resolutions import ResolutionRepository, append_resolution
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.submissions import SubmissionRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
PAST_HORIZON = "2020-01-01T00:00:00.000000Z"
AFTER_HORIZON = "2020-06-01T00:00:00.000000Z"
BEFORE_HORIZON = "2019-01-01T00:00:00.000000Z"


def identity(principal: UUID | None = None) -> CommandIdentity:
    return CommandIdentity(principal or uuid4(), uuid4(), uuid4(), uuid4())


def question(question_id: str, horizon: str = PAST_HORIZON) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "target_definition_hash": "a" * 64,
        "resolver_id": "citation-reach-v1",
        "resolver_version": 1,
        "horizon": horizon,
    }


def resolution_payload(
    forecast_id: str,
    question_id: str,
    *,
    version: int = 1,
    supersedes: str | None = None,
    status: str = "true",
    witness_ids: list[str] | None = None,
    completion_proof_hash: str | None = None,
    lower_bound: int = 5,
    upper_bound: int | None = None,
    as_of: str = AFTER_HORIZON,
    resolver_build_digest: str = "e" * 64,
    target_definition_hash: str = "a" * 64,
    observation_protocol_version: int = 1,
    observation_hash: str = "f" * 64,
    reason: str = "sufficient_positive_witnesses",
) -> dict[str, Any]:
    return {
        "forecast_id": forecast_id,
        "question_id": question_id,
        "as_of": as_of,
        "resolver_id": "citation-reach-v1",
        "resolver_build_digest": resolver_build_digest,
        "target_definition_hash": target_definition_hash,
        "observation_protocol_version": observation_protocol_version,
        "observation_hash": observation_hash,
        "status": status,
        "witness_ids": witness_ids or [],
        "completion_proof_hash": completion_proof_hash,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "reason": reason,
        "resolution_version": version,
        "supersedes_resolution_id": supersedes,
    }


class _Storage:
    def __init__(self, database: Database, artifact_root: Path) -> None:
        self.database = database
        self.store = ArtifactStore(artifact_root)
        kwargs = {
            "producer": PRODUCER,
            "config_hash": "c" * 64,
            "retention_policy_hash": "d" * 64,
        }
        self.artifacts = ArtifactRepository(database, self.store)
        self.sheets = SheetRepository(database, self.store, **kwargs)
        self.submissions = SubmissionRepository(database, self.store, **kwargs)
        self.resolutions = ResolutionRepository(database, self.store, **kwargs)

    def artifact(self, payload: bytes) -> str:
        digest = sha256_hex(payload)
        publication = self.artifacts.publish(
            [payload],
            expected_hash=digest,
            byte_length=len(payload),
            maximum_length=1024 * 1024,
            media_type="application/json",
            kind="study_evidence",
            input_hashes=(),
            producer_version=PRODUCER,
            config_hash="c" * 64,
            retention_policy_hash="d" * 64,
            command_id=uuid4(),
        )
        return publication.manifest_hash

    def sealed_forecast(self, horizon: str = PAST_HORIZON) -> tuple[str, str]:
        """Seal one fresh question and one sealed forecast against it."""
        question_id = str(uuid4())
        response = self.sheets.execute(
            "seal",
            identity=identity(),
            payload={"questions": [question(question_id, horizon)]},
        )
        sheet_hash = str(canonical_loads(response.body)["data"]["sheet_hash"])
        evidence = self.artifact(b'{"evidence":1}')
        result = seal_forecasts(
            self.submissions,
            identity=identity(),
            sheet_hash=sheet_hash,
            submitter_id=str(uuid4()),
            claims=[
                {
                    "kind": "forecast",
                    "question_id": question_id,
                    "evidence_hashes": [evidence],
                    "confidence": 0.6,
                }
            ],
            questions={question_id: horizon},
            retrieved_evidence_ids=frozenset({evidence}),
        )
        forecast_id = str(canonical_loads(result.body)["data"]["submission_ids"][0])
        return forecast_id, question_id


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> _Storage:
    return _Storage(Database(postgres_dsn), artifact_root)


def test_true_false_and_unresolvable_settlements_append(storage: _Storage) -> None:
    forecast_id, question_id = storage.sealed_forecast()
    result = append_resolution(
        storage.resolutions,
        identity=identity(),
        payload=resolution_payload(
            forecast_id, question_id, status="true", witness_ids=["family-1"]
        ),
    )
    data = dict(canonical_loads(result.body)["data"])
    assert data["resolution_id"]

    forecast_id, question_id = storage.sealed_forecast()
    result = append_resolution(
        storage.resolutions,
        identity=identity(),
        payload=resolution_payload(
            forecast_id,
            question_id,
            status="false",
            witness_ids=[],
            completion_proof_hash="b" * 64,
            lower_bound=0,
            upper_bound=0,
        ),
    )
    assert dict(canonical_loads(result.body)["data"])["resolution_id"]

    forecast_id, question_id = storage.sealed_forecast()
    result = append_resolution(
        storage.resolutions,
        identity=identity(),
        payload=resolution_payload(
            forecast_id,
            question_id,
            status="unresolvable",
            witness_ids=[],
            lower_bound=0,
            upper_bound=None,
            reason="incomplete_capture",
        ),
    )
    assert dict(canonical_loads(result.body)["data"])["resolution_id"]


def test_a_forecast_before_its_horizon_gets_no_resolution_record(
    storage: _Storage,
) -> None:
    forecast_id, question_id = storage.sealed_forecast(horizon=PAST_HORIZON)
    with pytest.raises(ContractValidationError, match="horizon"):
        append_resolution(
            storage.resolutions,
            identity=identity(),
            payload=resolution_payload(
                forecast_id,
                question_id,
                status="true",
                witness_ids=["family-1"],
                as_of=BEFORE_HORIZON,
            ),
        )
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM resolutions WHERE forecast_id=%s", (forecast_id,)
        ).fetchone()
    assert count is not None and count[0] == 0


def test_failed_append_leaves_the_forecast_unsettled(storage: _Storage) -> None:
    """A correction naming a resolution that was never actually appended rolls back clean."""
    forecast_id, question_id = storage.sealed_forecast()
    with pytest.raises(ContractValidationError, match="supersede"):
        append_resolution(
            storage.resolutions,
            identity=identity(),
            payload=resolution_payload(
                forecast_id,
                question_id,
                version=2,
                supersedes=str(uuid4()),
                status="true",
                witness_ids=["family-1"],
            ),
        )
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM resolutions WHERE forecast_id=%s", (forecast_id,)
        ).fetchone()
        ledger_count = connection.execute(
            "SELECT count(*) FROM ledger_records WHERE event_kind='resolution_recorded'"
        ).fetchone()
    assert count is not None and count[0] == 0
    assert ledger_count is not None and ledger_count[0] == 0


def test_correction_appends_lineage_and_original_forecast_stays_byte_identical(
    storage: _Storage,
) -> None:
    forecast_id, question_id = storage.sealed_forecast()
    with storage.database.connect() as connection:
        before = connection.execute(
            "SELECT status, confidence, horizon, sealed_at FROM submissions WHERE id=%s",
            (forecast_id,),
        ).fetchone()

    first = append_resolution(
        storage.resolutions,
        identity=identity(),
        payload=resolution_payload(
            forecast_id, question_id, status="true", witness_ids=["family-1"]
        ),
    )
    first_id = dict(canonical_loads(first.body)["data"])["resolution_id"]

    second = append_resolution(
        storage.resolutions,
        identity=identity(),
        payload=resolution_payload(
            forecast_id,
            question_id,
            version=2,
            supersedes=first_id,
            status="unresolvable",
            witness_ids=[],
            reason="uncertain_dates",
        ),
    )
    assert dict(canonical_loads(second.body)["data"])["resolution_id"]

    with storage.database.connect() as connection:
        after = connection.execute(
            "SELECT status, confidence, horizon, sealed_at FROM submissions WHERE id=%s",
            (forecast_id,),
        ).fetchone()
        rows = connection.execute(
            "SELECT resolution_version, status FROM resolutions"
            " WHERE forecast_id=%s ORDER BY resolution_version",
            (forecast_id,),
        ).fetchall()
    assert before == after
    assert [tuple(row) for row in rows] == [(1, "true"), (2, "unresolvable")]


def test_a_changed_resolver_build_under_the_same_name_is_rejected(
    storage: _Storage,
) -> None:
    forecast_id, question_id = storage.sealed_forecast()
    first = append_resolution(
        storage.resolutions,
        identity=identity(),
        payload=resolution_payload(
            forecast_id, question_id, status="true", witness_ids=["family-1"]
        ),
    )
    first_id = dict(canonical_loads(first.body)["data"])["resolution_id"]
    with pytest.raises(ContractValidationError, match="identity"):
        append_resolution(
            storage.resolutions,
            identity=identity(),
            payload=resolution_payload(
                forecast_id,
                question_id,
                version=2,
                supersedes=first_id,
                status="unresolvable",
                witness_ids=[],
                reason="uncertain_dates",
                resolver_build_digest="9" * 64,
            ),
        )


def test_retrying_the_same_request_returns_the_original_receipt(
    storage: _Storage,
) -> None:
    forecast_id, question_id = storage.sealed_forecast()
    payload = resolution_payload(
        forecast_id, question_id, status="true", witness_ids=["family-1"]
    )
    first = append_resolution(storage.resolutions, identity=identity(), payload=payload)
    second = append_resolution(
        storage.resolutions, identity=identity(), payload=payload
    )
    first_id = dict(canonical_loads(first.body)["data"])["resolution_id"]
    second_id = dict(canonical_loads(second.body)["data"])["resolution_id"]
    assert first_id == second_id
    with storage.database.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM resolutions WHERE forecast_id=%s", (forecast_id,)
        ).fetchone()
    assert count is not None and count[0] == 1


def test_a_different_request_at_the_same_version_conflicts(storage: _Storage) -> None:
    forecast_id, question_id = storage.sealed_forecast()
    append_resolution(
        storage.resolutions,
        identity=identity(),
        payload=resolution_payload(
            forecast_id, question_id, status="true", witness_ids=["family-1"]
        ),
    )
    with pytest.raises(StateConflict):
        append_resolution(
            storage.resolutions,
            identity=identity(),
            payload=resolution_payload(
                forecast_id, question_id, status="true", witness_ids=["family-2"]
            ),
        )
