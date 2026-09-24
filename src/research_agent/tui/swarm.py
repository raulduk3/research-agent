"""A terminal dashboard of the population: the seats, the selected seat's
latest run as its trace lands, and the paper that run is reading.

Every read goes through the owner storage client and the trace poller of
``agents/tail.py``; nothing is stored. A cell no read provides stays empty.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import (
    Footer,
    Input,
    OptionList,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from research_agent.agents.tail import (
    OWNER_SCOPES,
    Line,
    RunFollower,
    Tail,
    TailStorage,
    resources_line,
)
from research_agent.storage.client import StorageClient

TRACE_SECONDS = 1.0
POPULATION_SECONDS = 10.0
_STYLES = {
    "start": "bold",
    "call": "",
    "result": "dim",
    "error": "red",
    "refused": "red",
    "void": "bold red",
    "submitted": "bold green",
    "forecast": "green",
    "settled": "dim",
    "resources": "dim",
}
_GLYPHS = {"running": "●", "idle": "○", "void": "✕", "done": "✓"}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass(slots=True)
class Seat:
    """One genome's lineage as the day's runs show it."""

    lineage_id: str
    island: str
    runs: list[str] = field(default_factory=list)
    configuration_id: str | None = None
    state: str = "idle"
    tool: str | None = None

    @property
    def latest(self) -> str | None:
        return self.runs[-1] if self.runs else None

    def label(self) -> Text:
        tool = f" {self.tool}" if self.state == "running" and self.tool else ""
        return Text.assemble(
            (_GLYPHS[self.state] + " ", "bold" if self.state == "running" else ""),
            f"{self.lineage_id:<14.14} {len(self.runs):>3} runs{tool}",
        )


class Population:
    """The seats of one UTC day, grouped by island, read by cursor pages."""

    def __init__(self, storage: TailStorage, day: str) -> None:
        self._storage = storage
        self._day = day
        self._cursor: tuple[str, str] | None = None
        self.seats: dict[str, Seat] = {}

    def refresh(self) -> None:
        while True:
            page = self._storage.list_owner_runs(
                day=self._day, cursor=self._cursor
            ).data
            for run in page["runs"]:
                seat = self.seats.setdefault(
                    run["lineage_id"], Seat(run["lineage_id"], run["island"])
                )
                seat.runs.append(run["run_id"])
                seat.configuration_id = run.get("configuration_id")
                self._cursor = (run["created_at"], run["run_id"])
            if page["next_cursor"] is None:
                return

    def islands(self) -> list[str]:
        return sorted({seat.island for seat in self.seats.values()})

    def ordered(self, text: str = "") -> list[Seat]:
        return sorted(
            (
                s
                for s in self.seats.values()
                if text in s.lineage_id or text in s.island
            ),
            key=lambda s: (s.island, s.lineage_id),
        )


def _state(lines: Sequence[Line]) -> tuple[str, str | None]:
    """The seat state and current tool its latest run's lines show."""

    state, tool = "running", None
    for line in lines:
        if line.kind == "call":
            tool = line.text.split(" ", 2)[1]
        elif line.kind in {"result", "error"}:
            tool = None
        elif line.kind == "void":
            state = "void"
        elif line.kind == "submitted":
            state = "done"
    return state, tool


class SwarmApp(App[None]):
    """One screen: Topology (seats, run, paper) and Feed on tabs."""

    CSS = """
    Screen { layout: vertical; }
    #topology Horizontal { height: 1fr; }
    #seats { width: 34; border-right: solid $accent; }
    #run { width: 1fr; }
    #paper { width: 36; border-left: solid $accent; padding: 0 1; }
    #filter { display: none; height: 1; border: none; }
    #filter.shown { display: block; }
    #status { height: 1; background: $accent 20%; }
    """
    BINDINGS = [
        Binding("j", "move(1)", "down"),
        Binding("k", "move(-1)", "up"),
        Binding("1", "island(0)", "island 1", show=False),
        Binding("2", "island(1)", "island 2", show=False),
        Binding("3", "island(2)", "island 3", show=False),
        Binding("slash", "filter", "filter"),
        Binding("enter", "expand", "payloads"),
        Binding("p", "pause", "pause"),
        Binding("o", "open", "paper url"),
        Binding("i", "resources", "resources"),
        Binding("tab", "next_tab", "view"),
        Binding("question_mark", "help", "keys"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(
        self,
        storage: TailStorage,
        *,
        day: str | None = None,
        front_end: str = "",
        live: bool = True,
    ) -> None:
        super().__init__()
        self._storage = storage
        self._front_end = front_end.rstrip("/")
        self._live = live
        self.population = Population(storage, day or _today())
        self._feed = Tail(storage, day=day or _today())
        self._filter = ""
        self._seat: Seat | None = None
        self._follower: RunFollower | None = None
        self._lines: list[Line] = []
        self._paper: str | None = None
        self.paused = False
        self.verbose = False

    def compose(self) -> ComposeResult:
        with TabbedContent(id="views"):
            with TabPane("Topology", id="topology"):
                yield Input(placeholder="lineage or island", id="filter")
                with Horizontal():
                    yield OptionList(id="seats")
                    yield RichLog(id="run", wrap=False, markup=False)
                    yield Static(id="paper")
            with TabPane("Feed", id="feed"):
                yield RichLog(id="feed-log", wrap=False, markup=False)
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_population()
        self.poll_trace()
        if self._live:
            self.set_interval(POPULATION_SECONDS, self.refresh_population)
            self.set_interval(TRACE_SECONDS, self.poll_trace)

    # reads

    def refresh_population(self) -> None:
        self.population.refresh()
        self._render_seats()

    def poll_trace(self) -> None:
        if self.paused:
            return
        feed = self.query_one("#feed-log", RichLog)
        for line in self._feed.poll():
            feed.write(self._text(line))
        if self._follower is not None and self._seat is not None:
            fresh = self._follower.poll(self._storage)
            self._lines.extend(fresh)
            self._seat.state, self._seat.tool = _state(self._lines)
            self.query_one("#seats", OptionList).replace_option_prompt(
                self._seat.lineage_id, self._seat.label()
            )
            log = self.query_one("#run", RichLog)
            for line in fresh:
                log.write(self._text(line))
        self._render_status()

    # rendering

    def _text(self, line: Line) -> Text:
        text = Text.assemble(
            (f"{line.at[11:19]} ", "dim"),
            (f"{line.kind:<9} ", _STYLES.get(line.kind, "")),
            line.text,
        )
        if self.verbose and line.payload is not None:
            text.append(f"\n    {line.payload}", "dim")
        return text

    def _render_seats(self) -> None:
        seats = self.query_one("#seats", OptionList)
        highlighted = self._seat.lineage_id if self._seat else None
        seats.clear_options()
        island = None
        index = None
        for seat in self.population.ordered(self._filter):
            if seat.island != island:
                island = seat.island
                seats.add_option(Option(Text(island, "bold"), disabled=True))
            seats.add_option(Option(seat.label(), id=seat.lineage_id))
            if seat.lineage_id == highlighted:
                index = seats.option_count - 1
        if index is None:
            index = next(
                (
                    i
                    for i in range(seats.option_count)
                    if not seats.get_option_at_index(i).disabled
                ),
                None,
            )
        seats.highlighted = index

    def _render_status(self) -> None:
        seats = list(self.population.seats.values())
        count = {s: sum(seat.state == s for seat in seats) for s in _GLYPHS}
        glyphs = " ".join(f"{_GLYPHS[s]} {count[s]}" for s in _GLYPHS)
        mode = "paused" if self.paused else "live"
        runs = sum(len(seat.runs) for seat in seats)
        self.query_one("#status", Static).update(
            f" {len(seats)} seats  {glyphs}  runs today {runs}  {mode}"
        )

    def _render_paper(self) -> None:
        pane = self.query_one("#paper", Static)
        if self._seat is None:
            pane.update("")
            return
        run = (
            self._storage.read_owner_run(UUID(self._seat.latest)).data
            if self._seat.latest
            else {}
        )
        configuration = run.get("configuration_id") or self._seat.configuration_id
        genome: dict[str, Any] | None = None
        if configuration is not None:
            genome = self._storage.read_genome_view(UUID(configuration))
        self._paper = run.get("paper_id")
        body = Text()
        body.append(f"{self._paper or '-'}\n", "bold")
        body.append(f"lineage {self._seat.lineage_id}\nisland  {self._seat.island}\n")
        if genome is not None:
            body.append(f"founder {'yes' if genome.get('founder') else 'no'}\n")
            for part, value in dict(genome.get("emphasis") or {}).items():
                body.append(f"{part}: {value}\n", "dim")
        pane.update(body)

    def select(self, lineage_id: str) -> None:
        seat = self.population.seats.get(lineage_id)
        if seat is None or seat is self._seat:
            return
        self._seat = seat
        self._lines = []
        self._follower = RunFollower(seat.latest) if seat.latest else None
        self.query_one("#run", RichLog).clear()
        self._render_paper()
        self.poll_trace()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option.id is not None:
            self.select(event.option.id)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._filter = event.value
        self._render_seats()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.input.remove_class("shown")
        self.query_one("#seats", OptionList).focus()

    # actions

    def action_move(self, step: int) -> None:
        seats = self.query_one("#seats", OptionList)
        (seats.action_cursor_down if step > 0 else seats.action_cursor_up)()

    def action_island(self, index: int) -> None:
        islands = self.population.islands()
        if index >= len(islands):
            return
        seats = self.query_one("#seats", OptionList)
        for i in range(seats.option_count):
            option = seats.get_option_at_index(i)
            if (
                option.id is not None
                and self.population.seats[option.id].island == islands[index]
            ):
                seats.highlighted = i
                return

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.add_class("shown")
        box.focus()

    def action_expand(self) -> None:
        self.verbose = not self.verbose
        log = self.query_one("#run", RichLog)
        log.clear()
        for line in self._lines:
            log.write(self._text(line))

    def action_pause(self) -> None:
        self.paused = not self.paused
        self._render_status()

    def action_open(self) -> None:
        if self._paper is not None:
            self.notify(f"{self._front_end}/owner/papers/{self._paper}")

    def action_resources(self) -> None:
        """The selected seat's latest run's resources, from its trace (#330)."""

        if self._seat is None or self._seat.latest is None:
            return
        run_id = self._seat.latest
        section = self._storage.read_run_trace(UUID(run_id)).data.get("resources")
        if section is None:
            self.notify(f"run {run_id[:8]} has no resources recorded yet")
            return
        line = resources_line(run_id, section)
        self.notify(f"{line.text}\n{line.payload}", title="resources", timeout=15)

    def action_next_tab(self) -> None:
        views = self.query_one("#views", TabbedContent)
        views.active = "feed" if views.active == "topology" else "topology"

    def action_help(self) -> None:
        self.notify(
            "  ".join(
                f"{b.key}: {b.description}"
                for b in self.BINDINGS
                if isinstance(b, Binding)
            ),
            timeout=8,
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    run: Callable[[SwarmApp], None] = SwarmApp.run,
) -> int:
    parser = argparse.ArgumentParser(description="The population, live.")
    parser.add_argument(
        "--day", help="the UTC day whose runs are shown (default today)"
    )
    parser.add_argument("--front-end", default="", help="base URL of the owner pages")
    for name in (
        "--storage-host",
        "--storage-server-name",
        "--ca-file",
        "--owner-cert",
        "--owner-key",
    ):
        parser.add_argument(name, required=True)
    parser.add_argument("--storage-port", type=int, required=True)
    args = parser.parse_args(argv)
    storage = StorageClient(
        connect_host=args.storage_host,
        port=args.storage_port,
        server_hostname=args.storage_server_name,
        ca_file=Path(args.ca_file),
        client_cert_file=Path(args.owner_cert),
        client_key_file=Path(args.owner_key),
        scopes=OWNER_SCOPES,
    )
    run(SwarmApp(storage, day=args.day, front_end=args.front_end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
