"""Fit, calibrate, qualify and bundle the three heads from a corpus release (#278).

``bin/fit-heads`` runs this module as one resumable ``fit`` batch job
(PL-11) over two committed corpus releases (PL-17): the initial-fit corpus
and the acquisition pilot that decides source feasibility. The job

1. builds and publishes one ``TrainingArrays`` record per partition from
   the release's own rows, combined feature records, automatic labels and
   recorded card fields, checkpointing each, then materializes it back
   through ``arrays.materialize_training_arrays``, which verifies every row
   against the records it cites;
2. fits the three heads, calibrates each by primary category, runs
   ``qualify_corpus`` on the locked evaluation partition, writes the bundle
   through ``bundles.validate_bundle`` and the promotion decision through
   ``promote.promote_three_heads``; a target that did not qualify is never
   scored for promotion.

It activates nothing: activation stays with the registry and its own
command. It makes no paid call and downloads nothing. Every output is a
pure function of the two releases and the fixed configuration, so a rerun
reproduces the same bundle id and bundle bytes.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json
from research_agent.contracts.corpus import CorpusRelease, CorpusRow
from research_agent.contracts.learning import (
    EMBEDDING_FEATURE_DIMENSION,
    TARGET_IDS,
    AutomaticLabel,
    CombinedFeatureRecord,
    TrainingArrays,
    admitted_category,
)
from research_agent.learning.arrays import materialize_training_arrays
from research_agent.learning.bundles import (
    LabelWindow,
    ModelBundle,
    QualifiedHead,
    UnavailableHead,
    validate_bundle,
)
from research_agent.learning.calibration import (
    CalibrationResult,
    CalibrationUnavailable,
    fit_calibrators_by_category,
)
from research_agent.learning.features import (
    CardMetadata,
    assemble_metadata_block,
    row_card_metadata,
)
from research_agent.learning.fit import (
    LAMBDAS,
    FitResult,
    MaterializedPartition,
    _sigmoid,
    _standardized_matrix,
)
from research_agent.learning.heads import (
    HeadUnavailable,
    ThreeHeadFit,
    calibrate_three_heads,
    fit_three_heads,
)
from research_agent.learning.promote import (
    PromotionDecision,
    base_rate_baseline,
    promote_three_heads,
)
from research_agent.learning.qualification import (
    PERMUTATION_COUNT,
    BrierRow,
    CoverageSlice,
    PermutationNullResult,
    PilotFeasibilityReport,
    PilotPaper,
    QualificationReport,
    TargetQualificationInput,
    evaluate_modeling_coverage,
    evaluate_pilot_feasibility,
    permutation_null,
    qualify_corpus,
)
from research_agent.learning.release import (
    _TARGET_META,
    BatchJobWorker,
    Identity,
    _commit,
    _Lease,
    derived_uuid,
    utc_now,
    work_key,
)
from research_agent.learning.smoke import solver_runtime_hash
from research_agent.learning.tensors import decode_tensor, encode_tensor
from research_agent.outcomes.targets import registry as target_registry
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.jobs import JobRepository
from research_agent.storage.migrate import migrate

JOB_KIND = "fit"
PARTITIONS = ("fit", "development", "calibration", "locked_evaluation")
_FIT_PURPOSES = frozenset({"initial_fit", "initial_expansion"})
_RETENTION = (
    b"Prediction-head training arrays, qualification reports, bundles and "
    b"promotion decisions are retained privately for this research and are "
    b"not redistributed."
)

Read = Callable[[str], bytes]
# Commits bytes under a media type and artifact kind; returns the publication
# manifest hash the job's checkpoints cite.
Publish = Callable[[bytes, str, str], str]


class PipelineError(ValueError):
    """A release, or a record it cites, cannot enter head fitting."""


@dataclass(frozen=True, slots=True)
class Releases:
    """The two committed releases one fit consumes, each with its content hash."""

    corpus: CorpusRelease
    corpus_hash: str
    pilot: CorpusRelease
    pilot_hash: str


@dataclass(frozen=True, slots=True)
class FitOutcome:
    """Everything the job commits after the partitions are materialized."""

    report: QualificationReport
    bundle: ModelBundle
    decisions: tuple[PromotionDecision, ...]


def load_releases(read: Read, corpus_hash: str, pilot_hash: str) -> Releases:
    """Read both releases by content hash and refuse a wrong purpose or registry."""

    corpus = CorpusRelease.from_json(read(corpus_hash))
    pilot = CorpusRelease.from_json(read(pilot_hash))
    if corpus.purpose not in _FIT_PURPOSES:
        raise PipelineError("--release must name an initial-fit corpus release")
    if pilot.purpose != "acquisition_pilot":
        raise PipelineError("--pilot-release must name the acquisition pilot release")
    registry_hash = sha256(
        target_registry(_TARGET_META).to_canonical_json()
    ).hexdigest()
    if corpus.target_registry_hash != registry_hash:
        raise PipelineError("corpus release target registry differs from the protocol")
    return Releases(corpus, corpus_hash, pilot, pilot_hash)


def partition_rows(release: CorpusRelease, partition: str) -> tuple[CorpusRow, ...]:
    """The partition's rows that carry a combined feature record, in rank order.

    A row without a feature record cannot train; it still counts in the
    coverage denominators. A row with one must record its card fields, and a
    release written before they were recorded is refused here by name.
    """

    rows = tuple(
        row
        for row in release.rows
        if row.partition == partition and row.feature_hash is not None
    )
    if not rows:
        raise PipelineError(f"corpus release has no {partition} rows with features")
    for row in rows:
        row_card_metadata(row)
    return rows


def training_arrays(
    releases: Releases,
    partition: str,
    *,
    read: Read,
    publish: Publish,
    producer: ProducerVersion,
    config_hash: str,
) -> str:
    """Build and publish one partition's ``TrainingArrays``; return its hash.

    Tensors are published before the record that cites them. The record's
    creation instant is the release's own, so the same release always yields
    the same bytes.
    """

    release = releases.corpus
    rows = partition_rows(release, partition)
    blocks: list[NDArray[np.float32]] = []
    labels = np.zeros((len(rows), 3), dtype=np.uint8)
    mask = np.zeros((len(rows), 3), dtype=np.uint8)
    feature_hashes: list[str] = []
    label_hashes: list[tuple[str | None, str | None, str | None]] = []
    for index, row in enumerate(rows):
        assert row.feature_hash is not None
        record = CombinedFeatureRecord.from_json(read(row.feature_hash))
        vector = decode_tensor(
            record.combined_vector, read(record.combined_vector.payload_hash)
        )
        metadata = np.asarray(
            assemble_metadata_block(row_card_metadata(row)), dtype=np.float32
        )
        blocks.append(np.concatenate((vector.astype(np.float32), metadata)))
        feature_hashes.append(row.feature_hash)
        label_hashes.append(row.label_hashes)
        for column, label_hash in enumerate(row.label_hashes):
            if label_hash is None:
                continue
            label = AutomaticLabel.from_json(read(label_hash))
            if label.state in {"true", "false"}:
                mask[index, column] = 1
                labels[index, column] = 1 if label.state == "true" else 0
    features = np.stack(blocks).astype(np.float32)
    references = []
    for array in (features, labels, mask):
        reference, payload = encode_tensor(array)
        publish(payload, "application/octet-stream", "vector_payload")
        references.append(reference)
    arrays = TrainingArrays(
        1,
        (releases.corpus_hash,),
        producer,
        config_hash,
        release.created_at,
        tuple(row.paper_family_id for row in rows),
        references[0],
        references[1],
        references[2],
        tuple(feature_hashes),
        tuple(label_hashes),
        releases.corpus_hash,
        release.split_hash,
        release.target_registry_hash,
        release.representation_hash,
        partition,
    )
    body = arrays.to_canonical_json()
    publish(body, "application/json", "manifest")
    return sha256(body).hexdigest()


def materialize(
    arrays_hash: str,
    releases: Releases,
    *,
    read: Read,
    requested_family_ids: frozenset[str],
) -> MaterializedPartition:
    """Read one committed ``TrainingArrays`` back and verify every row it cites."""

    raw = read(arrays_hash)
    if sha256(raw).hexdigest() != arrays_hash:
        raise PipelineError("training arrays bytes differ from their hash")
    record = TrainingArrays.from_json(raw)
    if record.corpus_release_hash != releases.corpus_hash:
        raise PipelineError("training arrays name a different corpus release")
    members = set(record.ordered_family_ids)
    metadata: dict[str, CardMetadata] = {
        row.paper_family_id: row_card_metadata(row)
        for row in releases.corpus.rows
        if row.paper_family_id in members
    }
    return materialize_training_arrays(
        record,
        read_tensor=read,
        registry=target_registry(_TARGET_META),
        solver_runtime_hash=solver_runtime_hash(),
        read_label=lambda value: AutomaticLabel.from_json(read(value)),
        read_feature=lambda value: CombinedFeatureRecord.from_json(read(value)),
        read_metadata=metadata.__getitem__,
        requested_family_ids=requested_family_ids,
    )


def pilot_feasibility(pilot: CorpusRelease) -> PilotFeasibilityReport:
    """The acquisition pilot's source-feasibility gate from its own rows.

    A paper has complete original text when its row carries a combined
    feature record (features exist only for a complete extraction, FT-09),
    and passes conformance when the release admitted it without an
    exclusion. Shortfalls stay in the intended denominator.
    """

    return evaluate_pilot_feasibility(
        pilot.intended_population_count,
        tuple(
            PilotPaper(
                row.paper_family_id,
                row.feature_hash is not None,
                row.known_mask,
                row.partition == "pilot" and not row.exclusion_reasons,
            )
            for row in pilot.rows
        ),
    )


def _primary_month(row: CorpusRow) -> str | None:
    if row.categories is None or row.t0 is None:
        return None
    return f"{admitted_category(row.categories)}/{row.t0[:7]}"


def coverage_slices(
    release: CorpusRelease, target_index: int
) -> tuple[CoverageSlice, tuple[CoverageSlice, ...]]:
    """One target's overall and primary-category/month coverage.

    A family is covered when it has a combined feature record and a known
    label for the target. The overall denominator is the intended population,
    so shortfalls count against it.
    """

    def covered(row: CorpusRow) -> bool:
        return row.feature_hash is not None and row.known_mask[target_index]

    intended: Counter[str] = Counter()
    hit: Counter[str] = Counter()
    for row in release.rows:
        key = _primary_month(row)
        if key is None:
            continue
        intended[key] += 1
        hit[key] += covered(row)
    return (
        CoverageSlice(
            "overall",
            release.intended_population_count,
            sum(covered(row) for row in release.rows),
        ),
        tuple(CoverageSlice(key, intended[key], hit[key]) for key in sorted(intended)),
    )


def _clusters(pairs: Iterable[tuple[str, str]]) -> dict[str, frozenset[str]]:
    groups: dict[str, set[str]] = {}
    for key, family_id in pairs:
        groups.setdefault(key, set()).add(family_id)
    return {key: frozenset(value) for key, value in sorted(groups.items())}


def brier_rows(
    head: FitResult,
    calibrations: tuple[CalibrationResult | CalibrationUnavailable, ...],
    fit: MaterializedPartition,
    locked_evaluation: MaterializedPartition,
    rows: Mapping[str, CorpusRow],
) -> tuple[BrierRow, ...]:
    """Score the locked partition with the calibrator of each row's category.

    A row whose category has no calibrator is unavailable for that category
    and is not scored.
    """

    index = TARGET_IDS.index(head.target_id)
    calibrators = {
        item.primary_category: item
        for item in calibrations
        if isinstance(item, CalibrationResult)
    }
    known = locked_evaluation.known_mask[:, index].astype(bool)
    logits = (
        _standardized_matrix(
            locked_evaluation.features.astype(np.float64), head.standardization
        )
        @ head.weights
        + head.intercept
    )
    baseline = base_rate_baseline(fit, head.target_id)
    scored: list[BrierRow] = []
    for position, family_id in enumerate(locked_evaluation.family_ids):
        row = rows[family_id]
        assert row.categories is not None and row.publication_week is not None
        calibrator = calibrators.get(admitted_category(row.categories))
        if not known[position] or calibrator is None:
            continue
        probability = _sigmoid(
            np.asarray([calibrator.a * logits[position] + calibrator.b])
        )[0]
        scored.append(
            BrierRow(
                family_id,
                row.publication_week,
                float(probability),
                baseline,
                float(locked_evaluation.labels[position, index]),
            )
        )
    return tuple(scored)


def fit_and_qualify(
    releases: Releases,
    partitions: Mapping[str, MaterializedPartition],
    *,
    requested_family_ids: frozenset[str],
    permutations: int = PERMUTATION_COUNT,
    dataset_hash: str,
) -> FitOutcome:
    """Fit, calibrate by category, qualify, bundle and decide promotion."""

    release = releases.corpus
    registry = target_registry(_TARGET_META)
    fit, development = partitions["fit"], partitions["development"]
    calibration, locked = partitions["calibration"], partitions["locked_evaluation"]
    fitted = fit_three_heads(registry, fit, development)
    pilot = pilot_feasibility(releases.pilot)
    rows = {row.paper_family_id: row for row in release.rows}
    weeks = _clusters(
        (row.publication_week, row.paper_family_id)
        for row in release.rows
        if row.publication_week is not None
    )
    months = {
        row.paper_family_id: row.t0[:7] for row in release.rows if row.t0 is not None
    }
    month_clusters = _clusters((month, family) for family, month in months.items())

    calibrations: dict[str, tuple[CalibrationResult | CalibrationUnavailable, ...]] = {}
    inputs: list[TargetQualificationInput] = []
    for index, (target, item) in enumerate(
        zip(registry.definitions, fitted.fitted, strict=True)
    ):
        overall, slices = coverage_slices(release, index)
        coverage = evaluate_modeling_coverage(target.target_id, overall, slices)
        if isinstance(item, HeadUnavailable):
            inputs.append(
                TargetQualificationInput(
                    target.target_id, coverage, None, item.reason, (), None
                )
            )
            continue
        calibrations[target.target_id] = fit_calibrators_by_category(item, calibration)
        scored = brier_rows(item, calibrations[target.target_id], fit, locked, rows)
        if not scored:
            inputs.append(
                TargetQualificationInput(
                    target.target_id,
                    coverage,
                    None,
                    "no primary category calibrated",
                    (),
                    None,
                )
            )
            continue
        permutation: PermutationNullResult | None = None
        if pilot.passed and coverage.passed:
            permutation = permutation_null(
                target,
                fit,
                development,
                calibration,
                locked,
                months,
                month_clusters,
                permutations=permutations,
            )
        inputs.append(
            TargetQualificationInput(
                target.target_id, coverage, item, None, scored, permutation
            )
        )

    excluded = Counter(
        reason for row in release.rows for reason in row.exclusion_reasons
    )
    report = qualify_corpus(
        pilot,
        (inputs[0], inputs[1], inputs[2]),
        weeks,
        locked,
        requested_family_ids=requested_family_ids,
        exclusions=tuple(f"{reason}:{excluded[reason]}" for reason in sorted(excluded)),
    )
    heads: list[QualifiedHead | UnavailableHead] = []
    for item, outcome in zip(fitted.fitted, report.outcomes, strict=True):
        if isinstance(item, HeadUnavailable):
            heads.append(UnavailableHead(item.target_id, item.reason))
        else:
            heads.append(
                QualifiedHead(
                    item,
                    calibrations[item.target_id],
                    outcome.qualified,
                    outcome.reason,
                    outcome.evaluation_report_id,
                )
            )
    bundle = validate_bundle(
        release.representation_hash,
        LabelWindow(release.fitting_cutoff, dataset_hash),
        releases.corpus_hash,
        release.split_hash,
        release.target_registry_hash,
        (heads[0], heads[1], heads[2]),
    )
    # Only a target the bundle carries as qualified is ever scored for
    # promotion; every other one is decided unavailable without a number.
    gated = ThreeHeadFit(
        tuple(
            item
            if isinstance(item, FitResult) and entry.status == "qualified"
            else HeadUnavailable(item.target_id, entry.reason or "not qualified")
            for item, entry in zip(fitted.fitted, bundle.entries, strict=True)
        )
    )
    decisions = promote_three_heads(
        calibrate_three_heads(gated, calibration), fit, development
    )
    return FitOutcome(report, bundle, decisions)


def dataset_hash(
    releases: Releases,
    arrays: Mapping[str, TrainingArrays],
    *,
    permutations: int,
) -> str:
    """The frozen data and fitting configuration a bundle was fit under.

    Built from content identities only, never from record creation metadata,
    so the same releases and configuration always give the same hash.
    """

    return sha256(
        canonical_json(
            {
                "corpus_release_hash": releases.corpus_hash,
                "pilot_release_hash": releases.pilot_hash,
                "partitions": {
                    name: {
                        "family_ids": list(record.ordered_family_ids),
                        "features": record.features.payload_hash,
                        "labels": record.labels.payload_hash,
                        "known_mask": record.known_mask.payload_hash,
                        "feature_hashes": list(record.feature_hashes),
                    }
                    for name, record in sorted(arrays.items())
                },
                "configuration": fit_configuration(permutations),
            }
        )
    ).hexdigest()


def fit_configuration(permutations: int) -> dict[str, Any]:
    return {
        "stage": JOB_KIND,
        "lambdas": list(LAMBDAS),
        "permutations": permutations,
        "solver_runtime_hash": solver_runtime_hash(),
        "embedding_feature_dimension": EMBEDDING_FEATURE_DIMENSION,
    }


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.generic):
        return _plain(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        raise PipelineError("a committed fit document holds a nonfinite number")
    return value


def documents(outcome: FitOutcome) -> tuple[bytes, bytes, bytes]:
    """The qualification report, bundle and promotion decision, as committed."""

    return (
        canonical_json(_plain(outcome.report)),
        canonical_json(_plain(outcome.bundle)),
        canonical_json(
            {
                "bundle_id": outcome.bundle.bundle_id,
                "activated": False,
                "decisions": _plain(outcome.decisions),
            }
        ),
    )


# --- resumable job ------------------------------------------------------


class FitWorker(BatchJobWorker):
    """Claims ``fit`` jobs; checkpoints each partition, then the fit itself."""

    kind = JOB_KIND
    # The largest partition's feature tensor is the largest artifact; this is
    # the tensor decode budget, so nothing is published that cannot be read.
    maximum_length = 256 * 1024 * 1024

    def __init__(
        self,
        jobs: JobRepository,
        artifacts: ArtifactRepository,
        database: Database,
        *,
        worker_id: UUID,
        identity: Identity,
        requested_family_ids: frozenset[str],
    ) -> None:
        super().__init__(
            jobs, artifacts, database, worker_id=worker_id, identity=identity
        )
        self._requested = requested_family_ids

    def _work(self, lease: _Lease) -> dict[str, Any]:
        spec = lease.spec
        permutations = int(spec["permutations"])
        releases = load_releases(
            self._read_content, str(spec["release"]), str(spec["pilot_release"])
        )

        def publish(payload: bytes, media_type: str, kind: str) -> str:
            return self._publish(
                lease,
                payload,
                media_type=media_type,
                kind=kind,
                inputs=(lease.input_manifest,),
            )

        arrays: dict[str, TrainingArrays] = {}
        for output in lease.outputs:
            record = TrainingArrays.from_json(self._read(output))
            arrays[record.partition] = record
        for partition in PARTITIONS:
            if partition in arrays:
                continue
            manifests: list[str] = []

            def recorded(payload: bytes, media_type: str, kind: str) -> str:
                manifests.append(publish(payload, media_type, kind))
                return manifests[-1]

            with self._heartbeat(lease):
                arrays_hash = training_arrays(
                    releases,
                    partition,
                    read=self._read_content,
                    publish=recorded,
                    producer=self._identity.producer,
                    config_hash=self._identity.config_hash,
                )
            arrays[partition] = TrainingArrays.from_json(
                self._read_content(arrays_hash)
            )
            # The record is published last; its manifest is the checkpoint's
            # output, so a resumed job reads this partition back instead of
            # rebuilding it.
            self._checkpoint(lease, work_key(JOB_KIND, partition), (manifests[-1],))
        with self._heartbeat(lease):
            partitions = {
                name: materialize(
                    sha256(record.to_canonical_json()).hexdigest(),
                    releases,
                    read=self._read_content,
                    requested_family_ids=self._requested,
                )
                for name, record in arrays.items()
            }
            outcome = fit_and_qualify(
                releases,
                partitions,
                requested_family_ids=self._requested,
                permutations=permutations,
                dataset_hash=dataset_hash(releases, arrays, permutations=permutations),
            )
        report, bundle, decision = documents(outcome)
        for body in (report, bundle, decision):
            publish(body, "application/json", "manifest")
        return {
            "stage": JOB_KIND,
            "release_artifact_hash": releases.corpus_hash,
            "pilot_release_artifact_hash": releases.pilot_hash,
            "qualification_report_hash": sha256(report).hexdigest(),
            "bundle_hash": sha256(bundle).hexdigest(),
            "bundle_id": outcome.bundle.bundle_id,
            "promotion_decision_hash": sha256(decision).hexdigest(),
            "promoted_targets": [
                item.target_id for item in outcome.decisions if item.promoted
            ],
        }


# --- local operator -----------------------------------------------------


def _identity(permutations: int) -> Identity:
    producer = ProducerVersion(sha256(b"local-process").hexdigest(), _commit(), 1)
    return Identity(
        producer,
        sha256(canonical_json(fit_configuration(permutations))).hexdigest(),
        sha256(_RETENTION).hexdigest(),
    )


def requested_families(database: Database) -> frozenset[str]:
    """Every family an agent ever requested; none of them trains a head (0025)."""

    return database.transaction(
        lambda connection: frozenset(
            str(row[0])
            for row in connection.execute(
                "SELECT family_id FROM paper_requests"
            ).fetchall()
        )
    )


def _job(database: Database, job_id: UUID) -> tuple[str, str | None] | None:
    row = database.transaction(
        lambda connection: connection.execute(
            "SELECT j.state, encode(o.artifact_hash,'hex') FROM jobs j "
            "LEFT JOIN job_outputs o ON o.job_id=j.id WHERE j.id=%s",
            (job_id,),
        ).fetchone()
    )
    return (
        None if row is None else (str(row[0]), None if row[1] is None else str(row[1]))
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--dsn", required=True, help="DSN selecting a release schema")
    parser.add_argument(
        "--release", required=True, help="initial-fit CorpusRelease content hash"
    )
    parser.add_argument(
        "--pilot-release",
        required=True,
        help="acquisition-pilot CorpusRelease content hash",
    )
    parser.add_argument("--permutations", type=int, default=PERMUTATION_COUNT)
    args = parser.parse_args(argv)
    if args.permutations <= 0:
        parser.error("--permutations must be positive")
    state: Path = args.state
    identity = _identity(args.permutations)
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
    spec = canonical_json(
        {
            "release": args.release,
            "pilot_release": args.pilot_release,
            "permutations": args.permutations,
        }
    )
    spec_hash = sha256(spec).hexdigest()
    operator = derived_uuid("fit-heads", state.as_posix())
    job_id = derived_uuid(JOB_KIND, spec_hash)
    if _job(database, job_id) is None:
        publication = artifacts.publish(
            [spec],
            expected_hash=spec_hash,
            byte_length=len(spec),
            maximum_length=len(spec),
            media_type="application/json",
            kind="manifest",
            # The spec names both releases by content hash; lineage checks
            # take publication manifests, which the command line never sees.
            input_hashes=(),
            producer_version=identity.producer,
            config_hash=identity.config_hash,
            retention_policy_hash=identity.retention_policy_hash,
            command_id=derived_uuid("fit-heads-spec", spec_hash),
        )
        command = derived_uuid("fit-heads-enqueue", spec_hash)
        jobs.execute(
            "enqueue",
            identity=CommandIdentity(operator, command, command, command),
            payload={
                "job_id": str(job_id),
                "kind": JOB_KIND,
                "input_manifest": publication.manifest_hash,
                "scheduled_at": utc_now(),
            },
        )
    worker = FitWorker(
        jobs,
        artifacts,
        database,
        worker_id=derived_uuid("fit-worker", state.as_posix()),
        identity=identity,
        requested_family_ids=requested_families(database),
    )
    worker.run()
    job = _job(database, job_id)
    if job is None or job[0] != "committed" or job[1] is None:
        print(
            json.dumps(
                {"job_id": str(job_id), "state": None if job is None else job[0]}
            ),
            file=sys.stderr,
        )
        return 1
    summary = cast(dict[str, Any], worker._read_json(job[1]))
    print(
        f"qualification report: {store.path_for(summary['qualification_report_hash'])}"
    )
    print(f"bundle: {summary['bundle_id']}")
    print(f"bundle file: {store.path_for(summary['bundle_hash'])}")
    print(f"promotion decision: {store.path_for(summary['promotion_decision_hash'])}")
    print(f"promoted targets: {', '.join(summary['promoted_targets']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
