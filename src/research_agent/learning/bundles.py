"""Content-addressed model bundle assembly and validation (SDD-FT-23).

A bundle names every value TDD-1.1.18 requires before it can be published:
the representation namespace, the fitted head input width, each qualified
target's own standardization (#149) and the mature-label window it was fit
and calibrated under. Any of these missing, or any qualified entry's hashes,
dimensions or coefficients failing to verify, refuses the whole bundle
rather than publishing a partial one; an individual target instead stays an
explicit ``"unavailable"`` member with its reason (FT-22, FT-23).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast

import numpy as np

from research_agent.contracts import canonical_json, canonical_loads
from research_agent.contracts.learning import (
    HEAD_INPUT_DIMENSION,
    PRIMARY_CATEGORY_IDS,
    TARGET_IDS,
)
from research_agent.contracts.primitives import (
    validate_finite,
    validate_non_empty_string,
    validate_sha256,
    validate_utc_instant,
)
from research_agent.learning.calibration import (
    CalibrationResult,
    CalibrationUnavailable,
)
from research_agent.learning.features import Standardization
from research_agent.learning.fit import FitResult
from research_agent.learning.tensors import encode_tensor

HEAD_STATUSES: frozenset[str] = frozenset({"qualified", "unavailable"})
CALIBRATION_STATUSES: frozenset[str] = frozenset({"qualified", "unavailable"})


class BundleError(ValueError):
    """A candidate bundle, or one of its pieces, is not admissible for publishing."""


@dataclass(frozen=True, slots=True)
class LabelWindow:
    """The mature-label freeze a bundle's heads were fit and calibrated under.

    ``dataset_hash`` is the refresh job's own content hash of the frozen
    dataset and fitting configuration (TDD-1.1.10); a bundle carries it so a
    reader can tell two bundles were fit from the identical mature-label
    freeze without recomputing that hash itself.
    """

    freeze_at: str
    dataset_hash: str

    def __post_init__(self) -> None:
        validate_utc_instant(self.freeze_at)
        validate_sha256(self.dataset_hash)


@dataclass(frozen=True, slots=True)
class BundleCategoryCalibration:
    """One target's calibration for one primary category, as bundled."""

    primary_category: str
    status: str
    reason: str | None
    a: float | None
    b: float | None
    calibration_row_ids_hash: str | None

    def __post_init__(self) -> None:
        if self.primary_category not in PRIMARY_CATEGORY_IDS:
            raise BundleError("bundle calibration names an unadmitted primary category")
        if self.status not in CALIBRATION_STATUSES:
            raise BundleError("bundle calibration status is not recognized")
        if self.status == "qualified":
            if (
                self.reason is not None
                or self.a is None
                or self.b is None
                or self.calibration_row_ids_hash is None
            ):
                raise BundleError(
                    "a qualified calibration entry requires its parameters and no reason"
                )
            if validate_finite(self.a) < 0:
                raise BundleError(
                    "a qualified calibration slope must be finite and nonnegative"
                )
            validate_finite(self.b)
            validate_sha256(self.calibration_row_ids_hash)
        elif self.reason is None or self.a is not None or self.b is not None:
            raise BundleError(
                "an unavailable calibration entry carries only its reason"
            )

    @classmethod
    def from_result(
        cls, item: CalibrationResult | CalibrationUnavailable
    ) -> "BundleCategoryCalibration":
        if isinstance(item, CalibrationUnavailable):
            return cls(
                item.primary_category, "unavailable", item.reason, None, None, None
            )
        if item.primary_category is None:
            raise BundleError("a bundled calibrator must name its primary category")
        return cls(
            item.primary_category,
            "qualified",
            None,
            item.a,
            item.b,
            item.calibration_row_ids_hash,
        )


@dataclass(frozen=True, slots=True)
class BundleHeadEntry:
    """One registry target's bundled disposition: qualified with an artifact, or unavailable.

    A qualified entry carries the full coefficient vector, standardization
    and development Brier loss beside their hashes, so the bundle file alone
    is enough to publish the serving head; both vectors are verified against
    their hashes on construction.
    """

    target_id: str
    status: str
    reason: str | None
    target_definition_hash: str | None
    weights_hash: str | None
    intercept: float | None
    standardization_hash: str | None
    calibrations: tuple[BundleCategoryCalibration, ...]
    evaluation_report_id: str | None
    weights: tuple[float, ...] | None
    standardization: Standardization | None
    development_brier: float | None

    def __post_init__(self) -> None:
        if self.target_id not in TARGET_IDS:
            raise BundleError("bundle head entry names an unregistered target")
        if self.status not in HEAD_STATUSES:
            raise BundleError("bundle head entry status is not recognized")
        categories = tuple(item.primary_category for item in self.calibrations)
        if len(set(categories)) != len(categories):
            raise BundleError("bundle head entry repeats a primary category")
        if self.status == "qualified":
            if (
                self.reason is not None
                or self.target_definition_hash is None
                or self.weights_hash is None
                or self.intercept is None
                or self.standardization_hash is None
                or self.evaluation_report_id is None
            ):
                raise BundleError(
                    "a qualified head entry requires its full artifact identity"
                )
            validate_sha256(self.target_definition_hash)
            validate_sha256(self.weights_hash)
            validate_sha256(self.standardization_hash)
            validate_finite(self.intercept)
            validate_non_empty_string(self.evaluation_report_id)
            if not any(item.status == "qualified" for item in self.calibrations):
                raise BundleError(
                    "a qualified head entry requires at least one qualified category calibration"
                )
            if (
                not isinstance(self.weights, tuple)
                or len(self.weights) != HEAD_INPUT_DIMENSION
                or not isinstance(self.standardization, Standardization)
                or self.development_brier is None
            ):
                raise BundleError(
                    "a qualified head entry requires its coefficient vectors"
                )
            for value in self.weights:
                validate_finite(value)
            validate_finite(self.development_brier)
            if _vector_hash(self.weights) != self.weights_hash:
                raise BundleError("bundled weights do not match their hash")
            if (
                sha256(self.standardization.to_canonical_json()).hexdigest()
                != self.standardization_hash
            ):
                raise BundleError("bundled standardization does not match its hash")
        else:
            if self.reason is None:
                raise BundleError("an unavailable head entry requires a reason")
            if (
                self.target_definition_hash is not None
                or self.weights_hash is not None
                or self.intercept is not None
                or self.standardization_hash is not None
                or self.evaluation_report_id is not None
                or self.weights is not None
                or self.standardization is not None
                or self.development_brier is not None
            ):
                raise BundleError(
                    "an unavailable head entry carries no artifact identity"
                )


@dataclass(frozen=True, slots=True)
class RetainedArtifact:
    """A prior release's head entry, reused unchanged in a new manifest.

    Accepted only "when their representation and target identity match the
    new manifest" (TDD-1.1.18): it is an explicit member of the new bundle,
    never a mutable pointer back to the old one.
    """

    entry: BundleHeadEntry
    representation_hash: str
    source_bundle_id: str

    def __post_init__(self) -> None:
        validate_sha256(self.representation_hash)
        validate_sha256(self.source_bundle_id)
        if self.entry.status != "qualified":
            raise BundleError("only a qualified head entry can be retained")


@dataclass(frozen=True, slots=True)
class ModelBundle:
    """A content-addressed, validated bundle manifest (TDD-1.1.18)."""

    bundle_id: str
    representation_hash: str
    head_input_dimension: int
    label_window: LabelWindow
    corpus_release_hash: str
    split_hash: str
    target_registry_hash: str
    entries: tuple[BundleHeadEntry, ...]
    retained: tuple[RetainedArtifact, ...]

    def __post_init__(self) -> None:
        validate_sha256(self.bundle_id)
        validate_sha256(self.representation_hash)
        validate_sha256(self.corpus_release_hash)
        validate_sha256(self.split_hash)
        validate_sha256(self.target_registry_hash)
        if not isinstance(self.label_window, LabelWindow):
            raise BundleError("a bundle requires its label window")
        if self.head_input_dimension != HEAD_INPUT_DIMENSION:
            raise BundleError(
                "bundle head input width differs from the closed contract"
            )
        if tuple(item.target_id for item in self.entries) != TARGET_IDS:
            raise BundleError("bundle entries must cover the registry in order")
        for retained in self.retained:
            if retained.representation_hash != self.representation_hash:
                raise BundleError(
                    "a retained artifact's representation differs from this manifest"
                )
            matching = next(
                (
                    item
                    for item in self.entries
                    if item.target_id == retained.entry.target_id
                ),
                None,
            )
            if (
                matching is None
                or matching.target_definition_hash
                != retained.entry.target_definition_hash
            ):
                raise BundleError(
                    "a retained artifact's target identity differs from this manifest"
                )


@dataclass(frozen=True, slots=True)
class QualifiedHead:
    """One target ready to bundle: its fit, per-category calibrations and qualification."""

    fit: FitResult
    calibrations: tuple[CalibrationResult | CalibrationUnavailable, ...]
    qualified: bool
    reason: str | None
    evaluation_report_id: str | None


@dataclass(frozen=True, slots=True)
class UnavailableHead:
    """One target that never produced a fit worth bundling."""

    target_id: str
    reason: str


def _vector_hash(weights: tuple[float, ...]) -> str:
    reference, _ = encode_tensor(np.asarray(weights, dtype=np.float64))
    return reference.payload_hash


def _unavailable_entry(target_id: str, reason: str) -> BundleHeadEntry:
    return BundleHeadEntry(
        target_id,
        "unavailable",
        reason,
        None,
        None,
        None,
        None,
        (),
        None,
        None,
        None,
        None,
    )


def _bundle_id(
    representation_hash: str,
    label_window: LabelWindow,
    corpus_release_hash: str,
    split_hash: str,
    target_registry_hash: str,
    entries: Sequence[BundleHeadEntry],
) -> str:
    manifest_identity = {
        "representation_hash": representation_hash,
        "corpus_release_hash": corpus_release_hash,
        "split_hash": split_hash,
        "target_registry_hash": target_registry_hash,
        "label_window": {
            "freeze_at": label_window.freeze_at,
            "dataset_hash": label_window.dataset_hash,
        },
        "entries": [
            {
                "target_id": entry.target_id,
                "status": entry.status,
                "target_definition_hash": entry.target_definition_hash,
                "weights_hash": entry.weights_hash,
                "standardization_hash": entry.standardization_hash,
            }
            for entry in entries
        ],
    }
    return sha256(canonical_json(manifest_identity)).hexdigest()


def validate_bundle(
    representation_hash: str,
    label_window: LabelWindow,
    corpus_release_hash: str,
    split_hash: str,
    target_registry_hash: str,
    heads: tuple[
        QualifiedHead | UnavailableHead,
        QualifiedHead | UnavailableHead,
        QualifiedHead | UnavailableHead,
    ],
    retained: tuple[RetainedArtifact, ...] = (),
) -> ModelBundle:
    """Assemble and validate one bundle manifest from three targets' outcomes.

    Each target enters the manifest qualified with a verified artifact, or
    explicitly unavailable with a reason; an identity mismatch against the
    manifest's own representation, corpus, split or registry hashes demotes
    a candidate to unavailable rather than silently mixing namespaces
    (SDD-FT-23). Missing any of the manifest-level identities (the
    representation namespace, the head input width, or the label window)
    refuses the whole bundle before any entry is built.
    """

    validate_sha256(representation_hash)
    validate_sha256(corpus_release_hash)
    validate_sha256(split_hash)
    validate_sha256(target_registry_hash)
    if not isinstance(label_window, LabelWindow):
        raise BundleError("a bundle requires its label window")
    if (
        tuple(
            item.fit.target_id if isinstance(item, QualifiedHead) else item.target_id
            for item in heads
        )
        != TARGET_IDS
    ):
        raise BundleError("bundle inputs must cover the registry in order")

    entries: list[BundleHeadEntry] = []
    for item in heads:
        if isinstance(item, UnavailableHead):
            entries.append(_unavailable_entry(item.target_id, item.reason))
            continue
        fit = item.fit
        if (
            fit.corpus_release_hash != corpus_release_hash
            or fit.split_hash != split_hash
            or fit.target_registry_hash != target_registry_hash
            or fit.representation_hash != representation_hash
        ):
            entries.append(
                _unavailable_entry(
                    fit.target_id, "fitted head identity differs from the manifest"
                )
            )
            continue
        if not item.qualified:
            entries.append(
                _unavailable_entry(fit.target_id, item.reason or "qualification failed")
            )
            continue
        if item.evaluation_report_id is None:
            raise BundleError(
                "a qualified head entry requires its evaluation report id"
            )
        calibrations = tuple(
            BundleCategoryCalibration.from_result(result)
            for result in item.calibrations
        )
        if not any(entry.status == "qualified" for entry in calibrations):
            entries.append(
                _unavailable_entry(fit.target_id, "no primary category calibrated")
            )
            continue
        weights = tuple(float(value) for value in fit.weights.tolist())
        entries.append(
            BundleHeadEntry(
                fit.target_id,
                "qualified",
                None,
                fit.target_definition_hash,
                _vector_hash(weights),
                float(fit.intercept),
                sha256(fit.standardization.to_canonical_json()).hexdigest(),
                calibrations,
                item.evaluation_report_id,
                weights,
                fit.standardization,
                float(fit.development_brier),
            )
        )

    bundle_id = _bundle_id(
        representation_hash,
        label_window,
        corpus_release_hash,
        split_hash,
        target_registry_hash,
        entries,
    )
    return ModelBundle(
        bundle_id,
        representation_hash,
        HEAD_INPUT_DIMENSION,
        label_window,
        corpus_release_hash,
        split_hash,
        target_registry_hash,
        tuple(entries),
        retained,
    )


def _fields(value: object, names: frozenset[str], what: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != names:
        raise BundleError(f"{what} fields do not match schema")
    return cast(dict[str, Any], value)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(cast(float, value))


def _calibration_from(value: object) -> BundleCategoryCalibration:
    item = _fields(
        value,
        frozenset(
            {
                "primary_category",
                "status",
                "reason",
                "a",
                "b",
                "calibration_row_ids_hash",
            }
        ),
        "bundle calibration",
    )
    return BundleCategoryCalibration(
        item["primary_category"],
        item["status"],
        item["reason"],
        _optional_float(item["a"]),
        _optional_float(item["b"]),
        item["calibration_row_ids_hash"],
    )


def _entry_from(value: object) -> BundleHeadEntry:
    item = _fields(
        value,
        frozenset(BundleHeadEntry.__dataclass_fields__),
        "bundle head entry",
    )
    calibrations, weights = item["calibrations"], item["weights"]
    standardization = item["standardization"]
    if not isinstance(calibrations, list) or not isinstance(weights, list | None):
        raise BundleError("bundle head entry arrays are invalid")
    if not isinstance(standardization, dict | None):
        raise BundleError("bundle head entry standardization is invalid")
    return BundleHeadEntry(
        item["target_id"],
        item["status"],
        item["reason"],
        item["target_definition_hash"],
        item["weights_hash"],
        _optional_float(item["intercept"]),
        item["standardization_hash"],
        tuple(_calibration_from(entry) for entry in calibrations),
        item["evaluation_report_id"],
        None if weights is None else tuple(float(value) for value in weights),
        None
        if standardization is None
        else Standardization.from_json(canonical_json(standardization)),
        _optional_float(item["development_brier"]),
    )


def bundle_from_json(raw: bytes) -> ModelBundle:
    """Read a committed bundle file back, verifying its content-addressed id.

    Every qualified entry's vectors are checked against their hashes on
    construction, and the bundle id is recomputed from the parsed entries,
    so a bundle whose bytes were altered after ``validate_bundle`` built it
    is refused rather than activated.
    """

    value = _fields(
        canonical_loads(raw), frozenset(ModelBundle.__dataclass_fields__), "bundle"
    )
    window = _fields(
        value["label_window"],
        frozenset({"freeze_at", "dataset_hash"}),
        "bundle label window",
    )
    entries, retained = value["entries"], value["retained"]
    if not isinstance(entries, list) or not isinstance(retained, list):
        raise BundleError("bundle arrays are invalid")
    retained_items = []
    for element in retained:
        item = _fields(
            element,
            frozenset({"entry", "representation_hash", "source_bundle_id"}),
            "retained artifact",
        )
        retained_items.append(
            RetainedArtifact(
                _entry_from(item["entry"]),
                item["representation_hash"],
                item["source_bundle_id"],
            )
        )
    label_window = LabelWindow(window["freeze_at"], window["dataset_hash"])
    bundle = ModelBundle(
        value["bundle_id"],
        value["representation_hash"],
        value["head_input_dimension"],
        label_window,
        value["corpus_release_hash"],
        value["split_hash"],
        value["target_registry_hash"],
        tuple(_entry_from(entry) for entry in entries),
        tuple(retained_items),
    )
    if bundle.bundle_id != _bundle_id(
        bundle.representation_hash,
        bundle.label_window,
        bundle.corpus_release_hash,
        bundle.split_hash,
        bundle.target_registry_hash,
        bundle.entries,
    ):
        raise BundleError("bundle id does not match its entries")
    return bundle
