"""Strict wire contracts for storage-owned agent run records."""

from __future__ import annotations

from typing import Any

from .primitives import (
    ContractValidationError,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

ALLOWED_TOOLS = frozenset({"query_cards", "neighbors", "graph", "deep_read", "submit"})

BUDGET_FIELDS = frozenset(
    {
        "context_tokens",
        "generation_tokens",
        "tool_calls",
        "deep_reads",
        "images",
        "timeout_seconds",
        "retries",
        "wall_time_seconds",
        "spend_micros",
    }
)

EVENT_KINDS = frozenset({"request", "response"})


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _bounded_list(value: object, lower: int, upper: int, name: str) -> list[Any]:
    if not isinstance(value, list) or not lower <= len(value) <= upper:
        raise ContractValidationError(
            f"{name} must be a JSON array with {lower} to {upper} items"
        )
    return value


def _slot(value: object) -> dict[str, Any]:
    slot = _closed(
        value,
        {"batch_id", "paper_id", "configuration_id", "attempt"},
        "RunSlot",
    )
    paper_id = slot["paper_id"]
    if (
        not isinstance(paper_id, str)
        or not 1 <= len(paper_id) <= 128
        or "\x00" in paper_id
    ):
        raise ContractValidationError("RunSlot.paper_id is invalid")
    return {
        "batch_id": validate_sha256(slot["batch_id"]),
        "paper_id": paper_id,
        "configuration_id": validate_uuid4(slot["configuration_id"]),
        "attempt": validate_non_negative_int(slot["attempt"]),
    }


def _budgets(value: object) -> dict[str, int]:
    budgets = _closed(value, set(BUDGET_FIELDS), "RunBudgets")
    result: dict[str, int] = {}
    for name in BUDGET_FIELDS:
        if name in {"timeout_seconds", "wall_time_seconds"}:
            result[name] = validate_positive_int(budgets[name])
        else:
            result[name] = validate_non_negative_int(budgets[name])
    return result


def _allowed_tools(value: object) -> list[str]:
    tools = _bounded_list(value, 1, len(ALLOWED_TOOLS), "allowed_tools")
    for tool in tools:
        if not isinstance(tool, str) or tool not in ALLOWED_TOOLS:
            raise ContractValidationError("allowed_tools names an inadmissible tool")
    if len(set(tools)) != len(tools):
        raise ContractValidationError("allowed_tools must be distinct")
    return tools


def _model_identity(value: object) -> dict[str, Any]:
    identity = _closed(
        value,
        {
            "agent_model_manifest",
            "service_image_versions",
            "paper_card_manifest",
            "prediction_head_bundles",
        },
        "ModelIdentity",
    )
    versions = identity["service_image_versions"]
    if not isinstance(versions, dict) or not 1 <= len(versions) <= 20:
        raise ContractValidationError(
            "ModelIdentity.service_image_versions must hold 1 to 20 entries"
        )
    service_image_versions = {
        _service_name(name): validate_sha256(digest)
        for name, digest in versions.items()
    }
    bundles = identity["prediction_head_bundles"]
    if not isinstance(bundles, dict) or len(bundles) > 20:
        raise ContractValidationError(
            "ModelIdentity.prediction_head_bundles must hold at most 20 entries"
        )
    prediction_head_bundles = {
        _service_name(name): (None if digest is None else validate_sha256(digest))
        for name, digest in bundles.items()
    }
    return {
        "agent_model_manifest": validate_sha256(identity["agent_model_manifest"]),
        "service_image_versions": service_image_versions,
        "paper_card_manifest": validate_sha256(identity["paper_card_manifest"]),
        "prediction_head_bundles": prediction_head_bundles,
    }


def _service_name(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or "\x00" in value:
        raise ContractValidationError("service or bundle name is invalid")
    return value


def _checkpoint_dates(value: object) -> list[str]:
    dates = _bounded_list(value, 0, 20, "checkpoint_dates")
    return [validate_utc_instant(item) for item in dates]


def _issued_question_ids(value: object) -> list[str]:
    ids = _bounded_list(value, 0, 3, "issued_question_ids")
    question_ids = [validate_uuid4(item) for item in ids]
    if len(set(question_ids)) != len(question_ids):
        raise ContractValidationError("issued_question_ids must be distinct")
    return question_ids


def validate_run_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a run-record operation."""

    if operation == "create":
        value = _closed(
            payload,
            {
                "run_id",
                "slot",
                "genome_hash",
                "seed",
                "snapshot_hash",
                "budgets",
                "allowed_tools",
                "model_identity",
                "checkpoint_dates",
                "issued_question_ids",
            },
            "create run payload",
        )
        return {
            "run_id": validate_uuid4(value["run_id"]),
            "slot": _slot(value["slot"]),
            "genome_hash": validate_sha256(value["genome_hash"]),
            "seed": validate_non_negative_int(value["seed"]),
            "snapshot_hash": validate_sha256(value["snapshot_hash"]),
            "budgets": _budgets(value["budgets"]),
            "allowed_tools": _allowed_tools(value["allowed_tools"]),
            "model_identity": _model_identity(value["model_identity"]),
            "checkpoint_dates": _checkpoint_dates(value["checkpoint_dates"]),
            "issued_question_ids": _issued_question_ids(value["issued_question_ids"]),
        }
    if operation == "append_event":
        value = _closed(
            payload,
            {"run_id", "attempt", "ordinal", "kind", "payload_hash"},
            "append run event payload",
        )
        kind = value["kind"]
        if not isinstance(kind, str) or kind not in EVENT_KINDS:
            raise ContractValidationError("RunEvent.kind is not an admitted value")
        return {
            "run_id": validate_uuid4(value["run_id"]),
            "attempt": validate_positive_int(value["attempt"]),
            "ordinal": validate_non_negative_int(value["ordinal"]),
            "kind": kind,
            "payload_hash": validate_sha256(value["payload_hash"]),
        }
    raise ContractValidationError("unknown run operation")
