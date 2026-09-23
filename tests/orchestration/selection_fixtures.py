"""Shared fixtures for orchestration.selection tests."""

from __future__ import annotations

from research_agent.evolution.genome import Genome, GenomeStanding
from research_agent.scoring.scores import TargetSkill

TARGET_ID = "citation_reach_365d"
PROFILE_HASH = "a" * 64
INFRA_HASH = "b" * 64


def emphasis(prompt: str = "evidence-first") -> dict[str, str]:
    return {
        "prompt": prompt,
        "scan_policy": "breadth-first",
        "read_policy": "cite-first",
        "probability_assignment_rule": "single-sample",
    }


def genome(
    *,
    lineage_id: str = "lineage-1",
    island: str = "cs",
    founder: bool = False,
    prompt: str | None = None,
    infra_hash: str = INFRA_HASH,
    parent_hash: str | None = None,
) -> Genome:
    # Two distinct test genomes must not accidentally share a
    # configuration hash: default the prompt to the lineage id so callers
    # who only vary lineage_id still get distinguishable genomes.
    return Genome(
        lineage_id=lineage_id,
        island=island,
        infra_hash=infra_hash,
        emphasis=emphasis(
            prompt if prompt is not None else f"evidence-first-{lineage_id}"
        ),
        founder=founder,
        parent_hash=parent_hash,
    )


def available_skill(
    skill: float,
    *,
    skill_per_dollar: float | None = None,
    target_id: str = TARGET_ID,
) -> TargetSkill:
    has_cost = skill_per_dollar is not None
    return TargetSkill(
        target_id=target_id,
        agent_producer_id="agent-1",
        baseline_producer_id="baseline-1",
        support_count=30,
        agent_mean_brier=0.1,
        baseline_mean_brier=0.2,
        skill=skill,
        disposition="available",
        skill_per_dollar=skill_per_dollar,
        cost_microdollars=1_000_000 if has_cost else None,
        cost_record_ids=("11111111-1111-4111-8111-111111111111",) if has_cost else (),
        cost_disposition="available" if has_cost else "unavailable",
    )


def unavailable_skill(*, target_id: str = TARGET_ID) -> TargetSkill:
    return TargetSkill(
        target_id=target_id,
        agent_producer_id="agent-1",
        baseline_producer_id="baseline-1",
        support_count=0,
        agent_mean_brier=None,
        baseline_mean_brier=None,
        skill=None,
        disposition="unavailable",
        skill_per_dollar=None,
        cost_microdollars=None,
        cost_record_ids=(),
        cost_disposition="unavailable",
    )


def standing(
    *,
    genome_: Genome | None = None,
    resolved_claim_count: int = 30,
    grounding_share: float | None = 1.0,
    skill: float | None = 0.2,
    skill_per_dollar: float | None = None,
    proxy: float | None = None,
) -> GenomeStanding:
    target_skills = (
        (available_skill(skill, skill_per_dollar=skill_per_dollar),)
        if skill is not None
        else (unavailable_skill(),)
    )
    return GenomeStanding(
        genome=genome_ if genome_ is not None else genome(),
        resolved_claim_count=resolved_claim_count,
        grounding_share=grounding_share,
        target_skills=target_skills,
        proxy=proxy,
    )
