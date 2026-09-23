import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.contracts.verification import (
    VerificationRecord,
    VerificationRegistry,
    VerificationUnavailable,
)

REVISION = "d556a88e332558790b210f7bdbe87da2fa94a8d8"


def _verified(**overrides: object) -> VerificationRecord:
    values: dict[str, object] = {
        "artifact_identity": "nomic-ai/modernbert-embed-base",
        "component_revision": REVISION,
        "source_url": "https://huggingface.co/nomic-ai/modernbert-embed-base",
        "status": "verified",
        "checked_at": "2026-09-22T00:00:00.000000Z",
        "verifier_reference": "owner-manual-check",
    }
    values.update(overrides)
    return VerificationRecord(**values)  # type: ignore[arg-type]


def test_unverified_record_requires_no_check_evidence() -> None:
    record = VerificationRecord(
        artifact_identity="unreviewed-component",
        component_revision="0",
        source_url="https://example.com/component",
        status="unverified",
    )
    assert record.status == "unverified"


def test_unverified_record_rejects_check_evidence() -> None:
    with pytest.raises(ContractValidationError):
        VerificationRecord(
            artifact_identity="unreviewed-component",
            component_revision="0",
            source_url="https://example.com/component",
            status="unverified",
            checked_at="2026-09-22T00:00:00.000000Z",
        )


def test_verified_record_requires_checked_at_and_verifier() -> None:
    with pytest.raises(ContractValidationError):
        VerificationRecord(
            artifact_identity="a",
            component_revision="0",
            source_url="https://example.com/a",
            status="verified",
        )


def test_registry_distinguishes_unknown_from_a_dated_check() -> None:
    registry = VerificationRegistry()
    with pytest.raises(VerificationUnavailable):
        registry.require_verified(
            "nomic-ai/modernbert-embed-base", component_revision=REVISION
        )
    registry.register(_verified())
    record = registry.require_verified(
        "nomic-ai/modernbert-embed-base", component_revision=REVISION
    )
    assert record.checked_at == "2026-09-22T00:00:00.000000Z"


def test_registry_rejects_a_reference_whose_revision_differs() -> None:
    registry = VerificationRegistry()
    registry.register(_verified())
    with pytest.raises(VerificationUnavailable):
        registry.require_verified(
            "nomic-ai/modernbert-embed-base", component_revision="a-different-revision"
        )


def test_registry_refuses_readiness_on_an_unverified_entry() -> None:
    registry = VerificationRegistry()
    registry.register(
        VerificationRecord(
            artifact_identity="specter2",
            component_revision="0",
            source_url="https://example.com/specter2",
            status="unverified",
        )
    )
    with pytest.raises(VerificationUnavailable):
        registry.require_verified("specter2", component_revision="0")
