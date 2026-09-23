from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.papers.diagnostics import (
    DISABLED_DIAGNOSTIC_KINDS,
    DisabledDiagnostic,
    disabled_diagnostic,
)

DISABLED_KINDS = (
    "citation_intent",
    "repository_forks",
    "linked_artifact",
    "artifact_upvotes",
    "repository_stars",
    "discussion_mentions",
)


@pytest.mark.parametrize("kind", DISABLED_KINDS)
def test_each_launch_disabled_kind_refuses_as_unavailable(kind: str) -> None:
    """The launch adapter registry has no enabled job for any of these six
    kinds (EN-18 to EN-23, TDD-3.1.19 to TDD-3.1.24): the typed view is
    always unavailable/disabled_by_profile, never a substituted zero."""

    diagnostic = disabled_diagnostic(kind)
    assert diagnostic.status == "unavailable"
    assert diagnostic.reason == "disabled_by_profile"
    assert diagnostic.artifact_role == "card_diagnostic"
    assert diagnostic.kind == kind


@pytest.mark.parametrize("kind", DISABLED_KINDS)
def test_each_kind_names_its_own_reserved_provenance_shape(kind: str) -> None:
    diagnostic = disabled_diagnostic(kind)
    assert diagnostic.reserved_fields == DISABLED_DIAGNOSTIC_KINDS[kind]
    assert len(set(diagnostic.reserved_fields)) == len(diagnostic.reserved_fields)


def test_an_unadmitted_kind_is_rejected_rather_than_silently_disabled() -> None:
    with pytest.raises(ContractValidationError):
        disabled_diagnostic("repository_watchers")


def test_disabled_diagnostic_never_accepts_an_available_status() -> None:
    with pytest.raises(ContractValidationError):
        DisabledDiagnostic(
            artifact_role="card_diagnostic",
            kind="citation_intent",
            status="available",
            reason="disabled_by_profile",
            reserved_fields=DISABLED_DIAGNOSTIC_KINDS["citation_intent"],
        )


def test_injecting_arbitrary_diagnostic_values_does_not_change_the_refusal() -> None:
    """Whatever a caller might otherwise have supplied, the six disabled
    kinds always resolve to the same fixed refusal: this view takes no
    count, evidence or capture-time argument to substitute."""

    first = disabled_diagnostic("repository_stars")
    second = disabled_diagnostic("repository_stars")
    assert first == second
