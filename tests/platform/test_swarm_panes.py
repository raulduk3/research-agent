"""``bin/panes`` opens several agents in tmux splits, live or replayed (#329).

The script drives a real tmux server on a private socket. ``bin/tail-runs``,
``bin/swarm`` and ``bin/bindings`` are replaced by small scripts that answer
as the trace read does: a replay of a run without an ending exits 2, and a
followed run prints its start line first.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

PANES = Path(__file__).resolve().parents[2] / "bin" / "panes"

# run id -> (ended, lineage, island)
RUNS = {
    "run-a": (False, "lin-1", "alpha"),
    "run-b": (False, "lin-2", "beta"),
    "run-c": (True, "lin-1", "alpha"),
}

FAKE_TAIL = """#!/bin/sh
mode=$1 id=$2
case $id in
{cases}
esac
line="start run $id paper=p lineage=$lineage island=$island budgets tool_calls=1"
if [ "$mode" = --replay ]; then
  [ "$ended" = 1 ] || exit 2
  echo "$line"
  exit 0
fi
echo "$line"
exec sleep 60
"""


def _fake_tail() -> str:
    cases = "\n".join(
        f"{run}) ended={int(ended)} lineage={lineage} island={island} ;;"
        for run, (ended, lineage, island) in RUNS.items()
    )
    return FAKE_TAIL.format(cases=cases)


def _script(path: Path, text: str) -> str:
    path.write_text(text)
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def panes(tmp_path: Path) -> Iterator[tuple[dict[str, str], list[str]]]:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    socket = f"panes-test-{uuid4().hex[:8]}"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"TMUX", "TERM_PROGRAM", "LC_TERMINAL"}
    }
    env.update(
        PANES_SOCKET=socket,
        PANES_TAIL=_script(tmp_path / "tail-runs", _fake_tail()),
        PANES_SWARM=_script(tmp_path / "swarm", "#!/bin/sh\nexec sleep 60\n"),
        PANES_BINDINGS=_script(
            tmp_path / "bindings", "#!/bin/sh\nprintf 'run-a\\nrun-b\\nrun-c\\n'\n"
        ),
        PANES_INTERVAL="60",
    )
    yield env, ["tmux", "-L", socket]
    subprocess.run(["tmux", "-L", socket, "kill-server"], env=env, capture_output=True)


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(PANES), *args], env=env, capture_output=True, text=True, timeout=60
    )


def _panes(tmux: list[str], env: dict[str, str], window: str) -> list[tuple[str, str]]:
    listed = subprocess.run(
        [
            *tmux,
            "list-panes",
            "-t",
            f"swarm:{window}",
            "-F",
            "#{@run}\t#{pane_start_command}",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [tuple(line.split("\t", 1)) for line in listed.splitlines()]  # type: ignore[misc]


def test_live_opens_the_control_pane_and_one_pane_per_running_run(
    panes: tuple[dict[str, str], list[str]], tmp_path: Path
) -> None:
    env, tmux = panes
    result = _run(
        env,
        "live",
        "--day",
        "2026-09-24",
        "--state",
        str(tmp_path),
        "--",
        "--storage-host",
        "h",
    )
    assert result.returncode == 0, result.stderr

    shown = _panes(tmux, env, "live")
    assert [run for run, _ in shown] == ["swarm", "run-a", "run-b"]
    assert "--run" in shown[1][1] and "--storage-host" in shown[1][1]

    # A second pass adds nothing that already has a pane.
    assert (
        _run(env, "retile", "--day", "2026-09-24", "--state", str(tmp_path)).returncode
        == 0
    )
    assert [run for run, _ in _panes(tmux, env, "live")] == ["swarm", "run-a", "run-b"]

    windows = subprocess.run(
        [*tmux, "list-windows", "-t", "swarm", "-F", "#{window_name}"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "retile" in windows


def test_live_keeps_to_the_island_and_the_pane_limit(
    panes: tuple[dict[str, str], list[str]], tmp_path: Path
) -> None:
    env, tmux = panes
    result = _run(env, "live", "--state", str(tmp_path), "--island", "beta")
    assert result.returncode == 0, result.stderr
    assert [run for run, _ in _panes(tmux, env, "live")] == ["swarm", "run-b"]

    subprocess.run([*tmux, "kill-server"], env=env, capture_output=True)
    assert _run(env, "live", "--state", str(tmp_path), "--max", "1").returncode == 0
    assert [run for run, _ in _panes(tmux, env, "live")] == ["swarm", "run-a"]


def test_a_run_pane_closes_when_its_run_settles(
    panes: tuple[dict[str, str], list[str]], tmp_path: Path
) -> None:
    env, tmux = panes
    assert _run(env, "live", "--state", str(tmp_path)).returncode == 0
    pane = (
        subprocess.run(
            [*tmux, "list-panes", "-t", "swarm:live", "-F", "#{@run} #{pane_pid}"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.splitlines()[1]
        .split()
    )
    assert pane[0] == "run-a"
    subprocess.run(["pkill", "-P", pane[1]])
    subprocess.run(["kill", pane[1]])
    for _ in range(50):
        if "run-a" not in [run for run, _ in _panes(tmux, env, "live")]:
            break
        time.sleep(0.1)
    assert [run for run, _ in _panes(tmux, env, "live")] == ["swarm", "run-b"]


def test_replay_opens_one_pane_per_run_at_the_same_speed(
    panes: tuple[dict[str, str], list[str]],
) -> None:
    env, tmux = panes
    result = _run(env, "replay", "run-c", "run-a", "--", "--storage-host", "h")
    assert result.returncode == 0, result.stderr
    window = subprocess.run(
        [*tmux, "list-windows", "-t", "swarm", "-F", "#{window_name}"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[0]
    shown = _panes(tmux, env, window)
    assert [run for run, _ in shown] == ["run-c", "run-a"]
    for _, command in shown:
        assert "--replay" in command and "--speed '4'" in command
        assert "'--storage-host' 'h'" in command


def test_agent_replays_ended_runs_and_follows_the_running_one(
    panes: tuple[dict[str, str], list[str]], tmp_path: Path
) -> None:
    env, tmux = panes
    result = _run(env, "agent", "lin-1", "--state", str(tmp_path))
    assert result.returncode == 0, result.stderr
    shown = dict(_panes(tmux, env, "agent-lin-1"))
    assert set(shown) == {"run-a", "run-c"}
    assert "--run" in shown["run-a"]
    assert "--replay" in shown["run-c"]

    assert _run(env, "agent", "lin-9", "--state", str(tmp_path)).returncode == 1


@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        ("iTerm.app", "-L s -CC attach -t swarm"),
        ("Apple_Terminal", "-L s attach -t swarm"),
    ],
)
def test_attach_uses_control_mode_only_under_iterm(
    tmp_path: Path, terminal: str, expected: str
) -> None:
    fake = _script(tmp_path / "tmux", '#!/bin/sh\necho "$*"\n')
    env = {
        key: value for key, value in os.environ.items() if key not in {"LC_TERMINAL"}
    }
    env.update(PANES_TMUX=fake, PANES_SOCKET="s", TERM_PROGRAM=terminal)
    result = _run(env, "attach")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
