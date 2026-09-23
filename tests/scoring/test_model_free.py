"""SDD-SR-03: the scorer's dependency graph carries no language model."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from uuid import uuid4

from research_agent.contracts import ProducerVersion, RecordMeta
from research_agent.contracts.learning import TARGET_IDS
from research_agent.scoring.schemas import ScoreInput, ScoringResolution, ScoringRow
from research_agent.scoring.scores import score_ledger
from research_agent.scoring.service import ScoringService

_DENIED_MODULE_PREFIXES = ("research_agent.agents", "research_agent.models")

AS_OF = "2026-01-01T00:00:00.000000Z"
SEALED_AT = "2025-12-31T00:00:00.000000Z"
RESOLVED_AT = "2026-06-01T00:00:00.000000Z"
META = RecordMeta(1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, AS_OF)


def _module_path(module_name: str) -> Path:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None
    return Path(spec.origin)


def _imported_module_names(module_name: str) -> set[str]:
    tree = ast.parse(_module_path(module_name).read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_scoring_service_dependency_graph_imports_no_agent_or_model_module() -> None:
    for module_name in (
        "research_agent.scoring.service",
        "research_agent.scoring.scores",
        "research_agent.scoring.schemas",
        "research_agent.scoring.baselines",
    ):
        imported = _imported_module_names(module_name)
        for denied_prefix in _DENIED_MODULE_PREFIXES:
            offending = {
                name
                for name in imported
                if name == denied_prefix or name.startswith(denied_prefix + ".")
            }
            assert not offending, f"{module_name} imports {offending}"


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


def test_scoring_service_matches_the_pure_scorer_with_every_model_unreachable() -> None:
    score_input = _score_input((_row(),))
    service = ScoringService(producer_id="scorer-v1")
    from_service = service.score(score_input, computed_at=AS_OF)
    from_pure_function = score_ledger(
        score_input, producer_id="scorer-v1", computed_at=AS_OF
    )
    assert from_service == from_pure_function
