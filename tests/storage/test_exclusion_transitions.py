"""The exclusion action contract: closed payloads and the fixed step order (AG-22)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from research_agent.contracts.exclusions import TRANSITIONS, validate_exclusion_payload
from research_agent.contracts.primitives import ContractValidationError

OPERATOR = str(uuid4())


def payload(action: str, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "action": action,
        "scope_id": str(uuid4()),
        "evidence_hashes": ["1" * 64],
        "trigger_run_ids": [],
        "authority": "system",
        "operator_id": None,
    }
    value.update(overrides)
    return value


def test_the_steps_run_run_then_configuration_then_purge() -> None:
    assert list(TRANSITIONS.values()) == [
        ("run", "active", "run_quarantined"),
        ("configuration", "active", "configuration_quarantined"),
        ("configuration", "configuration_quarantined", "authority_revoked"),
    ]


def test_a_valid_step_is_copied_unchanged() -> None:
    runs = [str(uuid4()) for _ in range(3)]
    value = payload("quarantine_configuration", trigger_run_ids=runs)
    assert validate_exclusion_payload(value) == value
    operator = payload("revoke_authority", authority="operator", operator_id=OPERATOR)
    assert validate_exclusion_payload(operator) == operator


@pytest.mark.parametrize(
    "bad",
    [
        {**payload("quarantine_run"), "extra": 1},
        payload("purge"),
        payload("quarantine_run", evidence_hashes=[]),
        payload("quarantine_run", evidence_hashes=["1" * 64, "1" * 64]),
        payload("quarantine_run", scope_id="not-a-uuid"),
        payload("quarantine_run", authority="operator"),
        payload("quarantine_run", operator_id=OPERATOR),
        payload("quarantine_run", trigger_run_ids=[str(uuid4())]),
        payload("quarantine_configuration"),
        payload(
            "quarantine_configuration", trigger_run_ids=[str(uuid4()) for _ in range(2)]
        ),
        payload("quarantine_configuration", trigger_run_ids=[str(uuid4())] * 3),
        payload("revoke_authority"),
    ],
)
def test_a_step_outside_the_contract_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ContractValidationError):
        validate_exclusion_payload(bad)
