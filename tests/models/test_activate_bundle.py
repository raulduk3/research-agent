"""The operator command that activates a fit job's bundle (SDD PL-14, FT-23).

TDD-1.1.21: the bundle ``bin/fit-heads`` commits is verified against its
committed bytes, its vectors' hashes and the promotion decision before the
derived manifest is activated; a target that was not promoted is refused
unless a reason is recorded; activating the active bundle again writes
nothing.
"""

from __future__ import annotations

import importlib.util
import json
import math
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import numpy as np
import pytest

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import ProducerVersion, canonical_json
from research_agent.contracts.learning import TARGET_IDS
from research_agent.learning import pipeline
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
)
from research_agent.learning.features import Standardization
from research_agent.learning.fit import (
    DIMENSION,
    LAMBDAS,
    CandidateDiagnostics,
    FitResult,
    _row_ids_hash,
)
from research_agent.learning.release import _TARGET_META
from research_agent.models import activation
from research_agent.models.activation import ActivationError, activate_fit_bundle
from research_agent.models.predict import predict_targets
from research_agent.models.registry import (
    PublishedHead,
    ServingHandle,
    active_bundle,
)
from research_agent.outcomes.targets import registry as target_registry
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database

REGISTRY = target_registry(_TARGET_META)
REGISTRY_HASH = sha256(REGISTRY.to_canonical_json()).hexdigest()
CORPUS, SPLIT, REPRESENTATION, SOLVER = (
    "1" * 64,
    "2" * 64,
    "4" * 64,
    "5" * 64,
)
FREEZE_AT = "2026-09-20T00:00:00.000000Z"
ORIGINAL_VERSION_ID = "00000000-0000-4000-8000-000000000002"
REASON = "development Brier accepted for the first launch"


def _pipeline_tests() -> ModuleType:
    """The fit-heads smoke fixtures, loaded from their own test module."""

    path = Path(__file__).parents[1] / "learning" / "test_pipeline.py"
    spec = importlib.util.spec_from_file_location("fit_heads_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repository(dsn: str, root: Path) -> ArtifactRepository:
    return ArtifactRepository(Database(dsn), ArtifactStore(root))


def _commit(repository: ArtifactRepository, payload: bytes) -> None:
    repository.publish(
        [payload],
        expected_hash=sha256(payload).hexdigest(),
        byte_length=len(payload),
        maximum_length=len(payload),
        media_type="application/json",
        kind="manifest",
        input_hashes=(),
        producer_version=ProducerVersion("a" * 64, "b" * 40, 1),
        config_hash="c" * 64,
        retention_policy_hash="f" * 64,
        command_id=uuid4(),
    )


def _counts(dsn: str) -> tuple[object, ...]:
    return Database(dsn).transaction(
        lambda connection: connection.execute(
            "SELECT (SELECT count(*) FROM artifacts), "
            "(SELECT count(*) FROM ledger_records)"
        ).fetchone()
        or ()
    )


def _fit(index: int, standardization: Standardization) -> FitResult:
    definition = REGISTRY.definitions[index]
    diagnostics = tuple(
        CandidateDiagnostics(
            value, 0.5, 1, 0.0, True, 100, 100, 0.2, None, "L-BFGS", SOLVER
        )
        for value in LAMBDAS
    )
    return FitResult(
        definition.target_id,
        sha256(definition.to_canonical_json()).hexdigest(),
        np.array(
            [0.001 * ((column % 5) - 2) for column in range(DIMENSION)],
            dtype=np.float64,
        ),
        0.1 * (index + 1),
        0.1,
        diagnostics,
        0.2,
        (),
        (),
        (),
        CORPUS,
        SPLIT,
        REGISTRY_HASH,
        REPRESENTATION,
        SOLVER,
        _row_ids_hash(()),
        _row_ids_hash(()),
        standardization,
    )


def _calibration(
    fit: FitResult, category: str, a: float, b: float
) -> CalibrationResult:
    return CalibrationResult(
        fit.target_id,
        a,
        b,
        0.1,
        5,
        1e-7,
        _row_ids_hash(()),
        1e-6,
        "L-BFGS-B",
        True,
        30,
        30,
        SOLVER,
        fit.target_definition_hash,
        CORPUS,
        SPLIT,
        REGISTRY_HASH,
        REPRESENTATION,
        category,
    )


def _bundle(standardization: Standardization) -> ModelBundle:
    heads: list[QualifiedHead | UnavailableHead] = []
    for index in (0, 1):
        fit = _fit(index, standardization)
        calibrations = (
            _calibration(fit, "cs.AI", 1.2, -0.2),
            _calibration(fit, "cs.LG", 0.8, 0.1),
            CalibrationUnavailable(
                fit.target_id, "quant-ph", "insufficient calibration classes"
            ),
            _calibration(fit, "q-bio", 1.0, 0.0),
        )
        heads.append(
            QualifiedHead(fit, calibrations, True, None, f"report-{fit.target_id}")
        )
    heads.append(
        UnavailableHead(REGISTRY.definitions[2].target_id, "insufficient fit classes")
    )
    return validate_bundle(
        REPRESENTATION,
        LabelWindow(FREEZE_AT, "d" * 64),
        CORPUS,
        SPLIT,
        REGISTRY_HASH,
        (heads[0], heads[1], heads[2]),
    )


def _decision(bundle: ModelBundle, promoted: tuple[bool, bool, bool]) -> bytes:
    return canonical_json(
        {
            "bundle_id": bundle.bundle_id,
            "activated": False,
            "decisions": [
                {
                    "target_id": entry.target_id,
                    "promoted": value,
                    "reason": "promoted" if value else "unavailable",
                    "evaluation": None,
                }
                for entry, value in zip(bundle.entries, promoted, strict=True)
            ],
        }
    )


def _committed_files(
    repository: ArtifactRepository,
    bundle: ModelBundle,
    promoted: tuple[bool, bool, bool],
) -> tuple[bytes, bytes]:
    bundle_bytes = canonical_json(pipeline._plain(bundle))
    decision_bytes = _decision(bundle, promoted)
    _commit(repository, bundle_bytes)
    _commit(repository, decision_bytes)
    return bundle_bytes, decision_bytes


def _with_primary(
    metadata_block: tuple[float, ...], category: str
) -> tuple[float, ...]:
    one_hot = tuple(
        1.0 if item == category else 0.0
        for item in ("cs.AI", "cs.LG", "quant-ph", "q-bio")
    )
    return metadata_block[:2] + one_hot + metadata_block[6:]


@pytest.mark.integration
def test_the_fit_heads_smoke_bundle_activates_once(
    postgres_dsn: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    smoke = _pipeline_tests()
    state = tmp_path / "state"
    blobs, corpus, pilot = smoke._releases(tmp_path)
    smoke._publish_all(postgres_dsn, state / "artifacts", blobs)
    printed = smoke._run(postgres_dsn, state, corpus, pilot, capsys)
    argv = [
        "--bundle",
        printed["bundle file"],
        "--decision",
        printed["promotion decision"],
        "--dsn",
        postgres_dsn,
        "--artifacts",
        str(state / "artifacts"),
    ]

    assert activation.main(argv) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    record = json.loads(lines[0])
    assert record["fit_bundle_id"] == printed["bundle"]
    assert record["served_targets"] == []
    assert record["already_active"] is False
    assert lines[1] == f"active bundle: {record['manifest_hash']}"
    assert lines[2] == f"generation: {record['generation']}"

    repository = _repository(postgres_dsn, state / "artifacts")
    handle = ServingHandle.load(Database(postgres_dsn), repository)
    bundle = json.loads(Path(printed["bundle file"]).read_bytes())
    assert handle.bundle_hash == record["manifest_hash"]
    assert handle.manifest.created_at == bundle["label_window"]["freeze_at"]
    assert [(entry.status, entry.reason) for entry in handle.manifest.entries] == [
        ("unavailable", entry["reason"]) for entry in bundle["entries"]
    ]

    # Activating the active bundle again reports it and writes nothing.
    before = _counts(postgres_dsn)
    assert activation.main(argv) == 0
    again = json.loads(capsys.readouterr().out.strip().splitlines()[0])
    assert again == {**record, "already_active": True}
    assert _counts(postgres_dsn) == before


@pytest.mark.integration
def test_a_qualified_bundle_serves_each_category_through_its_own_calibrator(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    standardization: Standardization,
    embedding_block: tuple[float, ...],
    metadata_block: tuple[float, ...],
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path / "artifacts")
    bundle = _bundle(standardization)
    bundle_bytes, decision_bytes = _committed_files(
        repository, bundle, (True, True, False)
    )

    record = activate_fit_bundle(
        database,
        repository,
        bundle_bytes,
        decision_bytes,
        unpromoted_reason=None,
        producer_version=producer_version,
    )
    assert record.served_targets == TARGET_IDS[:2]
    assert record.unpromoted_targets == ()

    handle = ServingHandle.load(database, repository)
    assert handle.bundle_hash == record.manifest_hash
    heads = {}
    for entry in bundle.entries[:2]:
        head = handle.qualified_head(repository, entry.target_id)
        assert head == PublishedHead.from_bundle_entry(bundle, entry)
        heads[entry.target_id] = head
    third = handle.manifest.entries[2]
    assert (third.status, third.reason) == ("unavailable", "insufficient fit classes")

    served = {}
    for category in ("cs.AI", "cs.LG", "quant-ph"):
        served[category] = predict_targets(
            handle,
            heads,
            REGISTRY.definitions,
            original_version_id=ORIGINAL_VERSION_ID,
            requested_bundle_hash=handle.bundle_hash,
            representation_hash=REPRESENTATION,
            embedding_block=embedding_block,
            metadata_block=_with_primary(metadata_block, category),
            computed_at=FREEZE_AT,
            available_at=FREEZE_AT,
        )[0]
    for category, (a, b) in {"cs.AI": (1.2, -0.2), "cs.LG": (0.8, 0.1)}.items():
        logit = served[category].raw_logit
        assert logit is not None
        assert served[category].probability == 1.0 / (1.0 + math.exp(-(a * logit + b)))
    assert served["quant-ph"].status == "unavailable"


@pytest.mark.integration
def test_an_unpromoted_target_is_refused_unless_a_reason_is_recorded(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    standardization: Standardization,
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path / "artifacts")
    bundle = _bundle(standardization)
    bundle_bytes, decision_bytes = _committed_files(
        repository, bundle, (True, False, False)
    )

    with pytest.raises(ActivationError, match=TARGET_IDS[1]):
        activate_fit_bundle(
            database,
            repository,
            bundle_bytes,
            decision_bytes,
            unpromoted_reason=None,
            producer_version=producer_version,
        )
    assert active_bundle(database) is None

    record = activate_fit_bundle(
        database,
        repository,
        bundle_bytes,
        decision_bytes,
        unpromoted_reason=REASON,
        producer_version=producer_version,
    )
    assert record.served_targets == TARGET_IDS[:2]
    assert record.unpromoted_targets == (TARGET_IDS[1],)
    assert record.unpromoted_reason == REASON
    payload = canonical_json(record.to_dict())
    (_length, _media), stream = repository.read(sha256(payload).hexdigest())
    with stream:
        assert json.loads(stream.read())["unpromoted_reason"] == REASON


@pytest.mark.integration
def test_reactivating_the_same_bundle_from_a_later_commit_writes_nothing(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    standardization: Standardization,
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path / "artifacts")
    bundle = _bundle(standardization)
    bundle_bytes, decision_bytes = _committed_files(
        repository, bundle, (True, True, False)
    )
    first = activate_fit_bundle(
        database,
        repository,
        bundle_bytes,
        decision_bytes,
        unpromoted_reason=None,
        producer_version=producer_version,
    )
    before = _counts(postgres_dsn)
    later = ProducerVersion(
        producer_version.image_digest, "0" * 40, producer_version.contract_version
    )
    again = activate_fit_bundle(
        database,
        repository,
        bundle_bytes,
        decision_bytes,
        unpromoted_reason=None,
        producer_version=later,
    )

    assert again.already_active
    assert (again.manifest_hash, again.generation) == (
        first.manifest_hash,
        first.generation,
    )
    assert _counts(postgres_dsn) == before


@pytest.mark.integration
def test_files_the_fit_job_did_not_commit_together_are_refused(
    postgres_dsn: str,
    tmp_path: Path,
    producer_version: ProducerVersion,
    standardization: Standardization,
) -> None:
    database = Database(postgres_dsn)
    repository = _repository(postgres_dsn, tmp_path / "artifacts")
    bundle = _bundle(standardization)
    uncommitted = canonical_json(pipeline._plain(bundle))
    decision = _decision(bundle, (True, True, False))
    _commit(repository, decision)
    with pytest.raises(ActivationError, match="not a committed artifact"):
        activate_fit_bundle(
            database,
            repository,
            uncommitted,
            decision,
            unpromoted_reason=None,
            producer_version=producer_version,
        )

    bundle_bytes, _ = _committed_files(repository, bundle, (True, True, False))
    other = json.loads(decision)
    other["bundle_id"] = "e" * 64
    other_bytes = canonical_json(other)
    _commit(repository, other_bytes)
    with pytest.raises(ActivationError, match="different bundle"):
        activate_fit_bundle(
            database,
            repository,
            bundle_bytes,
            other_bytes,
            unpromoted_reason=None,
            producer_version=producer_version,
        )

    # A target promoted without a bundled head is an inconsistent pair.
    promotes_missing = _decision(bundle, (True, True, True))
    _commit(repository, promotes_missing)
    with pytest.raises(ActivationError, match="no head"):
        activate_fit_bundle(
            database,
            repository,
            bundle_bytes,
            promotes_missing,
            unpromoted_reason=REASON,
            producer_version=producer_version,
        )
    assert active_bundle(database) is None
