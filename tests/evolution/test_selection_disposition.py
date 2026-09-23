from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.evolution.policy import selection_disposition
from genome_fixtures import PROFILE_HASH, available_skill


def test_selection_disposition_reports_target_skill_and_manifest_hash() -> None:
    skills = (
        available_skill(0.4),
        available_skill(-0.2, target_id="late_citation_activity_365d"),
    )
    report = selection_disposition(
        configuration_manifest_hash=PROFILE_HASH, target_skills=skills
    )
    assert report.configuration_manifest_hash == PROFILE_HASH
    assert report.target_skills == skills


def test_selection_disposition_has_no_fitness_or_cost_objective_field() -> None:
    report = selection_disposition(
        configuration_manifest_hash=PROFILE_HASH, target_skills=(available_skill(0.9),)
    )
    fields = {field for field in report.__dataclass_fields__}
    assert fields == {"configuration_manifest_hash", "target_skills"}


def test_selection_disposition_rejects_a_missing_manifest_hash() -> None:
    with pytest.raises(ContractValidationError):
        selection_disposition(configuration_manifest_hash="", target_skills=())


def test_selection_disposition_rejects_non_target_skill_entries() -> None:
    with pytest.raises(ContractValidationError):
        selection_disposition(
            configuration_manifest_hash=PROFILE_HASH,
            target_skills=("not-a-target-skill",),
        )


def test_drastically_changed_inputs_change_only_the_report() -> None:
    # Changing the citation/preference/cost inputs behind target_skills can
    # only ever change what this report shows -- it exposes no operation
    # that could request a parent draw or a replacement, so there is no
    # population identity for it to disturb.
    low = selection_disposition(
        configuration_manifest_hash=PROFILE_HASH, target_skills=(available_skill(-0.9),)
    )
    high = selection_disposition(
        configuration_manifest_hash=PROFILE_HASH, target_skills=(available_skill(0.99),)
    )
    assert low.configuration_manifest_hash == high.configuration_manifest_hash
    assert not hasattr(low, "select") and not hasattr(low, "draw_parent")
