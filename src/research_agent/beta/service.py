"""The running swarm: the operations the API, the heartbeat and the CLI share.

The swarm moves in two ways. An ingestion pass brings in current papers and
assigns them. An advance lets every idle agent take its next paper. Both are
bounded by the budget plan, and both can be started by the process itself on
an interval, so a deployed swarm keeps reading without anyone starting runs.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from research_agent.beta.budget import BudgetState, budget_state
from research_agent.beta.config import BetaConfig
from research_agent.beta.db import Clock, Json, connect, migrate
from research_agent.beta.evolution import maybe_run_evolution
from research_agent.beta.ingest import Fetcher, PaperFetcher, run_ingestion_pass
from research_agent.beta.models import ModelClient
from research_agent.beta.papers import recover_failed_decisions
from research_agent.beta.runs import advance_swarm, execute_run, sweep_interrupted_runs
from research_agent.beta.spec import current_spec, ensure_seed
from research_agent.beta.text import TextFetcher


@dataclass
class Swarm:
    config: BetaConfig
    client: ModelClient | None
    clock: Clock
    fetch: Fetcher
    fetch_paper: PaperFetcher | None = None
    sleep: Callable[[float], None] = time.sleep
    #: Reads a paper's full text; ``None`` keeps papers to their abstracts.
    fetch_text: TextFetcher | None = None
    _last_advance: float = field(default=0.0, repr=False)

    def prepare(self) -> None:
        """Bring the store to the current schema, seed the spec, close stale runs."""
        migrate(self.config.database)
        with connect(self.config.database) as db:
            now = self.clock()
            ensure_seed(db, now)
            sweep_interrupted_runs(db, now)
            _, spec = current_spec(db)
            recover_failed_decisions(db, spec, now)

    def state(self) -> tuple[int, Json, BudgetState]:
        with connect(self.config.database) as db:
            revision, spec = current_spec(db)
            budget = budget_state(
                db, spec, self.clock(), self.config.provider is not None
            )
        return revision, spec, budget

    def execute(self, run_ids: Sequence[str]) -> None:
        """Carry queued runs to their end, then let evolution act on the results."""
        provider = self.config.provider
        if provider is None or self.client is None:
            return
        for run_id in run_ids:
            execute_run(
                self.config.database,
                run_id,
                client=self.client,
                provider=provider,
                clock=self.clock,
                fetch_paper=self.fetch_paper,
                fetch_text=self.fetch_text,
            )
        if run_ids:
            self.evolve()

    def evolve(self, island_id: str | None = None, force: bool = False) -> list[Json]:
        """Run an evolution cycle on every island where one is due."""
        generations: list[Json] = []
        with connect(self.config.database) as db:
            _, spec = current_spec(db)
            for island in spec["islands"]:
                if island_id is not None and island["id"] != island_id:
                    continue
                record = maybe_run_evolution(
                    db,
                    island["id"],
                    self.clock(),
                    force,
                    provider=self.config.provider,
                    client=self.client,
                )
                if record is not None:
                    generations.append(record)
        return generations

    def advance(self) -> Json:
        """Let idle agents take their next papers; return who started and who waits."""
        with connect(self.config.database) as db:
            revision, spec = current_spec(db)
            return advance_swarm(
                db,
                spec=spec,
                revision=revision,
                provider=self.config.provider,
                clock=self.clock,
            )

    def ingest(
        self,
        categories: Sequence[str] | None = None,
        limit: int | None = None,
        advance: bool | None = None,
    ) -> Json:
        """Run one ingestion pass, then advance the swarm when the levers say to."""
        with connect(self.config.database) as db:
            _, spec = current_spec(db)
            budget = budget_state(
                db, spec, self.clock(), self.config.provider is not None
            )
            summary = run_ingestion_pass(
                db,
                spec,
                budget.plan,
                fetch=self.fetch,
                clock=self.clock,
                categories=categories,
                limit=limit,
                delay_seconds=self.config.arxiv_delay_seconds,
                sleep=self.sleep,
                fetch_text=self.fetch_text,
                prune_after_days=budget.levers.unread_paper_days,
            )
        wanted = budget.levers.auto_run_on_ingest if advance is None else advance
        summary["advance"] = (
            self.advance() if wanted else {"started": [], "waiting": []}
        )
        return summary

    def _ingest_due(self, now: datetime) -> bool:
        if not self.config.ingest_seconds:
            return False
        with connect(self.config.database) as db:
            row = db.execute("SELECT MAX(started_at) FROM ingest_passes").fetchone()
        if row[0] is None:
            return True
        last = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=now.tzinfo
        )
        return (now - last).total_seconds() >= self.config.ingest_seconds

    def heartbeat(self) -> None:
        """One beat of the self-driving swarm: ingest when due, advance when due."""
        if self._ingest_due(self.clock()):
            summary = self.ingest()
            self._last_advance = time.monotonic()
            self.execute([item["run_id"] for item in summary["advance"]["started"]])
            return
        tick = self.config.tick_seconds
        if tick and time.monotonic() - self._last_advance >= tick:
            self._last_advance = time.monotonic()
            self.execute([item["run_id"] for item in self.advance()["started"]])
