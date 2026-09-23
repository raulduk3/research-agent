"""The scorer's declared boundary: sealed ledger data in, a score out (SDD-SR-03, AG-13).

`ScoringService` is the one place a caller reaches to turn a `ScoreInput` into
a `ScoreRecord` or a `TargetSkill`. Its entire dependency graph is
`research_agent.scoring.scores`: pure numeric functions over already-sealed
forecast and resolution rows. It imports nothing from `research_agent.agents`
or `research_agent.models`, so nothing here can reach a language model, and it
takes no run id, trace or agent-model client as an argument, so no agent run
has an interface to it. It runs the same computation whether or not any agent
run or process exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts.primitives import validate_non_empty_string
from research_agent.scoring.schemas import ScoreInput
from research_agent.scoring.scores import (
    ScoreRecord,
    TargetSkill,
    score_ledger,
    target_skill,
)


@dataclass(frozen=True, slots=True)
class ScoringService:
    """Computes scores and skill from sealed ledger data alone.

    `producer_id` names this service's own deployment; it never names an
    agent run. Every method is a pure function of its arguments and of
    nothing else: neither method reads a clock, draws a random value or
    calls a model.
    """

    producer_id: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.producer_id)

    def score(self, score_input: ScoreInput, *, computed_at: str) -> ScoreRecord:
        """Score one target's rows in *score_input* (SDD-IN-01, SR-03)."""

        return score_ledger(
            score_input, producer_id=self.producer_id, computed_at=computed_at
        )

    def skill(self, agent: ScoreRecord, baseline: ScoreRecord) -> TargetSkill:
        """Report *agent*'s skill against *baseline* over their matched support (FT-12)."""

        return target_skill(agent, baseline)
