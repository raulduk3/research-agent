"""Strict wire contracts for stored preference credit (IN-43, TDD-4.1.79)."""

from __future__ import annotations

import math
import re
from typing import Any

from .digests import DIGEST_ISLANDS
from .primitives import (
    ContractValidationError,
    validate_non_empty_string,
    validate_probability,
    validate_sha256,
    validate_uuid4,
)

_ISO_WEEK = re.compile(r"\d{4}-W(?:0[1-9]|[1-4][0-9]|5[0-3])\Z")
_SHARE_TOLERANCE = 1e-9
CREDIT_LIMIT = 100
REASON_LIMIT = 512


def validate_iso_week(value: object) -> str:
    if not isinstance(value, str) or _ISO_WEEK.fullmatch(value) is None:
        raise ContractValidationError("iso_week must be an ISO YYYY-Www string")
    return value


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return value


def _credit(value: object) -> dict[str, Any]:
    credit = _closed(
        value,
        {
            "rating_id",
            "genome_hash",
            "island",
            "entry_id",
            "sealed_probability",
            "share",
            "iso_week",
        },
        "PreferenceCredit",
    )
    island = credit["island"]
    if not isinstance(island, str) or island not in DIGEST_ISLANDS:
        raise ContractValidationError("island is not an admitted value")
    share = credit["share"]
    if (
        isinstance(share, bool)
        or not isinstance(share, (int, float))
        or not math.isfinite(share)
        or not -1 <= share <= 1
    ):
        raise ContractValidationError("share must be a finite number from -1 to 1")
    return {
        "rating_id": validate_uuid4(credit["rating_id"]),
        "genome_hash": validate_sha256(credit["genome_hash"]),
        "island": island,
        "entry_id": validate_uuid4(credit["entry_id"]),
        "sealed_probability": validate_probability(credit["sealed_probability"]),
        "share": float(share),
        "iso_week": validate_iso_week(credit["iso_week"]),
    }


def _credits(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= CREDIT_LIMIT:
        raise ContractValidationError(
            f"credits must be a JSON array with 1 to {CREDIT_LIMIT} items"
        )
    credits = [_credit(item) for item in value]
    for field in ("rating_id", "entry_id", "island", "iso_week"):
        if len({credit[field] for credit in credits}) != 1:
            raise ContractValidationError(
                f"credits of one rating must share one {field}"
            )
    if len({credit["genome_hash"] for credit in credits}) != len(credits):
        raise ContractValidationError("credits must name distinct genome_hash")
    if any(credit["share"] == 0 for credit in credits) or (
        len({credit["share"] > 0 for credit in credits}) != 1
    ):
        raise ContractValidationError(
            "credits of one rating must share one non-zero sign"
        )
    total = sum(credit["sealed_probability"] for credit in credits)
    if total <= 0:
        raise ContractValidationError("credited probabilities must sum above zero")
    for credit in credits:
        expected = credit["sealed_probability"] / total
        if abs(abs(credit["share"]) - expected) > _SHARE_TOLERANCE:
            raise ContractValidationError(
                "each share must be its probability over the credited probabilities"
            )
    return credits


def validate_preference_payload(operation: str, payload: object) -> dict[str, Any]:
    """Validate and copy the exact payload for a preference-credit operation.

    ``record`` carries every credit of one rating; ``record_gap`` carries the
    reason a rating's nominating submissions could not be read, so that no
    credit is imputed for it.
    """

    if operation == "record":
        value = _closed(payload, {"credits"}, "record payload")
        return {"credits": _credits(value["credits"])}
    if operation == "record_gap":
        value = _closed(payload, {"rating_id", "iso_week", "reason"}, "gap payload")
        reason = validate_non_empty_string(value["reason"])
        if len(reason) > REASON_LIMIT:
            raise ContractValidationError(
                f"reason must be at most {REASON_LIMIT} characters"
            )
        return {
            "rating_id": validate_uuid4(value["rating_id"]),
            "iso_week": validate_iso_week(value["iso_week"]),
            "reason": reason,
        }
    raise ContractValidationError("unknown preference operation")
