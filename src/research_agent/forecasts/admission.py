"""Typed refusal path admitting forecast types, issued questions and the
target registry (EN-24 to EN-27, EN-30, EN-31).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.forecasts import (
    AdmissionRefusal,
    RegistryAdmission,
    validate_issued_question_request,
    validate_target_request,
)
from research_agent.contracts.learning import TARGET_IDS
from research_agent.contracts.primitives import ContractValidationError, validate_sha256

__all__ = ["validate_target", "validate_issued_question", "admit_registry"]


def _request_hash(parsed: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(dict(parsed)))


def validate_target(request: object) -> AdmissionRefusal | dict[str, Any]:
    """Admit a proposed forecast only for the three launch target ids (EN-24 to EN-27).

    A disabled type -- trend-to-paper, co-citation, query-growth or
    citation-rate-growth -- is refused before any outcome acquisition or
    sealing, even when the request names an admitted resolver id or an
    admitted target's own definition hash: ``requested_type`` alone
    decides admission, never a borrowed identity.
    """

    parsed = validate_target_request(request)
    if parsed["requested_type"] not in TARGET_IDS:
        return AdmissionRefusal(
            reason="unadmitted_type",
            attempted_type=parsed["requested_type"],
            request_hash=_request_hash(parsed),
        )
    return parsed


def validate_issued_question(
    request: object, issued: Mapping[tuple[str, str], str]
) -> AdmissionRefusal | dict[str, Any]:
    """Admit a forecast only for a question this run's own sheet actually issued (EN-30).

    ``issued`` maps each ``(paper_id, requested_type)`` this run's sheet
    actually issued to the ``question_id`` it was issued under. A missing
    identity, an extra question id or a new paper/target combination all
    resolve to the same ``unissued_question`` refusal; nominations are a
    separate accepted path (AG-26) and never reach this gate.
    """

    parsed = validate_issued_question_request(request)
    key = (parsed["paper_id"], parsed["requested_type"])
    if parsed["question_id"] is None or issued.get(key) != parsed["question_id"]:
        return AdmissionRefusal(
            reason="unissued_question",
            attempted_type=parsed["requested_type"],
            request_hash=_request_hash(parsed),
        )
    return parsed


def admit_registry(
    *,
    caller_role: str,
    target_definition_hashes: Mapping[str, str],
    resolver_build_hashes: Mapping[str, str],
    conformance_report_hash: str,
    repeat_results: Mapping[str, tuple[bytes, bytes]],
) -> RegistryAdmission:
    """Record admission of the fixed automatic-citations-v1 registry (EN-31).

    Only an operator-owned caller may admit the registry; agent tool
    credentials never reach this path. Each of the three targets must show
    byte-identical canonical results across two independent resolver runs
    over the same preserved fixtures before its build is trusted as
    deterministic. A target outside the fixed three, or one whose repeat
    run disagrees -- a random-number resolver fixture, for example --
    refuses the whole admission rather than admitting the targets that did
    check out.
    """

    if caller_role != "operator":
        raise ContractValidationError("registry admission requires an operator caller")
    if (
        set(target_definition_hashes) != set(TARGET_IDS)
        or set(resolver_build_hashes) != set(TARGET_IDS)
        or set(repeat_results) != set(TARGET_IDS)
    ):
        raise ContractValidationError(
            "registry admission requires exactly the three admitted targets"
        )
    for target_id in TARGET_IDS:
        validate_sha256(target_definition_hashes[target_id])
        validate_sha256(resolver_build_hashes[target_id])
        first, second = repeat_results[target_id]
        if not isinstance(first, bytes) or not isinstance(second, bytes):
            raise ContractValidationError("repeat results must be canonical bytes")
        if first != second:
            raise ContractValidationError(
                f"resolver for {target_id} produced non-deterministic repeat results"
            )
    validate_sha256(conformance_report_hash)
    return RegistryAdmission(
        admitted_target_ids=TARGET_IDS,
        target_definition_hashes=tuple(
            target_definition_hashes[target_id] for target_id in TARGET_IDS
        ),
        resolver_build_hashes=tuple(
            resolver_build_hashes[target_id] for target_id in TARGET_IDS
        ),
        conformance_report_hash=conformance_report_hash,
    )
