from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from research_agent.contracts.learning import TARGET_IDS
from research_agent.learning.smoke import (
    TOLERANCE,
    SmokeError,
    SmokeHead,
    build_engineering_slice,
    infer,
    load_slice,
    main,
    read_head,
    run_smoke,
)

SLICE = Path(__file__).parents[2] / "fixtures" / "learning" / "head_smoke_slice.npz"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the smoke test must not open a connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_committed_slice_is_the_deterministic_engineering_slice(
    tmp_path: Path,
) -> None:
    rebuilt = tmp_path / "slice.npz"
    build_engineering_slice(rebuilt)
    committed, again = load_slice(SLICE), load_slice(rebuilt)
    assert np.array_equal(committed.features, again.features)
    assert np.array_equal(committed.labels, again.labels)
    assert np.array_equal(committed.known_mask, again.known_mask)
    assert committed.family_ids == again.family_ids
    assert len(committed.family_ids) == 100


def test_small_slice_stays_not_qualified_with_no_serving_bundle(
    tmp_path: Path,
) -> None:
    report = run_smoke(SLICE, tmp_path)
    assert report["engineering_only"] is True
    assert report["qualification"]["qualified"] is False
    assert report["qualification"]["active_serving_bundle"] is None
    assert report["qualification"]["forecasting_accuracy_claim"] is False
    assert [item["status"] for item in report["production_gates"]] == [
        "unavailable"
    ] * 3
    assert all(
        item["reason"] == "insufficient fit classes"
        for item in report["production_gates"]
    )
    assert all(
        item["reason"] == "no_bundle_activated"
        for item in report["qualification"]["readiness"]
    )


def test_target_without_both_classes_reports_insufficient_not_negative(
    tmp_path: Path,
) -> None:
    report = run_smoke(SLICE, tmp_path)
    by_target = {item["target_id"]: item for item in report["heads"]}
    assert by_target[TARGET_IDS[0]]["status"] == "fitted_engineering_only"
    assert by_target[TARGET_IDS[1]]["status"] == "fitted_engineering_only"
    assert by_target[TARGET_IDS[2]]["status"] == "insufficient"
    assert "lack both known classes" in by_target[TARGET_IDS[2]]["reason"]
    # Unknown rows of the second target were left out, not read as negative.
    data = load_slice(SLICE)
    fit_rows = [i for i, name in enumerate(data.partition) if name == "fit"]
    known = int(data.known_mask[fit_rows, 1].sum())
    assert known < len(fit_rows)
    assert by_target[TARGET_IDS[1]]["fit_rows"] == known


def test_fit_serialize_reload_and_infer_agree_within_tolerance(
    tmp_path: Path,
) -> None:
    report = run_smoke(SLICE, tmp_path)
    cache = tmp_path / "cache" / report["replay"]["cache_key"]
    head = read_head(cache, TARGET_IDS[0])
    assert isinstance(head, SmokeHead) and head.engineering_only
    data = load_slice(SLICE)
    probabilities = infer(head, data.features)
    assert probabilities.shape == (100,)
    assert ((probabilities >= 0) & (probabilities <= 1)).all()
    # The signal is real: reloaded coefficients separate the two classes.
    labels = data.labels[:, 0].astype(bool)
    assert probabilities[labels].mean() > probabilities[~labels].mean() + 0.2
    assert report["replay"]["equal_within_tolerance"] is True
    assert report["replay"]["max_abs_difference"] <= TOLERANCE


def test_rerun_reuses_cache_and_matches_a_clean_refit(tmp_path: Path) -> None:
    first = run_smoke(SLICE, tmp_path)
    second = run_smoke(SLICE, tmp_path)
    assert first["replay"]["cache_hit"] is False
    assert second["replay"]["cache_hit"] is True
    assert second["replay"]["equal_within_tolerance"] is True
    assert first["heads"] == second["heads"]
    assert first["slice"] == second["slice"]

    clean = run_smoke(SLICE, tmp_path / "clean")
    assert clean["replay"]["cache_hit"] is False
    assert clean["heads"] == first["heads"]


def test_report_records_hashes_configuration_environment_timing_and_memory(
    tmp_path: Path,
) -> None:
    run_smoke(SLICE, tmp_path)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    for name in (
        "file_hash",
        "features_hash",
        "labels_hash",
        "known_mask_hash",
        "family_ids_hash",
        "corpus_release_hash",
        "split_hash",
        "representation_hash",
    ):
        assert len(report["slice"][name]) == 64
    assert report["slice"]["partition_rows"] == {
        "fit": 60,
        "development": 15,
        "calibration": 10,
        "locked_evaluation": 15,
    }
    assert report["configuration"]["lambdas"] == [0.0001, 0.001, 0.01, 0.1, 1.0]
    assert report["environment"]["numpy"] == np.__version__
    assert report["timing_seconds"]["total"] > 0
    assert report["peak_memory_bytes"] > 0
    assert all(len(item["weights_hash"]) == 64 for item in report["heads"][:2])


def test_changed_slice_bytes_change_the_cache_key(tmp_path: Path) -> None:
    other = tmp_path / "other.npz"
    build_engineering_slice(other, seed=84)
    first = run_smoke(SLICE, tmp_path / "out")
    second = run_smoke(other, tmp_path / "out")
    assert first["replay"]["cache_key"] != second["replay"]["cache_key"]
    assert second["replay"]["cache_hit"] is False


def test_slice_with_unexpected_layout_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.npz"
    np.savez(bad, features=np.zeros((1, 3), dtype=np.float32))
    with pytest.raises(SmokeError, match="layout"):
        load_slice(bad)


def test_command_line_runs_the_slice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--slice", str(SLICE), "--out", str(tmp_path)]) == 0
    assert '"qualified": false' in capsys.readouterr().out
    assert (tmp_path / "report.json").exists()
