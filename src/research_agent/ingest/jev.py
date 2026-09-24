"""Ingest-owned, bounded Jev assessment requests (RD-19, RD-20; TDD-4.1.57, 4.1.58).

Ingest is the only component that reaches the Jev provider, through the
gateway's `POST /v1/systemone` interface (#59's capability evidence). One
request carries the rubric's eight questions over the whole extracted state
text. The reader never calls the provider: it reads only results this
module has persisted.

`JevWorker` keys each piece of work by SHA-256 over the input, rubric and
provider-configuration hashes. Under a storage lease on that key it reuses
a committed available result, reserves each attempt against the daily
attempt cap and the Jev spend sublimit before sending, and holds at most
two requests in flight. A request has a 30-second timeout; only an explicit
429 or 503 rejection is retried, once, after 2 seconds, and both attempts
consume a reservation. A timeout is ambiguous: the provider may have run
and billed it, so it is recorded as `timeout_ambiguous` with uncertain
billing and is not retried.

`persist_attempt` writes the sanitized request, the response and the result
as immutable artifacts and commits the attempt manifest last, so a failure
anywhere before that commit leaves no reader-visible result. The request
artifact is the request body only; the bearer credential travels in a
header and is never stored.

Leases, attempt and spend reservations and the manifest commit are storage
operations reached through :class:`JevWorkStore`, exactly as the summarizer
leaves its lease and persistence to storage (TDD-3.1.75).
"""

from __future__ import annotations

import http.client
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

from research_agent.artifacts.store import ArtifactStore
from research_agent.assessments.input import AssessmentInput
from research_agent.assessments.rubric import Rubric
from research_agent.assessments.schemas import (
    AssessmentResult,
    InvalidResponse,
    JevAttemptRecord,
    JevAvailable,
    JevUnavailable,
    parse_field_answers,
    result_from_json,
    result_hash,
)
from research_agent.contracts.assessments import (
    JEV_PROVIDER,
    JevAssessmentInput,
    JevProviderIdentity,
)
from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.primitives import (
    ContractValidationError,
    validate_https_url,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_positive_int,
    validate_sha256,
)

__all__ = [
    "TIMEOUT_SECONDS",
    "RETRY_DELAY_SECONDS",
    "CONCURRENCY",
    "DAILY_ATTEMPT_CAP",
    "RETRYABLE_STATUSES",
    "MAX_ARTIFACT_BYTES",
    "JevProviderConfig",
    "AmbiguousTimeout",
    "ConnectionFailed",
    "SystemOneTransport",
    "HttpSystemOneTransport",
    "JevWorkStore",
    "JevWorkOutcome",
    "JevWorker",
    "work_key",
    "request_body",
    "persist_attempt",
    "read_committed",
]

#: Appendix A: Launch profile, Jev operating limits.
TIMEOUT_SECONDS = 30.0
RETRY_DELAY_SECONDS = 2.0
CONCURRENCY = 2
DAILY_ATTEMPT_CAP = 1000
RETRYABLE_STATUSES = frozenset({429, 503})
_PERMISSION_STATUSES = frozenset({401, 403})
MAX_ARTIFACT_BYTES = 1024 * 1024
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _instant(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _bare(model: str) -> str:
    return model.rsplit("/", 1)[-1]


@dataclass(frozen=True, slots=True)
class JevProviderConfig:
    """The declared provider configuration; its hash keys work and results.

    `known_revisions` are the immutable revisions the capability evidence
    verified, in the bare form the response's `model` field returns them
    (`jev-1.13.0`). `smoke_revision` is the revision the active smoke report
    ran against, or null before one exists. No credential is part of this
    record.
    """

    endpoint: str
    configured_model: str
    known_revisions: frozenset[str]
    capability_evidence_hash: str
    max_input_tokens: int
    prompt_price_micros_per_million_tokens: int
    daily_limit_micros: int
    smoke_revision: str | None

    def __post_init__(self) -> None:
        _validate_endpoint(self.endpoint)
        validate_non_empty_string(self.configured_model)
        for revision in self.known_revisions:
            validate_non_empty_string(revision)
        validate_sha256(self.capability_evidence_hash)
        validate_positive_int(self.max_input_tokens)
        validate_non_negative_int(self.prompt_price_micros_per_million_tokens)
        validate_non_negative_int(self.daily_limit_micros)
        if self.smoke_revision is not None and (
            self.smoke_revision not in self.known_revisions
        ):
            raise ContractValidationError("smoke_revision must be a verified revision")

    @property
    def configuration_hash(self) -> str:
        return sha256_hex(
            canonical_json(
                {
                    "provider": JEV_PROVIDER,
                    "endpoint": self.endpoint,
                    "configured_model": self.configured_model,
                    "known_revisions": sorted(self.known_revisions),
                    "capability_evidence_hash": self.capability_evidence_hash,
                    "max_input_tokens": self.max_input_tokens,
                    "prompt_price_micros_per_million_tokens": (
                        self.prompt_price_micros_per_million_tokens
                    ),
                    "timeout_seconds": TIMEOUT_SECONDS,
                    "retry_delay_seconds": RETRY_DELAY_SECONDS,
                }
            )
        )

    @property
    def worst_case_micros(self) -> int:
        """The most one request can cost: the whole input limit, rounded up."""

        product = self.max_input_tokens * self.prompt_price_micros_per_million_tokens
        return -(-product // 1_000_000)

    def identity(self, returned_model: str | None) -> JevProviderIdentity:
        """Record the configured and returned identity with its pinning kind.

        A returned identity that is a verified revision pins the result. A
        configured name that is itself a verified revision pins it when the
        response names none. Anything else is a mutable alias with no
        revision: nothing is invented to stand in for one.
        """

        configured = _bare(self.configured_model)
        if returned_model is not None and returned_model in self.known_revisions:
            revision: str | None = returned_model
        elif returned_model is None and configured in self.known_revisions:
            revision = configured
        else:
            revision = None
        return JevProviderIdentity(
            provider=JEV_PROVIDER,
            configured_model_alias=self.configured_model,
            returned_model_identity=returned_model,
            immutable_revision=revision,
            identity_kind="immutable_revision" if revision else "mutable_alias",
            capability_evidence_hash=self.capability_evidence_hash,
            configuration_hash=self.configuration_hash,
        )


def _validate_endpoint(endpoint: str) -> None:
    parts = urlsplit(endpoint)
    if parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS:
        return
    validate_https_url(endpoint)


class AmbiguousTimeout(Exception):
    """The request may have reached the provider; its outcome is unknown."""


class ConnectionFailed(Exception):
    """The provider could not be reached; no answer was produced."""


class SystemOneTransport(Protocol):
    """Send one request body; return the HTTP status and response bytes."""

    def post(self, body: bytes, *, timeout: float) -> tuple[int, bytes]: ...


@dataclass(frozen=True, slots=True)
class HttpSystemOneTransport:
    """The gateway's `POST /v1/systemone`, with a bearer credential header."""

    endpoint: str
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        _validate_endpoint(self.endpoint)
        if not self.api_key:
            raise ContractValidationError("api_key must be nonempty")

    def post(self, body: bytes, *, timeout: float) -> tuple[int, bytes]:
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read(MAX_ARTIFACT_BYTES + 1)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read(MAX_ARTIFACT_BYTES + 1)
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise AmbiguousTimeout(str(error.reason)) from error
            raise ConnectionFailed(str(error.reason)) from error
        except (TimeoutError, socket.timeout) as error:
            raise AmbiguousTimeout(str(error)) from error
        except (http.client.HTTPException, ConnectionError) as error:
            raise AmbiguousTimeout(str(error)) from error


class JevWorkStore(Protocol):
    """The storage operations one piece of Jev work needs.

    `commit_attempt` makes an attempt manifest the key's committed attempt
    atomically and records its actual availability time; until it returns,
    no reader can see the attempt. `reserve_attempt` checks and counts one
    attempt against the UTC day's attempt cap and the Jev spend sublimit in
    one transaction, returning a reservation id, or `None` when either limit
    would be exceeded.
    """

    def committed_attempt(self, work_key: str) -> bytes | None: ...

    def acquire_lease(self, work_key: str) -> bool: ...

    def release_lease(self, work_key: str) -> None: ...

    def reserve_attempt(
        self,
        *,
        work_key: str,
        day: str,
        worst_case_micros: int,
        daily_attempt_cap: int,
        daily_limit_micros: int,
    ) -> str | None: ...

    def settle_attempt(self, reservation_id: str, billing_state: str) -> None: ...

    def commit_attempt(self, work_key: str, manifest: bytes) -> None: ...


def work_key(input_hash: str, rubric_hash: str, provider_config_hash: str) -> str:
    """SHA-256 over the input, rubric and provider-configuration hashes."""

    for value in (input_hash, rubric_hash, provider_config_hash):
        validate_sha256(value)
    return sha256_hex(f"{input_hash}:{rubric_hash}:{provider_config_hash}".encode())


def request_body(assessment: AssessmentInput, rubric: Rubric, model: str) -> bytes:
    """The exact request: the configured model, the state text, eight questions."""

    return canonical_json(
        {
            "model": model,
            "state": assessment.state_text,
            "questions": rubric.request_questions(),
        }
    )


def _put(artifacts: ArtifactStore, raw: bytes) -> str:
    artifact_hash = sha256_hex(raw)
    artifacts.commit(
        (raw,),
        expected_hash=artifact_hash,
        expected_length=len(raw),
        maximum_length=MAX_ARTIFACT_BYTES,
    )
    return artifact_hash


def _read(artifacts: ArtifactStore, artifact_hash: str) -> bytes:
    with artifacts.open_verified(artifact_hash) as stream:
        return stream.read()


def _check_provenance(
    key: str,
    assessment: JevAssessmentInput,
    result: AssessmentResult,
    request: bytes | None,
    response: bytes | None,
) -> None:
    if result.rubric_hash != assessment.rubric_hash:
        raise ContractValidationError("result rubric differs from its input's")
    if result.input_hash is not None and result.input_hash != assessment.input_hash:
        raise ContractValidationError("result names another input")
    for recorded, raw in (
        (result.sanitized_request_hash, request),
        (result.sanitized_response_hash, response),
    ):
        if recorded is not None and (raw is None or sha256_hex(raw) != recorded):
            raise ContractValidationError("result names bytes that are not stored")
    if isinstance(result, JevAvailable):
        if result.input_hash is None or request is None or response is None:
            raise ContractValidationError(
                "an available result needs its input, request and response"
            )
        if (
            result.provider_identity.configuration_hash
            != assessment.provider_configuration_hash
        ):
            raise ContractValidationError("result names another provider configuration")
        if result.smoke_report_hash != assessment.smoke_report_hash:
            raise ContractValidationError("result names another smoke report")
    if key != work_key(
        assessment.input_hash,
        assessment.rubric_hash,
        assessment.provider_configuration_hash,
    ):
        raise ContractValidationError("work key does not match the input")


def persist_attempt(
    artifacts: ArtifactStore,
    store: JevWorkStore,
    *,
    key: str,
    assessment: JevAssessmentInput,
    rubric: Rubric,
    result: AssessmentResult,
    request: bytes | None,
    response: bytes | None,
    requested_at: str | None,
    completed_at: str,
    attempts: int,
) -> JevAttemptRecord:
    """Store an attempt's artifacts, then commit its manifest last (TDD-4.1.57).

    A result whose provenance does not resolve (an available result without
    its input, request or response, or naming bytes that are not the ones
    stored) is refused before anything is written. If any write fails, the
    manifest is not committed and no reader can see the result.
    """

    if rubric.rubric_hash != assessment.rubric_hash:
        raise ContractValidationError("rubric differs from the input's")
    _check_provenance(key, assessment, result, request, response)
    request_hash = None if request is None else _put(artifacts, request)
    response_hash = None if response is None else _put(artifacts, response)
    record = JevAttemptRecord(
        work_key=key,
        input=assessment,
        rubric_version=rubric.version,
        result_artifact_hash=_put(artifacts, result.to_canonical_json()),
        request_artifact_hash=request_hash,
        response_artifact_hash=response_hash,
        requested_at=requested_at,
        completed_at=completed_at,
        attempts=attempts,
    )
    manifest = record.to_canonical_json()
    _put(artifacts, manifest)
    store.commit_attempt(key, manifest)
    return record


def read_committed(
    artifacts: ArtifactStore, store: JevWorkStore, key: str
) -> tuple[JevAttemptRecord, AssessmentResult] | None:
    """The key's committed attempt and its verified result, if one is committed."""

    manifest = store.committed_attempt(key)
    if manifest is None:
        return None
    record = JevAttemptRecord.from_json(manifest)
    result = result_from_json(_read(artifacts, record.result_artifact_hash))
    if result_hash(result) != record.result_artifact_hash:
        raise ContractValidationError("stored result does not match its manifest")
    return record, result


@dataclass(frozen=True, slots=True)
class JevWorkOutcome:
    """What one `assess` call did: the result, reuse, attempts, or a held lease."""

    result: AssessmentResult | None
    reused: bool
    attempts: int
    lease_held_elsewhere: bool = False


def _decode(body: bytes) -> tuple[str | None, object]:
    try:
        value = canonical_loads(body)
    except CanonicalJsonError as error:
        raise InvalidResponse("response is not JSON") from error
    if not isinstance(value, dict):
        raise InvalidResponse("response must be an object")
    model = value.get("model")
    if model is not None and not isinstance(model, str):
        raise InvalidResponse("model must be a string")
    return model, value.get("answers")


class JevWorker:
    """Run one assessment per input under the Jev operating limits (RD-20)."""

    def __init__(
        self,
        *,
        store: JevWorkStore,
        artifacts: ArtifactStore,
        transport: SystemOneTransport,
        config: JevProviderConfig,
        rubric: Rubric,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store = store
        self._artifacts = artifacts
        self._transport = transport
        self._config = config
        self._rubric = rubric
        self._clock = clock
        self._sleep = sleep
        self._in_flight = threading.BoundedSemaphore(CONCURRENCY)

    def assess(self, assessment: AssessmentInput) -> JevWorkOutcome:
        record = assessment.record
        if record.provider_configuration_hash != self._config.configuration_hash:
            raise ContractValidationError("input names another provider configuration")
        if record.rubric_hash != self._rubric.rubric_hash:
            raise ContractValidationError("input names another rubric")
        key = work_key(
            record.input_hash, record.rubric_hash, record.provider_configuration_hash
        )
        reused = self._reusable(key)
        if reused is not None:
            return JevWorkOutcome(reused, True, 0)
        if not self._store.acquire_lease(key):
            return JevWorkOutcome(None, False, 0, lease_held_elsewhere=True)
        try:
            reused = self._reusable(key)
            if reused is not None:
                return JevWorkOutcome(reused, True, 0)
            return self._run(key, assessment)
        finally:
            self._store.release_lease(key)

    def _reusable(self, key: str) -> AssessmentResult | None:
        committed = read_committed(self._artifacts, self._store, key)
        if committed is not None and isinstance(committed[1], JevAvailable):
            return committed[1]
        return None

    def _unavailable(
        self,
        assessment: JevAssessmentInput,
        reason: str,
        billing_state: str,
        *,
        identity: JevProviderIdentity | None = None,
        request: bytes | None = None,
        response: bytes | None = None,
    ) -> JevUnavailable:
        return JevUnavailable(
            reason=reason,
            input_hash=assessment.input_hash,
            rubric_hash=assessment.rubric_hash,
            provider_identity=identity,
            sanitized_request_hash=None if request is None else sha256_hex(request),
            sanitized_response_hash=None if response is None else sha256_hex(response),
            billing_state=billing_state,
            recorded_at=_instant(self._clock()),
        )

    def _run(self, key: str, assessment: AssessmentInput) -> JevWorkOutcome:
        record = assessment.record
        if assessment.unavailable_reason is not None:
            result: AssessmentResult = self._unavailable(
                record, assessment.unavailable_reason, "no_attempt"
            )
            self._persist(key, record, result, None, None, None, 0)
            return JevWorkOutcome(result, False, 0)

        body = request_body(assessment, self._rubric, self._config.configured_model)
        requested_at: str | None = None
        attempts = 0
        with self._in_flight:
            while True:
                reservation = self._store.reserve_attempt(
                    work_key=key,
                    day=_instant(self._clock())[:10],
                    worst_case_micros=self._config.worst_case_micros,
                    daily_attempt_cap=DAILY_ATTEMPT_CAP,
                    daily_limit_micros=self._config.daily_limit_micros,
                )
                if reservation is None:
                    billing = "no_attempt" if attempts == 0 else "known_rejected"
                    result = self._unavailable(
                        record,
                        "budget_exhausted",
                        billing,
                        request=body if attempts else None,
                    )
                    self._persist(
                        key,
                        record,
                        result,
                        body if attempts else None,
                        None,
                        requested_at,
                        attempts,
                    )
                    return JevWorkOutcome(result, False, attempts)
                attempts += 1
                requested_at = _instant(self._clock())
                try:
                    status, response = self._transport.post(
                        body, timeout=TIMEOUT_SECONDS
                    )
                except AmbiguousTimeout:
                    self._store.settle_attempt(reservation, "uncertain")
                    result = self._unavailable(
                        record, "timeout_ambiguous", "uncertain", request=body
                    )
                    self._persist(
                        key, record, result, body, None, requested_at, attempts
                    )
                    return JevWorkOutcome(result, False, attempts)
                except ConnectionFailed:
                    self._store.settle_attempt(reservation, "known_rejected")
                    result = self._unavailable(
                        record, "provider_failure", "known_rejected", request=body
                    )
                    self._persist(
                        key, record, result, body, None, requested_at, attempts
                    )
                    return JevWorkOutcome(result, False, attempts)
                if status in RETRYABLE_STATUSES and attempts == 1:
                    self._store.settle_attempt(reservation, "known_rejected")
                    self._sleep(RETRY_DELAY_SECONDS)
                    continue
                break

        if len(response) > MAX_ARTIFACT_BYTES:
            self._store.settle_attempt(reservation, "known_completed")
            result = self._unavailable(
                record, "invalid_response", "known_completed", request=body
            )
            self._persist(key, record, result, body, None, requested_at, attempts)
            return JevWorkOutcome(result, False, attempts)
        if not 200 <= status < 300:
            self._store.settle_attempt(reservation, "known_rejected")
            reason = (
                "permission_missing"
                if status in _PERMISSION_STATUSES
                else "provider_failure"
            )
            result = self._unavailable(
                record, reason, "known_rejected", request=body, response=response
            )
            self._persist(key, record, result, body, response, requested_at, attempts)
            return JevWorkOutcome(result, False, attempts)

        self._store.settle_attempt(reservation, "known_completed")
        result = self._answer(record, body, response)
        self._persist(key, record, result, body, response, requested_at, attempts)
        return JevWorkOutcome(result, False, attempts)

    def _answer(
        self, record: JevAssessmentInput, body: bytes, response: bytes
    ) -> AssessmentResult:
        identity: JevProviderIdentity | None = None
        try:
            returned_model, answers = _decode(response)
            identity = self._config.identity(returned_model)
            if record.smoke_report_hash is not None and (
                identity.immutable_revision != self._config.smoke_revision
            ):
                return self._unavailable(
                    record,
                    "identity_changed",
                    "known_completed",
                    identity=identity,
                    request=body,
                    response=response,
                )
            fields = parse_field_answers(answers, self._rubric.record)
        except (InvalidResponse, ContractValidationError):
            return self._unavailable(
                record,
                "invalid_response",
                "known_completed",
                identity=identity,
                request=body,
                response=response,
            )
        return JevAvailable(
            fields=fields,
            input_hash=record.input_hash,
            rubric_hash=record.rubric_hash,
            provider_identity=identity,
            sanitized_request_hash=sha256_hex(body),
            sanitized_response_hash=sha256_hex(response),
            computed_at=_instant(self._clock()),
            smoke_report_hash=record.smoke_report_hash,
        )

    def _persist(
        self,
        key: str,
        record: JevAssessmentInput,
        result: AssessmentResult,
        request: bytes | None,
        response: bytes | None,
        requested_at: str | None,
        attempts: int,
    ) -> None:
        persist_attempt(
            self._artifacts,
            self._store,
            key=key,
            assessment=record,
            rubric=self._rubric,
            result=result,
            request=request,
            response=response,
            requested_at=requested_at,
            completed_at=_instant(self._clock()),
            attempts=attempts,
        )
