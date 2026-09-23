"""Command-line contract of `pilot_run requeue`.

The function `requeue` is tested with fixtures in test_pilot_run.py. These
tests cover the command line around it: which stages and families reach it,
where the record cap comes from, what is printed, and what is refused.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from research_agent.ingest import pilot_run

STATE = {
    "frozen_at": "2025-12-01T00:00:00.000000Z",
    "population_rule": "rule",
    "cap": 10,
    "seed": 7,
    "per_month": 0,
    "categories": ["cs.AI", "cs.LG", "quant-ph", "q-bio"],
    "gate_on_labels": True,
    "record_cap": 2_000_000,
}


class _Storage:
    """A sentinel the command must hand to `requeue` unchanged."""


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    (tmp_path / "state.json").write_text(json.dumps(STATE) + "\n")
    return tmp_path


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Cut the command off from PostgreSQL and record what reaches `requeue`."""
    calls: dict[str, Any] = {}
    storage = _Storage()

    @contextmanager
    def fake_local_storage(**kwargs: Any) -> Iterator[_Storage]:
        calls["storage_kwargs"] = kwargs
        yield storage

    def fake_requeue(
        received: _Storage,
        *,
        stages: tuple[str, ...],
        families: tuple[str, ...],
        record_cap: int | None,
    ) -> list[dict[str, Any]]:
        assert received is storage
        calls["stages"] = stages
        calls["families"] = families
        calls["record_cap"] = record_cap
        return [
            {"stage": "openalex", "job_id": "b", "family_id": "2503.00002"},
            {"job_id": "a", "stage": "listing", "set_spec": "cs"},
        ]

    monkeypatch.setattr(pilot_run, "migrate", lambda database: None)
    monkeypatch.setattr(pilot_run, "local_storage", fake_local_storage)
    monkeypatch.setattr(pilot_run, "requeue", fake_requeue)
    return calls


def _run(state_dir: Path, *extra: str) -> int:
    return pilot_run.main(
        ["requeue", "--state", str(state_dir), "--dsn", "dbname=unused", *extra]
    )


def test_defaults_to_the_two_family_stages_and_every_family(
    state_dir: Path, captured: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(state_dir) == 0
    assert captured["stages"] == ("openalex", "documents")
    assert captured["families"] == ()
    printed = json.loads(capsys.readouterr().out)
    assert printed == [
        {"family_id": "2503.00002", "job_id": "b", "stage": "openalex"},
        {"job_id": "a", "set_spec": "cs", "stage": "listing"},
    ]


def test_output_is_sorted_key_json_of_what_was_enqueued(
    state_dir: Path, captured: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    _run(state_dir)
    out = capsys.readouterr().out
    # Keys within each entry are emitted in sorted order, so the text is stable
    # for the operator and for diffs, whatever order `requeue` built them in.
    assert out.index('"family_id"') < out.index('"job_id"') < out.index('"stage"')
    assert out == json.dumps(json.loads(out), indent=2, sort_keys=True) + "\n"


def test_stage_and_family_are_repeatable_and_passed_in_order(
    state_dir: Path, captured: dict[str, Any]
) -> None:
    assert (
        _run(
            state_dir,
            "--stage",
            "listing",
            "--stage",
            "openalex",
            "--family",
            "2503.00002",
            "--family",
            "2503.00009",
        )
        == 0
    )
    assert captured["stages"] == ("listing", "openalex")
    assert captured["families"] == ("2503.00002", "2503.00009")


def test_one_stage_replaces_the_default_rather_than_adding_to_it(
    state_dir: Path, captured: dict[str, Any]
) -> None:
    _run(state_dir, "--stage", "documents")
    assert captured["stages"] == ("documents",)


def test_record_cap_comes_from_the_pilot_state(
    state_dir: Path, captured: dict[str, Any]
) -> None:
    _run(state_dir)
    assert captured["record_cap"] == STATE["record_cap"]


def test_state_without_a_record_cap_uses_the_module_default(
    tmp_path: Path, captured: dict[str, Any]
) -> None:
    stored = dict(STATE)
    del stored["record_cap"]
    (tmp_path / "state.json").write_text(json.dumps(stored) + "\n")
    _run(tmp_path)
    assert captured["record_cap"] == pilot_run.RECORD_CAP


def test_a_record_cap_flag_that_differs_from_the_fixed_value_is_refused(
    state_dir: Path, captured: dict[str, Any]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run(state_dir, "--record-cap", "5")
    assert exit_info.value.code == 2
    assert "stages" not in captured


def test_unknown_stage_is_refused_before_anything_runs(
    state_dir: Path, captured: dict[str, Any]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run(state_dir, "--stage", "select")
    assert exit_info.value.code == 2
    assert "stages" not in captured


def test_requeue_without_a_pilot_state_is_refused(
    tmp_path: Path, captured: dict[str, Any]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _run(tmp_path / "fresh")
    assert exit_info.value.code == 2
    assert "stages" not in captured
    # The command must not have created a state file as a side effect of refusing.
    assert not (tmp_path / "fresh" / "state.json").exists()


def test_storage_is_opened_on_the_state_directory(
    state_dir: Path, captured: dict[str, Any]
) -> None:
    _run(state_dir)
    kwargs = captured["storage_kwargs"]
    assert kwargs["artifact_root"] == state_dir / "artifacts"
    assert kwargs["tls_directory"] == state_dir / "tls"
    assert kwargs["dsn"] == "dbname=unused"
