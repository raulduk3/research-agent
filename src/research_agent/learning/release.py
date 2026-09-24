"""Assemble and publish the versioned historical training corpus release.

A resumable, checkpointed batch job (PL-11, PL-15, PL-16) that, for one
release purpose, resolves automatic labels for a frozen population, assigns
each family's chronological split, writes a coverage report and publishes
one immutable ``CorpusRelease`` artifact with content hashes. The corpus
population rule is a configured value the owner has not yet answered on
#66; this job refuses to run without one.

Selection of the population itself (the 100-paper pilot and the modeling
manifests) and construction of the automatic observations it resolves
labels from belong to other slices of #66. This job consumes their already
published, content-addressed outputs by reference.
"""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import (
    ProducerVersion,
    RecordMeta,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.corpus import CorpusRelease, CorpusRow
from research_agent.contracts.jobs import JobCheckpoint
from research_agent.contracts.learning import (
    AutomaticLabel,
    CitationFamilyRecord,
    CitationObservation,
    TargetDefinition,
)
from research_agent.contracts.papers import PaperVersionRecord
from research_agent.learning.corpus import WeekSplit, publication_week
from research_agent.learning.coverage import FamilySupport, summarize_support
from research_agent.learning.features import (
    PassageEmbedding,
    combined_feature_record,
    detect_code_link,
)
from research_agent.outcomes.resolve import Resolver
from research_agent.outcomes.targets import definitions as target_definitions
from research_agent.outcomes.targets import registry as target_registry
from research_agent.outcomes.windows import instant, maturity_at
from research_agent.storage.artifacts import ArtifactRepository, PublicationAdmission
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.jobs import JobRepository
from research_agent.storage.migrate import migrate

JOB_KIND = "label"
_SPEC_LIMIT = 16 * 1024 * 1024
_LABELED_PARTITIONS = frozenset(
    {
        "fit",
        "development",
        "calibration",
        "locked_evaluation",
        "refresh_fit",
        "refresh_calibration",
    }
)
_WEEK_PARTITIONS = ("fit", "development", "calibration", "locked_evaluation")
_ROOT = Path(__file__).resolve().parents[3]
_RETENTION = (
    b"Corpus release manifests and their coverage reports are retained "
    b"privately for this research and are not redistributed."
)
# The automatic-citations-v1 registry is one fixed, versioned identity shared
# by every historical and prospective resolution path (FT-19): its hash must
# not depend on any one release job's own input manifest or fitting cutoff.
# The fixed instant only needs to precede every fitting cutoff this protocol
# version is ever used with; it is not a claim about when it was adopted.
_TARGET_META = RecordMeta(
    1,
    (),
    ProducerVersion(sha256(b"automatic-citations-v1").hexdigest(), "0" * 40, 1),
    sha256(b"automatic-citations-v1").hexdigest(),
    "2000-01-01T00:00:00.000000Z",
)


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


@dataclass(frozen=True, slots=True)
class Identity:
    """The capability this job publishes under; storage re-checks all of it."""

    producer: ProducerVersion
    config_hash: str
    retention_policy_hash: str


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    """One population member as the operator selected it, before resolution."""

    paper_family_id: str
    original_version_id: str
    selection_rank: int
    t0: str
    source_subfield: str | None
    paper_artifact_hash: str | None
    observation_artifact_hash: str | None
    feature_artifact_hash: str | None

    @classmethod
    def from_spec(cls, value: dict[str, Any]) -> "ReleaseCandidate":
        return cls(
            value["paper_family_id"],
            value["original_version_id"],
            value["selection_rank"],
            value["t0"],
            value.get("source_subfield"),
            value.get("paper_artifact_hash"),
            value.get("observation_artifact_hash"),
            value.get("feature_artifact_hash"),
        )


# --- pure assembly -----------------------------------------------------


def label_fields(
    label: AutomaticLabel | None,
) -> tuple[str | None, bool]:
    """The row's stored reference and known state for one resolved target."""
    if label is None:
        return None, False
    return sha256_hex(label.to_canonical_json()), label.state != "unknown"


def week_partition(t0: str, split: WeekSplit) -> str:
    week = publication_week(t0)
    for weeks, name in zip(
        (split.fit, split.development, split.calibration, split.locked_evaluation),
        _WEEK_PARTITIONS,
        strict=True,
    ):
        if week in weeks:
            return name
    raise ValueError("candidate publication week is outside the frozen split")


def build_row(
    candidate: ReleaseCandidate,
    *,
    rank: int,
    paper: PaperVersionRecord | None,
    labels: tuple[AutomaticLabel | None, AutomaticLabel | None, AutomaticLabel | None],
    purpose: str,
    split: WeekSplit | None,
    fitting_cutoff: str,
    count_tokens: Callable[[str], int] | None = None,
    feature_hash: str | None = None,
) -> CorpusRow:
    """Build one release row.

    ``count_tokens`` is the pinned embedding tokenizer's count; with it and
    a paper, the row records every card field the metadata block needs
    (#278). ``feature_hash`` names the combined feature record published
    for this row and takes the place of the candidate's own reference.
    """
    t0 = paper.first_public_at if paper is not None else candidate.t0
    exclusions: set[str] = set()
    if paper is None:
        exclusions.add("source_unavailable")
    if t0 is None:
        exclusions.add("unknown_t0")
    if not exclusions:
        assert t0 is not None
        if purpose == "acquisition_pilot":
            partition = "pilot"
        else:
            if split is None:
                raise ValueError(
                    "a chronological split is required for this release purpose"
                )
            partition = week_partition(t0, split)
        if partition in _LABELED_PARTITIONS and instant(maturity_at(t0)) > instant(
            fitting_cutoff
        ):
            raise ValueError(
                "a family whose t0 is later than the label horizon end cannot "
                "enter a labeled split"
            )
    else:
        partition = "excluded"
    label_hashes: list[str | None] = []
    known_mask: list[bool] = []
    for label in labels:
        label_hash, known = label_fields(label)
        label_hashes.append(label_hash)
        known_mask.append(known)
    source_subfield = (
        paper.primary_source_subfield
        if paper is not None
        else candidate.source_subfield
    )
    card = paper if count_tokens is not None else None
    return CorpusRow(
        paper_family_id=candidate.paper_family_id,
        original_version_id=candidate.original_version_id,
        t0=t0,
        publication_week=None if t0 is None else publication_week(t0),
        source_subfield=source_subfield,
        selection_rank=rank,
        feature_hash=feature_hash or candidate.feature_artifact_hash,
        label_hashes=(label_hashes[0], label_hashes[1], label_hashes[2]),
        known_mask=(known_mask[0], known_mask[1], known_mask[2]),
        partition=partition,
        exclusion_reasons=tuple(sorted(exclusions)),
        author_count=paper.author_count if paper is not None else None,
        categories=paper.categories if paper is not None else None,
        version_count=paper.version_count if paper is not None else None,
        abstract_tokens=(
            None
            if card is None or count_tokens is None
            else count_tokens(card.abstract)
        ),
        title_tokens=(
            None if card is None or count_tokens is None else count_tokens(card.title)
        ),
        first_available_weekday=(
            None if card is None or t0 is None else instant(t0).weekday()
        ),
        # The comments field the rule also reads is not captured for
        # historical versions, so only the abstract is searched.
        code_link=None if card is None else detect_code_link(card.abstract, None),
    )


def coverage_report_bytes(rows: tuple[CorpusRow, ...], *, intended: int) -> bytes:
    support = tuple(
        FamilySupport(
            row.paper_family_id,
            "source_unavailable" not in row.exclusion_reasons,
            row.feature_hash is not None,
            row.known_mask,
        )
        for row in rows
    )
    summary = summarize_support(support, intended=intended)
    return canonical_json(
        {
            "intended": summary.intended,
            "selected": summary.selected,
            "source_available": summary.source_available,
            "features_complete": summary.features_complete,
            "known_labels": list(summary.known_labels),
            "jointly_eligible": list(summary.jointly_eligible),
            "shortfall": summary.shortfall,
        }
    )


def assemble_release(
    *,
    purpose: str,
    population_rule: str,
    selection_seed: int,
    selection_frozen_at: str,
    fitting_cutoff: str,
    intended_population_count: int,
    enumerated_population_hash: str,
    rows: tuple[CorpusRow, ...],
    target_registry_hash: str,
    representation_hash: str,
    source_observation_hashes: tuple[str, ...],
    prior_release_hash: str | None,
    meta: RecordMeta,
) -> tuple[CorpusRelease, bytes]:
    """Build the immutable release record and its coverage report bytes.

    Refuses to run without a configured, non-blank population rule (the
    owner's still-open decision on #66).
    """
    if not population_rule or population_rule != population_rule.strip():
        raise ValueError(
            "corpus release refuses to run without a configured population rule"
        )
    families = [row.paper_family_id for row in rows]
    if len(set(families)) != len(families):
        raise ValueError("corpus release rows repeat a family")
    for row in rows:
        if row.partition in _LABELED_PARTITIONS:
            if row.t0 is None:
                raise ValueError(
                    "a labeled split row requires a known first-public time"
                )
            if instant(maturity_at(row.t0)) > instant(fitting_cutoff):
                raise ValueError(
                    "a family whose t0 is later than the label horizon end cannot "
                    "enter a labeled split"
                )
    shortfall_count = intended_population_count - len(rows)
    if shortfall_count < 0:
        raise ValueError("selected rows exceed the intended population")
    coverage_bytes = coverage_report_bytes(rows, intended=intended_population_count)
    split_hash = sha256_hex(
        canonical_json(
            {
                "purpose": purpose,
                "partitions": sorted(
                    (row.paper_family_id, row.partition) for row in rows
                ),
            }
        )
    )
    release = CorpusRelease(
        schema_version=meta.schema_version,
        input_hashes=meta.input_hashes,
        producer_version=meta.producer_version,
        config_hash=meta.config_hash,
        created_at=meta.created_at,
        purpose=purpose,
        target_registry_hash=target_registry_hash,
        representation_hash=representation_hash,
        selection_seed=selection_seed,
        selection_frozen_at=selection_frozen_at,
        fitting_cutoff=fitting_cutoff,
        intended_population_count=intended_population_count,
        enumerated_population_hash=enumerated_population_hash,
        rows=rows,
        shortfall_count=shortfall_count,
        split_hash=split_hash,
        coverage_report_hash=sha256_hex(coverage_bytes),
        source_observation_hashes=tuple(sorted(set(source_observation_hashes))),
        prior_release_hash=prior_release_hash,
    )
    return release, coverage_bytes


# --- resumable worker ----------------------------------------------------


@dataclass
class _Lease:
    job_id: UUID
    epoch: int
    input_manifest: str
    spec: dict[str, Any] = field(default_factory=dict)
    completed: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


class BatchJobWorker:
    """Claims one kind of batch job and commits its work through storage.

    Talks to storage directly through ``JobRepository``/``ArtifactRepository``
    rather than over the network boundary the deployed storage service
    exposes: these batch jobs run inside the same trust domain as the
    operator that enqueues them, so the extra hop buys nothing here. A
    subclass names its ``kind`` and does one job's work in ``_work``.
    """

    kind = ""
    maximum_length = _SPEC_LIMIT

    def __init__(
        self,
        jobs: JobRepository,
        artifacts: ArtifactRepository,
        database: Database,
        *,
        worker_id: UUID,
        identity: Identity,
    ) -> None:
        self._jobs = jobs
        self._artifacts = artifacts
        self._database = database
        self._worker = worker_id
        self._identity = identity

    # --- storage plumbing --------------------------------------------

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
        command = derived_uuid(
            lease.job_id, "publish", digest, media_type, kind, inputs
        )
        identity = CommandIdentity(self._worker, command, command, uuid4())
        admission = PublicationAdmission(
            lease.job_id, lease.epoch, self._worker, frozenset({self.kind})
        )
        response = self._artifacts.publish_command(
            [payload],
            identity=identity,
            expected_hash=digest,
            byte_length=len(payload),
            maximum_length=self.maximum_length,
            media_type=media_type,
            kind=kind,
            input_hashes=inputs,
            producer_version=self._identity.producer,
            config_hash=self._identity.config_hash,
            retention_policy_hash=self._identity.retention_policy_hash,
            source_available_at=None,
            admission=admission,
        )
        envelope = canonical_loads(response.body)
        assert isinstance(envelope, dict)
        result = envelope["data"]
        assert isinstance(result, dict)
        receipt = result["receipt"]
        assert isinstance(receipt, dict)
        artifact_hashes = receipt["artifact_hashes"]
        assert isinstance(artifact_hashes, list)
        manifest = artifact_hashes[1]
        assert isinstance(manifest, str)
        return manifest

    def _raw(self, manifest_hash: str) -> str:
        row = self._database.transaction(
            lambda connection: connection.execute(
                "SELECT encode(artifact_hash,'hex') FROM artifact_productions "
                "WHERE manifest_hash=decode(%s,'hex')",
                (manifest_hash,),
            ).fetchone()
        )
        assert row is not None
        return str(row[0])

    def _read(self, manifest_hash: str) -> bytes:
        return self._read_content(self._raw(manifest_hash))

    def _read_content(self, artifact_hash: str) -> bytes:
        """Read committed bytes by their own content hash; storage verifies it."""
        (_length, _media), stream = self._artifacts.read(artifact_hash)
        with stream:
            return stream.read()

    def _read_json(self, manifest_hash: str) -> Any:
        return canonical_loads(self._read(manifest_hash))

    def _job_execute(
        self, operation: str, payload: dict[str, Any], *, job_id: UUID | None = None
    ) -> dict[str, Any]:
        command = uuid4()
        identity = CommandIdentity(self._worker, command, command, uuid4())
        response = self._jobs.execute(
            operation, identity=identity, payload=payload, job_id=job_id
        )
        data = canonical_loads(response.body)
        assert isinstance(data, dict)
        result = data["data"]
        assert isinstance(result, dict)
        return result

    def _renew(self, lease: _Lease) -> None:
        self._job_execute(
            "renew",
            {"worker_id": str(self._worker), "lease_epoch": lease.epoch},
            job_id=lease.job_id,
        )

    @contextmanager
    def _heartbeat(self, lease: _Lease) -> Iterator[None]:
        """Keep the lease alive through one long, uncheckpointable step."""
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(JobRepository.LEASE_SECONDS / 4):
                self._renew(lease)

        thread = threading.Thread(target=beat, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join()

    def _checkpoint(self, lease: _Lease, key: str, outputs: tuple[str, ...]) -> None:
        lease.completed.append(key)
        lease.outputs.extend(
            o for o in dict.fromkeys(outputs) if o not in lease.outputs
        )
        body = JobCheckpoint(
            1,
            str(lease.job_id),
            self.kind,
            (lease.input_manifest,),
            self._identity.config_hash,
            tuple(lease.completed),
            None,
            tuple(lease.outputs),
        ).to_canonical_json()
        checkpoint_hash = self._publish(
            lease,
            body,
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *lease.outputs),
        )
        self._job_execute(
            "checkpoint",
            {
                "fence": {"worker_id": str(self._worker), "lease_epoch": lease.epoch},
                "checkpoint": checkpoint_hash,
            },
            job_id=lease.job_id,
        )
        self._renew(lease)

    def _complete(self, lease: _Lease, summary: dict[str, Any]) -> None:
        report = self._publish(
            lease,
            canonical_json(summary),
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *lease.outputs),
        )
        self._job_execute(
            "complete",
            {
                "fence": {"worker_id": str(self._worker), "lease_epoch": lease.epoch},
                "result": {"kind": "committed", "output_hashes": [report]},
            },
            job_id=lease.job_id,
        )

    def _resume(self, lease: _Lease, checkpoint: str | None) -> None:
        if checkpoint is None:
            return
        state = JobCheckpoint.from_json(self._read(checkpoint))
        lease.completed = list(state.completed_work_keys)
        lease.outputs = list(state.output_hashes)

    # --- run loop -------------------------------------------------------

    def run(self, *, maximum_jobs: int | None = None) -> int:
        completed = 0
        while maximum_jobs is None or completed < maximum_jobs:
            claimed = self._job_execute(
                "claim", {"worker_id": str(self._worker), "kinds": [self.kind]}
            )["lease"]
            if claimed is None:
                break
            job_id = UUID(claimed["job_id"])
            lease = _Lease(job_id, claimed["lease_epoch"], claimed["input_manifest"])
            spec = self._read_json(lease.input_manifest)
            if not isinstance(spec, dict):
                raise ValueError(f"{self.kind} job input is not a specification object")
            lease.spec = spec
            self._resume(lease, claimed["checkpoint"])
            summary = self._work(lease)
            self._complete(lease, summary)
            completed += 1
        return completed

    def _work(self, lease: _Lease) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class EmbeddedVersion:
    """One paper version's embedded vectors with the passage spans they cover."""

    extraction_hash: str
    coverage: str
    overview: tuple[float, ...]
    passages: tuple[PassageEmbedding, ...]
    computed_at: str
    vector_file_hash: str


class ReleaseWorker(BatchJobWorker):
    """Claims ``label`` jobs and assembles one corpus release per job.

    With ``count_tokens`` every row records the card fields its metadata
    block needs; with ``embedded`` every row whose original version was
    embedded completely gets one published ``CombinedFeatureRecord``, and
    the row's ``feature_hash`` names it (#278).
    """

    kind = JOB_KIND

    def __init__(
        self,
        jobs: JobRepository,
        artifacts: ArtifactRepository,
        database: Database,
        *,
        worker_id: UUID,
        identity: Identity,
        count_tokens: Callable[[str], int] | None = None,
        embedded: Callable[[PaperVersionRecord], EmbeddedVersion | None] | None = None,
    ) -> None:
        super().__init__(
            jobs, artifacts, database, worker_id=worker_id, identity=identity
        )
        self._count_tokens = count_tokens
        self._embedded = embedded

    def _work(self, lease: _Lease) -> dict[str, Any]:
        return self._label(lease)

    # --- the one stage ----------------------------------------------------

    def _read_family(self, artifact_hash: str) -> CitationFamilyRecord:
        # Resolver addresses citation families by their own content hash
        # (verified against the record's bytes), not by publication manifest.
        return CitationFamilyRecord.from_json(self._read_content(artifact_hash))

    def _publish_feature(
        self,
        lease: _Lease,
        candidate: ReleaseCandidate,
        paper: PaperVersionRecord,
        representation_hash: str,
    ) -> str | None:
        """Publish the row's combined feature record; return its content hash.

        A version that was not embedded, or whose extraction is incomplete or
        whose vectors do not pool, gets no record and the row no feature.
        """
        assert self._embedded is not None
        version = self._embedded(paper)
        if version is None:
            return None
        paper_hash = sha256_hex(paper.to_canonical_json())
        try:
            record, payloads = combined_feature_record(
                version.overview,
                version.passages,
                paper_family_id=candidate.paper_family_id,
                source_version_id=paper.version_id,
                original_version_id=candidate.original_version_id,
                original_source_hash=paper.original_source_hash,
                extraction_hash=version.extraction_hash,
                extraction_coverage=version.coverage,
                representation_hash=representation_hash,
                computed_at=version.computed_at,
                meta=RecordMeta(
                    1,
                    (paper_hash, version.vector_file_hash),
                    self._identity.producer,
                    self._identity.config_hash,
                    version.computed_at,
                ),
            )
        except ValueError:
            return None
        for payload in payloads.values():
            self._publish(
                lease,
                payload,
                media_type="application/octet-stream",
                kind="vector_payload",
                inputs=(lease.input_manifest,),
            )
        body = record.to_canonical_json()
        self._publish(
            lease,
            body,
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest,),
        )
        return sha256_hex(body)

    def _row(
        self,
        lease: _Lease,
        candidate: ReleaseCandidate,
        *,
        rank: int,
        resolver: Resolver,
        targets: tuple[TargetDefinition, ...],
        as_of: str,
        purpose: str,
        split: WeekSplit | None,
        representation_hash: str,
    ) -> tuple[CorpusRow, str | None]:
        paper = (
            None
            if candidate.paper_artifact_hash is None
            else PaperVersionRecord.from_json(self._read(candidate.paper_artifact_hash))
        )
        observation = (
            None
            if candidate.observation_artifact_hash is None
            else CitationObservation.from_json(
                self._read(candidate.observation_artifact_hash)
            )
        )
        labels: tuple[
            AutomaticLabel | None, AutomaticLabel | None, AutomaticLabel | None
        ] = (None, None, None)
        observation_hash = None
        if paper is not None and observation is not None:
            resolved = tuple(
                resolver.resolve_target(target, paper, observation, as_of)
                for target in targets
            )
            labels = (resolved[0], resolved[1], resolved[2])
            observation_hash = sha256_hex(observation.to_canonical_json())
            # The row cites each label by content hash; publishing it is what
            # lets training materialization read and verify it (#278).
            for label in labels:
                if label is not None:
                    self._publish(
                        lease,
                        label.to_canonical_json(),
                        media_type="application/json",
                        kind="manifest",
                        inputs=(lease.input_manifest,),
                    )
        feature_hash = (
            self._publish_feature(lease, candidate, paper, representation_hash)
            if paper is not None and self._embedded is not None
            else None
        )
        row = build_row(
            candidate,
            rank=rank,
            paper=paper,
            labels=labels,
            purpose=purpose,
            split=split,
            fitting_cutoff=as_of,
            count_tokens=self._count_tokens,
            feature_hash=feature_hash,
        )
        return row, observation_hash

    def _label(self, lease: _Lease) -> dict[str, Any]:
        spec = lease.spec
        purpose = str(spec["purpose"])
        fitting_cutoff = str(spec["fitting_cutoff"])
        candidates = sorted(
            (ReleaseCandidate.from_spec(item) for item in spec["candidates"]),
            key=lambda item: item.selection_rank,
        )
        meta = RecordMeta(
            1,
            (lease.input_manifest,),
            self._identity.producer,
            self._identity.config_hash,
            fitting_cutoff,
        )
        targets = target_definitions(_TARGET_META)
        registry = target_registry(_TARGET_META)
        resolver = Resolver(self._read_family, meta, registry=registry)
        split = None
        if purpose != "acquisition_pilot":
            split = WeekSplit(
                tuple(spec["fit_weeks"]),
                tuple(spec["development_weeks"]),
                tuple(spec["calibration_weeks"]),
                tuple(spec["locked_evaluation_weeks"]),
            )
        observation_hashes: list[str] = []
        for index in range(len(lease.completed), len(candidates)):
            candidate = candidates[index]
            row, observation_hash = self._row(
                lease,
                candidate,
                rank=candidate.selection_rank,
                resolver=resolver,
                targets=targets,
                as_of=fitting_cutoff,
                purpose=purpose,
                split=split,
                representation_hash=str(spec["representation_hash"]),
            )
            if observation_hash is not None:
                observation_hashes.append(observation_hash)
            row_hash = self._publish(
                lease,
                row.to_canonical_json(),
                media_type="application/json",
                kind="manifest",
                inputs=(lease.input_manifest,),
            )
            self._checkpoint(
                lease, work_key(JOB_KIND, candidate.paper_family_id), (row_hash,)
            )
        rows = tuple(CorpusRow.from_json(self._read(h)) for h in lease.outputs)
        release, coverage_bytes = assemble_release(
            purpose=purpose,
            population_rule=str(spec["population_rule"]),
            selection_seed=int(spec["selection_seed"]),
            selection_frozen_at=str(spec["selection_frozen_at"]),
            fitting_cutoff=fitting_cutoff,
            intended_population_count=int(spec["intended_population_count"]),
            enumerated_population_hash=str(spec["enumerated_population_hash"]),
            rows=rows,
            target_registry_hash=sha256_hex(registry.to_canonical_json()),
            representation_hash=str(spec["representation_hash"]),
            source_observation_hashes=tuple(observation_hashes),
            prior_release_hash=spec.get("prior_release_hash"),
            meta=RecordMeta(
                1,
                (lease.input_manifest, *lease.outputs),
                self._identity.producer,
                self._identity.config_hash,
                utc_now(),
            ),
        )
        coverage_hash = self._publish(
            lease,
            coverage_bytes,
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *lease.outputs),
        )
        release_hash = self._publish(
            lease,
            release.to_canonical_json(),
            media_type="application/json",
            kind="manifest",
            inputs=(lease.input_manifest, *lease.outputs),
        )
        return {
            "stage": JOB_KIND,
            "purpose": purpose,
            "release_hash": release_hash,
            "release_artifact_hash": sha256_hex(release.to_canonical_json()),
            "coverage_report_hash": coverage_hash,
            "rows": len(rows),
            "shortfall_count": release.shortfall_count,
        }


# --- local operator -----------------------------------------------------


def _commit() -> str:
    return subprocess.run(
        ("git", "-C", str(_ROOT), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def local_identity(config: dict[str, Any]) -> Identity:
    """The local operator's publishing identity for one configuration."""
    producer = ProducerVersion(sha256(b"local-process").hexdigest(), _commit(), 1)
    return Identity(
        producer,
        sha256(canonical_json(config)).hexdigest(),
        sha256(_RETENTION).hexdigest(),
    )


def _identity(
    *, population_rule: str, purpose: str, representation_hash: str
) -> Identity:
    return local_identity(
        {
            "population_rule": population_rule,
            "purpose": purpose,
            "representation_hash": representation_hash,
        }
    )


def release_job_id(release_id: str) -> UUID:
    """The one job a named release is built by, so a rerun finds it again."""
    return derived_uuid("corpus-release", release_id)


def _spec_from_args(args: argparse.Namespace, population_rule: str) -> dict[str, Any]:
    candidates_path: Path = args.candidates
    payload = json.loads(candidates_path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("candidates file must contain a JSON object")
    # A list built for one purpose carries that purpose's split weeks, or none.
    if payload.get("purpose", args.purpose) != args.purpose:
        raise ValueError(
            f"candidates file was built for purpose {payload['purpose']!r}, "
            f"not {args.purpose!r}"
        )
    payload["purpose"] = args.purpose
    payload["population_rule"] = population_rule
    payload["representation_hash"] = args.representation_hash
    payload["prior_release_hash"] = args.prior_release_hash
    return payload


def local_embedding_inputs(
    embeddings: Path,
    text: Path,
    *,
    representation_hash: str,
    cache_dir: Path | None,
) -> tuple[
    Callable[[str], int], Callable[[PaperVersionRecord], EmbeddedVersion | None]
]:
    """Bind a verified ``bin/embed-batch`` output to the pinned tokenizer.

    Loads the tokenizer from the local model cache only; nothing is
    downloaded. Passage spans are rebuilt from the exported text with the
    same chunker the batch used and must match each vector's text hash.
    """
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    from research_agent.models import batch as batch_module
    from research_agent.models.manifest import MODEL_ID, REVISION
    from research_agent.retrieval.passages import build_passages

    manifest = batch_module.read_batch_manifest(embeddings)
    batch_module.verify_batch_manifest(embeddings, manifest)
    snapshot = snapshot_download(
        MODEL_ID,
        revision=REVISION,
        cache_dir=None if cache_dir is None else str(cache_dir),
        local_files_only=True,
    )
    tokenizer = batch_module.OffsetTokenizer(AutoTokenizer.from_pretrained(snapshot))

    def count_tokens(value: str) -> int:
        return len(tokenizer.encode_offsets(value))

    def embedded(paper: PaperVersionRecord) -> EmbeddedVersion | None:
        file_hash = manifest.file_hashes.get(paper.version_id)
        if file_hash is None:
            return None
        path = batch_module.paper_batch_path(embeddings, paper.version_id)
        if sha256(path.read_bytes()).hexdigest() != file_hash:
            raise ValueError("embedded vector file differs from its batch manifest")
        vectors = batch_module.read_paper_batch(path)
        exported = batch_module.read_paper_text(text, paper.version_id)
        if exported.extraction_hash != vectors.extraction_hash:
            raise ValueError("exported text and vectors name different extractions")
        spans = build_passages(
            exported.extraction,
            exported.canonical_text,
            exported.extraction_hash,
            tokenizer,
        )
        if [span.text_hash for span in spans] != [
            passage.text_hash
            for passage in sorted(vectors.passages, key=lambda p: p.passage_order)
        ]:
            raise ValueError("rebuilt passages differ from the embedded passages")
        return EmbeddedVersion(
            vectors.extraction_hash,
            vectors.coverage,
            vectors.overview_vector,
            tuple(
                PassageEmbedding(
                    span.section_order,
                    span.section_token_start,
                    span.section_token_end_exclusive,
                    representation_hash,
                    passage.vector,
                )
                for span, passage in zip(
                    spans,
                    sorted(vectors.passages, key=lambda p: p.passage_order),
                    strict=True,
                )
            ),
            manifest.created_at,
            file_hash,
        )

    return count_tokens, embedded


def _job_rows(
    database: Database, job_id: UUID | None = None
) -> list[tuple[str, str, str | None]]:
    """Every release job in the schema, or only ``job_id``'s."""
    return database.transaction(
        lambda connection: [
            (str(row[0]), str(row[1]), None if row[2] is None else str(row[2]))
            for row in connection.execute(
                "SELECT j.id, j.state, encode(o.artifact_hash,'hex') "
                "FROM jobs j LEFT JOIN job_outputs o ON o.job_id=j.id "
                "WHERE j.kind=%s AND (%s::uuid IS NULL OR j.id=%s::uuid) "
                "ORDER BY j.scheduled_at, j.id",
                (JOB_KIND, job_id, job_id),
            ).fetchall()
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "report"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--dsn", required=True, help="DSN selecting a release schema")
    parser.add_argument(
        "--population-rule",
        required=True,
        help="the owner's configured population rule; refuses to run without it",
    )
    parser.add_argument("--purpose", default="acquisition_pilot")
    parser.add_argument("--representation-hash", required=True)
    parser.add_argument("--prior-release-hash", default=None)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument(
        "--release-id",
        help=(
            "names this release, so several releases share one schema; run "
            "enqueues it once and report lists only it"
        ),
    )
    parser.add_argument(
        "--embeddings",
        type=Path,
        help="a verified bin/embed-batch output; rows get feature records",
    )
    parser.add_argument(
        "--text", type=Path, help="the bin/export-text directory it embedded"
    )
    parser.add_argument("--model-cache-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    if (args.embeddings is None) != (args.text is None):
        parser.error("--embeddings and --text are given together")
    population_rule = args.population_rule.strip()
    if not population_rule:
        parser.error(
            "corpus release refuses to run without a configured population rule"
        )
    state: Path = args.state
    state.mkdir(parents=True, exist_ok=True)
    identity = _identity(
        population_rule=population_rule,
        purpose=args.purpose,
        representation_hash=args.representation_hash,
    )
    migrate(Database(args.dsn))
    database = Database(args.dsn)
    store = ArtifactStore(state / "artifacts")
    artifacts = ArtifactRepository(database, store)
    jobs = JobRepository(
        database,
        store,
        producer=identity.producer,
        config_hash=identity.config_hash,
        retention_policy_hash=identity.retention_policy_hash,
    )
    # Without a release id the schema holds one release, its first job.
    release_job = None if args.release_id is None else release_job_id(args.release_id)
    existing = _job_rows(database, release_job)
    if args.command == "report":
        print(json.dumps({"jobs": existing}, indent=2, sort_keys=True))
        return 0
    if not existing and args.candidates is None:
        parser.error("--candidates is required to enqueue this release job")
    worker_id = derived_uuid("release-worker", state.as_posix())
    if not existing:
        assert args.candidates is not None
        try:
            spec = _spec_from_args(args, population_rule)
        except ValueError as error:
            parser.error(str(error))
        spec_bytes = canonical_json(spec)
        digest = sha256(spec_bytes).hexdigest()
        command = uuid4()
        publication = artifacts.publish(
            [spec_bytes],
            expected_hash=digest,
            byte_length=len(spec_bytes),
            maximum_length=_SPEC_LIMIT,
            media_type="application/json",
            kind="manifest",
            input_hashes=(),
            producer_version=identity.producer,
            config_hash=identity.config_hash,
            retention_policy_hash=identity.retention_policy_hash,
            command_id=command,
        )
        job_id = uuid4() if release_job is None else release_job
        jobs.execute(
            "enqueue",
            identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
            payload={
                "job_id": str(job_id),
                "kind": JOB_KIND,
                "input_manifest": publication.manifest_hash,
                "scheduled_at": utc_now(),
            },
        )
    count_tokens: Callable[[str], int] | None = None
    embedded: Callable[[PaperVersionRecord], EmbeddedVersion | None] | None = None
    if args.embeddings is not None:
        count_tokens, embedded = local_embedding_inputs(
            args.embeddings,
            args.text,
            representation_hash=args.representation_hash,
            cache_dir=args.model_cache_dir,
        )
    worker = ReleaseWorker(
        jobs,
        artifacts,
        database,
        worker_id=worker_id,
        identity=identity,
        count_tokens=count_tokens,
        embedded=embedded,
    )
    started = time.monotonic()
    completed = worker.run()
    run = {
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.monotonic() - started, 3),
        # macOS reports bytes, Linux kibibytes.
        "peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "platform": sys.platform,
        "jobs_completed": completed,
        "artifact_disk_bytes": sum(
            f.stat().st_size for f in (state / "artifacts").rglob("*") if f.is_file()
        ),
        "free_disk_bytes": shutil.disk_usage(state).free,
    }
    with (state / "runs.jsonl").open("a") as runs:
        runs.write(json.dumps(run) + "\n")
    print(json.dumps(run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
