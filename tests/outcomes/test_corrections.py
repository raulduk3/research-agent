from dataclasses import replace

import pytest

from research_agent.contracts import sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.outcomes.corrections import CorrectionRequest, CorrectionService
from research_agent.outcomes.resolve import Resolver
from research_agent.outcomes.targets import definitions, registry
from tests.outcomes.test_resolution import AS_OF, META, scenario


def test_source_correction_propagates_new_evidence_into_a_superseding_label() -> None:
    paper, original_observation, original_stored = scenario(4, complete=True)
    target = definitions(META)[0]
    original = Resolver(
        original_stored.__getitem__, META, registry=registry(META)
    ).resolve_target(target, paper, original_observation, AS_OF)
    assert original.state == "false"

    _, replacement_raw, replacement_stored = scenario(6, complete=False)
    replacement_observation = replace(
        replacement_raw,
        paper_family_id=paper.family_id,
        original_version_id=paper.version_id,
    )
    service = CorrectionService(
        replacement_stored.__getitem__, META, registry=registry(META)
    )
    corrected = service.correct(
        target,
        paper,
        original,
        CorrectionRequest(
            reason="replacement_source_evidence",
            defect_description=None,
            observation=replacement_observation,
        ),
        AS_OF,
    )
    assert corrected.state == "true"
    assert corrected.supersedes_label_hash == sha256_hex(original.to_canonical_json())
    assert corrected.correction_hash is not None


def test_a_preference_only_correction_is_refused() -> None:
    paper, observation, stored = scenario(4, complete=True)
    target = definitions(META)[0]
    original = Resolver(
        stored.__getitem__, META, registry=registry(META)
    ).resolve_target(target, paper, observation, AS_OF)
    service = CorrectionService(stored.__getitem__, META, registry=registry(META))
    with pytest.raises(ContractValidationError, match="new preserved evidence"):
        service.correct(
            target,
            paper,
            original,
            CorrectionRequest(
                reason="replacement_source_evidence",
                defect_description=None,
                observation=observation,
            ),
            AS_OF,
        )


def test_an_unaccepted_correction_reason_is_refused() -> None:
    paper, observation, stored = scenario(4, complete=True)
    target = definitions(META)[0]
    original = Resolver(
        stored.__getitem__, META, registry=registry(META)
    ).resolve_target(target, paper, observation, AS_OF)
    service = CorrectionService(stored.__getitem__, META, registry=registry(META))
    with pytest.raises(ContractValidationError, match="accepted evidence or defect"):
        service.correct(
            target,
            paper,
            original,
            CorrectionRequest(
                reason="preference", defect_description=None, observation=observation
            ),
            AS_OF,
        )


def test_a_resolver_defect_correction_requires_a_description() -> None:
    paper, observation, stored = scenario(4, complete=True)
    target = definitions(META)[0]
    original = Resolver(
        stored.__getitem__, META, registry=registry(META)
    ).resolve_target(target, paper, observation, AS_OF)
    service = CorrectionService(stored.__getitem__, META, registry=registry(META))
    with pytest.raises(ContractValidationError, match="defect description"):
        service.correct(
            target,
            paper,
            original,
            CorrectionRequest(
                reason="resolver_defect",
                defect_description=None,
                observation=observation,
            ),
            AS_OF,
        )
