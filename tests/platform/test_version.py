from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research_agent.platform.version import VersionUnavailableError, get_version


def git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--initial-branch=develop")
    git(tmp_path, "config", "user.name", "Test User")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "record.txt").write_text("first\n", encoding="utf-8")
    git(tmp_path, "add", "record.txt")
    git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def commit(repository: Path, contents: str) -> None:
    (repository / "record.txt").write_text(contents, encoding="utf-8")
    git(repository, "add", "record.txt")
    git(repository, "commit", "-m", "change")


@pytest.mark.parametrize(
    ("tag", "expected"),
    (("v1.2.3", "1.2.3"), ("v1.2.3-rc.2", "1.2.3-rc.2")),
)
def test_tag_version_is_the_product_version(
    repository: Path, tag: str, expected: str
) -> None:
    git(repository, "tag", "-a", tag, "-m", tag)

    assert get_version(repository) == expected


def test_commit_after_tag_uses_next_patch_branch_distance_and_sha(
    repository: Path,
) -> None:
    git(repository, "tag", "-a", "v0.1.0", "-m", "v0.1.0")
    git(repository, "checkout", "-b", "feat/durable-storage")
    commit(repository, "second\n")

    assert (
        get_version(repository)
        == f"0.1.1-feat-durable-storage.1+{git(repository, 'rev-parse', 'HEAD')[:8]}"
    )


def test_dirty_worktree_does_not_change_the_graph_derived_version(
    repository: Path,
) -> None:
    git(repository, "tag", "-a", "v0.1.0", "-m", "v0.1.0")
    commit(repository, "second\n")
    expected = get_version(repository)
    (repository / "record.txt").write_text("dirty\n", encoding="utf-8")

    assert get_version(repository) == expected


def test_missing_version_tag_fails_closed(repository: Path) -> None:
    with pytest.raises(VersionUnavailableError, match="no reachable"):
        get_version(repository)
