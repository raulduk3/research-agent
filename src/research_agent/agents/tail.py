"""Watch the swarm's trace in a terminal as it happens, or again later (#326).

An agent has no terminal: what it does is the trace the tool service records
in storage (#297, #308). This follows that trace through the owner's
``StorageClient``, one line per event: the run with its genome lineage,
paper and budgets; each tool call with its note and intent and its decision
or refusal reason; each call's result with the budgets left after it; the
run's accepted submission (each forecast's probability and one-line
rationale) or its void reason; and its settlement's tokens.

Following polls and sleeps between polls. The run listing is read from a
cursor at the last run seen; a run's trace is read whole, and a cursor at
the last call printed keeps each event to one line. A run is read no more
once it has settled. A replay prints a finished run from the same stored
records, in the same line format, spaced by the stored instants scaled by a
speed.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from research_agent.storage.client import QueryResult, StorageClient, StorageClientError

#: The budgets a tool call charges in its trace terminal (``tools/service.py``);
#: token and spend budgets are charged by model turns, which the trace does
#: not hold, so these are the budgets a call leaves (#301).
TRACE_BUDGETS: tuple[str, ...] = ("tool_calls", "deep_reads", "images")
TEXT_LIMIT = 160
OWNER_SCOPES = frozenset({"owner:read"})
_COLORS = {
    "start": "1",
    "call": "36",
    "refused": "31",
    "result": "32",
    "error": "31",
    "submitted": "1;32",
    "forecast": "32",
    "void": "1;31",
    "settled": "2",
}


class TailStorage(Protocol):
    """The owner reads a tail makes (``storage/client.py``)."""

    def read_owner_run(self, run_id: UUID) -> QueryResult: ...

    def read_run_trace(self, run_id: UUID) -> QueryResult: ...

    def read_run_settlement(self, run_id: UUID) -> QueryResult: ...

    def read_genome_view(self, configuration_id: UUID) -> dict[str, object] | None: ...

    def list_owner_runs(
        self,
        *,
        day: str | None = None,
        island: str | None = None,
        since: str | None = None,
        cursor: tuple[str, str] | None = None,
    ) -> QueryResult: ...


@dataclass(frozen=True, slots=True)
class Line:
    """One event of one run at its stored UTC instant."""

    at: str
    run_id: str
    kind: str
    text: str
    payload: str | None = None

    def render(self, *, color: bool = False, verbose: bool = False) -> str:
        kind = f"{self.kind:<9}"
        if color:
            kind = f"\x1b[{_COLORS[self.kind]}m{kind}\x1b[0m"
        rendered = f"{self.at[:23]}Z {self.run_id[:8]} {kind} {self.text}"
        if verbose and self.payload is not None:
            rendered += f"\n    {self.payload}"
        return rendered


def _one_line(value: object) -> str:
    text = " ".join(str(value).split())
    if len(text) > TEXT_LIMIT:
        text = text[: TEXT_LIMIT - 1] + "…"
    return json.dumps(text, ensure_ascii=False)


def _payload(payload: Mapping[str, Any] | None) -> str | None:
    """A stored payload as the text a person reads; bytes that are not UTF-8
    read as U+FFFD, and the exact bytes stay with the artifact it names."""

    if payload is None:
        return None
    text = base64.b64decode(payload["bytes"]).decode("utf-8", errors="replace")
    return f"{text} (truncated)" if payload["truncated"] else text


def _note_and_intent(request: Mapping[str, Any] | None) -> tuple[object, object]:
    """The note and intent of the ``{note, intent, arguments}`` envelope the
    run sent, which the stored request carries as its ``arguments`` (AG-39)."""

    text = _payload(request)
    if text is None:
        return None, None
    try:
        call = json.loads(text)
    except ValueError:
        return None, None
    envelope = call.get("arguments") if isinstance(call, dict) else None
    if not isinstance(envelope, dict):
        return None, None
    return envelope.get("note"), envelope.get("intent")


def _budgets(budgets: Mapping[str, int]) -> str:
    return " ".join(f"{name}={budgets[name]}" for name in TRACE_BUDGETS)


class RunFollower:
    """One run's events, each printed once, read again until it has settled.

    A call is printed when it is recorded and its result when that is; the
    ending once the run holds one; the settlement once the run has ended,
    every admitted call has its result and storage holds it.
    """

    def __init__(self, run_id: str, *, genome: Mapping[str, Any] | None = None) -> None:
        self.run_id = run_id
        self.done = False
        self._genome = genome
        self._started = False
        self._calls = 0
        self._results: set[int] = set()
        self._ended = False

    def poll(self, storage: TailStorage) -> list[Line]:
        if self.done:
            return []
        run_id = UUID(self.run_id)
        lines: list[Line] = []
        run = storage.read_owner_run(run_id).data
        if not self._started:
            lines.append(self._start(storage, run))
        calls = storage.read_run_trace(run_id).data["calls"]
        remaining = {name: int(run["budgets"][name]) for name in TRACE_BUDGETS}
        for call in calls:
            sequence = int(call["call_sequence"])
            terminal = call["terminal"]
            if terminal is not None:
                for name, spent in terminal["budget_deltas"].items():
                    if name in remaining:
                        remaining[name] -= int(spent)
            if sequence > self._calls:
                lines.append(self._call(call, remaining))
                self._calls = sequence
            if terminal is not None and sequence not in self._results:
                lines.append(self._result(call, terminal, remaining))
                self._results.add(sequence)
        ending = run["ending"]
        if ending is not None and not self._ended:
            lines.extend(self._ending(ending))
            self._ended = True
        pending = any(
            call["decision"] == "admitted" and call["terminal"] is None
            for call in calls
        )
        if self._ended and not pending:
            try:
                settlement = storage.read_run_settlement(run_id).data
            except StorageClientError as error:
                if error.status_code != 404:
                    raise
            else:
                lines.append(
                    Line(
                        settlement["settled_at"],
                        self.run_id,
                        "settled",
                        f"{settlement['provider']} {settlement['model']} "
                        f"input_tokens={settlement['input_tokens']} "
                        f"output_tokens={settlement['output_tokens']} "
                        f"usage={settlement['usage_source']}",
                    )
                )
                self.done = True
        return lines

    def _start(self, storage: TailStorage, run: Mapping[str, Any]) -> Line:
        if self._genome is None:
            self._genome = storage.read_genome_view(UUID(run["configuration_id"]))
        genome = self._genome or {}
        self._started = True
        return Line(
            run["created_at"],
            self.run_id,
            "start",
            f"run {self.run_id} paper={run['paper_id']} "
            f"lineage={genome.get('lineage_id') or '-'} "
            f"island={genome.get('island') or '-'} "
            f"budgets {_budgets(run['budgets'])}",
        )

    def _call(self, call: Mapping[str, Any], remaining: Mapping[str, int]) -> Line:
        note, intent = _note_and_intent(call["request"])
        text = (
            f"#{call['call_sequence']} {call['tool']} "
            f"note={_one_line(note) if note is not None else '-'} "
            f"intent={_one_line(intent) if intent is not None else '-'}"
        )
        if call["decision"] == "refused":
            return Line(
                call["started_at"],
                self.run_id,
                "refused",
                f"{text} reason={call['reason']} left {_budgets(remaining)}",
                _payload(call["request"]),
            )
        return Line(
            call["started_at"], self.run_id, "call", text, _payload(call["request"])
        )

    def _result(
        self,
        call: Mapping[str, Any],
        terminal: Mapping[str, Any],
        remaining: Mapping[str, int],
    ) -> Line:
        failed = terminal["outcome"] == "error"
        outcome = f"error={terminal['error_code']}" if failed else "response"
        return Line(
            terminal["ended_at"],
            self.run_id,
            "error" if failed else "result",
            f"#{call['call_sequence']} {call['tool']} {outcome} "
            f"retrieved={len(terminal['retrieved_ids'])} "
            f"left {_budgets(remaining)}",
            _payload(terminal["response"]),
        )

    def _ending(self, ending: Mapping[str, Any]) -> list[Line]:
        submission = ending["submission"]
        if submission is None:
            return [
                Line(
                    ending["ended_at"],
                    self.run_id,
                    "void",
                    f"reason={ending['reason']}",
                )
            ]
        forecasts = submission["forecasts"]
        return [
            Line(
                ending["ended_at"],
                self.run_id,
                "submitted",
                f"submission={submission['submission_id']} forecasts={len(forecasts)}",
            ),
            *(
                Line(
                    ending["ended_at"],
                    self.run_id,
                    "forecast",
                    f"question={forecast['question_id']} "
                    f"p={forecast['probability']:.2f} "
                    f"rationale={_one_line(forecast['rationale'])}",
                )
                for forecast in forecasts
            ),
        ]


class Tail:
    """Follow one run, or every run of a UTC day or an island as it appears."""

    def __init__(
        self,
        storage: TailStorage,
        *,
        run_id: str | None = None,
        day: str | None = None,
        island: str | None = None,
        since: str | None = None,
    ) -> None:
        if sum(value is not None for value in (run_id, day, island)) != 1:
            raise ValueError("exactly one of run, day and island is followed")
        self._storage = storage
        self._day, self._island, self._since = day, island, since
        self._cursor: tuple[str, str] | None = None
        self._followers: list[RunFollower] = []
        self._single = run_id is not None
        if run_id is not None:
            self._followers.append(RunFollower(run_id))

    @property
    def finished(self) -> bool:
        """A followed run has settled; a day or an island is never finished."""

        return self._single and all(follower.done for follower in self._followers)

    def poll(self) -> list[Line]:
        """The events recorded since the last poll, in stored-instant order."""

        if not self._single:
            self._discover()
        lines: list[Line] = []
        for follower in self._followers:
            lines.extend(follower.poll(self._storage))
        self._followers = [
            follower
            for follower in self._followers
            if not follower.done or self._single
        ]
        return sorted(
            (
                line
                for line in lines
                if self._since is None or line.kind == "start" or line.at >= self._since
            ),
            key=lambda line: line.at,
        )

    def _discover(self) -> None:
        while True:
            page = self._storage.list_owner_runs(
                day=self._day,
                island=self._island,
                since=self._since,
                cursor=self._cursor,
            ).data
            for run in page["runs"]:
                self._followers.append(
                    RunFollower(
                        run["run_id"],
                        genome={
                            "lineage_id": run["lineage_id"],
                            "island": run["island"],
                        },
                    )
                )
                self._cursor = (run["created_at"], run["run_id"])
            if page["next_cursor"] is None:
                return


def follow(
    tail: Tail,
    *,
    interval_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[Line]:
    """Every event as it is recorded, polling every *interval_seconds*."""

    while True:
        yield from tail.poll()
        if tail.finished:
            return
        sleep(interval_seconds)


class RunNotEnded(Exception):
    """A replay names a run that holds no ending yet."""


def replay(
    storage: TailStorage,
    run_id: str,
    *,
    speed: float | None,
    since: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[Line]:
    """A finished run's events in their stored order, spaced by the stored
    instants divided by *speed*; ``None`` prints them without waiting."""

    if storage.read_owner_run(UUID(run_id)).data["ending"] is None:
        raise RunNotEnded("the run has not ended; follow it with --run")
    tail = Tail(storage, run_id=run_id, since=since)
    previous: datetime | None = None
    for line in tail.poll():
        at = _instant(line.at)
        if speed is not None and previous is not None and at > previous:
            sleep((at - previous).total_seconds() / speed)
        previous = at
        yield line


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


def _utc_instant(value: str) -> str:
    """A ``--since`` value in the stored instant form."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("--since must be an ISO instant") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _positive(value: str) -> float:
    number = float(value)
    if not number > 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(
    argv: Sequence[str] | None = None,
    *,
    storage: TailStorage | None = None,
    out: Any = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(
        description="Print the swarm's trace, one line per event."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run", type=UUID, help="follow one run until it settles")
    target.add_argument("--day", help="follow every run created on a UTC day")
    target.add_argument("--island", help="follow every run of an island's genomes")
    target.add_argument("--replay", type=UUID, help="print a finished run again")
    parser.add_argument(
        "--since", type=_utc_instant, help="only events at or after this instant"
    )
    pace = parser.add_mutually_exclusive_group()
    pace.add_argument("--speed", type=_positive, default=1.0)
    pace.add_argument("--instant", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="print payloads")
    parser.add_argument("--interval", type=_positive, default=2.0)
    parser.add_argument("--storage-host")
    parser.add_argument("--storage-port", type=int)
    parser.add_argument("--storage-server-name")
    parser.add_argument("--ca-file")
    parser.add_argument("--owner-cert")
    parser.add_argument("--owner-key")
    args = parser.parse_args(argv)

    if storage is None:
        missing = [
            name
            for name in (
                "storage_host",
                "storage_port",
                "storage_server_name",
                "ca_file",
                "owner_cert",
                "owner_key",
            )
            if getattr(args, name) is None
        ]
        if missing:
            parser.error(
                "required: " + ", ".join("--" + n.replace("_", "-") for n in missing)
            )
        storage = StorageClient(
            connect_host=args.storage_host,
            port=args.storage_port,
            server_hostname=args.storage_server_name,
            ca_file=Path(args.ca_file),
            client_cert_file=Path(args.owner_cert),
            client_key_file=Path(args.owner_key),
            scopes=OWNER_SCOPES,
        )
    out = out if out is not None else sys.stdout
    color = bool(getattr(out, "isatty", lambda: False)())
    if args.replay is not None:
        lines = replay(
            storage,
            str(args.replay),
            speed=None if args.instant else args.speed,
            since=args.since,
            sleep=sleep,
        )
    else:
        lines = follow(
            Tail(
                storage,
                run_id=None if args.run is None else str(args.run),
                day=args.day,
                island=args.island,
                since=args.since,
            ),
            interval_seconds=args.interval,
            sleep=sleep,
        )
    try:
        for line in lines:
            print(line.render(color=color, verbose=args.verbose), file=out, flush=True)
    except RunNotEnded as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    except StorageClientError as error:
        print(f"storage: {error.code}: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
