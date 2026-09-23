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

from dataclasses import dataclass
from hashlib import sha256

import numpy as np

from research_agent.contracts import canonical_json
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
    """One registry target's bundled disposition: qualified with an artifact, or unavailable."""

    target_id: str
    status: str
    reason: str | None
    target_definition_hash: str | None
    weights_hash: str | None
    intercept: float | None
    standardization_hash: str | None
    calibrations: tuple[BundleCategoryCalibration, ...]
    evaluation_report_id: str | None

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
        else:
            if self.reason is None:
                raise BundleError("an unavailable head entry requires a reason")
            if (
                self.target_definition_hash is not None
                or self.weights_hash is not None
                or self.intercept is not None
                or self.standardization_hash is not None
                or self.evaluation_report_id is not None
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


def _weights_hash(fit: FitResult) -> str:
    reference, _ = encode_tensor(fit.weights.astype(np.float64))
    return reference.payload_hash


def _unavailable_entry(target_id: str, reason: str) -> BundleHeadEntry:
    return BundleHeadEntry(
        target_id, "unavailable", reason, None, None, None, None, (), None
    )


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
        entries.append(
            BundleHeadEntry(
                fit.target_id,
                "qualified",
                None,
                fit.target_definition_hash,
                _weights_hash(fit),
                fit.intercept,
                sha256(fit.standardization.to_canonical_json()).hexdigest(),
                calibrations,
                item.evaluation_report_id,
            )
        )

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
    bundle_id = sha256(canonical_json(manifest_identity)).hexdigest()
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
