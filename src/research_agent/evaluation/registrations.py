"""Immutable comparison preregistration (SDD-SR-18, SDD-IN-17).

`ComparisonRegistration` freezes a comparison's hypothesis, primary measure and
pass/kill thresholds before the comparison may run. Every function here is a
pure function of its arguments: nothing reads a clock or allocates an identity,
so the caller supplies `registered_at`/`imported_at`/`new_registration_id` and
gets byte-identical output for the same input on any two calls. Whether a job
may actually obtain a lease against a registration is decided by storage, which
resolves the immutable record and calls `admit_execution` before starting it
(TDD-4.1.21) -- the same validator SDD-SR-18 uses for any relied-on comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, replace as _replace
from typing import Any, TypeVar, cast

from research_agent.contracts.canonical import (
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    ProducerVersion,
    RecordMeta,
    validate_finite,
    validate_non_empty_string,
    validate_positive_int,
    validate_sha256,
    validate_utc_instant,
    validate_uuid4,
)

T = TypeVar("T")

ENDPOINT_ROLES: frozenset[str] = frozenset({"primary", "secondary", "diagnostic"})
DIRECTIONS: frozenset[str] = frozenset({"lower", "higher", "descriptive"})
FAILURE_HANDLING: frozenset[str] = frozenset({"exclude", "count_as_failure"})
PROVENANCES: frozenset[str] = frozenset({"runtime", "imported"})


def _closed(raw: bytes, fields: set[str], name: str) -> dict[str, Any]:
    value = canonical_loads(raw)
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractValidationError(f"{name} has unknown or missing fields")
    return cast(dict[str, Any], value)


def _meta(values: dict[str, Any]) -> None:
    producer = values.get("producer_version")
    inputs = values.get("input_hashes")
    if not isinstance(producer, dict) or not isinstance(inputs, list):
        raise ContractValidationError("RecordMeta fields are invalid")
    values["producer_version"] = ProducerVersion.from_json(canonical_json(producer))
    values["input_hashes"] = tuple(inputs)


def _fields(cls: Any, *, meta: bool = False) -> set[str]:
    fields = set(cls.__slots__)
    if meta:
        fields.update(RecordMeta.__slots__)
    return fields


def _construct(cls: type[T], values: dict[str, Any], name: str) -> T:
    try:
        return cls(**values)
    except ContractValidationError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise ContractValidationError(f"{name} field types are invalid") from error


@dataclass(frozen=True, slots=True)
class ComparisonEndpoint:
    """One measured quantity a registration commits to, with its role and direction."""

    metric: str
    role: str
    direction: str

    def __post_init__(self) -> None:
        validate_non_empty_string(self.metric)
        if self.role not in ENDPOINT_ROLES:
            raise ContractValidationError("comparison endpoint role is invalid")
        if self.direction not in DIRECTIONS:
            raise ContractValidationError("comparison endpoint direction is invalid")
        if self.role == "primary" and self.direction == "descriptive":
            raise ContractValidationError(
                "a primary endpoint requires a decisive direction"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "role": self.role, "direction": self.direction}

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ComparisonEndpoint":
        return _construct(
            cls, _closed(raw, _fields(cls), "ComparisonEndpoint"), "ComparisonEndpoint"
        )


@dataclass(frozen=True, slots=True)
class ComparisonRegistration(RecordMeta):
    """A strict, dated registration for one relied-on comparison.

    `registered_at` is the runtime ledger timestamp for a registration entered
    directly; for a pre-runtime signed import, `registered_at` preserves the
    original evidenced date while `imported_at`/`signature_evidence_hash`
    record the separate later act of bringing it into this system
    (SDD-SR-18's "distinct original and import timestamps"). A changed
    analysis never overwrites a registration in place: `derive_exploratory`
    below returns a new record instead.
    """

    registration_id: str
    hypothesis: str
    population_hash: str
    split_hash: str
    subject_configuration_hash: str
    endpoints: tuple[ComparisonEndpoint, ...]
    pass_threshold: float
    kill_threshold: float
    minimum_effect: float
    exclusions: tuple[str, ...]
    sample_size: int
    failure_handling: str
    stop_rule_hash: str
    provenance: str
    registered_at: str
    imported_at: str | None
    signature_evidence_hash: str | None
    exploratory_of: str | None

    def __post_init__(self) -> None:
        RecordMeta.__post_init__(self)
        validate_uuid4(self.registration_id)
        validate_non_empty_string(self.hypothesis)
        validate_sha256(self.population_hash)
        validate_sha256(self.split_hash)
        validate_sha256(self.subject_configuration_hash)
        validate_sha256(self.stop_rule_hash)
        if not isinstance(self.endpoints, tuple) or not self.endpoints:
            raise ContractValidationError("a registration needs at least one endpoint")
        for endpoint in self.endpoints:
            if not isinstance(endpoint, ComparisonEndpoint):
                raise ContractValidationError("endpoints must be ComparisonEndpoint")
        metrics = [endpoint.metric for endpoint in self.endpoints]
        if len(set(metrics)) != len(metrics):
            raise ContractValidationError("comparison endpoints repeat a metric")
        primaries = [e for e in self.endpoints if e.role == "primary"]
        if len(primaries) != 1:
            raise ContractValidationError(
                "a registration names exactly one primary measure"
            )
        primary = primaries[0]
        pass_threshold = validate_finite(self.pass_threshold)
        kill_threshold = validate_finite(self.kill_threshold)
        if primary.direction == "higher" and pass_threshold < kill_threshold:
            raise ContractValidationError(
                "a higher-is-better pass threshold cannot be below its kill threshold"
            )
        if primary.direction == "lower" and pass_threshold > kill_threshold:
            raise ContractValidationError(
                "a lower-is-better pass threshold cannot be above its kill threshold"
            )
        if validate_finite(self.minimum_effect) <= 0:
            raise ContractValidationError("minimum_effect must be strictly positive")
        if not isinstance(self.exclusions, tuple):
            raise ContractValidationError("exclusions must be an ordered tuple")
        if len(set(self.exclusions)) != len(self.exclusions):
            raise ContractValidationError("exclusions are duplicated")
        for exclusion in self.exclusions:
            validate_non_empty_string(exclusion)
        validate_positive_int(self.sample_size)
        if self.failure_handling not in FAILURE_HANDLING:
            raise ContractValidationError("failure_handling is invalid")
        if self.provenance not in PROVENANCES:
            raise ContractValidationError("provenance is invalid")
        validate_utc_instant(self.registered_at)
        if self.provenance == "imported":
            if self.imported_at is None or self.signature_evidence_hash is None:
                raise ContractValidationError(
                    "an imported registration needs its import time and signature evidence"
                )
            validate_sha256(self.signature_evidence_hash)
            if validate_utc_instant(self.imported_at) <= self.registered_at:
                raise ContractValidationError(
                    "an imported registration's import time must follow its original date"
                )
        elif self.imported_at is not None or self.signature_evidence_hash is not None:
            raise ContractValidationError(
                "a runtime registration carries no import provenance"
            )
        if self.exploratory_of is not None:
            validate_uuid4(self.exploratory_of)
            if self.exploratory_of == self.registration_id:
                raise ContractValidationError(
                    "an exploratory registration cannot cite itself"
                )

    @property
    def primary_endpoint(self) -> ComparisonEndpoint:
        return next(
            endpoint for endpoint in self.endpoints if endpoint.role == "primary"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "input_hashes": list(self.input_hashes),
            "producer_version": self.producer_version.to_dict(),
            "config_hash": self.config_hash,
            "created_at": self.created_at,
            "registration_id": self.registration_id,
            "hypothesis": self.hypothesis,
            "population_hash": self.population_hash,
            "split_hash": self.split_hash,
            "subject_configuration_hash": self.subject_configuration_hash,
            "endpoints": [endpoint.to_dict() for endpoint in self.endpoints],
            "pass_threshold": self.pass_threshold,
            "kill_threshold": self.kill_threshold,
            "minimum_effect": self.minimum_effect,
            "exclusions": list(self.exclusions),
            "sample_size": self.sample_size,
            "failure_handling": self.failure_handling,
            "stop_rule_hash": self.stop_rule_hash,
            "provenance": self.provenance,
            "registered_at": self.registered_at,
            "imported_at": self.imported_at,
            "signature_evidence_hash": self.signature_evidence_hash,
            "exploratory_of": self.exploratory_of,
        }

    def to_canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, raw: bytes) -> "ComparisonRegistration":
        values = _closed(raw, _fields(cls, meta=True), "ComparisonRegistration")
        _meta(values)
        endpoints = values["endpoints"]
        exclusions = values["exclusions"]
        if not isinstance(endpoints, list) or not isinstance(exclusions, list):
            raise ContractValidationError("ComparisonRegistration fields are invalid")
        values["endpoints"] = tuple(
            ComparisonEndpoint.from_json(canonical_json(item)) for item in endpoints
        )
        values["exclusions"] = tuple(exclusions)
        return _construct(cls, values, "ComparisonRegistration")


def registration_identity_hash(registration: ComparisonRegistration) -> str:
    """The canonical hash a registration is frozen under before its first job.

    Two registrations that share `registration_id` but differ in any other
    field -- an attempted modification under an existing identity -- always
    differ here, so storage can detect and refuse the change (SDD-SR-18).
    """

    return sha256_hex(registration.to_canonical_json())


def admit_execution(registration: ComparisonRegistration, *, execution_at: str) -> str:
    """Return the registration's evidenced availability if it precedes *execution_at*.

    A runtime registration relies on `registered_at`, the ledger's own order.
    An imported registration relies on `imported_at`: the original,
    independently-evidenced `registered_at` is preserved but never re-proves
    itself to this system, only the act of import does (SDD-SR-18,
    SDD-IN-17). Raises when the comparison would start before its
    registration is evidenced -- an unregistered or backdated comparison.
    """

    reliance_at = (
        registration.imported_at
        if registration.provenance == "imported"
        else registration.registered_at
    )
    assert reliance_at is not None
    if validate_utc_instant(reliance_at) > validate_utc_instant(execution_at):
        raise ContractValidationError(
            "comparison execution precedes its registration's evidenced availability"
        )
    return reliance_at


def derive_exploratory_registration(
    original: ComparisonRegistration,
    *,
    new_registration_id: str,
    **changes: Any,
) -> ComparisonRegistration:
    """Return a new, linked registration for changed analysis; *original* is untouched.

    SDD-SR-18: "Changed analysis receives a new exploratory identity, never
    overwrites the original." `original` is a frozen record already immutable
    at the type level; this only ever returns a fresh value.
    """

    validate_uuid4(new_registration_id)
    if new_registration_id == original.registration_id:
        raise ContractValidationError(
            "an exploratory registration needs a new identity"
        )
    if "registration_id" in changes or "exploratory_of" in changes:
        raise ContractValidationError(
            "derive_exploratory_registration assigns identity and lineage itself"
        )
    return _replace(
        original,
        registration_id=new_registration_id,
        exploratory_of=original.registration_id,
        **changes,
    )
