"""Strict wire contract for graduated exclusion actions (AG-22, AG-23, TDD-3.1.69)."""

from __future__ import annotations

from typing import Any

from .primitives import ContractValidationError, validate_sha256, validate_uuid4

#: Each action moves one scope from one state to the next, in this order.
#: ``quarantine_run`` acts on a run; the other two act on the immutable
#: configuration that run was issued for. ``authority_revoked`` is the purge:
#: it revokes execution authority and deletes no audit record.
TRANSITIONS: dict[str, tuple[str, str, str]] = {
    "quarantine_run": ("run", "active", "run_quarantined"),
    "quarantine_configuration": (
        "configuration",
        "active",
        "configuration_quarantined",
    ),
    "revoke_authority": (
        "configuration",
        "configuration_quarantined",
        "authority_revoked",
    ),
}
AUTHORITIES = ("system", "operator")
#: Integrity run quarantines of one configuration that quarantine it, and the
#: rolling span they must fall inside.
CONFIGURATION_QUARANTINE_RUNS = 3
CONFIGURATION_QUARANTINE_DAYS = 7
EVIDENCE_LIMIT = 16


def _hashes(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= EVIDENCE_LIMIT:
        raise ContractValidationError(
            f"{name} must list between 1 and {EVIDENCE_LIMIT} hashes"
        )
    hashes = [validate_sha256(item) for item in value]
    if len(set(hashes)) != len(hashes):
        raise ContractValidationError(f"{name} must not repeat a hash")
    return hashes


def validate_exclusion_payload(payload: object) -> dict[str, Any]:
    """Validate and copy one exclusion action step.

    ``scope_id`` is a run id for ``quarantine_run`` and a configuration id for
    the two configuration steps. ``trigger_run_ids`` names the run
    quarantines that quarantine a configuration and is empty otherwise.
    ``operator_id`` is present exactly for operator authority; revoking
    authority is never a system step.
    """

    fields = {
        "action",
        "scope_id",
        "evidence_hashes",
        "trigger_run_ids",
        "authority",
        "operator_id",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ContractValidationError("exclusion payload has unknown or missing fields")
    action = payload["action"]
    if not isinstance(action, str) or action not in TRANSITIONS:
        raise ContractValidationError("unknown exclusion action")
    authority = payload["authority"]
    if authority not in AUTHORITIES:
        raise ContractValidationError("unknown exclusion authority")
    operator_id = payload["operator_id"]
    if (authority == "operator") != (operator_id is not None):
        raise ContractValidationError("operator_id is required exactly for operator")
    if action == "revoke_authority" and authority != "operator":
        raise ContractValidationError("revoking authority requires an operator")
    triggers = payload["trigger_run_ids"]
    if not isinstance(triggers, list):
        raise ContractValidationError("trigger_run_ids must be a list")
    trigger_ids = [validate_uuid4(item) for item in triggers]
    if action == "quarantine_configuration":
        if (
            len(set(trigger_ids)) != len(trigger_ids)
            or len(trigger_ids) < CONFIGURATION_QUARANTINE_RUNS
        ):
            raise ContractValidationError(
                f"a configuration quarantine cites at least "
                f"{CONFIGURATION_QUARANTINE_RUNS} distinct run quarantines"
            )
    elif trigger_ids:
        raise ContractValidationError("only a configuration quarantine cites runs")
    return {
        "action": action,
        "scope_id": validate_uuid4(payload["scope_id"]),
        "evidence_hashes": _hashes(payload["evidence_hashes"], "evidence_hashes"),
        "trigger_run_ids": trigger_ids,
        "authority": authority,
        "operator_id": None if operator_id is None else validate_uuid4(operator_id),
    }
