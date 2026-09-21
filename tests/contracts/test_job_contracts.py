from __future__ import annotations

import pytest

from research_agent.contracts import ContractValidationError, canonical_json
from research_agent.contracts.jobs import JobCheckpoint, validate_job_payload


ID = "123e4567-e89b-42d3-a456-426614174000"
WORKER = "123e4567-e89b-42d3-a456-426614174001"
HASH = "a" * 64
OTHER_HASH = "b" * 64
FENCE = {"worker_id": WORKER, "lease_epoch": 3}


@pytest.mark.parametrize(
    ("operation", "payload"),
    (
        ("claim", {"worker_id": WORKER, "kinds": ["extract", "embed"]}),
        ("renew", FENCE),
        ("checkpoint", {"fence": FENCE, "checkpoint": HASH}),
        (
            "complete",
            {"fence": FENCE, "result": {"kind": "committed", "output_hashes": [HASH]}},
        ),
        (
            "enqueue",
            {
                "job_id": ID,
                "kind": "extract",
                "input_manifest": HASH,
                "scheduled_at": "2026-09-21T00:00:00.000000Z",
            },
        ),
    ),
)
def test_job_payloads_accept_only_the_normative_route_shapes(
    operation: str, payload: dict[str, object]
) -> None:
    assert validate_job_payload(operation, payload) == payload
    with pytest.raises(ContractValidationError):
        validate_job_payload(operation, {**payload, "extra": True})


def test_job_results_are_closed_discriminated_unions() -> None:
    error = {
        "code": "unavailable_input",
        "message": "declared input is unavailable",
        "retryable": False,
        "evidence_ids": [HASH],
    }
    failed = {
        "fence": FENCE,
        "result": {"kind": "failed", "error": error},
    }
    skipped = {
        "fence": FENCE,
        "result": {
            "kind": "skipped",
            "reason": "ineligible",
            "evidence_hashes": [],
        },
    }
    assert validate_job_payload("complete", failed) == failed
    assert validate_job_payload("complete", skipped) == skipped
    for invalid in (
        {"fence": FENCE, "result": {"kind": "committed", "output_hashes": []}},
        {
            "fence": FENCE,
            "result": {"kind": "failed", "error": {**error, "x": 1}},
        },
        {
            "fence": FENCE,
            "result": {"kind": "skipped", "reason": "other", "evidence_hashes": []},
        },
    ):
        with pytest.raises(ContractValidationError):
            validate_job_payload("complete", invalid)


def test_job_payloads_reject_coercion_and_invalid_bounds() -> None:
    invalid = (
        ("claim", {"worker_id": WORKER, "kinds": []}),
        ("claim", {"worker_id": WORKER, "kinds": ["unknown"]}),
        ("renew", {"worker_id": WORKER, "lease_epoch": True}),
        ("checkpoint", {"fence": FENCE, "checkpoint": "A" * 64}),
        (
            "enqueue",
            {
                "job_id": ID,
                "kind": "extract",
                "input_manifest": HASH,
                "scheduled_at": "2026-09-21T00:00:00Z",
            },
        ),
    )
    for operation, payload in invalid:
        with pytest.raises(ContractValidationError):
            validate_job_payload(operation, payload)


def test_checkpoint_manifest_is_closed_and_canonical() -> None:
    fields = {
        "schema_version": 1,
        "job_id": ID,
        "stage": "encode_documents",
        "input_hashes": [HASH],
        "config_hash": OTHER_HASH,
        "completed_work_keys": ["c" * 64],
        "continuation_cursor": "family:42",
        "output_hashes": ["d" * 64],
    }
    checkpoint = JobCheckpoint.from_json(canonical_json(fields))
    assert checkpoint.to_canonical_json() == canonical_json(fields)
    for changed in (
        {**fields, "job": fields["job_id"]},
        {**fields, "schema_version": 2},
        {**fields, "completed_work_keys": ["not-a-content-key"]},
        {**fields, "continuation_cursor": ""},
    ):
        with pytest.raises(ContractValidationError):
            JobCheckpoint.from_json(canonical_json(changed))
