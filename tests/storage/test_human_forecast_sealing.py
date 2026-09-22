"""Real-storage proof that a granted rating_app capability can seal a human
forecast end to end (SDD-EN-34): the same sheet-then-submit path an agent
forecast uses, with the rater as submitter (TDD-3.1.33)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_loads, sha256_hex
from research_agent.ratings.forecasts import HumanQuestionOffer, seal_human_forecast
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.submissions import SubmissionRepository

pytestmark = pytest.mark.integration
PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
QUESTION_ID = "123e4567-e89b-42d3-a456-426614174000"
OPEN_HORIZON = "2999-01-01T00:00:00.000000Z"
PAST_HORIZON = "2000-01-01T00:00:00.000000Z"


def question(horizon: str) -> dict[str, Any]:
    return {
        "question_id": QUESTION_ID,
        "target_definition_hash": "a" * 64,
        "resolver_id": "citation_reach_365d",
        "resolver_version": 1,
        "horizon": horizon,
    }


@dataclass
class _Result:
    data: dict[str, Any]


class _RepositorySealCommands:
    """Adapts the real repositories to the ``SealCommands`` shape a rating
    app's storage client presents, so this test proves the seal against real
    storage rather than a substitute for it."""

    def __init__(
        self, sheets: SheetRepository, submissions: SubmissionRepository
    ) -> None:
        self._sheets = sheets
        self._submissions = submissions

    def seal_sheet(
        self,
        *,
        questions: tuple[dict[str, Any], ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> _Result:
        response = self._sheets.execute(
            "seal",
            identity=CommandIdentity(uuid4(), idempotency_key, command_id, request_id),
            payload={"questions": [dict(item) for item in questions]},
        )
        return _Result(dict(canonical_loads(response.body)["data"]))

    def submit(
        self,
        *,
        sheet_hash: str,
        submitter_id: UUID,
        claims: tuple[dict[str, Any], ...],
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> _Result:
        response = self._submissions.execute(
            "submit",
            identity=CommandIdentity(uuid4(), idempotency_key, command_id, request_id),
            payload={
                "sheet_hash": sheet_hash,
                "submitter_id": str(submitter_id),
                "claims": [dict(item) for item in claims],
            },
        )
        return _Result(dict(canonical_loads(response.body)["data"]))


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
        self.commands = _RepositorySealCommands(self.sheets, self.submissions)

    def view_receipt(self, payload: bytes) -> str:
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


@pytest.fixture
def storage(postgres_dsn: str, artifact_root: Path) -> _Storage:
    return _Storage(Database(postgres_dsn), artifact_root)


def _identity() -> dict[str, UUID]:
    return {"command_id": uuid4(), "request_id": uuid4(), "idempotency_key": uuid4()}


def test_rating_app_seals_a_raters_answer_once(storage: _Storage) -> None:
    offer = HumanQuestionOffer(question_id=QUESTION_ID, deadline=OPEN_HORIZON)
    receipt = storage.view_receipt(b'{"viewed":1}')
    rater_id = uuid4()

    result = seal_human_forecast(
        storage.commands,
        offer=offer,
        question=question(OPEN_HORIZON),
        rater_id=rater_id,
        probability=0.4,
        evidence_hashes=[receipt],
        **_identity(),
    )

    assert result.accepted is True
    assert result.reason is None


def test_a_duplicate_answer_is_refused_by_storages_own_idempotent_check(
    storage: _Storage,
) -> None:
    offer = HumanQuestionOffer(question_id=QUESTION_ID, deadline=OPEN_HORIZON)
    receipt = storage.view_receipt(b'{"viewed":1}')
    rater_id = uuid4()

    first = seal_human_forecast(
        storage.commands,
        offer=offer,
        question=question(OPEN_HORIZON),
        rater_id=rater_id,
        probability=0.4,
        evidence_hashes=[receipt],
        **_identity(),
    )
    second = seal_human_forecast(
        storage.commands,
        offer=offer,
        question=question(OPEN_HORIZON),
        rater_id=rater_id,
        probability=0.9,
        evidence_hashes=[receipt],
        **_identity(),
    )

    assert first.accepted is True
    assert second.accepted is False
    assert second.reason is not None and "already" in second.reason


def test_an_expired_question_is_refused_and_the_sheet_is_never_sealed(
    storage: _Storage,
) -> None:
    offer = HumanQuestionOffer(question_id=QUESTION_ID, deadline=PAST_HORIZON)
    receipt = storage.view_receipt(b'{"viewed":1}')
    now = datetime(2999, 6, 1, tzinfo=timezone.utc)

    result = seal_human_forecast(
        storage.commands,
        offer=offer,
        question=question(PAST_HORIZON),
        rater_id=uuid4(),
        probability=0.4,
        evidence_hashes=[receipt],
        now=now,
        **_identity(),
    )

    assert result.accepted is False
    assert result.reason == "offer expired"
    with storage.database.connect() as connection:
        count = connection.execute("SELECT count(*) FROM sheets").fetchone()
    assert count is not None and count[0] == 0
