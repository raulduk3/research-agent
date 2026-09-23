import pytest

from research_agent.contracts.outcomes import OperationalFinding
from research_agent.contracts.primitives import ContractValidationError

_HASH = "a" * 64
_AS_OF = "2022-01-01T00:00:00.000000Z"


def test_a_resolver_unavailable_finding_carries_its_registry_hash_and_detail() -> None:
    finding = OperationalFinding(
        kind="resolver_unavailable",
        pinned_registry_hash=_HASH,
        detail=f"resolver build unavailable for registry {_HASH}",
        detected_at=_AS_OF,
    )
    assert finding.kind == "resolver_unavailable"
    assert finding.pinned_registry_hash == _HASH
    assert _HASH in finding.detail
    assert finding.detected_at == _AS_OF


def test_an_unadmitted_kind_is_refused() -> None:
    with pytest.raises(ContractValidationError, match="kind"):
        OperationalFinding(
            kind="unknown_condition",
            pinned_registry_hash=_HASH,
            detail="detail",
            detected_at=_AS_OF,
        )


def test_a_malformed_registry_hash_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        OperationalFinding(
            kind="resolver_unavailable",
            pinned_registry_hash="not-a-hash",
            detail="detail",
            detected_at=_AS_OF,
        )


def test_an_empty_detail_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        OperationalFinding(
            kind="resolver_unavailable",
            pinned_registry_hash=_HASH,
            detail="",
            detected_at=_AS_OF,
        )


def test_a_non_canonical_detected_at_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        OperationalFinding(
            kind="resolver_unavailable",
            pinned_registry_hash=_HASH,
            detail="detail",
            detected_at="2022-01-01",
        )
