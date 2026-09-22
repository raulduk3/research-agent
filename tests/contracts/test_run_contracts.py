from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError
from research_agent.contracts.runs import validate_run_payload

RUN_ID = "123e4567-e89b-42d3-a456-426614174000"
CONFIGURATION_ID = "123e4567-e89b-42d3-a456-426614174001"
HASH = "a" * 64
OTHER_HASH = "b" * 64

BUDGETS = {
    "context_tokens": 8000,
    "generation_tokens": 2000,
    "tool_calls": 40,
    "deep_reads": 10,
    "images": 5,
    "timeout_seconds": 30,
    "retries": 2,
    "wall_time_seconds": 600,
    "spend_micros": 500_000,
}
MODEL_IDENTITY = {
    "agent_model_manifest": HASH,
    "service_image_versions": {"reader": OTHER_HASH},
    "paper_card_manifest": HASH,
    "prediction_head_bundles": {"citation_head": None},
}
CREATE_PAYLOAD = {
    "run_id": RUN_ID,
    "slot": {
        "batch_id": HASH,
        "shard_id": "shard-0",
        "configuration_id": CONFIGURATION_ID,
        "attempt": 0,
    },
    "genome_hash": HASH,
    "seed": 42,
    "snapshot_hash": OTHER_HASH,
    "budgets": BUDGETS,
    "allowed_tools": ["query_cards", "submit"],
    "model_identity": MODEL_IDENTITY,
    "checkpoint_dates": ["2026-09-01T00:00:00.000000Z"],
}
EVENT_PAYLOAD = {
    "run_id": RUN_ID,
    "attempt": 1,
    "ordinal": 0,
    "kind": "request",
    "payload_hash": HASH,
}


def test_create_and_append_event_accept_the_normative_shape() -> None:
    assert validate_run_payload("create", CREATE_PAYLOAD) == CREATE_PAYLOAD
    assert validate_run_payload("append_event", EVENT_PAYLOAD) == EVENT_PAYLOAD


def test_create_rejects_unknown_fields_and_extra_tools() -> None:
    with pytest.raises(ContractValidationError):
        validate_run_payload("create", {**CREATE_PAYLOAD, "extra": True})
    with pytest.raises(ContractValidationError):
        validate_run_payload(
            "create", {**CREATE_PAYLOAD, "allowed_tools": ["query_cards", "unknown"]}
        )
    with pytest.raises(ContractValidationError):
        validate_run_payload(
            "create",
            {**CREATE_PAYLOAD, "allowed_tools": ["submit", "submit"]},
        )


def test_budgets_reject_missing_keys_and_negative_or_zero_bounded_values() -> None:
    incomplete = {key: value for key, value in BUDGETS.items() if key != "retries"}
    with pytest.raises(ContractValidationError):
        validate_run_payload("create", {**CREATE_PAYLOAD, "budgets": incomplete})
    with pytest.raises(ContractValidationError):
        validate_run_payload(
            "create", {**CREATE_PAYLOAD, "budgets": {**BUDGETS, "retries": -1}}
        )
    with pytest.raises(ContractValidationError):
        validate_run_payload(
            "create", {**CREATE_PAYLOAD, "budgets": {**BUDGETS, "timeout_seconds": 0}}
        )


def test_model_identity_allows_explicitly_unavailable_bundles() -> None:
    unavailable = {
        **MODEL_IDENTITY,
        "prediction_head_bundles": {"citation_head": None, "novelty_head": HASH},
    }
    payload = {**CREATE_PAYLOAD, "model_identity": unavailable}
    assert validate_run_payload("create", payload)["model_identity"] == unavailable


def test_event_kind_is_closed_to_request_and_response() -> None:
    with pytest.raises(ContractValidationError):
        validate_run_payload("append_event", {**EVENT_PAYLOAD, "kind": "other"})


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(ContractValidationError):
        validate_run_payload("delete", CREATE_PAYLOAD)
