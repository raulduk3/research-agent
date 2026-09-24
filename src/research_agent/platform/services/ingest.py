"""``serve-ingest``: the daily worker loop over the local storage adapters (#315).

Once per UTC day it runs the day pass ``bin/daily`` runs
(``orchestration/daily.py#main``): listing, documents, the requested-paper
pass, cards, sheets, the snapshot and the day's run records, over
``ingest/pilot_local.py`` as the pilot does today. That pass holds the
database DSN and reads papers in-process, so there is no separate reader
service; decision 0029 records both and what they defer.

The day pass is resumable and a repeated day issues nothing new, so a pass
that fails is left to raise: the supervisor restarts the launcher and the
next pass resumes from storage.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_agent.orchestration import daily
from research_agent.platform.services.config import (
    LaunchConfig,
    LaunchRefused,
    load_launch_config,
)

DayPass = Callable[[list[str]], int]


def day_pass_arguments(config: LaunchConfig, day: str) -> list[str]:
    """The day pass's arguments for *day*, every value from the checked config.

    The profile passed is the file whose hash the launcher checked; the DSN
    is read from its secret file into this process, never onto a command line.
    """

    arguments = [
        "--state",
        config.text("state_dir"),
        "--dsn",
        config.secret_text("database_dsn"),
        "--profile",
        str(config.profile_file),
        "--agent-model-manifest",
        config.text("agent_model_manifest"),
        "--day",
        day,
        "--device",
        config.text("device") if "device" in config.values else "cpu",
    ]
    images = config.mapping("images")
    for role in sorted(images):
        arguments += ["--image", f"{role}={config.text(role, section='images')}"]
    identities = config.values.get("index_identities")
    if not isinstance(identities, list) or not identities:
        raise LaunchRefused("index_identities must be a nonempty string list")
    for identity in identities:
        if not isinstance(identity, str):
            raise LaunchRefused("index_identities must be a nonempty string list")
        arguments += ["--index-identity", identity]
    for key, flag in (("since", "--since"), ("model_cache_dir", "--cache-dir")):
        if key in config.values:
            arguments += [flag, config.text(key)]
    return arguments


def serve_ingest(
    config_path: Path,
    *,
    once: bool = False,
    day_pass: DayPass = daily.main,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
    secrets_root: Path | None = None,
) -> None:
    """Run the day pass for today, then again after each UTC midnight."""

    config = load_launch_config(config_path, "ingest", secrets_root=secrets_root)
    while True:
        started = now()
        status = day_pass(day_pass_arguments(config, started.strftime("%Y-%m-%d")))
        if status != 0:
            raise RuntimeError(f"the day pass exited with status {status}")
        if once:
            return
        tomorrow = (started + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        sleep(max((tomorrow - now()).total_seconds(), 0.0))
