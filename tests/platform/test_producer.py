"""The producer commit an operator command records, in and out of the image (#366)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from research_agent.ingest import daily
from research_agent.platform import builds
from research_agent.platform.producer import (
    SOURCE_COMMIT_VARIABLE,
    SourceCommitUnavailable,
    source_commit,
)

ROOT = Path(__file__).resolve().parents[2]
RECORDED = "c" * 40


@pytest.fixture
def no_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A PATH that holds no `git`, as in the application image."""

    empty = tmp_path / "bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert shutil.which("git") is None


@pytest.mark.usefixtures("no_git")
def test_the_recorded_commit_is_the_producer_without_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SOURCE_COMMIT_VARIABLE, RECORDED)
    assert source_commit() == RECORDED


@pytest.mark.usefixtures("no_git")
def test_without_the_variable_or_git_the_commit_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SOURCE_COMMIT_VARIABLE, raising=False)
    with pytest.raises(SourceCommitUnavailable, match=SOURCE_COMMIT_VARIABLE):
        source_commit()


def test_an_abbreviated_recorded_commit_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SOURCE_COMMIT_VARIABLE, "cfaaacdc")
    with pytest.raises(SourceCommitUnavailable, match="full commit id"):
        source_commit()


def test_a_checkout_without_the_variable_names_its_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SOURCE_COMMIT_VARIABLE, raising=False)
    head = subprocess.run(
        ("git", "-C", str(ROOT), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert source_commit() == head


@pytest.mark.usefixtures("no_git")
def test_the_daily_command_records_the_image_commit_without_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = daily.DailyWindow("2026-09-23", "2026-09-23")
    monkeypatch.setenv(SOURCE_COMMIT_VARIABLE, RECORDED)
    assert daily._identity(window).producer.source_commit == RECORDED

    monkeypatch.delenv(SOURCE_COMMIT_VARIABLE)
    with pytest.raises(SourceCommitUnavailable, match=SOURCE_COMMIT_VARIABLE):
        daily._identity(window)


def test_the_image_build_bakes_the_recorded_commit_into_the_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("Dockerfile", "uv.lock", "pyproject.toml"):
        shutil.copy(ROOT / name, tmp_path / name)
    (tmp_path / "deploy").mkdir()
    answers = {
        ("git", "rev-parse", "HEAD"): RECORDED,
        ("git", "ls-tree", "-r", "--full-tree", "HEAD"): "tree",
        ("git", "status", "--porcelain", "--untracked-files=normal"): "",
        ("docker", "version", "--format", "{{.Server.Version}}"): "29.8.0",
    }
    monkeypatch.setattr(builds, "_run", lambda root, *command: answers[command])
    monkeypatch.setattr(builds, "get_version", lambda root: "0.1.0")
    built: list[tuple[str, ...]] = []

    def docker_build(command: tuple[str, ...], **_: Any) -> None:
        built.append(command)
        Path(command[command.index("--iidfile") + 1]).write_text("sha256:" + "e" * 64)

    monkeypatch.setattr(subprocess, "run", docker_build)

    record = builds.build_image(tmp_path)

    (command,) = built
    argument = command[command.index("--build-arg") + 1]
    assert argument == f"{SOURCE_COMMIT_VARIABLE}={record.source_commit}"
    assert record.source_commit == RECORDED
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert f"ARG {SOURCE_COMMIT_VARIABLE}\n" in dockerfile
    assert f"ENV {SOURCE_COMMIT_VARIABLE}=${{{SOURCE_COMMIT_VARIABLE}}}\n" in dockerfile
