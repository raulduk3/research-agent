from __future__ import annotations

import json

import numpy as np
import pytest

from research_agent.contracts import canonical_json
from research_agent.contracts.learning import (
    HEAD_INPUT_DIMENSION,
    METADATA_DIMENSION,
    TARGET_IDS,
)
from research_agent.learning import pipeline
from research_agent.learning.bundles import (
    BundleError,
    LabelWindow,
    ModelBundle,
    QualifiedHead,
    RetainedArtifact,
    UnavailableHead,
    bundle_from_json,
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

IDENTITY = ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64)
FREEZE_AT = "2026-09-20T00:00:00.000000Z"
DATASET_HASH = "d" * 64


def _fit(target_id: str, target_hash: str) -> FitResult:
    diagnostics = tuple(
        CandidateDiagnostics(
            value, 0.5, 1, 0.0, True, 100, 100, 0.2, None, "L-BFGS", IDENTITY[4]
        )
        for value in LAMBDAS
    )
    return FitResult(
        target_id,
        target_hash,
        np.zeros(DIMENSION, dtype=np.float64),
        0.0,
        0.1,
        diagnostics,
        0.2,
        (),
        (),
        (),
        *IDENTITY,
        _row_ids_hash(()),
        _row_ids_hash(()),
        Standardization((0.0,) * METADATA_DIMENSION, (1.0,) * METADATA_DIMENSION),
    )


def _calibration(target_id: str, target_hash: str, category: str) -> CalibrationResult:
    return CalibrationResult(
        target_id,
        1.0,
        0.0,
        0.1,
        5,
        1e-7,
        _row_ids_hash(()),
        1e-6,
        "L-BFGS-B",
        True,
        30,
        30,
        IDENTITY[4],
        target_hash,
        *IDENTITY[:4],
        category,
    )


TARGET_HASHES = ("a" * 64, "b" * 64, "c" * 64)


def _qualified_heads() -> tuple[QualifiedHead, QualifiedHead, QualifiedHead]:
    heads = []
    for target_id, target_hash in zip(TARGET_IDS, TARGET_HASHES, strict=True):
        fit = _fit(target_id, target_hash)
        calibrations = (
            _calibration(target_id, target_hash, "cs.AI"),
            CalibrationUnavailable(
                target_id, "cs.LG", "insufficient calibration classes"
            ),
        )
        heads.append(
            QualifiedHead(fit, calibrations, True, None, f"report-{target_id}")
        )
    return tuple(heads)  # type: ignore[return-value]


def test_validate_bundle_assembles_three_qualified_entries() -> None:
    label_window = LabelWindow(FREEZE_AT, DATASET_HASH)
    bundle = validate_bundle(
        IDENTITY[3],
        label_window,
        IDENTITY[0],
        IDENTITY[1],
        IDENTITY[2],
        _qualified_heads(),
    )
    assert bundle.head_input_dimension == HEAD_INPUT_DIMENSION
    assert bundle.label_window == label_window
    assert tuple(entry.target_id for entry in bundle.entries) == TARGET_IDS
    assert all(entry.status == "qualified" for entry in bundle.entries)
    assert all(
        any(cal.status == "qualified" for cal in entry.calibrations)
        for entry in bundle.entries
    )


def test_validate_bundle_records_an_unavailable_target_with_a_reason() -> None:
    heads = list(_qualified_heads())
    heads[1] = UnavailableHead(TARGET_IDS[1], "insufficient fit classes")
    label_window = LabelWindow(FREEZE_AT, DATASET_HASH)
    bundle = validate_bundle(
        IDENTITY[3],
        label_window,
        IDENTITY[0],
        IDENTITY[1],
        IDENTITY[2],
        tuple(heads),  # type: ignore[arg-type]
    )
    assert bundle.entries[1].status == "unavailable"
    assert bundle.entries[1].reason == "insufficient fit classes"
    assert bundle.entries[1].weights_hash is None


def test_validate_bundle_demotes_an_identity_mismatch_to_unavailable() -> None:
    heads = list(_qualified_heads())
    mismatched_fit = _fit(TARGET_IDS[0], TARGET_HASHES[0])
    object.__setattr__(mismatched_fit, "representation_hash", "9" * 64)
    heads[0] = QualifiedHead(
        mismatched_fit,
        (_calibration(TARGET_IDS[0], TARGET_HASHES[0], "cs.AI"),),
        True,
        None,
        "report",
    )
    label_window = LabelWindow(FREEZE_AT, DATASET_HASH)
    bundle = validate_bundle(
        IDENTITY[3],
        label_window,
        IDENTITY[0],
        IDENTITY[1],
        IDENTITY[2],
        tuple(heads),  # type: ignore[arg-type]
    )
    assert bundle.entries[0].status == "unavailable"
    assert "differs from the manifest" in (bundle.entries[0].reason or "")


def test_validate_bundle_refuses_without_a_label_window() -> None:
    with pytest.raises(BundleError, match="label window"):
        validate_bundle(
            IDENTITY[3],
            None,  # type: ignore[arg-type]
            IDENTITY[0],
            IDENTITY[1],
            IDENTITY[2],
            _qualified_heads(),
        )


def test_validate_bundle_refuses_out_of_order_registry() -> None:
    heads = list(_qualified_heads())
    heads[0], heads[1] = heads[1], heads[0]
    label_window = LabelWindow(FREEZE_AT, DATASET_HASH)
    with pytest.raises(BundleError, match="registry in order"):
        validate_bundle(
            IDENTITY[3],
            label_window,
            IDENTITY[0],
            IDENTITY[1],
            IDENTITY[2],
            tuple(heads),  # type: ignore[arg-type]
        )


def test_retained_artifact_requires_matching_representation_and_target_identity() -> (
    None
):
    label_window = LabelWindow(FREEZE_AT, DATASET_HASH)
    bundle = validate_bundle(
        IDENTITY[3],
        label_window,
        IDENTITY[0],
        IDENTITY[1],
        IDENTITY[2],
        _qualified_heads(),
    )
    retained = RetainedArtifact(bundle.entries[0], IDENTITY[3], "e" * 64)
    revalidated = validate_bundle(
        IDENTITY[3],
        label_window,
        IDENTITY[0],
        IDENTITY[1],
        IDENTITY[2],
        _qualified_heads(),
        (retained,),
    )
    assert revalidated.retained == (retained,)

    mismatched = RetainedArtifact(bundle.entries[0], "f" * 64, "e" * 64)
    with pytest.raises(BundleError, match="representation differs"):
        validate_bundle(
            IDENTITY[3],
            label_window,
            IDENTITY[0],
            IDENTITY[1],
            IDENTITY[2],
            _qualified_heads(),
            (mismatched,),
        )


def _bundle_file(bundle: ModelBundle) -> bytes:
    """The bundle bytes exactly as the fit job commits them."""

    return canonical_json(pipeline._plain(bundle))


def test_a_committed_bundle_file_reads_back_to_the_same_bundle() -> None:
    bundle = validate_bundle(
        IDENTITY[3],
        LabelWindow(FREEZE_AT, DATASET_HASH),
        IDENTITY[0],
        IDENTITY[1],
        IDENTITY[2],
        _qualified_heads(),
    )
    entry = bundle.entries[0]
    assert entry.weights is not None and len(entry.weights) == HEAD_INPUT_DIMENSION
    assert entry.standardization is not None
    assert entry.development_brier == 0.2

    assert bundle_from_json(_bundle_file(bundle)) == bundle


def test_a_bundle_file_whose_vectors_or_identity_changed_is_refused() -> None:
    bundle = validate_bundle(
        IDENTITY[3],
        LabelWindow(FREEZE_AT, DATASET_HASH),
        IDENTITY[0],
        IDENTITY[1],
        IDENTITY[2],
        _qualified_heads(),
    )
    value = json.loads(_bundle_file(bundle))
    value["entries"][0]["weights"][0] = 0.5
    with pytest.raises(BundleError, match="weights do not match"):
        bundle_from_json(canonical_json(value))

    value = json.loads(_bundle_file(bundle))
    value["entries"][1]["standardization"]["std"][0] = 2.0
    with pytest.raises(BundleError, match="standardization does not match"):
        bundle_from_json(canonical_json(value))

    value = json.loads(_bundle_file(bundle))
    value["label_window"]["freeze_at"] = "2026-09-21T00:00:00.000000Z"
    with pytest.raises(BundleError, match="bundle id"):
        bundle_from_json(canonical_json(value))

    value = json.loads(_bundle_file(bundle))
    del value["entries"][2]["weights"]
    with pytest.raises(BundleError, match="fields"):
        bundle_from_json(canonical_json(value))
