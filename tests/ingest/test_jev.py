"""The Jev adapter against a real local HTTP fault endpoint (TDD-4.1.57, 4.1.58)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import research_agent.ingest.jev as jev
from research_agent.artifacts.store import ArtifactStore
from research_agent.assessments.input import AssessmentInput
from research_agent.assessments.rubric import Rubric
from research_agent.assessments.schemas import (
    JevAttemptRecord,
    JevAvailable,
    JevUnavailable,
    parse_field_answers,
)
from research_agent.contracts.assessments import JevAssessmentInput
from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.ingest.jev import (
    HttpSystemOneTransport,
    JevProviderConfig,
    JevWorker,
    persist_attempt,
    read_committed,
    work_key,
)
from research_agent.storage.assessments import JevWorkRepository
from research_agent.storage.database import Database

_RECORDED = Path(__file__).parents[1] / "fixtures" / "jev" / "systemone-response.json"
_API_KEY = "test-credential-9f3c"
_SMOKE_HASH = "5" * 64


def _recorded(**changes: Any) -> bytes:
    body = json.loads(_RECORDED.read_text(encoding="utf-8"))
    body.update(changes)
    return json.dumps(body).encode("utf-8")


@dataclass
class _Endpoint:
    """A scripted provider: each request takes the next (status, body, delay)."""

    script: list[tuple[int, bytes, float]] = field(default_factory=list)
    default: tuple[int, bytes, float] = (200, b"", 0.0)
    requests: list[tuple[dict[str, str], bytes]] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    url: str = ""

    def next(self, headers: dict[str, str], body: bytes) -> tuple[int, bytes, float]:
        with self.lock:
            self.requests.append((headers, body))
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            return self.script.pop(0) if self.script else self.default

    def done(self) -> None:
        with self.lock:
            self.in_flight -= 1


@pytest.fixture
def endpoint() -> Iterator[_Endpoint]:
    state = _Endpoint(default=(200, _recorded(), 0.0))

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            status, response, delay = state.next(dict(self.headers.items()), body)
            try:
                time.sleep(delay)
                self.send_response(status)
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                state.done()

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}/v1/systemone"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


class _Store:
    """In-memory storage seam: leases, per-day attempt and spend counters, manifests."""

    def __init__(self, *, attempts_today: int = 0, fail_commit: bool = False) -> None:
        self.lock = threading.Lock()
        self.leases: set[str] = set()
        self.manifests: dict[str, bytes] = {}
        self.attempts_today = attempts_today
        self.spent_micros = 0
        self.reservations: dict[str, str | None] = {}
        self.fail_commit = fail_commit

    def committed_attempt(self, work_key: str) -> bytes | None:
        with self.lock:
            return self.manifests.get(work_key)

    def acquire_lease(self, work_key: str) -> bool:
        with self.lock:
            if work_key in self.leases:
                return False
            self.leases.add(work_key)
            return True

    def release_lease(self, work_key: str) -> None:
        with self.lock:
            self.leases.discard(work_key)

    def reserve_attempt(
        self,
        *,
        work_key: str,
        day: str,
        worst_case_micros: int,
        daily_attempt_cap: int,
        daily_limit_micros: int,
    ) -> str | None:
        with self.lock:
            if self.attempts_today + 1 > daily_attempt_cap:
                return None
            if self.spent_micros + worst_case_micros > daily_limit_micros:
                return None
            self.attempts_today += 1
            self.spent_micros += worst_case_micros
            reservation = f"r{len(self.reservations)}"
            self.reservations[reservation] = None
            return reservation

    def settle_attempt(self, reservation_id: str, billing_state: str) -> None:
        with self.lock:
            assert self.reservations[reservation_id] is None
            self.reservations[reservation_id] = billing_state

    def commit_attempt(self, work_key: str, manifest: bytes) -> None:
        if self.fail_commit:
            raise OSError("storage went away before the manifest commit")
        with self.lock:
            self.manifests[work_key] = manifest


class _PostgresStore:
    """The same seam on PostgreSQL, with the fake's inspection views over its rows."""

    _DAY = "2026-09-23"

    def __init__(
        self, dsn: str, *, attempts_today: int = 0, fail_commit: bool = False
    ) -> None:
        self.database = Database(dsn)
        self.repository = JevWorkRepository(self.database)
        self.fail_commit = fail_commit
        if attempts_today:
            with self.database.connect() as connection:
                connection.execute(
                    "INSERT INTO jev_daily_usage(day, attempts) VALUES(%s, %s)",
                    (self._DAY, attempts_today),
                )

    def committed_attempt(self, work_key: str) -> bytes | None:
        return self.repository.committed_attempt(work_key)

    def acquire_lease(self, work_key: str) -> bool:
        return self.repository.acquire_lease(work_key)

    def release_lease(self, work_key: str) -> None:
        self.repository.release_lease(work_key)

    def reserve_attempt(self, **limits: Any) -> str | None:
        return self.repository.reserve_attempt(**limits)

    def settle_attempt(self, reservation_id: str, billing_state: str) -> None:
        self.repository.settle_attempt(reservation_id, billing_state)

    def commit_attempt(self, work_key: str, manifest: bytes) -> None:
        if self.fail_commit:
            raise OSError("storage went away before the manifest commit")
        self.repository.commit_attempt(work_key, manifest)

    def _rows(self, query: str) -> list[tuple[Any, ...]]:
        with self.database.connect() as connection:
            return connection.execute(query).fetchall()

    @property
    def attempts_today(self) -> int:
        rows = self._rows("SELECT coalesce(sum(attempts), 0) FROM jev_daily_usage")
        return int(rows[0][0])

    @property
    def reservations(self) -> dict[str, str | None]:
        rows = self._rows(
            "SELECT billing_state FROM jev_attempt_reservations ORDER BY reserved_at"
        )
        return {f"r{index}": row[0] for index, row in enumerate(rows)}

    @property
    def leases(self) -> set[str]:
        rows = self._rows(
            """SELECT encode(work_key,'hex') FROM jev_work_leases
               WHERE expires_at > clock_timestamp()"""
        )
        return {row[0] for row in rows}

    @property
    def manifests(self) -> dict[str, bytes]:
        rows = self._rows(
            """SELECT DISTINCT ON (work_key) encode(work_key,'hex'), manifest
               FROM jev_attempt_manifests ORDER BY work_key, id DESC"""
        )
        return {row[0]: bytes(row[1]) for row in rows}


@pytest.fixture(autouse=True, params=["memory", "postgres"])
def _store_seam(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run every worker test against the in-memory seam and the real store."""

    if request.param == "postgres":
        dsn = request.getfixturevalue("postgres_dsn")
        monkeypatch.setitem(
            globals(), "_Store", lambda **kwargs: _PostgresStore(dsn, **kwargs)
        )


def _config(url: str, *, smoke_revision: str | None = None) -> JevProviderConfig:
    return JevProviderConfig(
        endpoint=url,
        configured_model="typesafeai/jev-latest",
        known_revisions=frozenset({"jev-1.13.0"}),
        capability_evidence_hash="c" * 64,
        max_input_tokens=32768,
        prompt_price_micros_per_million_tokens=42000,
        daily_limit_micros=2_000_000,
        smoke_revision=smoke_revision,
    )


def _input(
    config: JevProviderConfig,
    *,
    text: str = "We propose a method and compare it with two baselines.",
    smoke_report_hash: str | None = None,
    unavailable_reason: str | None = None,
) -> AssessmentInput:
    encoded = text.encode("utf-8")
    record = JevAssessmentInput(
        paper_version_id="0f8fad5b-d9cb-469f-a165-70867728950e",
        extraction_hash="e" * 64,
        supplied_text_hash=sha256_hex(encoded),
        supplied_text_bytes=len(encoded),
        coverage="complete",
        coverage_reasons=(),
        rubric_hash=Rubric.launch().rubric_hash,
        provider_configuration_hash=config.configuration_hash,
        smoke_report_hash=smoke_report_hash,
    )
    return AssessmentInput(record, text, unavailable_reason)


def _worker(
    tmp_path: Path,
    config: JevProviderConfig,
    store: _Store,
    sleeps: list[float] | None = None,
) -> JevWorker:
    recorded = sleeps if sleeps is not None else []
    return JevWorker(
        store=store,
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        transport=HttpSystemOneTransport(config.endpoint, _API_KEY),
        config=config,
        rubric=Rubric.launch(),
        clock=lambda: datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc),
        sleep=recorded.append,
    )


def _key(assessment: AssessmentInput) -> str:
    record = assessment.record
    return work_key(
        record.input_hash, record.rubric_hash, record.provider_configuration_hash
    )


def test_one_request_carries_all_eight_choices_and_persists_provenance(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    config = _config(endpoint.url)
    store = _Store()
    worker = _worker(tmp_path, config, store)
    assessment = _input(config)
    outcome = worker.assess(assessment)

    assert isinstance(outcome.result, JevAvailable)
    assert outcome.attempts == 1 and not outcome.reused
    assert len(endpoint.requests) == 1
    headers, body = endpoint.requests[0]
    assert headers["Authorization"] == f"Bearer {_API_KEY}"
    sent = json.loads(body)
    assert set(sent) == {"model", "state", "questions"}
    assert sent["model"] == "typesafeai/jev-latest"
    assert sent["state"] == assessment.state_text
    assert canonical_json(sent["questions"]) == canonical_json(
        Rubric.launch().choice_questions()
    )

    committed = read_committed(
        ArtifactStore(tmp_path / "artifacts"), store, _key(assessment)
    )
    assert committed is not None
    record, result = committed
    assert result == outcome.result
    assert record.request_artifact_hash == sha256_hex(body)
    stored_request = (tmp_path / "artifacts").rglob(record.request_artifact_hash or "")
    request_bytes = next(stored_request).read_bytes()
    assert _API_KEY.encode() not in request_bytes
    assert b"Authorization" not in request_bytes
    identity = outcome.result.provider_identity
    assert identity.identity_kind == "immutable_revision"
    assert identity.configured_model_alias == "typesafeai/jev-latest"
    assert identity.returned_model_identity == "jev-1.13.0"
    assert store.reservations == {"r0": "known_completed"}


def test_a_completed_work_key_is_reused_without_a_second_request(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    config = _config(endpoint.url)
    store = _Store()
    worker = _worker(tmp_path, config, store)
    first = worker.assess(_input(config))
    second = worker.assess(_input(config))
    assert second.reused and second.result == first.result
    assert len(endpoint.requests) == 1
    assert store.attempts_today == 1


def test_an_explicit_429_is_retried_once_after_two_seconds(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    endpoint.script = [(429, b'{"error":"rate"}', 0.0)]
    config = _config(endpoint.url)
    store = _Store()
    sleeps: list[float] = []
    outcome = _worker(tmp_path, config, store, sleeps).assess(_input(config))
    assert isinstance(outcome.result, JevAvailable)
    assert outcome.attempts == 2 and sleeps == [2.0]
    assert store.reservations == {"r0": "known_rejected", "r1": "known_completed"}


def test_a_second_explicit_rejection_is_not_retried_again(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    endpoint.script = [(503, b"busy", 0.0), (503, b"busy", 0.0)]
    config = _config(endpoint.url)
    outcome = _worker(tmp_path, config, _Store()).assess(_input(config))
    assert isinstance(outcome.result, JevUnavailable)
    assert outcome.result.reason == "provider_failure"
    assert outcome.attempts == 2 and len(endpoint.requests) == 2


@pytest.mark.parametrize(
    ("status", "reason"), [(500, "provider_failure"), (401, "permission_missing")]
)
def test_other_rejections_are_not_retried(
    tmp_path: Path, endpoint: _Endpoint, status: int, reason: str
) -> None:
    endpoint.script = [(status, b"no", 0.0)]
    config = _config(endpoint.url)
    outcome = _worker(tmp_path, config, _Store()).assess(_input(config))
    assert isinstance(outcome.result, JevUnavailable)
    assert outcome.result.reason == reason
    assert outcome.result.billing_state == "known_rejected"
    assert len(endpoint.requests) == 1


def test_a_timeout_is_ambiguous_billing_and_never_retried(
    tmp_path: Path, endpoint: _Endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jev, "TIMEOUT_SECONDS", 0.2)
    endpoint.script = [(200, _recorded(), 1.0)]
    config = _config(endpoint.url)
    store = _Store()
    outcome = _worker(tmp_path, config, store).assess(_input(config))
    assert isinstance(outcome.result, JevUnavailable)
    assert outcome.result.reason == "timeout_ambiguous"
    assert outcome.result.billing_state == "uncertain"
    assert outcome.attempts == 1 and len(endpoint.requests) == 1
    assert store.reservations == {"r0": "uncertain"}


def test_budget_exhaustion_sends_nothing_and_records_unavailable(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    config = _config(endpoint.url)
    store = _Store(attempts_today=jev.DAILY_ATTEMPT_CAP)
    outcome = _worker(tmp_path, config, store).assess(_input(config))
    assert isinstance(outcome.result, JevUnavailable)
    assert outcome.result.reason == "budget_exhausted"
    assert outcome.result.billing_state == "no_attempt"
    assert endpoint.requests == []


def test_an_unfunded_sublimit_refuses_the_request(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    base = _config(endpoint.url)
    config = JevProviderConfig(
        endpoint=base.endpoint,
        configured_model=base.configured_model,
        known_revisions=base.known_revisions,
        capability_evidence_hash=base.capability_evidence_hash,
        max_input_tokens=base.max_input_tokens,
        prompt_price_micros_per_million_tokens=42000,
        daily_limit_micros=0,
        smoke_revision=None,
    )
    outcome = _worker(tmp_path, config, _Store()).assess(_input(config))
    assert isinstance(outcome.result, JevUnavailable)
    assert outcome.result.reason == "budget_exhausted"
    assert endpoint.requests == []


def test_concurrent_jobs_on_one_key_send_one_request(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    endpoint.default = (200, _recorded(), 0.3)
    config = _config(endpoint.url)
    store = _Store()
    worker = _worker(tmp_path, config, store)
    outcomes: list[Any] = []
    threads = [
        threading.Thread(target=lambda: outcomes.append(worker.assess(_input(config))))
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(endpoint.requests) == 1
    assert sum(1 for item in outcomes if item.attempts == 1) == 1
    assert all(item.lease_held_elsewhere or item.result for item in outcomes)


def test_at_most_two_requests_are_in_flight(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    endpoint.default = (200, _recorded(), 0.2)
    config = _config(endpoint.url)
    worker = _worker(tmp_path, config, _Store())
    threads = [
        threading.Thread(
            target=worker.assess, args=(_input(config, text=f"Paper {n}."),)
        )
        for n in range(5)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(endpoint.requests) == 5
    assert endpoint.max_in_flight == 2


def test_an_invalid_distribution_is_unavailable_not_renormalized(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    body = json.loads(_recorded())
    body["answers"]["comparative_evaluation"]["probabilities"]["reported"] = 0.91
    endpoint.script = [(200, json.dumps(body).encode(), 0.0)]
    config = _config(endpoint.url)
    outcome = _worker(tmp_path, config, _Store()).assess(_input(config))
    assert isinstance(outcome.result, JevUnavailable)
    assert outcome.result.reason == "invalid_response"
    assert outcome.result.billing_state == "known_completed"
    assert outcome.result.sanitized_response_hash is not None


def test_a_changed_provider_identity_needs_a_fresh_smoke_test(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    endpoint.script = [(200, _recorded(model="jev-1.14.0"), 0.0)]
    config = _config(endpoint.url, smoke_revision="jev-1.13.0")
    outcome = _worker(tmp_path, config, _Store()).assess(
        _input(config, smoke_report_hash=_SMOKE_HASH)
    )
    assert isinstance(outcome.result, JevUnavailable)
    assert outcome.result.reason == "identity_changed"


def test_an_alias_only_identity_is_explicitly_unpinned(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    body = json.loads(_recorded())
    del body["model"]
    endpoint.script = [(200, json.dumps(body).encode(), 0.0)]
    config = _config(endpoint.url)
    outcome = _worker(tmp_path, config, _Store()).assess(_input(config))
    assert isinstance(outcome.result, JevAvailable)
    identity = outcome.result.provider_identity
    assert identity.identity_kind == "mutable_alias"
    assert identity.immutable_revision is None
    assert identity.returned_model_identity is None
    assert "weights" not in json.dumps(identity.to_dict())


def test_an_unsendable_input_makes_no_request(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    config = _config(endpoint.url)
    store = _Store()
    outcome = _worker(tmp_path, config, store).assess(
        _input(config, text="", unavailable_reason="missing_input")
    )
    assert isinstance(outcome.result, JevUnavailable)
    assert outcome.result.reason == "missing_input"
    assert outcome.result.billing_state == "no_attempt"
    assert endpoint.requests == [] and store.reservations == {}


def test_a_crash_before_the_manifest_commit_leaves_no_visible_result(
    tmp_path: Path, endpoint: _Endpoint
) -> None:
    config = _config(endpoint.url)
    store = _Store(fail_commit=True)
    assessment = _input(config)
    with pytest.raises(OSError):
        _worker(tmp_path, config, store).assess(assessment)
    assert len(endpoint.requests) == 1
    assert (
        read_committed(ArtifactStore(tmp_path / "artifacts"), store, _key(assessment))
        is None
    )
    assert store.leases == set()


def test_a_result_without_its_input_provenance_is_refused(tmp_path: Path) -> None:
    config = _config("https://gateway.example.org/v1/systemone")
    assessment = _input(config)
    request = b'{"state":"x"}'
    response = _recorded()
    result = JevAvailable(
        fields=parse_field_answers(json.loads(response)["answers"]),
        input_hash="9" * 64,
        rubric_hash=assessment.record.rubric_hash,
        provider_identity=config.identity("jev-1.13.0"),
        sanitized_request_hash=sha256_hex(request),
        sanitized_response_hash=sha256_hex(response),
        computed_at="2026-09-23T12:00:00.000000Z",
        smoke_report_hash=None,
    )
    store = _Store()
    right_input = replace(result, input_hash=assessment.record.input_hash)
    cases: list[tuple[JevAvailable, bytes | None]] = [
        (result, response),
        (right_input, None),
    ]
    for broken, stored_response in cases:
        with pytest.raises(ContractValidationError):
            persist_attempt(
                ArtifactStore(tmp_path / "artifacts"),
                store,
                key=_key(assessment),
                assessment=assessment.record,
                rubric=Rubric.launch(),
                result=broken,
                request=request,
                response=stored_response,
                requested_at="2026-09-23T12:00:00.000000Z",
                completed_at="2026-09-23T12:00:01.000000Z",
                attempts=1,
            )
    assert store.manifests == {}


def test_the_attempt_manifest_round_trips(tmp_path: Path, endpoint: _Endpoint) -> None:
    config = _config(endpoint.url)
    store = _Store()
    assessment = _input(config)
    _worker(tmp_path, config, store).assess(assessment)
    manifest = store.manifests[_key(assessment)]
    record = JevAttemptRecord.from_json(manifest)
    assert record.to_canonical_json() == manifest
    assert record.input == assessment.record
    assert record.rubric_version == Rubric.launch().version
