"""The source commit an operator command records as its producer.

A command run inside the application image has neither `git` nor the
repository. `bin/build-image` bakes the commit it records in
`deploy/images.json` into the image as `RESEARCH_AGENT_SOURCE_COMMIT`, so
every command in a container names the recorded commit. Outside the image the
commit is the checkout's `HEAD`.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SOURCE_COMMIT_VARIABLE = "RESEARCH_AGENT_SOURCE_COMMIT"
_COMMIT = re.compile(r"[0-9a-f]{40}")


class SourceCommitUnavailable(RuntimeError):
    """Raised when neither the environment nor a checkout names the commit."""


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def source_commit(root: Path | None = None) -> str:
    """The recorded image commit when set, else the checkout's `HEAD`."""

    recorded = os.environ.get(SOURCE_COMMIT_VARIABLE, "")
    if recorded:
        if not _COMMIT.fullmatch(recorded):
            raise SourceCommitUnavailable(
                f"{SOURCE_COMMIT_VARIABLE} is not a full commit id"
            )
        return recorded
    repository = root or _repository_root()
    try:
        commit = subprocess.run(
            ("git", "-C", str(repository), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise SourceCommitUnavailable(
            f"{SOURCE_COMMIT_VARIABLE} is unset and {repository} is not a readable "
            "git checkout"
        ) from error
    if not _COMMIT.fullmatch(commit):
        raise SourceCommitUnavailable(f"git named {commit!r}, not a full commit id")
    return commit
