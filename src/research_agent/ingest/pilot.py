"""Resumable acquisition worker for the source pilot and corpus release.

The worker holds no database connection. It claims `capture` jobs, reads their
input manifests and publishes every request record and payload through the
storage service, checkpointing after each unit so a killed worker resumes
without repeating completed requests or skipping continuation pages.
"""

from __future__ import annotations

import json
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from research_agent.contracts import (
    RecordMeta,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.jobs import JobCheckpoint
from research_agent.contracts.learning import (
    CitationFamilyRecord,
    CitationObservation,
    PaginationPage,
)
from research_agent.contracts.papers import (
    ExternalIdentifier,
    PaperVersionRecord,
    SourceAccess,
)
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.access import SourceNotPermitted, authorize_fetch
from research_agent.ingest.arxiv import (
    BUCKET_HOST,
    BUCKET_PARALLELISM,
    BUCKET_SOURCE,
    ArxivFormatError,
    bucket_pdf_path,
    document_path,
    listing_path,
    parse_listing_page,
)
from research_agent.ingest.fetch import (
    BoundedResponse,
    FetchedOpenAlexPage,
    FetchedSnapshotRange,
)
from research_agent.ingest.openalex import parse_retained_works_page
from research_agent.ingest.snapshot import (
    ParsedSnapshotPart,
    build_snapshot_observation,
    parse_snapshot_part,
)
from research_agent.learning.corpus import (
    DEFAULT_CAP,
    DEFAULT_CATEGORIES,
    DEFAULT_PER_MONTH,
    DEFAULT_POPULATION_RULE,
    SELECTION_SEED,
    PilotCandidate,
    select_pilot,
)
from research_agent.outcomes.resolve import Resolver
from research_agent.outcomes.targets import definitions as target_definitions
from research_agent.outcomes.targets import registry as target_registry
from research_agent.outcomes.windows import instant, maturity_at
from research_agent.storage.client import (
    StorageClient,
    StorageClientError,
    StorageTransportError,
)
from research_agent.storage.errors import IntegrityFailure, UnavailableInput

ARXIV_METADATA_LICENSE = "CC0-1.0"
LISTING_ADAPTER = "arxiv-oai-arxivraw-v1"
DOCUMENT_ADAPTER = "arxiv-original-v1-document-v1"
BUCKET_PDF_ADAPTER = "arxiv-gcs-pdf-v1"
OPENALEX_ADAPTER = "openalex-anonymous-citations-v1"
# One bucket PDF in this many is fetched from arXiv as well and the hashes
# compared: the ongoing check that the bucket still serves arXiv's bytes.
EQUIVALENCE_SAMPLE = 50
_RETRY_AFTER_LIMIT_SECONDS = 600.0
_LISTING_ATTEMPTS = 6
_CITATION_PAGE_FAILURES = frozenset(
    {"timeout", "rejected", "transport", "invalid_payload"}
)
_OPENALEX_SUBFIELD_PREFIX = "https://openalex.org/subfields/"
# Fixed automatic-citations-v1 resolver identity (FT-19): one instant that
# precedes every fitting cutoff this protocol version is used with, shared
# with learning/release.py's own _TARGET_META so both label-resolution call
# sites resolve against the same registry identity.
_GATE_TARGET_META = RecordMeta(
    1,
    (),
    ProducerVersion(sha256(b"automatic-citations-v1").hexdigest(), "0" * 40, 1),
    sha256(b"automatic-citations-v1").hexdigest(),
    "2000-01-01T00:00:00.000000Z",
)


_T = TypeVar("_T")


class BudgetExhausted(Exception):
    """A provider refused further requests today; the job resumes later."""


# A run stops after this many unexpected failures in a row: one broken job
# is recorded and passed over, a broken worker must not burn the queue.
MAX_CONSECUTIVE_UNEXPECTED_FAILURES = 5


class SourceFailed(Exception):
    """A required source response failed; the job ends failed, not retried."""

    def __init__(self, message: str, evidence: tuple[str, ...]) -> None:
        super().__init__(message)
        self.evidence = evidence


def _describe(error: BaseException) -> str:
    """`Type: message (file:line in function)` for the frame that raised."""
    frames = traceback.extract_tb(error.__traceback__)
    where = ""
    if frames:
        last = frames[-1]
        where = f" ({Path(last.filename).name}:{last.lineno} in {last.name})"
    return f"{type(error).__name__}: {error}{where}"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def derived_uuid(*parts: object) -> UUID:
    """A version-4-shaped UUID fixed by its inputs, so a retried command replays."""
    digest = bytearray(sha256(canonical_json([str(part) for part in parts])).digest())
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(digest[:16]))


def work_key(*parts: object) -> str:
    return sha256(canonical_json([str(part) for part in parts])).hexdigest()


def sampled_for_equivalence(family_id: str) -> bool:
    """Whether this family's bucket PDF is also fetched from arXiv, fixed by its id."""
    digest = sha256(canonical_json(["pdf-equivalence", family_id])).digest()
    return int.from_bytes(digest[:8], "big") % EQUIVALENCE_SAMPLE == 0


class RateGate:
    """Minimum spacing between requests to one provider.

    A new gate waits a full interval before its first request, because the
    previous process's last request time is unknown after a restart.
    """

    def __init__(
        self,
        interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("rate interval must be positive")
        self._interval = interval_seconds
        self._clock, self._sleep = clock, sleep
        self._last = clock()

    def wait(self) -> None:
        delay = self._last + self._interval - self._clock()
        if delay > 0:
            self._sleep(delay)
        self._last = self._clock()

    def hold(self, seconds: float) -> None:
        self._sleep(seconds)
        self._last = self._clock()


class ParallelGate:
    """At most `limit` requests in flight to one provider, with no spacing.

    For a provider that states no rate rule. Its requests run on their own
    threads, so they never wait on or count against another provider's gate.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("parallel limit must be positive")
        self._pool = ThreadPoolExecutor(
            max_workers=limit, thread_name_prefix="parallel-gate"
        )

    def submit(self, request: Callable[[], _T]) -> Future[_T]:
        return self._pool.submit(request)


@dataclass
class Sources:
    """Injectable request functions; production binds them to the real hosts.

    Without `pdf_bucket` every PDF comes from arXiv's own document host.
    """

    listing: Callable[[str], BoundedResponse]
    document: Callable[[str], BoundedResponse]
    openalex_match: Callable[[str, RecordMeta], FetchedOpenAlexPage]
    openalex_cites: Callable[[str, str | None, RecordMeta], FetchedOpenAlexPage]
    arxiv_gate: RateGate
    openalex_gate: RateGate
    pdf_bucket: Callable[[str], BoundedResponse] | None = None
    bucket_gate: ParallelGate = field(
        default_factory=lambda: ParallelGate(BUCKET_PARALLELISM)
    )
    snapshot_range: Callable[[str, str], FetchedSnapshotRange] | None = None


@dataclass(frozen=True, slots=True)
class Identity:
    """The capability this worker publishes under; storage re-checks all of it."""

    producer: ProducerVersion
    config_hash: str
    retention_policy_hash: str
    permission_evidence_hash: str


# --- pure gate resolution -------------------------------------------------


def _page_failure(value: str | None) -> str:
    return value if value in _CITATION_PAGE_FAILURES else "rejected"


def _match_target_subfield(payload: bytes) -> tuple[str | None, str]:
    """The matched work's own primary subfield, tolerant of any absent field.

    The `select` fields already requested for the match query include
    `primary_topic`; only `_match_result`-style id/cursor extraction is done
    elsewhere, so this reads the same response for the one additional field
    `cross_subfield_reach_365d` needs. Anything short of an exact, single
    matched work with a well-formed subfield id is reported missing, never
    guessed.
    """
    try:
        envelope = canonical_loads(payload)
        results = envelope.get("results") if isinstance(envelope, dict) else None
        if not isinstance(results, list) or len(results) != 1:
            return None, "missing"
        work = results[0]
        topic = work.get("primary_topic") if isinstance(work, dict) else None
        subfield = topic.get("subfield") if isinstance(topic, dict) else None
        identifier = subfield.get("id") if isinstance(subfield, dict) else None
        if (
            not isinstance(identifier, str)
            or not identifier.startswith(_OPENALEX_SUBFIELD_PREFIX)
            or not identifier.removeprefix(_OPENALEX_SUBFIELD_PREFIX).isdigit()
        ):
            return None, "missing"
        return identifier, "known"
    except (ValueError, AttributeError, TypeError):
        return None, "missing"


def resolve_citation_gate(
    family: dict[str, Any],
    *,
    target_match_state: str,
    matched_work_id: str | None,
    pages: tuple[PaginationPage, ...],
    citation_families: dict[str, CitationFamilyRecord],
    match_started_at: str | None,
    match_completed_at: str | None,
    target_subfield: tuple[str | None, str],
    as_of: str,
    producer: ProducerVersion,
    config_hash: str,
) -> dict[str, Any]:
    """Resolve the three automatic-citations-v1 labels from already-retained
    citation pages, without a downloaded original (outcomes/resolve.py,
    Appendix B: Learning protocol).

    Returns each target's state and reason plus an "acquire"/"skip" decision:
    acquire only when every target resolved to a known (true/false) state.
    """
    family_id = family["family_id"]
    t0 = family["first_public_at"]
    if pages:
        capture_started_at = match_started_at or pages[0].capture_started_at
        capture_completed_at = pages[-1].capture_completed_at
        pagination_complete = (
            target_match_state == "matched"
            and pages[-1].status != "failed"
            and pages[-1].cursor_out is None
        )
        observation_failure = None
    else:
        capture_started_at = match_started_at or as_of
        capture_completed_at = match_completed_at or as_of
        pagination_complete = False
        observation_failure = "initial_request_failed"
    maturity = maturity_at(t0)
    paper_family_id = str(derived_uuid("gate-paper-family", family_id))
    original_version_id = str(derived_uuid("gate-paper-version", family_id))
    registry = target_registry(_GATE_TARGET_META)
    target_registry_hash = sha256_hex(registry.to_canonical_json())
    target_subfield_id, target_subfield_state = target_subfield
    matched_ids: tuple[str, ...] = (
        (matched_work_id,)
        if target_match_state == "matched" and matched_work_id is not None
        else ()
    )
    observation = CitationObservation(
        schema_version=1,
        input_hashes=(),
        producer_version=producer,
        config_hash=config_hash,
        created_at=capture_completed_at,
        paper_family_id=paper_family_id,
        original_version_id=original_version_id,
        t0=t0,
        protocol="automatic-citations-v1",
        target_registry_hash=target_registry_hash,
        provider="openalex",
        kind="historical_reconstructed",
        target_match_state=target_match_state,
        target_provider_ids=matched_ids,
        target_subfield_id=target_subfield_id
        if target_match_state == "matched"
        else None,
        target_subfield_state=(
            target_subfield_state if target_match_state == "matched" else "missing"
        ),
        taxonomy_hash=None,
        capture_started_at=capture_started_at,
        capture_completed_at=capture_completed_at,
        maturity_at=maturity,
        acquisition_lag_seconds=(
            instant(capture_completed_at) - instant(maturity)
        ).total_seconds(),
        pages=pages,
        pagination_complete=pagination_complete,
        citation_family_hashes=tuple(citation_families),
        failure=observation_failure,
    )
    evidence_hash = sha256_hex(
        canonical_json({"family_id": family_id, "first_public_at": t0})
    )
    paper = PaperVersionRecord(
        schema_version=1,
        input_hashes=(),
        producer_version=producer,
        config_hash=config_hash,
        created_at=t0,
        family_id=paper_family_id,
        version_id=original_version_id,
        external_ids=(ExternalIdentifier("arxiv", f"{family_id}v1"),),
        is_first_public_version=True,
        first_public_at=t0,
        first_public_interval=None,
        first_public_evidence_hashes=(evidence_hash,),
        source_access_hashes=(evidence_hash,),
        title=f"pilot gate {family_id}",
        abstract="Original text is not retrieved before label gating.",
        author_ids=(),
        primary_source_subfield=None,
        original_source_hash=evidence_hash,
        text_source_kind="metadata",
        source_revision="v1",
        author_count=family["author_count"],
        categories=tuple(family["categories"]),
        version_count=family["version_count"],
    )
    meta = RecordMeta(1, (), producer, config_hash, as_of)
    resolver = Resolver(citation_families.__getitem__, meta, registry=registry)
    labels: dict[str, dict[str, str]] = {}
    for target in target_definitions(_GATE_TARGET_META):
        label = resolver.resolve_target(target, paper, observation, as_of)
        labels[target.target_id] = {"state": label.state, "reason": label.reason}
    decision = (
        "acquire"
        if all(value["state"] in ("true", "false") for value in labels.values())
        else "skip"
    )
    return {"family_id": family_id, "labels": labels, "decision": decision}


@dataclass(frozen=True, slots=True)
class _PendingCommand:
    """A command sent with an outcome not yet confirmed by storage."""

    idempotency_key: UUID
    content_hash: str


@dataclass
class _Lease:
    job_id: UUID
    epoch: int
    input_manifest: str
    spec: dict[str, Any]
    completed: list[str] = field(default_factory=list)
    cursor: str | None = None
    outputs: list[str] = field(default_factory=list)
    pending: _PendingCommand | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class RunSummary:
    jobs_completed: int
    stopped_for_budget: bool


class PilotWorker:
    def __init__(
        self,
        storage: StorageClient,
        *,
        worker_id: UUID,
        identity: Identity,
        sources: Sources,
        gate_on_labels: bool = False,
    ) -> None:
        self._storage = storage
        self._worker = worker_id
        self._identity = identity
        self._sources = sources
        self._gate_on_labels = gate_on_labels

    # --- storage plumbing -------------------------------------------------

    def _meta(self, lease: _Lease) -> RecordMeta:
        return RecordMeta(
            1,
            (lease.input_manifest,),
            self._identity.producer,
            self._identity.config_hash,
            utc_now(),
        )

    def _send(
        self, lease: _Lease, key: UUID, content_hash: str, send: Callable[[], _T]
    ) -> _T:
        """Send one command, resuming it after a request with an unknown outcome.

        The command's idempotency key and content hash are recorded on the
        lease before sending (#178). A transport failure leaves storage's
        own outcome ambiguous: the request may have committed with the
        response lost, or never arrived. Either way, resending the identical
        key and content is safe -- storage replays what already applied or
        applies it fresh -- and this never resends an old key with content
        that has changed, which storage would refuse.
        """
        lease.pending = _PendingCommand(key, content_hash)
        try:
            result = send()
        except StorageTransportError:
            result = send()
        lease.pending = None
        return result

    def _publish(
        self,
        lease: _Lease,
        payload: bytes,
        *,
        media_type: str,
        kind: str,
        inputs: tuple[str, ...],
    ) -> str:
        digest = sha256(payload).hexdigest()
        # Identical bytes can be published twice in one job with different
        # metadata, e.g. arXiv serving a PDF-only submission as its "source".
        command = derived_uuid(
            lease.job_id, "publish", digest, media_type, kind, inputs
        )
        result = self._send(
            lease,
            command,
            digest,
            lambda: self._storage.publish_artifact(
                payload,
                expected_hash=digest,
                media_type=media_type,
                kind=kind,
                input_hashes=inputs,
                producer_version=self._identity.producer,
                config_hash=self._identity.config_hash,
                retention_policy_hash=self._identity.retention_policy_hash,
                source_available_at=None,
                job_id=lease.job_id,
                lease_epoch=lease.epoch,
                command_id=command,
                request_id=uuid4(),
                idempotency_key=command,
            ),
        )
        manifest = result.data["receipt"]["artifact_hashes"][1]
        assert isinstance(manifest, str)
        return manifest

    def _record(
        self, lease: _Lease, access: SourceAccess, payload_manifest: str | None
    ) -> str:
        """Publish one request record; it names its payload's producing manifest."""
        inputs = (lease.input_manifest,) + (
            (payload_manifest,) if payload_manifest else ()
        )
        return self._publish(
            lease,
            access.to_canonical_json(),
            media_type="application/json",
            kind="source_response",
            inputs=inputs,
        )

    def _checkpoint(self, lease: _Lease, key: str, outputs: tuple[str, ...]) -> None:
        lease.completed.append(key)
        # Identical bytes replay one publication, so an output can recur.
        lease.outputs.extend(
            o for o in dict.fromkeys(outputs) if o not in lease.outputs
        )
        body = JobCheckpoint(
            1,
            str(lease.job_id),
            lease.spec["stage"],
            (lease.input_manifest,),
            self._identity.config_hash,
            tuple(lease.completed),
            lease.cursor,
            tuple(lease.outputs),
        ).to_canonical_json()
        checkpoint = self._publish(
            lease,
            body,
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *lease.outputs),
        )
        command = derived_uuid(lease.job_id, lease.epoch, "checkpoint", checkpoint)
        self._send(
            lease,
            command,
            checkpoint,
            lambda: self._storage.checkpoint(
                job_id=lease.job_id,
                worker_id=self._worker,
                lease_epoch=lease.epoch,
                checkpoint_hash=checkpoint,
                command_id=command,
                request_id=uuid4(),
                idempotency_key=command,
            ),
        )
        self._renew(lease)

    def _renew(self, lease: _Lease) -> None:
        command = uuid4()
        self._send(
            lease,
            command,
            "renew",
            lambda: self._storage.renew(
                job_id=lease.job_id,
                worker_id=self._worker,
                lease_epoch=lease.epoch,
                command_id=command,
                request_id=uuid4(),
                idempotency_key=command,
            ),
        )

    def _complete(self, lease: _Lease, summary: dict[str, Any]) -> None:
        report = self._publish(
            lease,
            canonical_json(summary),
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *lease.outputs),
        )
        command = derived_uuid(lease.job_id, lease.epoch, "complete", report)
        self._send(
            lease,
            command,
            report,
            lambda: self._storage.complete(
                job_id=lease.job_id,
                worker_id=self._worker,
                lease_epoch=lease.epoch,
                result={"kind": "committed", "output_hashes": [report]},
                command_id=command,
                request_id=uuid4(),
                idempotency_key=command,
            ),
        )

    def _fail(self, lease: _Lease, failure: Exception) -> None:
        """End the job failed with the error recorded on it.

        A `SourceFailed` names the source response that failed. Any other
        exception is this worker's own defect, recorded with its type and
        the frame it was raised from so the fix can be found and the job
        requeued afterwards (`pilot_run requeue`).
        """
        if isinstance(failure, SourceFailed):
            code, evidence = "unavailable_source", list(failure.evidence[:20])
            message = str(failure)[:512]
        else:
            code = (
                "integrity_failure"
                if isinstance(failure, IntegrityFailure)
                else "unavailable_input"
                if isinstance(failure, UnavailableInput)
                else "invalid_input"
            )
            evidence, message = [], _describe(failure)[:512]
        command = derived_uuid(lease.job_id, lease.epoch, "fail", message)
        self._send(
            lease,
            command,
            message,
            lambda: self._storage.complete(
                job_id=lease.job_id,
                worker_id=self._worker,
                lease_epoch=lease.epoch,
                result={
                    "kind": "failed",
                    "error": {
                        "code": code,
                        "message": message,
                        "retryable": False,
                        "evidence_ids": evidence,
                    },
                },
                command_id=command,
                request_id=uuid4(),
                idempotency_key=command,
            ),
        )

    def _read_json(self, lease: _Lease, artifact: str) -> Any:
        return canonical_loads(
            self._storage.read_artifact(
                artifact, job_id=lease.job_id, lease_epoch=lease.epoch
            ).payload
        )

    def _read(self, lease: _Lease, artifact: str) -> bytes:
        return self._storage.read_artifact(
            artifact, job_id=lease.job_id, lease_epoch=lease.epoch
        ).payload

    def _produced(self, lease: _Lease, manifest: str) -> bytes:
        """The bytes a producing manifest describes."""
        return self._read(lease, self._read_json(lease, manifest)["artifact_hash"])

    def _resume(self, lease: _Lease, checkpoint: str | None) -> None:
        if checkpoint is None:
            return
        state = JobCheckpoint.from_json(self._produced(lease, checkpoint))
        lease.completed = list(state.completed_work_keys)
        lease.cursor = state.continuation_cursor
        lease.outputs = list(state.output_hashes)

    # --- run loop ---------------------------------------------------------

    def run(self, *, maximum_jobs: int | None = None) -> RunSummary:
        completed = 0
        unexpected = 0
        while maximum_jobs is None or completed < maximum_jobs:
            command = uuid4()
            claimed = self._storage.claim(
                worker_id=self._worker,
                kinds=("capture",),
                command_id=command,
                request_id=uuid4(),
                idempotency_key=command,
            ).data["lease"]
            if claimed is None:
                break
            job_id = UUID(claimed["job_id"])
            lease = _Lease(
                job_id, claimed["lease_epoch"], claimed["input_manifest"], {}
            )
            spec = canonical_loads(self._produced(lease, lease.input_manifest))
            if not isinstance(spec, dict) or not isinstance(spec.get("stage"), str):
                raise ValueError("capture job input is not a pilot stage specification")
            lease.spec = spec
            self._resume(lease, claimed["checkpoint"])
            handler = {
                "listing": self._listing,
                "select": self._select,
                "documents": self._documents,
                "openalex": self._openalex,
                "openalex_snapshot": self._openalex_snapshot,
            }[str(lease.spec["stage"])]
            try:
                summary = handler(lease)
            except BudgetExhausted:
                return RunSummary(completed, True)
            except SourceFailed as failure:
                self._fail(lease, failure)
                completed += 1
                unexpected = 0
                continue
            except (StorageClientError, StorageTransportError):
                # Storage itself refused or vanished: the lease sweeps back to
                # the queue and the next run resumes the job, so nothing is
                # recorded against it.
                raise
            except Exception as error:
                # Anything else is this worker's own defect on this job's
                # input. Record it on the job, so the family is visible and
                # can be requeued once the defect is fixed, and move on.
                self._fail(lease, error)
                completed += 1
                unexpected += 1
                if unexpected >= MAX_CONSECUTIVE_UNEXPECTED_FAILURES:
                    raise RuntimeError(
                        f"{unexpected} jobs in a row failed unexpectedly; "
                        "the last was recorded on job "
                        f"{lease.job_id}: {_describe(error)}"
                    ) from error
                continue
            self._complete(lease, summary)
            completed += 1
            unexpected = 0
        return RunSummary(completed, False)

    # --- stages -----------------------------------------------------------

    def _access(
        self,
        lease: _Lease,
        *,
        source: str,
        url: str,
        parameters: bytes,
        adapter: str,
        response: BoundedResponse,
        license_expression: str | None,
        failure: str | None,
    ) -> SourceAccess:
        meta = self._meta(lease)
        return SourceAccess(
            schema_version=1,
            input_hashes=meta.input_hashes,
            producer_version=meta.producer_version,
            config_hash=meta.config_hash,
            created_at=response.completed_at,
            source=source,
            requested_url=url,
            request_parameters_hash=sha256(parameters).hexdigest(),
            adapter_version=adapter,
            capture_started_at=response.started_at,
            capture_completed_at=response.completed_at,
            http_status=response.status,
            retained_payload_hash=None
            if response.body is None or failure is not None
            else sha256(response.body).hexdigest(),
            retention_policy_hash=self._identity.retention_policy_hash,
            license_expression=license_expression,
            permission_evidence_hash=self._identity.permission_evidence_hash,
            failure=failure,
        )

    def _listing(self, lease: _Lease) -> dict[str, Any]:
        spec = lease.spec
        records = pages = 0
        while True:
            page_index = len(lease.completed)
            if page_index and lease.cursor is None:
                break
            path = listing_path(
                set_spec=spec["set_spec"],
                from_date=spec["from_date"],
                until_date=spec["until_date"],
                token=lease.cursor,
            )
            for attempt in range(_LISTING_ATTEMPTS):
                self._sources.arxiv_gate.wait()
                response = self._sources.listing(path)
                if response.status != 503:
                    break
                # OAI-PMH flow control: record the refusal, then honour Retry-After.
                refused = self._access(
                    lease,
                    source="arxiv",
                    url="https://oaipmh.arxiv.org" + path,
                    parameters=path.encode(),
                    adapter=LISTING_ADAPTER,
                    response=response,
                    license_expression=None,
                    failure="rejected",
                )
                lease.outputs.append(self._record(lease, refused, None))
                retry = dict(response.headers).get("retry-after", "")
                wait = float(retry) if retry.isdigit() else 30.0
                self._sources.arxiv_gate.hold(min(wait, _RETRY_AFTER_LIMIT_SECONDS))
            failure = response.failure
            parsed = None
            if response.body is not None:
                try:
                    parsed = parse_listing_page(response.body)
                except ArxivFormatError as error:
                    # An expired continuation token also lands here: the listing
                    # must restart from its first page in a new job.
                    failure = (
                        "rejected"
                        if "badResumptionToken" in str(error)
                        else "invalid_payload"
                    )
            access = self._access(
                lease,
                source="arxiv",
                url="https://oaipmh.arxiv.org" + path,
                parameters=path.encode(),
                adapter=LISTING_ADAPTER,
                response=response,
                license_expression=ARXIV_METADATA_LICENSE,
                failure=failure,
            )
            payload = None
            if parsed is not None and failure is None:
                assert response.body is not None
                payload = self._publish(
                    lease,
                    response.body,
                    media_type="text/plain",
                    kind="source_response",
                    inputs=(lease.input_manifest,),
                )
            record = self._record(lease, access, payload)
            if parsed is None or failure is not None:
                # A failed page leaves the listing incomplete; the job fails
                # rather than freezing a population with a gap.
                raise SourceFailed(f"listing page failed: {failure}", (record,))
            lease.cursor = parsed.resumption_token
            pages += 1
            records += len(parsed.records)
            self._checkpoint(
                lease,
                work_key("listing", spec["set_spec"], page_index),
                (record,) if payload is None else (payload, record),
            )
        return {
            "stage": "listing",
            "set_spec": spec["set_spec"],
            "pages": len(lease.completed),
            "records_this_attempt": records,
            "pages_this_attempt": pages,
        }

    def _listing_pages(self, lease: _Lease) -> Iterator[bytes]:
        """Every successful page from the admitted listing jobs, found by content.

        The lease is renewed after each page. Selection checkpoints nothing
        until it reports, and renewal otherwise rides on checkpoints, so a
        selection over hundreds of pages would outlive its lease and every
        scoped read after that would be refused as not found.
        """
        for report in lease.spec["listing_reports"]:
            for output in self._read_json(lease, report)["input_hashes"][1:]:
                raw = self._produced(lease, output)
                try:
                    access = SourceAccess.from_json(raw)
                except (ValueError, KeyError):
                    continue
                if (
                    access.adapter_version == LISTING_ADAPTER
                    and access.failure is None
                    and access.retained_payload_hash is not None
                ):
                    page = self._read(lease, access.retained_payload_hash)
                    self._renew(lease)
                    yield page

    def _select(self, lease: _Lease) -> dict[str, Any]:
        spec = lease.spec
        categories = frozenset(spec.get("categories", DEFAULT_CATEGORIES))
        candidates: list[PilotCandidate] = []
        listed: dict[str, dict[str, Any]] = {}
        legacy: set[str] = set()
        for raw in self._listing_pages(lease):
            for item in parse_listing_page(raw).records:
                if categories.isdisjoint(item.categories):
                    continue
                if item.legacy_identifier:
                    legacy.add(item.family_id)
                    continue
                candidates.append(
                    PilotCandidate(
                        item.family_id, item.first_public_at, item.categories
                    )
                )
                listed[item.family_id] = {
                    "family_id": item.family_id,
                    "first_public_at": item.first_public_at,
                    "categories": list(item.categories),
                    "license_url": item.license_url,
                    "doi": item.doi,
                    "title": item.title,
                    "abstract": item.abstract,
                    "author_count": item.author_count,
                    "version_count": len(item.versions),
                }
        selection = select_pilot(
            tuple(candidates),
            frozen_at=spec["frozen_at"],
            seed=spec.get("seed", SELECTION_SEED),
            cap=spec.get("cap", DEFAULT_CAP),
            per_month=spec.get("per_month", DEFAULT_PER_MONTH),
            population_rule=spec.get("population_rule", DEFAULT_POPULATION_RULE),
            categories=categories,
        )
        population = sorted(
            {(c.family_id, c.first_public_at) for c in candidates}, key=lambda x: x
        )
        per_category_counts = {
            category: sum(1 for c in candidates if category in c.categories)
            for category in selection.categories
        }
        return {
            "stage": "select",
            "frozen_at": selection.frozen_at,
            "publication_months": list(selection.publication_months),
            "eligible_counts": [list(item) for item in selection.eligible_counts],
            "month_shortfalls": [list(item) for item in selection.month_shortfalls],
            "population_hash": sha256(canonical_json(population)).hexdigest(),
            "intended_count": selection.intended_count,
            "seed": selection.seed,
            "population_rule": selection.population_rule,
            "categories": list(selection.categories),
            "per_category_counts": per_category_counts,
            "legacy_identifiers_skipped": len(legacy),
            "selected": [listed[c.family_id] for c in selection.selected],
        }

    def _publish_document(self, lease: _Lease, body: bytes) -> str:
        # By content: a PDF-only submission's "source" is its PDF, and storage
        # keys one media type to each byte identity.
        media_type = (
            "application/pdf"
            if body.startswith(b"%PDF")
            else "application/octet-stream"
        )
        try:
            return self._publish(
                lease,
                body,
                media_type=media_type,
                kind="source_document",
                inputs=(lease.input_manifest,),
            )
        except StorageClientError as error:
            # The same bytes are already retained under the other media type.
            if (
                error.code != "integrity_failure"
                or media_type == "application/octet-stream"
            ):
                raise
            return self._publish(
                lease,
                body,
                media_type="application/octet-stream",
                kind="source_document",
                inputs=(lease.input_manifest,),
            )

    def _arxiv_document(
        self, lease: _Lease, kind: str
    ) -> tuple[BoundedResponse, tuple[str, ...]]:
        """One document from arXiv's own host under the arXiv gate."""
        family = lease.spec["family"]
        path = document_path(family["family_id"], kind)
        self._sources.arxiv_gate.wait()
        response = self._sources.document(path)
        payload = None
        if response.failure is None and response.body is not None:
            payload = self._publish_document(lease, response.body)
        access = self._access(
            lease,
            source="arxiv",
            url="https://export.arxiv.org" + path,
            parameters=path.encode(),
            adapter=DOCUMENT_ADAPTER,
            response=response,
            license_expression=family["license_url"],
            failure=response.failure,
        )
        record = self._record(lease, access, payload)
        return response, (record,) if payload is None else (payload, record)

    def _bucket_permitted(self) -> bool:
        if self._sources.pdf_bucket is None:
            return False
        try:
            authorize_fetch(BUCKET_SOURCE, BUCKET_HOST)
        except SourceNotPermitted:
            return False
        return True

    def _documents(self, lease: _Lease) -> dict[str, Any]:
        family = lease.spec["family"]
        family_id = family["family_id"]
        # Outcomes live in the cursor so a resumed job still reports both kinds.
        results: dict[str, str] = json.loads(lease.cursor) if lease.cursor else {}
        src_key = work_key("document", family_id, "src")
        pdf_key = work_key("document", family_id, "pdf")
        bucket = self._sources.pdf_bucket
        bucket_path = bucket_pdf_path(family_id)
        pending: Future[BoundedResponse] | None = None
        if pdf_key not in lease.completed and self._bucket_permitted():
            assert bucket is not None
            # The bucket copy downloads while the source waits on arXiv's gate.
            pending = self._sources.bucket_gate.submit(lambda: bucket(bucket_path))
        if src_key not in lease.completed:
            response, outputs = self._arxiv_document(lease, "src")
            results["src"] = response.failure or "retained"
            lease.cursor = json.dumps(results, sort_keys=True)
            self._checkpoint(lease, src_key, outputs)
        if pdf_key in lease.completed:
            return {"stage": "documents", "family_id": family_id, **results}
        outputs = ()
        bucket_body: bytes | None = None
        if pending is not None:
            bucket_response = pending.result()
            outputs = self._bucket_pdf(lease, bucket_path, bucket_response)
            bucket_body = bucket_response.body
            # A 404 means the bucket lacks this version, not that arXiv does.
            results["pdf_bucket"] = (
                "absent"
                if bucket_response.failure == "not_found"
                else bucket_response.failure or "retained"
            )
        elif bucket is not None:
            results["pdf_bucket"] = "not_permitted"
        if results.get("pdf_bucket") in (None, "absent", "not_permitted"):
            response, fetched = self._arxiv_document(lease, "pdf")
            outputs += fetched
            results["pdf"] = response.failure or "retained"
            results["pdf_source"] = "arxiv"
        else:
            results["pdf"] = results["pdf_bucket"]
            results["pdf_source"] = BUCKET_SOURCE
            if results["pdf"] == "retained" and sampled_for_equivalence(family_id):
                # A mismatch is a finding about the bucket, not a failed family.
                response, fetched = self._arxiv_document(lease, "pdf")
                outputs += fetched
                results["pdf_equivalence"] = response.failure or (
                    "equal" if response.body == bucket_body else "mismatch"
                )
        lease.cursor = json.dumps(results, sort_keys=True)
        self._checkpoint(lease, pdf_key, outputs)
        return {"stage": "documents", "family_id": family_id, **results}

    def _bucket_pdf(
        self, lease: _Lease, path: str, response: BoundedResponse
    ) -> tuple[str, ...]:
        """Retain one bucket response and its request record.

        `SourceAccess.source` admits only its closed provenance family, not a
        host; the bucket serves arXiv's own bytes under arXiv's own terms, so
        it is recorded as source "arxiv" like every other arXiv capture, with
        its adapter version and requested URL naming the bucket channel. The
        permission gate above authorizes the distinct `arxiv_gcs_pdf`
        registry entry regardless of this record's source label.
        """
        payload = None
        if response.failure is None and response.body is not None:
            payload = self._publish_document(lease, response.body)
        access = self._access(
            lease,
            source="arxiv",
            url=f"https://{BUCKET_HOST}{path}",
            parameters=path.encode(),
            adapter=BUCKET_PDF_ADAPTER,
            response=response,
            license_expression=lease.spec["family"]["license_url"],
            failure=response.failure,
        )
        record = self._record(lease, access, payload)
        return (record,) if payload is None else (payload, record)

    def _openalex_page(
        self, lease: _Lease, fetched: FetchedOpenAlexPage
    ) -> tuple[tuple[str, ...], dict[str, Any] | None]:
        if fetched.access.http_status == 429:
            raise BudgetExhausted("OpenAlex refused further requests today")
        payload = None
        if fetched.payload is not None:
            payload = self._publish(
                lease,
                fetched.payload,
                media_type="application/json",
                kind="source_response",
                inputs=(lease.input_manifest,),
            )
        record = self._record(lease, fetched.access, payload)
        value = None if fetched.payload is None else json.loads(fetched.payload)
        return ((record,) if payload is None else (payload, record)), value

    def _openalex(self, lease: _Lease) -> dict[str, Any]:
        """Match one target by arXiv DOI, then page its incoming citations.

        The cursor records state across restarts: `page:<work>:<received>:<next>`,
        or a terminal `complete|incomplete|unmatched|ambiguous`. A failed page is
        an incomplete observation, never an empty one.
        """
        family_id = lease.spec["family"]["family_id"]
        budget = int(lease.spec["record_budget"])
        if not lease.completed:
            self._sources.openalex_gate.wait()
            outputs, value = self._openalex_page(
                lease, self._sources.openalex_match(family_id, self._meta(lease))
            )
            works = None if value is None else value["results"]
            if works is None:
                lease.cursor = "incomplete:-:0"
            elif not works:
                lease.cursor = "unmatched:-:0"
            elif len(works) > 1:
                lease.cursor = "ambiguous:-:0"
            else:
                lease.cursor = "page:" + works[0]["id"].rsplit("/", 1)[-1] + ":0:*"
            self._checkpoint(lease, work_key("openalex-match", family_id), outputs)
        assert lease.cursor is not None
        while lease.cursor.startswith("page:"):
            _, work, count, cursor = lease.cursor.split(":", 3)
            received = int(count)
            if received >= budget:
                lease.cursor = f"capped:{work}:{received}"
                break
            page_index = len(lease.completed)
            self._sources.openalex_gate.wait()
            outputs, value = self._openalex_page(
                lease,
                self._sources.openalex_cites(
                    work, None if cursor == "*" else cursor, self._meta(lease)
                ),
            )
            if value is None:
                lease.cursor = f"incomplete:{work}:{received}"
            else:
                received += len(value["results"])
                following = value["meta"]["next_cursor"]
                lease.cursor = (
                    f"complete:{work}:{received}"
                    if following is None
                    else f"page:{work}:{received}:{following}"
                )
            self._checkpoint(
                lease, work_key("openalex-cites", family_id, page_index), outputs
            )
        state, work, count = lease.cursor.split(":", 3)[:3]
        summary: dict[str, Any] = {
            "stage": "openalex",
            "family_id": family_id,
            "state": state,
            "work": None if work == "-" else work,
            "records_received": int(count),
        }
        if self._gate_on_labels:
            summary["gate"] = self._citation_gate(
                lease,
                lease.spec["family"],
                state=state,
                work=None if work == "-" else work,
            )
        return summary

    def _reconstruct_citation_pages(
        self, lease: _Lease, work: str | None
    ) -> tuple[
        list[PaginationPage],
        dict[str, CitationFamilyRecord],
        str | None,
        str | None,
        tuple[str | None, str],
    ]:
        """Rebuild this job's own citation pages from its already-published
        checkpoints, issuing no further request."""
        pages: list[PaginationPage] = []
        families: dict[str, CitationFamilyRecord] = {}
        cursor_in: str | None = None
        match_started: str | None = None
        match_completed: str | None = None
        target_subfield: tuple[str | None, str] = (None, "missing")
        for output in lease.outputs:
            raw = self._produced(lease, output)
            try:
                access = SourceAccess.from_json(raw)
            except (ValueError, KeyError):
                continue
            if access.adapter_version != OPENALEX_ADAPTER:
                continue
            query = parse_qs(urlsplit(access.requested_url).query)
            filt = (query.get("filter") or [""])[0]
            if filt.startswith("doi:"):
                match_started = access.capture_started_at
                match_completed = access.capture_completed_at
                if access.retained_payload_hash is not None:
                    target_subfield = _match_target_subfield(
                        self._read(lease, access.retained_payload_hash)
                    )
                continue
            if work is None or filt != f"cites:{work}":
                continue
            page_index = len(pages)
            if access.failure is not None or access.retained_payload_hash is None:
                pages.append(
                    PaginationPage(
                        page_index=page_index,
                        request_hash=access.request_parameters_hash,
                        response_hash=access.retained_payload_hash,
                        cursor_in=cursor_in,
                        cursor_out=None,
                        returned_count=0,
                        capture_started_at=access.capture_started_at,
                        capture_completed_at=access.capture_completed_at,
                        status="failed",
                        failure=_page_failure(access.failure),
                    )
                )
                break
            payload = self._read(lease, access.retained_payload_hash)
            # A family record dates from the capture it was parsed out of, not
            # from the parse: the observation it hangs from is dated by its last
            # capture and refuses a family newer than itself, and the same page
            # then rebuilds the same record identity on every resume.
            meta = RecordMeta(
                1,
                (access.retained_payload_hash,),
                self._identity.producer,
                self._identity.config_hash,
                access.capture_completed_at,
            )
            parsed = parse_retained_works_page(
                access,
                payload,
                page_index=page_index,
                cursor_in=cursor_in,
                target_provider_ids=(work,),
                meta=meta,
            )
            pages.append(parsed.page)
            for record in parsed.families:
                families[sha256_hex(record.to_canonical_json())] = record
            cursor_in = parsed.page.cursor_out
            if cursor_in is None:
                break
        return pages, families, match_started, match_completed, target_subfield

    def _citation_gate(
        self, lease: _Lease, family: dict[str, Any], *, state: str, work: str | None
    ) -> dict[str, Any]:
        key = work_key("openalex-gate", family["family_id"])
        if key in lease.completed:
            cached = canonical_loads(self._produced(lease, lease.outputs[-1]))
            assert isinstance(cached, dict)
            return cached
        target_match_state = (
            "ambiguous"
            if state == "ambiguous"
            else "matched"
            if work is not None
            else "unmatched"
        )
        pages, families, match_started, match_completed, target_subfield = (
            self._reconstruct_citation_pages(lease, work)
        )
        gate = resolve_citation_gate(
            family,
            target_match_state=target_match_state,
            matched_work_id=work,
            pages=tuple(pages),
            citation_families=families,
            match_started_at=match_started,
            match_completed_at=match_completed,
            target_subfield=target_subfield,
            as_of=utc_now(),
            producer=self._identity.producer,
            config_hash=self._identity.config_hash,
        )
        gate_hash = self._publish(
            lease,
            canonical_json(gate),
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest,),
        )
        self._checkpoint(lease, key, (gate_hash,))
        return gate

    def _openalex_snapshot(self, lease: _Lease) -> dict[str, Any]:
        """Scan the snapshot's works table for one family's incoming citations.

        The job names every part key to scan up front: unlike `_openalex`,
        there is no serialized daily budget forcing one request at a time, so
        one job scans every named part and commits one observation, rather
        than resuming page by page.
        """
        family = lease.spec["family"]
        family_id = family["family_id"]
        target_provider_ids = tuple(lease.spec["target_provider_ids"])
        release = lease.spec["release"]
        part_keys = tuple(lease.spec["part_keys"])
        assert self._sources.snapshot_range is not None

        def fetch_part(key: str) -> Callable[[str], FetchedSnapshotRange]:
            def fetch(range_spec: str) -> FetchedSnapshotRange:
                assert self._sources.snapshot_range is not None
                return self._sources.snapshot_range(key, range_spec)

            return fetch

        parts: list[ParsedSnapshotPart] = []
        outputs: list[str] = []
        for index, key in enumerate(part_keys):
            parsed = parse_snapshot_part(
                fetch_part(key),
                key=key,
                part_index=index,
                cursor_in=part_keys[index - 1] if index else None,
                next_key=part_keys[index + 1] if index + 1 < len(part_keys) else None,
                target_provider_ids=target_provider_ids,
                release=release,
                producer_version=self._identity.producer,
                config_hash=self._identity.config_hash,
            )
            parts.append(parsed)
            for access, payload in parsed.range_reads:
                payload_manifest = self._publish(
                    lease,
                    payload,
                    media_type="application/octet-stream",
                    kind="source_response",
                    inputs=(lease.input_manifest,),
                )
                outputs.append(self._record(lease, access, payload_manifest))
            for record in parsed.families:
                outputs.append(
                    self._publish(
                        lease,
                        record.to_canonical_json(),
                        media_type="application/json",
                        kind="manifest",
                        inputs=(lease.input_manifest,),
                    )
                )
            if parsed.page.status == "failed":
                break

        registry = target_registry(_GATE_TARGET_META)
        observation = build_snapshot_observation(
            tuple(parts),
            paper_family_id=str(derived_uuid("gate-paper-family", family_id)),
            original_version_id=str(derived_uuid("gate-paper-version", family_id)),
            t0=family["first_public_at"],
            target_registry_hash=sha256_hex(registry.to_canonical_json()),
            target_provider_ids=target_provider_ids,
            release=release,
            producer_version=self._identity.producer,
            config_hash=self._identity.config_hash,
        )
        observation_hash = self._publish(
            lease,
            observation.to_canonical_json(),
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *outputs),
        )
        outputs.append(observation_hash)
        self._checkpoint(
            lease, work_key("openalex-snapshot", family_id, release), tuple(outputs)
        )
        return {
            "stage": "openalex_snapshot",
            "family_id": family_id,
            "release": release,
            "parts_scanned": len(parts),
            "citation_families": len(observation.citation_family_hashes),
            "pagination_complete": observation.pagination_complete,
            "observation": observation_hash,
        }
