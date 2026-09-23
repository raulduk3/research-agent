"""SDD-AG-13: the scorer runs apart from any agent run or process."""

from __future__ import annotations

import inspect
from uuid import uuid4

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import TARGET_IDS
from research_agent.scoring.schemas import ScoreInput, ScoringResolution, ScoringRow
from research_agent.scoring.service import ScoringService

AS_OF = "2026-01-01T00:00:00.000000Z"
SEALED_AT = "2025-12-31T00:00:00.000000Z"
RESOLVED_AT = "2026-06-01T00:00:00.000000Z"
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, AS_OF)


def _row() -> ScoringRow:
    return ScoringRow(
        forecast_id=str(uuid4()),
        question_id=str(uuid4()),
        family_id=str(uuid4()),
        publication_week="2026-W01",
        target_id=TARGET_IDS[0],
        target_definition_hash="d" * 64,
        probability=0.3,
        sealed_at=SEALED_AT,
        eligible=True,
        ineligible_reason=None,
        resolution=ScoringResolution(True, RESOLVED_AT),
        settled_cost=None,
    )


def _score_input(rows: tuple[ScoringRow, ...]) -> ScoreInput:
    return ScoreInput(
        1,
        (),
        META.producer_version,
        META.config_hash,
        AS_OF,
        7,
        AS_OF,
        "e" * 64,
        rows,
        len(rows),
    )


def test_scoring_service_has_no_interface_that_takes_a_run_or_agent_process_argument() -> (
    None
):
    denied_substrings = ("run_id", "run_spec", "trace", "model_client", "agent_run")
    for name, method in vars(ScoringService).items():
        if name.startswith("_") or not callable(method):
            continue
        parameters = inspect.signature(method).parameters
        for parameter_name in parameters:
            lowered = parameter_name.lower()
            for denied in denied_substrings:
                assert denied not in lowered


def test_scoring_service_scores_the_same_ledger_with_no_agent_run_in_reach() -> None:
    score_input = _score_input((_row(),))
    service = ScoringService(producer_id="scorer-v1")

    first = service.score(score_input, computed_at=AS_OF)
    second = service.score(score_input, computed_at=AS_OF)

    assert first == second
