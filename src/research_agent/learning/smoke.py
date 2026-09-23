"""Engineering-only prediction-head smoke test over a small preserved slice (#83).

The smoke test runs the production gates and the production numerical
objective over a bounded slice and proves the pipeline end to end: fit,
serialize, reload, infer, replay. It is not a second trainer and it never
weakens a gate:

* the production three-head fit, calibration and readiness owners run
  unchanged over the slice; a slice below their class floors yields
  unavailable heads, no bundle, no active serving handle and no accuracy
  claim, and the report says so;
* the engineering fit reuses ``_fit_candidate`` and the shared standardization
  (the same objective and solver the production fit calls) on whatever known
  rows exist, only refusing a target that lacks both known classes or any
  usable row. Its result is a :class:`SmokeHead`, a type no bundle, promotion
  or serving owner accepts.

Inputs are immutable: a slice file addressed by its own hash. Outputs are
content-keyed, so a rerun over the same slice and configuration reuses the
cache without recomputation and a clean refit is compared to it within a
fixed numeric tolerance.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import numpy as np
import scipy  # type: ignore[import-untyped]
from numpy.typing import NDArray

from research_agent.contracts import (
    ProducerVersion,
    RecordMeta,
    canonical_json,
    canonical_loads,
)
from research_agent.contracts.learning import (
    EMBEDDING_FEATURE_DIMENSION,
    HEAD_INPUT_DIMENSION,
    METADATA_DIMENSION,
    PRIMARY_CATEGORY_IDS,
    TARGET_IDS,
    TargetRegistry,
    TensorRef,
)
from research_agent.learning.features import (
    Standardization,
    apply_head_input,
    fit_standardization,
)
from research_agent.learning.fit import (
    LAMBDAS,
    FitError,
    MaterializedPartition,
    _fit_candidate,
    _select_candidate,
    _standardized_matrix,
)
from research_agent.learning.heads import (
    HeadUnavailable,
    calibrate_three_heads,
    fit_three_heads,
)
from research_agent.learning.readiness import forecast_readiness
from research_agent.learning.tensors import decode_tensor, encode_tensor
from research_agent.outcomes.targets import registry as target_registry

SCHEMA = "head-smoke-v1"
# Stable numeric equality for weights and scores between a clean rerun and the
# cached artifacts; the solver is deterministic, so this bounds only
# floating-point library variation, not a modelling difference.
TOLERANCE = 1e-8
PARTITIONS = ("fit", "development", "calibration", "locked_evaluation")
_SLICE_KEYS = frozenset(
    {"features", "labels", "known_mask", "family_ids", "partition", "identity"}
)
_IDENTITY_FIELDS = (
    "corpus_release_hash",
    "split_hash",
    "representation_hash",
)


class SmokeError(ValueError):
    """The slice or a stored smoke artifact is not admissible."""


@dataclass(frozen=True, slots=True)
class Slice:
    """A preserved slice read back from its immutable file."""

    path: Path
    file_hash: str
    features: NDArray[np.float32]
    labels: NDArray[np.uint8]
    known_mask: NDArray[np.uint8]
    family_ids: tuple[str, ...]
    partition: tuple[str, ...]
    identity: dict[str, str]


@dataclass(frozen=True, slots=True)
class SmokeHead:
    """An engineering-only fitted head; never a bundle, promotion or serving input."""

    target_id: str
    weights: NDArray[np.float64]
    intercept: float
    selected_lambda: float
    standardization: Standardization
    fit_rows: int
    fit_positives: int
    development_brier: float
    engineering_only: bool = True


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_slice(path: Path) -> Slice:
    """Read a slice with pickles disabled and check its declared shape."""

    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != _SLICE_KEYS:
            raise SmokeError("slice arrays do not match the layout")
        features = cast(NDArray[np.float32], archive["features"])
        labels = cast(NDArray[np.uint8], archive["labels"])
        mask = cast(NDArray[np.uint8], archive["known_mask"])
        ids = tuple(str(item) for item in archive["family_ids"])
        partition = tuple(str(item) for item in archive["partition"])
        identity = json.loads(str(archive["identity"]))
    rows = features.shape[0]
    if (
        features.dtype != np.float32
        or features.ndim != 2
        or features.shape[1] != HEAD_INPUT_DIMENSION
        or labels.shape != (rows, 3)
        or mask.shape != (rows, 3)
        or len(ids) != rows
        or len(partition) != rows
        or not set(partition) <= set(PARTITIONS)
        or set(identity) != set(_IDENTITY_FIELDS)
    ):
        raise SmokeError("slice contents do not match the declared layout")
    return Slice(
        path, sha256_file(path), features, labels, mask, ids, partition, identity
    )


def _meta() -> RecordMeta:
    return RecordMeta(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        "2026-01-01T00:00:00.000000Z",
    )


def solver_runtime_hash() -> str:
    """Identify the numeric runtime a result was produced under."""

    return sha256(
        canonical_json(
            {
                "solver": "L-BFGS-B",
                "python": platform.python_version(),
                "numpy": np.__version__,
                "scipy": scipy.__version__,
            }
        )
    ).hexdigest()


def _partitions(
    data: Slice, registry: TargetRegistry
) -> dict[str, MaterializedPartition]:
    registry_hash = sha256(registry.to_canonical_json()).hexdigest()
    definition_hashes = cast(
        tuple[str, str, str],
        tuple(
            sha256(item.to_canonical_json()).hexdigest()
            for item in registry.definitions
        ),
    )
    result: dict[str, MaterializedPartition] = {}
    for name in PARTITIONS:
        rows = [index for index, item in enumerate(data.partition) if item == name]
        if not rows:
            raise SmokeError(f"slice has no {name} rows")
        result[name] = MaterializedPartition(
            data.features[rows],
            data.labels[rows],
            data.known_mask[rows],
            tuple(data.family_ids[index] for index in rows),
            name,
            data.identity["corpus_release_hash"],
            data.identity["split_hash"],
            registry_hash,
            data.identity["representation_hash"],
            solver_runtime_hash(),
            definition_hashes,
        )
    return result


def _known(
    partition: MaterializedPartition, index: int
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    known = partition.known_mask[:, index].astype(bool)
    return (
        partition.features[known].astype(np.float64),
        partition.labels[known, index].astype(np.float64),
    )


def fit_engineering_head(
    index: int,
    fit: MaterializedPartition,
    development: MaterializedPartition,
) -> SmokeHead | str:
    """Fit one target with the production objective, or return why it cannot.

    Returns the reason string when a partition lacks both known classes or a
    usable row; unknown labels are never counted, filled or read as negative.
    """

    fit_x, fit_y = _known(fit, index)
    dev_x, dev_y = _known(development, index)
    for name, values in (("fit", fit_y), ("development", dev_y)):
        if values.size == 0 or values.min() == values.max():
            return f"insufficient data: {name} rows lack both known classes"
    standardization = fit_standardization(
        fit_x[:, EMBEDDING_FEATURE_DIMENSION:].tolist()
    )
    fit_x = _standardized_matrix(fit_x, standardization)
    dev_x = _standardized_matrix(dev_x, standardization)
    hash_ = solver_runtime_hash()
    records = [
        _fit_candidate(fit_x, fit_y, dev_x, dev_y, regularization, hash_)
        for regularization in LAMBDAS
    ]
    try:
        diagnostic, parameters, brier = _select_candidate(records)
    except FitError:
        return "nonconvergence: no regularization candidate converged"
    return SmokeHead(
        TARGET_IDS[index],
        parameters[:-1].copy(),
        float(parameters[-1]),
        diagnostic.regularization,
        standardization,
        int(fit_y.size),
        int(fit_y.sum()),
        brier,
    )


def infer(head: SmokeHead, features: NDArray[np.float32]) -> NDArray[np.float64]:
    """Score rows through the shared input builder and the stored coefficients."""

    rows = np.asarray(
        [
            apply_head_input(
                tuple(float(v) for v in row[:EMBEDDING_FEATURE_DIMENSION]),
                tuple(float(v) for v in row[EMBEDDING_FEATURE_DIMENSION:]),
                head.standardization,
            )
            for row in features
        ],
        dtype=np.float64,
    )
    logits = rows @ head.weights + head.intercept
    return cast(NDArray[np.float64], np.exp(-np.logaddexp(0.0, -logits)))


def write_head(directory: Path, head: SmokeHead) -> None:
    reference, payload = encode_tensor(head.weights)
    (directory / f"{head.target_id}.weights").write_bytes(payload)
    (directory / f"{head.target_id}.json").write_bytes(
        canonical_json(
            {
                "target_id": head.target_id,
                "weights": canonical_loads(reference.to_canonical_json()),
                "intercept": head.intercept,
                "selected_lambda": head.selected_lambda,
                "standardization": head.standardization.to_dict(),
                "fit_rows": head.fit_rows,
                "fit_positives": head.fit_positives,
                "development_brier": head.development_brier,
                "engineering_only": True,
            }
        )
    )


def read_head(directory: Path, target_id: str) -> SmokeHead:
    record = cast(
        dict[str, Any],
        canonical_loads((directory / f"{target_id}.json").read_bytes()),
    )
    reference = TensorRef.from_json(canonical_json(record["weights"]))
    weights = cast(
        NDArray[np.float64],
        decode_tensor(reference, (directory / f"{target_id}.weights").read_bytes()),
    ).copy()
    return SmokeHead(
        record["target_id"],
        weights,
        float(record["intercept"]),
        float(record["selected_lambda"]),
        Standardization.from_json(canonical_json(record["standardization"])),
        int(record["fit_rows"]),
        int(record["fit_positives"]),
        float(record["development_brier"]),
    )


def _peak_memory_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak) if sys.platform == "darwin" else int(peak) * 1024


def _brier(probability: NDArray[np.float64], labels: NDArray[np.float64]) -> float:
    return float(np.mean((probability - labels) ** 2))


def _fit_all(
    partitions: dict[str, MaterializedPartition],
) -> dict[str, SmokeHead | str]:
    return {
        target_id: fit_engineering_head(
            index, partitions["fit"], partitions["development"]
        )
        for index, target_id in enumerate(TARGET_IDS)
    }


def run_smoke(slice_path: Path, out_dir: Path) -> dict[str, Any]:
    """Run the smoke pipeline over one slice and write its report."""

    timings: dict[str, float] = {}
    started = time.perf_counter()

    def lap(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = round(now - since, 6)
        return now

    mark = started
    data = load_slice(slice_path)
    registry = target_registry(_meta())
    partitions = _partitions(data, registry)
    mark = lap("load", mark)

    # Production gates, unchanged: a small slice must come out not-qualified.
    fitted = fit_three_heads(registry, partitions["fit"], partitions["development"])
    calibrated = calibrate_three_heads(fitted, partitions["calibration"])
    readiness = forecast_readiness(
        engineering_ready=True,
        paper_cards_readable=True,
        jev_smoke_tested=False,
        handle=None,
        mature_sealed_predictions=False,
    )
    production_gate = [
        {
            "target_id": item.target_id,
            "status": "unavailable" if isinstance(item, HeadUnavailable) else "fitted",
            "reason": item.reason if isinstance(item, HeadUnavailable) else None,
        }
        for item in calibrated.calibrated
    ]
    mark = lap("production_gates", mark)

    config = {
        "schema": SCHEMA,
        "lambdas": list(LAMBDAS),
        "tolerance": TOLERANCE,
        "head_input_dimension": HEAD_INPUT_DIMENSION,
        "metadata_dimension": METADATA_DIMENSION,
        "solver_runtime_hash": solver_runtime_hash(),
    }
    key = sha256(
        canonical_json({"slice": data.file_hash, "config": config})
    ).hexdigest()
    cache = out_dir / "cache" / key
    complete = (
        cache.is_dir()
        and all((cache / f"{target_id}.json").exists() for target_id in TARGET_IDS)
        and (cache / "COMPLETE").exists()
    )

    fresh: dict[str, SmokeHead | str] | None = None
    if not complete:
        fresh = _fit_all(partitions)
        cache.mkdir(parents=True, exist_ok=True)
        for target_id in TARGET_IDS:
            item = fresh[target_id]
            if isinstance(item, SmokeHead):
                write_head(cache, item)
            else:
                (cache / f"{target_id}.json").write_bytes(
                    canonical_json({"target_id": target_id, "unavailable": item})
                )
        (cache / "COMPLETE").write_bytes(b"")
    mark = lap("fit", mark)

    stored: dict[str, SmokeHead | str] = {}
    for target_id in TARGET_IDS:
        raw = json.loads((cache / f"{target_id}.json").read_bytes())
        stored[target_id] = (
            raw["unavailable"] if "unavailable" in raw else read_head(cache, target_id)
        )
    mark = lap("reload", mark)

    # Replay: a cache hit is compared with a clean refit from the same inputs;
    # a first run is compared with what it just reloaded from disk.
    reference = fresh if fresh is not None else _fit_all(partitions)
    replay_diff = 0.0
    replay_equal = True
    for target_id in TARGET_IDS:
        a, b = reference[target_id], stored[target_id]
        if isinstance(a, SmokeHead) and isinstance(b, SmokeHead):
            replay_diff = max(
                replay_diff,
                float(np.max(np.abs(a.weights - b.weights))),
                abs(a.intercept - b.intercept),
            )
        elif isinstance(a, SmokeHead) != isinstance(b, SmokeHead) or a != b:
            replay_equal = False
    replay_equal = replay_equal and replay_diff <= TOLERANCE
    mark = lap("replay", mark)

    held = partitions["locked_evaluation"]
    heads_report: list[dict[str, Any]] = []
    for index, target_id in enumerate(TARGET_IDS):
        item = stored[target_id]
        if isinstance(item, str):
            heads_report.append(
                {"target_id": target_id, "status": "insufficient", "reason": item}
            )
            continue
        features, labels = _known(held, index)
        entry: dict[str, Any] = {
            "target_id": target_id,
            "status": "fitted_engineering_only",
            "selected_lambda": item.selected_lambda,
            "fit_rows": item.fit_rows,
            "fit_positives": item.fit_positives,
            "development_brier": item.development_brier,
            "weights_hash": encode_tensor(item.weights)[0].payload_hash,
            "intercept": item.intercept,
            "scored_rows": int(labels.size),
        }
        if labels.size:
            probability = infer(item, features.astype(np.float32))
            if (
                not np.isfinite(probability).all()
                or ((probability < 0) | (probability > 1)).any()
            ):
                raise SmokeError("inference produced an invalid probability")
            entry["heldout_brier_uncalibrated"] = _brier(probability, labels)
        heads_report.append(entry)
    lap("inference", mark)

    result = {
        "schema": SCHEMA,
        "engineering_only": True,
        "slice": {
            "file_hash": data.file_hash,
            "rows": len(data.family_ids),
            "partition_rows": {
                name: len(part.family_ids) for name, part in partitions.items()
            },
            "family_ids_hash": sha256(
                canonical_json(list(data.family_ids))
            ).hexdigest(),
            "features_hash": encode_tensor(data.features)[0].payload_hash,
            "labels_hash": encode_tensor(data.labels)[0].payload_hash,
            "known_mask_hash": encode_tensor(data.known_mask)[0].payload_hash,
            **data.identity,
        },
        "configuration": config,
        "production_gates": production_gate,
        "qualification": {
            "qualified": False,
            "active_serving_bundle": None,
            "forecasting_accuracy_claim": False,
            "readiness": [
                {"target_id": t.target_id, "qualified": t.qualified, "reason": t.reason}
                for t in readiness.targets
            ],
        },
        "heads": heads_report,
        "replay": {
            "cache_key": key,
            "cache_hit": complete,
            "equal_within_tolerance": replay_equal,
            "max_abs_difference": replay_diff,
            "tolerance": TOLERANCE,
        },
    }
    result["environment"] = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "platform": platform.platform(),
    }
    timings["total"] = round(time.perf_counter() - started, 6)
    result["timing_seconds"] = timings
    result["peak_memory_bytes"] = _peak_memory_bytes()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def build_engineering_slice(path: Path, *, rows: int = 100, seed: int = 83) -> None:
    """Write a deterministic synthetic slice; visibly not corpus data.

    Rows are ordered by publication week and split 60/15/10/15. The third
    target has no positive fit label, so the smoke path must report it
    insufficient rather than invent a class; the second has unknown rows.
    """

    if rows != 100:
        raise SmokeError("the engineering slice is fixed at 100 rows")
    rng = np.random.default_rng(seed)
    features = np.zeros((rows, HEAD_INPUT_DIMENSION), dtype=np.float32)
    labels = np.zeros((rows, 3), dtype=np.uint8)
    mask = np.ones((rows, 3), dtype=np.uint8)
    signal = np.arange(rows) % 2
    for half in (0, 1):
        base = half * (EMBEDDING_FEATURE_DIMENSION // 2)
        block = rng.normal(size=(rows, 8)).astype(np.float32)
        block[:, 0] += signal * 2.0 - 1.0
        features[:, base : base + 8] = block
    norms = np.linalg.norm(features[:, :EMBEDDING_FEATURE_DIMENSION], axis=1)
    features[:, :EMBEDDING_FEATURE_DIMENSION] /= norms[:, None].astype(np.float32)
    meta = EMBEDDING_FEATURE_DIMENSION
    features[:, meta] = np.log1p(rng.integers(1, 9, size=rows))
    features[:, meta + 1] = rng.integers(1, 4, size=rows)
    categories = rng.integers(0, len(PRIMARY_CATEGORY_IDS), size=rows)
    features[np.arange(rows), meta + 2 + categories] = 1.0
    cursor = meta + 2 + len(PRIMARY_CATEGORY_IDS)
    features[:, cursor] = np.log1p(rng.integers(80, 300, size=rows))
    features[:, cursor + 1] = rng.integers(4, 16, size=rows)
    features[np.arange(rows), cursor + 2 + rng.integers(0, 7, size=rows)] = 1.0
    features[:, cursor + 9] = rng.integers(0, 2, size=rows)
    features[:, cursor + 10] = rng.integers(1, 4, size=rows)
    labels[:, 0] = signal.astype(np.uint8)
    labels[:, 1] = (signal ^ (rng.random(rows) < 0.15)).astype(np.uint8)
    mask[::7, 1] = 0
    labels[mask == 0] = 0
    partition = np.array(
        ["fit"] * 60
        + ["development"] * 15
        + ["calibration"] * 10
        + ["locked_evaluation"] * 15
    )
    mask[:60, 2] = 1
    labels[:60, 2] = 0
    labels[60:, 2] = signal[60:].astype(np.uint8)
    ids = np.array(
        [
            str(UUID(bytes=sha256(f"head-smoke-{i}".encode()).digest()[:16], version=4))
            for i in range(rows)
        ]
    )
    identity = {
        name: sha256(f"head-smoke-{name}".encode()).hexdigest()
        for name in _IDENTITY_FIELDS
    }
    np.savez_compressed(
        path,
        features=features,
        labels=labels,
        known_mask=mask,
        family_ids=ids,
        partition=partition,
        identity=np.array(json.dumps(identity, sort_keys=True)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the smoke test over a slice file")
    run.add_argument("--slice", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    fixture = commands.add_parser(
        "fixture", help="write the engineering-only synthetic slice"
    )
    fixture.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "fixture":
        build_engineering_slice(args.out)
        print(args.out)
        return 0
    result = run_smoke(args.slice, args.out)
    print(json.dumps(result["qualification"], sort_keys=True))
    print(args.out / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
