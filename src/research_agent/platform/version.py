"""Derive the runtime product version from the repository graph."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class VersionUnavailableError(RuntimeError):
    """Raised when the repository cannot supply a product version."""


_TAG = re.compile(
    r"v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-rc\.(?P<rc>\d+))?\Z"
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", str(root), *args),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise VersionUnavailableError("unable to read the Git version graph") from error
    return completed.stdout.strip()


def _branch_slug(branch: str) -> str:
    slug = re.sub(r"[^0-9a-z]+", "-", branch.lower()).strip("-")
    return slug or "detached"


def _nearest_version_tag(root: Path) -> tuple[str, re.Match[str], int]:
    candidates: list[tuple[int, str, re.Match[str]]] = []
    for tag in _git(root, "tag", "--merged", "HEAD").splitlines():
        match = _TAG.fullmatch(tag)
        if match is None:
            continue
        distance = int(_git(root, "rev-list", "--count", f"{tag}..HEAD"))
        candidates.append((distance, tag, match))
    if not candidates:
        raise VersionUnavailableError("no reachable vX.Y.Z or vX.Y.Z-rc.N tag")
    candidates.sort(key=lambda candidate: candidate[:2])
    distance, tag, match = candidates[0]
    return tag, match, distance


def get_version(root: Path | None = None) -> str:
    """Return the version prescribed by ``CONTRIBUTING.md`` for ``HEAD``.

    A tag itself yields its tag without the leading ``v``. Later commits advance
    the tag's patch component and identify their branch, distance, and SHA.
    """

    repository = (root or _repository_root()).resolve()
    tag, match, distance = _nearest_version_tag(repository)
    if distance == 0:
        return tag[1:]

    branch = _git(repository, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        branch = "detached"
    commit = _git(repository, "rev-parse", "HEAD")
    next_patch = int(match["patch"]) + 1
    return (
        f"{match['major']}.{match['minor']}.{next_patch}-"
        f"{_branch_slug(branch)}.{distance}+{commit[:8]}"
    )
