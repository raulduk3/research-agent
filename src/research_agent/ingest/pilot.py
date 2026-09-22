"""Resumable acquisition worker for the source pilot and corpus release.

The worker holds no database connection. It claims `capture` jobs, reads their
input manifests and publishes every request record and payload through the
storage service, checkpointing after each unit so a killed worker resumes
without repeating completed requests or skipping continuation pages.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from research_agent.contracts import RecordMeta, canonical_json, canonical_loads
from research_agent.contracts.jobs import JobCheckpoint
from research_agent.contracts.papers import SourceAccess
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.arxiv import (
    ArxivFormatError,
    document_path,
    listing_path,
    parse_listing_page,
)
from research_agent.ingest.fetch import BoundedResponse, FetchedOpenAlexPage
from research_agent.learning.corpus import (
    DEFAULT_CAP,
    DEFAULT_CATEGORIES,
    DEFAULT_PER_MONTH,
    DEFAULT_POPULATION_RULE,
    SELECTION_SEED,
    PilotCandidate,
    select_pilot,
)
from research_agent.storage.client import StorageClient, StorageClientError

ARXIV_METADATA_LICENSE = "CC0-1.0"
LISTING_ADAPTER = "arxiv-oai-arxivraw-v1"
DOCUMENT_ADAPTER = "arxiv-original-v1-document-v1"
_RETRY_AFTER_LIMIT_SECONDS = 600.0
_LISTING_ATTEMPTS = 6


class BudgetExhausted(Exception):
    """A provider refused further requests today; the job resumes later."""


class SourceFailed(Exception):
    """A required source response failed; the job ends failed, not retried."""

    def __init__(self, message: str, evidence: tuple[str, ...]) -> None:
        super().__init__(message)
        self.evidence = evidence


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


@dataclass
class Sources:
    """Injectable request functions; production binds them to the real hosts."""

    listing: Callable[[str], BoundedResponse]
    document: Callable[[str], BoundedResponse]
    openalex_match: Callable[[str, RecordMeta], FetchedOpenAlexPage]
    openalex_cites: Callable[[str, str | None, RecordMeta], FetchedOpenAlexPage]
    arxiv_gate: RateGate
    openalex_gate: RateGate


@dataclass(frozen=True, slots=True)
class Identity:
    """The capability this worker publishes under; storage re-checks all of it."""

    producer: ProducerVersion
    config_hash: str
    retention_policy_hash: str
    permission_evidence_hash: str


@dataclass
class _Lease:
    job_id: UUID
    epoch: int
    input_manifest: str
    spec: dict[str, Any]
    completed: list[str] = field(default_factory=list)
    cursor: str | None = None
    outputs: list[str] = field(default_factory=list)


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
    ) -> None:
        self._storage = storage
        self._worker = worker_id
        self._identity = identity
        self._sources = sources

    # --- storage plumbing -------------------------------------------------

    def _meta(self, lease: _Lease) -> RecordMeta:
        return RecordMeta(
            1,
            (lease.input_manifest,),
            self._identity.producer,
            self._identity.config_hash,
            utc_now(),
        )

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
        result = self._storage.publish_artifact(
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
        self._storage.checkpoint(
            job_id=lease.job_id,
            worker_id=self._worker,
            lease_epoch=lease.epoch,
            checkpoint_hash=checkpoint,
            command_id=command,
            request_id=uuid4(),
            idempotency_key=command,
        )
        self._renew(lease)

    def _renew(self, lease: _Lease) -> None:
        command = uuid4()
        self._storage.renew(
            job_id=lease.job_id,
            worker_id=self._worker,
            lease_epoch=lease.epoch,
            command_id=command,
            request_id=uuid4(),
            idempotency_key=command,
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
        self._storage.complete(
            job_id=lease.job_id,
            worker_id=self._worker,
            lease_epoch=lease.epoch,
            result={"kind": "committed", "output_hashes": [report]},
            command_id=command,
            request_id=uuid4(),
            idempotency_key=command,
        )

    def _fail(self, lease: _Lease, failure: SourceFailed) -> None:
        command = derived_uuid(lease.job_id, lease.epoch, "fail", str(failure))
        self._storage.complete(
            job_id=lease.job_id,
            worker_id=self._worker,
            lease_epoch=lease.epoch,
            result={
                "kind": "failed",
                "error": {
                    "code": "unavailable_source",
                    "message": str(failure)[:512],
                    "retryable": False,
                    "evidence_ids": list(failure.evidence[:20]),
                },
            },
            command_id=command,
            request_id=uuid4(),
            idempotency_key=command,
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
            }[str(lease.spec["stage"])]
            try:
                summary = handler(lease)
            except BudgetExhausted:
                return RunSummary(completed, True)
            except SourceFailed as failure:
                self._fail(lease, failure)
                completed += 1
                continue
            self._complete(lease, summary)
            completed += 1
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
        """Every successful page from the admitted listing jobs, found by content."""
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
                    yield self._read(lease, access.retained_payload_hash)

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

    def _documents(self, lease: _Lease) -> dict[str, Any]:
        family = lease.spec["family"]
        # Outcomes live in the cursor so a resumed job still reports both kinds.
        results: dict[str, str] = json.loads(lease.cursor) if lease.cursor else {}
        for kind in ("src", "pdf"):
            key = work_key("document", family["family_id"], kind)
            if key in lease.completed:
                continue
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
            results[kind] = response.failure or "retained"
            lease.cursor = json.dumps(results, sort_keys=True)

            self._checkpoint(
                lease, key, (record,) if payload is None else (payload, record)
            )
        return {"stage": "documents", "family_id": family["family_id"], **results}

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
        return {
            "stage": "openalex",
            "family_id": family_id,
            "state": state,
            "work": None if work == "-" else work,
            "records_received": int(count),
        }
