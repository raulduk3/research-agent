"""Read-only owner-inspector queries over durable storage, exactly as stored.

Every raw read here returns stored records unchanged: no recomputation, no
field invented to fill a gap the underlying tables do not yet hold. An owner
view may aggregate in storage, counting or summing the stored records it
reads, but never derives a score from them. A genome comes from the
population store (#177) and a verdict from the latest stored resolution; no
scorer output is stored yet, so no method here returns a Brier contribution.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, cast

from psycopg import Connection

from research_agent.artifacts.store import ArtifactStore
from research_agent.contracts import canonical_loads
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput
from research_agent.storage.settlements import _TOTALS as SETTLEMENT_TOTALS
from research_agent.storage.settlements import _totals as settlement_totals
from research_agent.storage.settlements import validate_day

PAGE_SIZE = 50
MAXIMUM_MANIFEST_BYTES = 1024 * 1024

_REPRESENTATION_MANIFEST_FIELDS = frozenset(
    {
        "model_id",
        "revision",
        "checkpoint_date",
        "dtype",
        "dimension",
        "pooling",
        "document_prefix",
        "query_prefix",
        "max_model_tokens",
        "tokenizer_hash",
        "weight_hash",
        "qualified",
    }
)
_DEPLOYMENT_MANIFEST_FIELDS = frozenset(
    {"provider", "model_id", "endpoint", "revision", "qualified"}
)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )


# Each question on the earliest sealed sheet carrying it, with the number of
# sheets that carry it, and the latest resolution version of each forecast.
_OWNER_QUESTIONS = """WITH carried AS (
    SELECT DISTINCT ON (q.question_id)
           q.question_id, q.target_definition_hash, q.resolver_id,
           q.resolver_version, q.horizon
    FROM sheet_questions q JOIN sheets s ON s.hash = q.sheet_hash
    ORDER BY q.question_id, s.sealed_at, q.sheet_hash),
questions AS (
    SELECT c.*, (SELECT count(*) FROM sheet_questions o
                 WHERE o.question_id = c.question_id) AS sheets
    FROM carried c),
current_resolutions AS (
    SELECT DISTINCT ON (forecast_id)
           forecast_id, question_id, status, resolution_version, resolved_at
    FROM resolutions
    ORDER BY forecast_id, resolution_version DESC)
"""


def _question_definition(row: tuple[object, ...]) -> dict[str, Any]:
    return {
        "question_id": str(row[0]),
        "target_definition_hash": bytes(cast(bytes, row[1])).hex(),
        "resolver_id": row[2],
        "resolver_version": row[3],
        "horizon": _utc(cast(datetime, row[4])),
        "sheets": row[5],
    }


def _decode_json(value: object) -> Any:
    return canonical_loads(bytes(cast("bytes | memoryview", value)))


class InspectorQueries:
    """Owner-facing reads over runs, submissions and manifest artifacts."""

    def __init__(self, database: Database, store: ArtifactStore) -> None:
        self._database = database
        self._store = store

    def run(self, run_id: str) -> dict[str, Any] | None:
        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            row = connection.execute(
                """SELECT id, encode(batch_id,'hex'), paper_id, configuration_id,
                          attempt, encode(genome_hash,'hex'), seed,
                          encode(snapshot_hash,'hex'), budgets, allowed_tools,
                          model_identity, checkpoint_dates, created_at
                   FROM runs WHERE id=%s""",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            events = connection.execute(
                """SELECT attempt, ordinal, kind, encode(payload_hash,'hex'),
                          recorded_at
                   FROM run_events WHERE run_id=%s ORDER BY attempt, ordinal""",
                (run_id,),
            ).fetchall()
            return {
                **_run_fields(row),
                "events": [_event_fields(event) for event in events],
            }

        return self._database.transaction(read)

    def run_specification(self, run_id: str) -> dict[str, Any] | None:
        """What the tool service applies to a run's calls (#287, TDD-2.1.36).

        The run's snapshot hash, admitted tools, paper and issued question
        ids, exactly as its immutable specification stores them, and whether
        it is still active: a run holding a terminal state, submitted or
        void, is not.
        """

        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            row = connection.execute(
                """SELECT r.id, encode(r.snapshot_hash,'hex'), r.allowed_tools,
                          r.paper_id, r.issued_question_ids, t.state
                   FROM runs r
                   LEFT JOIN run_terminal_states t ON t.run_id = r.id
                   WHERE r.id=%s""",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "run_id": str(row[0]),
                "snapshot_hash": row[1],
                "allowed_tools": sorted(cast(list[str], row[2])),
                "paper_id": row[3],
                "issued_question_ids": sorted(
                    str(item) for item in cast(list[object], row[4])
                ),
                "active": row[5] is None,
            }

        return self._database.transaction(read)

    def run_worker(self, run_id: str) -> dict[str, Any] | None:
        """What a run worker loads to drive one run (#306).

        The run's slot, budgets, snapshot, admitted tools, paper and issued
        question ids exactly as its immutable specification stores them, and
        the four emphasis parts of the genome its configuration names (#322).
        A run whose configuration has no stored genome is unavailable, not
        promptless.
        """

        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            row = connection.execute(
                """SELECT r.id, r.configuration_id, r.attempt,
                          encode(r.genome_hash,'hex'), encode(r.snapshot_hash,'hex'),
                          r.budgets, r.allowed_tools, r.paper_id,
                          r.issued_question_ids, p.prompt, p.scan_policy,
                          p.read_policy, p.probability_assignment_rule
                   FROM runs r
                   LEFT JOIN LATERAL (
                     SELECT max(value) FILTER (WHERE part = 'prompt') AS prompt,
                            max(value) FILTER (WHERE part = 'scan_policy')
                              AS scan_policy,
                            max(value) FILTER (WHERE part = 'read_policy')
                              AS read_policy,
                            max(value) FILTER (
                              WHERE part = 'probability_assignment_rule'
                            ) AS probability_assignment_rule
                     FROM genome_parts
                     WHERE configuration_id = r.configuration_id
                   ) p ON true
                   WHERE r.id=%s""",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            if any(part is None for part in row[9:13]):
                raise UnavailableInput("run configuration has no stored genome")
            return {
                "run_id": str(row[0]),
                "configuration_id": str(row[1]),
                "attempt": row[2],
                "genome_hash": row[3],
                "snapshot_hash": row[4],
                "budgets": _decode_json(row[5]),
                "allowed_tools": sorted(cast(list[str], row[6])),
                "paper_id": row[7],
                "issued_question_ids": sorted(
                    str(item) for item in cast(list[object], row[8])
                ),
                "prompt": row[9],
                "scan_policy": row[10],
                "read_policy": row[11],
                "probability_assignment_rule": row[12],
            }

        return self._database.transaction(read)

    def snapshot(self, snapshot_hash: str) -> dict[str, Any] | None:
        """A sealed snapshot's description for a run's first message (#306).

        When it was sealed, how many paper families it pins and the sheets
        its pins were made for, exactly as stored.
        """

        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            row = connection.execute(
                """SELECT encode(s.hash,'hex'), s.sealed_at,
                          (SELECT count(DISTINCT i.paper_family_id)
                           FROM snapshot_items i WHERE i.snapshot_hash = s.hash),
                          ARRAY(SELECT encode(h.sheet_hash,'hex')
                                FROM snapshot_sheets h
                                WHERE h.snapshot_hash = s.hash
                                ORDER BY h.sheet_hash)
                   FROM snapshots s WHERE s.hash=decode(%s,'hex')""",
                (snapshot_hash,),
            ).fetchone()
            if row is None:
                return None
            return {
                "snapshot_hash": row[0],
                "sealed_at": _utc(cast(datetime, row[1])),
                "pinned_family_count": row[2],
                "sheet_hashes": list(cast(list[str], row[3])),
            }

        return self._database.transaction(read)

    def runs_by_configuration(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]:
        return self._runs_page("configuration_id=%s", configuration_id, cursor)

    def runs_by_batch(
        self, batch_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]:
        """Every run of one batch; a batch with no runs is an empty page."""

        return self._runs_page("batch_id=decode(%s,'hex')", batch_id, cursor)

    def runs_by_paper(
        self, paper_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]:
        """Every run that read one paper (decision 0022: one paper per run).

        ``runs.paper_id`` has no index of its own yet, so this is a scan of
        ``runs`` ordered by the created_at/id cursor.
        """

        return self._runs_page("paper_id=%s", paper_id, cursor)

    def _runs_page(
        self, condition: str, value: str, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]:
        before = (_parse_utc(cursor[0]), cursor[1]) if cursor is not None else None
        page_filter = "" if before is None else "AND (created_at, id) < (%s, %s)"
        arguments: tuple[object, ...] = (
            (value, PAGE_SIZE + 1)
            if before is None
            else (value, before[0], before[1], PAGE_SIZE + 1)
        )

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                f"""SELECT id, encode(batch_id,'hex'), paper_id, configuration_id,
                          attempt, encode(genome_hash,'hex'), seed,
                          encode(snapshot_hash,'hex'), budgets, allowed_tools,
                          model_identity, checkpoint_dates, created_at
                   FROM runs WHERE {condition} {page_filter}
                   ORDER BY created_at DESC, id DESC LIMIT %s""",
                arguments,
            ).fetchall()

        rows = self._database.transaction(read)
        page, has_more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
        next_cursor = None
        if has_more:
            last = page[-1]
            next_cursor = (_utc(cast(datetime, last[12])), str(last[0]))
        return tuple(_run_fields(row) for row in page), next_cursor

    def owner_paper(
        self, paper_id: str, *, cursor: tuple[str, str] | None
    ) -> dict[str, Any] | None:
        """Everything storage holds about one paper family, for the owner (#301).

        One page of the runs that read it, newest first, each with its model
        turns by hash, its ending and its sealed claims' latest verdicts; the
        paper requests naming the family, oldest first; and, for each
        snapshot a run on the page received, the card record that snapshot
        pins for the family, exactly as stored. ``None`` when no run, request
        or snapshot pin names the family.
        """

        before = (_parse_utc(cursor[0]), cursor[1]) if cursor is not None else None
        page_filter = "" if before is None else "AND (created_at, id) < (%s, %s)"
        arguments: tuple[object, ...] = (
            (paper_id, PAGE_SIZE + 1)
            if before is None
            else (paper_id, before[0], before[1], PAGE_SIZE + 1)
        )

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> dict[str, Any] | None:
            rows = connection.execute(
                f"""SELECT id, encode(batch_id,'hex'), paper_id, configuration_id,
                          attempt, encode(genome_hash,'hex'), seed,
                          encode(snapshot_hash,'hex'), budgets, allowed_tools,
                          model_identity, checkpoint_dates, created_at
                   FROM runs WHERE paper_id=%s {page_filter}
                   ORDER BY created_at DESC, id DESC LIMIT %s""",
                arguments,
            ).fetchall()
            requests = connection.execute(
                """SELECT id, run_id, encode(snapshot_hash,'hex'), status, reason,
                          requested_at, started_at, paper_version_id
                   FROM paper_requests WHERE family_id=%s
                   ORDER BY requested_at, id""",
                (paper_id,),
            ).fetchall()
            pinned = connection.execute(
                "SELECT 1 FROM snapshot_items WHERE paper_family_id=%s LIMIT 1",
                (paper_id,),
            ).fetchone()
            if not rows and not requests and pinned is None and before is None:
                return None
            page = [_owner_run(connection, row) for row in rows[:PAGE_SIZE]]
            pins = connection.execute(
                """SELECT encode(snapshot_hash,'hex'), paper_version_id,
                          encode(card_hash,'hex')
                   FROM snapshot_items
                   WHERE paper_family_id=%s AND snapshot_hash = ANY(%s)
                   ORDER BY snapshot_hash""",
                (
                    paper_id,
                    sorted({bytes.fromhex(run["snapshot_hash"]) for run in page}),
                ),
            ).fetchall()
            next_cursor = None
            if len(rows) > PAGE_SIZE:
                next_cursor = f"{page[-1]['created_at']},{page[-1]['run_id']}"
            return {
                "paper_id": paper_id,
                "runs": page,
                "next_cursor": next_cursor,
                "requests": [_request_fields(row) for row in requests],
                "cards": [
                    {
                        "snapshot_hash": pin[0],
                        "paper_version_id": str(pin[1]),
                        "card_hash": pin[2],
                    }
                    for pin in pins
                ],
            }

        found = self._database.transaction(read)
        if found is None:
            return None
        for pin in found["cards"]:
            pin["card"] = self._pinned_record(pin["card_hash"])
        return found

    def owner_run(self, run_id: str) -> dict[str, Any] | None:
        """One run as the owner's paper page shows it (#301): its stored
        specification, model turns by hash, ending and verdicts."""

        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            row = connection.execute(
                """SELECT id, encode(batch_id,'hex'), paper_id, configuration_id,
                          attempt, encode(genome_hash,'hex'), seed,
                          encode(snapshot_hash,'hex'), budgets, allowed_tools,
                          model_identity, checkpoint_dates, created_at
                   FROM runs WHERE id=%s""",
                (run_id,),
            ).fetchone()
            return None if row is None else _owner_run(connection, row)

        return self._database.transaction(read)

    def owner_runs(
        self,
        *,
        day: str | None,
        island: str | None,
        since: str | None,
        cursor: tuple[str, str] | None,
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]:
        """Runs created on one UTC day or on one island, oldest first (#326).

        Exactly one of *day* and *island* selects; *since* keeps runs created
        at or after that instant, and *cursor* the runs after it, so a reader
        following new runs asks again from the last run it saw. Each run is
        its stored record with its genome's ``lineage_id`` and ``island``,
        ``null`` for a configuration the population store does not hold.
        """

        if (day is None) == (island is None):
            raise ValueError("exactly one of day and island selects runs")
        conditions: list[str] = []
        arguments: list[object] = []
        if day is not None:
            start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            conditions.append("r.created_at >= %s AND r.created_at < %s")
            arguments += [start, start + timedelta(days=1)]
        else:
            conditions.append("g.island = %s")
            arguments.append(island)
        if since is not None:
            conditions.append("r.created_at >= %s")
            arguments.append(_parse_utc(since))
        if cursor is not None:
            conditions.append("(r.created_at, r.id) > (%s, %s)")
            arguments += [_parse_utc(cursor[0]), cursor[1]]
        arguments.append(PAGE_SIZE + 1)

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                f"""SELECT r.id, encode(r.batch_id,'hex'), r.paper_id,
                          r.configuration_id, r.attempt, encode(r.genome_hash,'hex'),
                          r.seed, encode(r.snapshot_hash,'hex'), r.budgets,
                          r.allowed_tools, r.model_identity, r.checkpoint_dates,
                          r.created_at, g.lineage_id, g.island
                   FROM runs r
                   LEFT JOIN genomes g ON g.configuration_id = r.configuration_id
                   WHERE {" AND ".join(conditions)}
                   ORDER BY r.created_at, r.id LIMIT %s""",
                tuple(arguments),
            ).fetchall()

        rows = self._database.transaction(read)
        page, has_more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
        next_cursor = None
        if has_more:
            last = page[-1]
            next_cursor = (_utc(cast(datetime, last[12])), str(last[0]))
        return (
            tuple(
                {**_run_fields(row), "lineage_id": row[13], "island": row[14]}
                for row in page
            ),
            next_cursor,
        )

    def owner_islands(self) -> tuple[dict[str, Any], ...]:
        """Each island the population store holds, by name (#344).

        Counts its genomes, founders and lineages, the runs of those genomes,
        and the creation instant of its latest run, ``null`` before any run.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                """SELECT g.island, count(*), count(*) FILTER (WHERE g.founder),
                          count(DISTINCT g.lineage_id),
                          coalesce(sum(r.runs), 0), max(r.last_run)
                   FROM genomes g
                   LEFT JOIN (SELECT configuration_id, count(*) AS runs,
                                     max(created_at) AS last_run
                              FROM runs GROUP BY configuration_id) r
                          ON r.configuration_id = g.configuration_id
                   GROUP BY g.island ORDER BY g.island"""
            ).fetchall()

        return tuple(
            {
                "island": row[0],
                "genomes": row[1],
                "founders": row[2],
                "lineages": row[3],
                "runs": int(cast(int, row[4])),
                "last_run_at": None if row[5] is None else _utc(cast(datetime, row[5])),
            }
            for row in self._database.transaction(read)
        )

    def owner_island(self, island: str) -> tuple[dict[str, Any], ...]:
        """Each genome the population store holds on one island (#344).

        Founders first, then by admission. Beside the stored genome fields it
        counts the genome's runs, its void runs, its settled runs with a
        priced cost and their summed cost in micro-dollars, and gives the
        creation instant of its latest run, ``null`` before any run. An
        island with no genome yields an empty tuple.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                """SELECT g.configuration_id, g.configuration_hash, g.lineage_id,
                          g.founder, g.admission, g.admitted_at,
                          count(r.id), count(t.run_id) FILTER (WHERE t.state = 'void'),
                          count(s.cost_micros), coalesce(sum(s.cost_micros), 0),
                          max(r.created_at)
                   FROM genomes g
                   LEFT JOIN runs r ON r.configuration_id = g.configuration_id
                   LEFT JOIN run_terminal_states t ON t.run_id = r.id
                   LEFT JOIN run_settlements s ON s.run_id = r.id
                   WHERE g.island = %s
                   GROUP BY g.configuration_id
                   ORDER BY g.founder DESC, g.admitted_at, g.configuration_id""",
                (island,),
            ).fetchall()

        return tuple(
            {
                "configuration_id": str(row[0]),
                "configuration_hash": bytes(cast(bytes, row[1])).hex(),
                "lineage_id": row[2],
                "founder": row[3],
                "admission": row[4],
                "admitted_at": _utc(cast(datetime, row[5])),
                "runs": row[6],
                "void_runs": row[7],
                "priced_runs": row[8],
                "cost_micros": int(cast(int, row[9])),
                "last_run_at": None
                if row[10] is None
                else _utc(cast(datetime, row[10])),
            }
            for row in self._database.transaction(read)
        )

    def owner_agents(self) -> tuple[dict[str, Any], ...]:
        """Each genome the population store holds, with its record counts (#344).

        By island, founders first, then by admission. Counts the genome's
        runs, its void runs, its settled runs with a priced cost and their
        summed cost in micro-dollars, the forecasts its runs recorded, and
        the preference credit rows that name it with their summed share. No
        agreement or skill figure is stored, so none is given.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                """SELECT g.configuration_id, g.configuration_hash, g.island,
                          g.lineage_id, g.founder, g.admission, g.admitted_at,
                          (SELECT count(*) FROM runs r
                           WHERE r.configuration_id = g.configuration_id),
                          (SELECT count(*) FROM runs r
                           JOIN run_terminal_states t ON t.run_id = r.id
                           WHERE r.configuration_id = g.configuration_id
                             AND t.state = 'void'),
                          (SELECT count(s.cost_micros) FROM runs r
                           JOIN run_settlements s ON s.run_id = r.id
                           WHERE r.configuration_id = g.configuration_id),
                          (SELECT coalesce(sum(s.cost_micros), 0) FROM runs r
                           JOIN run_settlements s ON s.run_id = r.id
                           WHERE r.configuration_id = g.configuration_id),
                          (SELECT count(*) FROM runs r
                           JOIN run_forecasts f ON f.run_id = r.id
                           WHERE r.configuration_id = g.configuration_id),
                          (SELECT count(*) FROM preference_credits p
                           WHERE p.genome_hash = g.configuration_hash),
                          (SELECT coalesce(sum(p.share), 0) FROM preference_credits p
                           WHERE p.genome_hash = g.configuration_hash),
                          (SELECT max(r.created_at) FROM runs r
                           WHERE r.configuration_id = g.configuration_id)
                   FROM genomes g
                   ORDER BY g.island, g.founder DESC, g.admitted_at,
                            g.configuration_id"""
            ).fetchall()

        return tuple(
            {
                "configuration_id": str(row[0]),
                "configuration_hash": bytes(cast(bytes, row[1])).hex(),
                "island": row[2],
                "lineage_id": row[3],
                "founder": row[4],
                "admission": row[5],
                "admitted_at": _utc(cast(datetime, row[6])),
                "runs": row[7],
                "void_runs": row[8],
                "priced_runs": row[9],
                "cost_micros": int(cast(int, row[10])),
                "forecasts": row[11],
                "credits": row[12],
                "credit_share": float(cast(float, row[13])),
                "last_run_at": None
                if row[14] is None
                else _utc(cast(datetime, row[14])),
            }
            for row in self._database.transaction(read)
        )

    def owner_agent_runs(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[dict[str, Any], tuple[str, str] | None] | None:
        """One genome's run endings and its runs per UTC day (#344).

        ``None`` when the population store holds no such genome. ``days``
        counts, per UTC day of run creation and newest first, the runs, those
        ended by submission, those ended void, and the settled runs with a
        priced cost and their summed cost in micro-dollars; it is complete on
        every page. ``runs`` pages the genome's runs newest first, each with
        its stored ending (``submitted``, ``void`` or ``null`` while open),
        void reason, end instant, settled cost and settlement instant. No
        duration is stored, so none is given.
        """

        before = (_parse_utc(cursor[0]), cursor[1]) if cursor is not None else None
        page_filter = "" if before is None else "AND (r.created_at, r.id) < (%s, %s)"
        arguments: tuple[object, ...] = (
            (configuration_id, PAGE_SIZE + 1)
            if before is None
            else (configuration_id, before[0], before[1], PAGE_SIZE + 1)
        )

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]] | None:
            if (
                connection.execute(
                    "SELECT 1 FROM genomes WHERE configuration_id=%s",
                    (configuration_id,),
                ).fetchone()
                is None
            ):
                return None
            days = connection.execute(
                """SELECT to_char(r.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
                          count(*), count(*) FILTER (WHERE t.state = 'submitted'),
                          count(*) FILTER (WHERE t.state = 'void'),
                          count(s.cost_micros), coalesce(sum(s.cost_micros), 0)
                   FROM runs r
                   LEFT JOIN run_terminal_states t ON t.run_id = r.id
                   LEFT JOIN run_settlements s ON s.run_id = r.id
                   WHERE r.configuration_id = %s
                   GROUP BY 1 ORDER BY 1 DESC""",
                (configuration_id,),
            ).fetchall()
            runs = connection.execute(
                f"""SELECT r.id, r.paper_id, r.attempt, r.created_at, t.state,
                          t.reason, t.ended_at, s.cost_micros, s.settled_at
                   FROM runs r
                   LEFT JOIN run_terminal_states t ON t.run_id = r.id
                   LEFT JOIN run_settlements s ON s.run_id = r.id
                   WHERE r.configuration_id = %s {page_filter}
                   ORDER BY r.created_at DESC, r.id DESC LIMIT %s""",
                arguments,
            ).fetchall()
            return days, runs

        found = self._database.transaction(read)
        if found is None:
            return None
        days, rows = found
        page, has_more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
        next_cursor = None
        if has_more:
            last = page[-1]
            next_cursor = (_utc(cast(datetime, last[3])), str(last[0]))
        return (
            {
                "days": [
                    {
                        "day": row[0],
                        "runs": row[1],
                        "submitted_runs": row[2],
                        "void_runs": row[3],
                        "priced_runs": row[4],
                        "cost_micros": int(cast(int, row[5])),
                    }
                    for row in days
                ],
                "runs": [
                    {
                        "run_id": str(row[0]),
                        "paper_id": row[1],
                        "attempt": row[2],
                        "created_at": _utc(cast(datetime, row[3])),
                        "ending": row[4],
                        "void_reason": row[5],
                        "ended_at": None
                        if row[6] is None
                        else _utc(cast(datetime, row[6])),
                        "cost_micros": row[7],
                        "settled_at": None
                        if row[8] is None
                        else _utc(cast(datetime, row[8])),
                    }
                    for row in page
                ],
            },
            next_cursor,
        )

    def owner_run_record(self, run_id: str) -> dict[str, Any] | None:
        """What storage holds about one run beyond its run record (#344).

        ``None`` when no such run is stored. Gives the island of the run's
        genome (``null`` when the population store holds no genome for it),
        the run's stored ending (``submitted``, ``void`` or ``null`` while
        open), void reason, end instant, settled cost and settlement instant,
        the trace calls per tool with the refused ones counted, and each digest
        entry its sealed claims were nominated to, with the digest's island
        and build instant and the stated preference.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> (
            tuple[
                tuple[object, ...], list[tuple[object, ...]], list[tuple[object, ...]]
            ]
            | None
        ):
            record = connection.execute(
                """SELECT g.island, t.state, t.reason, t.ended_at,
                          s.cost_micros, s.settled_at
                   FROM runs r
                   LEFT JOIN genomes g ON g.configuration_id = r.configuration_id
                   LEFT JOIN run_terminal_states t ON t.run_id = r.id
                   LEFT JOIN run_settlements s ON s.run_id = r.id
                   WHERE r.id = %s""",
                (run_id,),
            ).fetchone()
            if record is None:
                return None
            calls = connection.execute(
                """SELECT tool, count(*), count(*) FILTER (WHERE decision = 'refused')
                   FROM run_trace_calls WHERE run_id = %s
                   GROUP BY tool ORDER BY tool""",
                (run_id,),
            ).fetchall()
            nominations = connection.execute(
                """SELECT n.entry_id, d.hash, d.island, d.built_at, n.preference
                   FROM submissions s
                   JOIN digest_nominations n ON n.submission_id = s.id
                   JOIN digest_entries e ON e.entry_id = n.entry_id
                   JOIN digests d ON d.hash = e.digest_hash
                   WHERE s.submitter_id = %s
                   ORDER BY d.built_at, n.entry_id""",
                (run_id,),
            ).fetchall()
            return record, calls, nominations

        found = self._database.transaction(read)
        if found is None:
            return None
        record, calls, nominations = found
        return {
            "island": record[0],
            "ending": record[1],
            "void_reason": record[2],
            "ended_at": None if record[3] is None else _utc(cast(datetime, record[3])),
            "cost_micros": record[4],
            "settled_at": None
            if record[5] is None
            else _utc(cast(datetime, record[5])),
            "calls": [
                {"tool": row[0], "calls": row[1], "refused": row[2]} for row in calls
            ],
            "nominations": [
                {
                    "entry_id": str(row[0]),
                    "digest_hash": bytes(cast(bytes, row[1])).hex(),
                    "island": row[2],
                    "built_at": _utc(cast(datetime, row[3])),
                    "preference": row[4],
                }
                for row in nominations
            ],
        }

    def owner_reports(self) -> tuple[dict[str, Any], ...]:
        """Each island and ISO week with a digest built or a rating recorded
        in it (#344).

        Newest week first, then by island. A digest counts in the ISO week of
        its build instant and a rating in that of its record instant, both in
        UTC, which is also the week its preference credit rows carry. Counts
        the digests, their entries, the ratings, and the credit rows. The
        report itself is built on request; nothing here states its verdict.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                """WITH built AS (
                       SELECT d.island,
                              to_char(d.built_at AT TIME ZONE 'UTC', 'IYYY-"W"IW')
                                  AS iso_week,
                              count(DISTINCT d.hash) AS digests,
                              count(e.entry_id) AS entries
                       FROM digests d
                       LEFT JOIN digest_entries e ON e.digest_hash = d.hash
                       GROUP BY 1, 2),
                   rated AS (
                       SELECT d.island,
                              to_char(r.rated_at AT TIME ZONE 'UTC', 'IYYY-"W"IW')
                                  AS iso_week,
                              count(*) AS ratings
                       FROM ratings r
                       JOIN digest_entries e ON e.entry_id = r.digest_entry_id
                       JOIN digests d ON d.hash = e.digest_hash
                       GROUP BY 1, 2),
                   credited AS (
                       SELECT island, iso_week, count(*) AS credits
                       FROM preference_credits GROUP BY 1, 2)
                   SELECT island, iso_week, coalesce(b.digests, 0),
                          coalesce(b.entries, 0), coalesce(r.ratings, 0),
                          coalesce(c.credits, 0)
                   FROM built b
                   FULL JOIN rated r USING (island, iso_week)
                   LEFT JOIN credited c USING (island, iso_week)
                   ORDER BY iso_week DESC, island"""
            ).fetchall()

        return tuple(
            {
                "island": row[0],
                "iso_week": row[1],
                "digests": row[2],
                "entries": row[3],
                "ratings": row[4],
                "credits": row[5],
            }
            for row in self._database.transaction(read)
        )

    def owner_impact(self) -> tuple[dict[str, Any], ...]:
        """Each island and ISO week with a rating recorded in it, with what
        the ratings set in motion (#344).

        Newest week first, then by island. A rating counts in the ISO week of
        its record instant in UTC, the week its credit rows carry. Counts the
        ratings by value, the credit rows, the genomes they credit, and the
        ratings recorded as a credit gap. Every rater's ratings count: an owner
        session carries no rater id to narrow them by.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                """WITH rated AS (
                       SELECT r.id, r.value, d.island,
                              to_char(r.rated_at AT TIME ZONE 'UTC', 'IYYY-"W"IW')
                                  AS iso_week
                       FROM ratings r
                       JOIN digest_entries e ON e.entry_id = r.digest_entry_id
                       JOIN digests d ON d.hash = e.digest_hash)
                   SELECT r.island, r.iso_week, count(*),
                          count(*) FILTER (WHERE r.value = 'like'),
                          count(*) FILTER (WHERE r.value = 'dislike'),
                          count(*) FILTER (WHERE r.value = 'skip'),
                          (SELECT count(*) FROM preference_credits p
                           JOIN rated x ON x.id = p.rating_id
                           WHERE x.island = r.island AND x.iso_week = r.iso_week),
                          (SELECT count(DISTINCT p.genome_hash)
                           FROM preference_credits p
                           JOIN rated x ON x.id = p.rating_id
                           WHERE x.island = r.island AND x.iso_week = r.iso_week),
                          count(g.rating_id)
                   FROM rated r
                   LEFT JOIN preference_credit_gaps g ON g.rating_id = r.id
                   GROUP BY r.island, r.iso_week
                   ORDER BY r.iso_week DESC, r.island"""
            ).fetchall()

        return tuple(
            {
                "island": row[0],
                "iso_week": row[1],
                "ratings": row[2],
                "likes": row[3],
                "dislikes": row[4],
                "skips": row[5],
                "credits": row[6],
                "genomes_credited": row[7],
                "credit_gaps": row[8],
            }
            for row in self._database.transaction(read)
        )

    def owner_cost_days(self, day: str) -> tuple[dict[str, Any], ...]:
        """Settled spend of each UTC day and island in ``day``'s month up to
        and including ``day`` (#344).

        The window and the sums are those of the owner's cost read (#251):
        priced spend sums ``cost_micros``, and unpriced settlements are counted
        with their tokens, never priced. A run whose configuration has no
        genome sums under a null island. Only days with a settlement appear,
        oldest first, then by island.
        """

        start = datetime.combine(validate_day(day), time(), tzinfo=timezone.utc)
        end = start + timedelta(days=1)

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                f"""SELECT to_char(s.settled_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')
                              AS day,
                          g.island, {SETTLEMENT_TOTALS}
                   FROM run_settlements s
                   JOIN runs r ON r.id = s.run_id
                   LEFT JOIN genomes g ON g.configuration_id = r.configuration_id
                   WHERE s.settled_at >= %s AND s.settled_at < %s
                   GROUP BY day, g.island
                   ORDER BY day, g.island NULLS LAST""",
                (start.replace(day=1), end),
            ).fetchall()

        return tuple(
            {"day": row[0], "island": row[1], **settlement_totals(row[2:])}
            for row in self._database.transaction(read)
        )

    def owner_models(self) -> tuple[dict[str, Any], ...]:
        """Each agent model manifest a stored run pins, with its runs (#344).

        The manifest hash is the one a run record's model identity carries,
        which :meth:`manifest` resolves. Counts the runs pinning it and gives
        the creation instants of the first and the latest; newest first.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                """SELECT convert_from(model_identity, 'UTF8')::jsonb
                              ->> 'agent_model_manifest' AS manifest_hash,
                          count(*), min(created_at), max(created_at)
                   FROM runs
                   GROUP BY manifest_hash
                   ORDER BY max(created_at) DESC, manifest_hash"""
            ).fetchall()

        return tuple(
            {
                "manifest_hash": row[0],
                "runs": row[1],
                "first_run_at": _utc(cast(datetime, row[2])),
                "last_run_at": _utc(cast(datetime, row[3])),
            }
            for row in self._database.transaction(read)
        )

    def owner_questions(self) -> tuple[dict[str, Any], ...]:
        """Each question a sealed sheet holds, with its resolution state (#344).

        By horizon, then by id. The definition is the one on the earliest
        sealed sheet that carries the question. Counts the sheets carrying
        it, the runs that forecast it, the sealed submissions on it, and the
        current resolution of each resolved forecast by status, with the
        latest resolution instant, ``null`` before any.
        """

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                _OWNER_QUESTIONS
                + """SELECT q.question_id, q.target_definition_hash, q.resolver_id,
                            q.resolver_version, q.horizon, q.sheets,
                            (SELECT count(*) FROM run_forecasts f
                             WHERE f.question_id = q.question_id),
                            (SELECT count(*) FROM submissions s
                             WHERE s.question_id = q.question_id
                               AND s.status = 'sealed'),
                            count(c.status) FILTER (WHERE c.status = 'true'),
                            count(c.status) FILTER (WHERE c.status = 'false'),
                            count(c.status) FILTER (WHERE c.status = 'unresolvable'),
                            max(c.resolved_at)
                     FROM questions q
                     LEFT JOIN current_resolutions c ON c.question_id = q.question_id
                     GROUP BY q.question_id, q.target_definition_hash, q.resolver_id,
                              q.resolver_version, q.horizon, q.sheets
                     ORDER BY q.horizon, q.question_id"""
            ).fetchall()

        return tuple(
            {
                **_question_definition(row),
                "runs": row[6],
                "submissions": row[7],
                "resolved_true": row[8],
                "resolved_false": row[9],
                "unresolvable": row[10],
                "last_resolved_at": None
                if row[11] is None
                else _utc(cast(datetime, row[11])),
            }
            for row in self._database.transaction(read)
        )

    def owner_question(self, question_id: str) -> dict[str, Any] | None:
        """One question's definition, the runs that forecast it and the
        current resolution of each resolved forecast on it (#344).

        Runs by acceptance, resolutions by instant. ``None`` for a question
        no sealed sheet holds.
        """

        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            row = connection.execute(
                _OWNER_QUESTIONS
                + """SELECT question_id, target_definition_hash, resolver_id,
                            resolver_version, horizon, sheets
                     FROM questions WHERE question_id = %s""",
                (question_id,),
            ).fetchone()
            if row is None:
                return None
            runs = connection.execute(
                """SELECT f.run_id, r.configuration_id, f.probability, s.accepted_at
                   FROM run_forecasts f
                   JOIN run_submissions s ON s.run_id = f.run_id
                   JOIN runs r ON r.id = f.run_id
                   WHERE f.question_id = %s
                   ORDER BY s.accepted_at, f.run_id""",
                (question_id,),
            ).fetchall()
            resolutions = connection.execute(
                _OWNER_QUESTIONS
                + """SELECT forecast_id, status, resolution_version, resolved_at
                     FROM current_resolutions WHERE question_id = %s
                     ORDER BY resolved_at, forecast_id""",
                (question_id,),
            ).fetchall()
            return {
                **_question_definition(row),
                "runs": [
                    {
                        "run_id": str(run[0]),
                        "configuration_id": str(run[1]),
                        "probability": run[2],
                        "accepted_at": _utc(cast(datetime, run[3])),
                    }
                    for run in runs
                ],
                "resolutions": [
                    {
                        "forecast_id": str(resolution[0]),
                        "status": resolution[1],
                        "resolution_version": resolution[2],
                        "resolved_at": _utc(cast(datetime, resolution[3])),
                    }
                    for resolution in resolutions
                ],
            }

        return self._database.transaction(read)

    def run_settlement(self, run_id: str) -> dict[str, Any] | None:
        """The settlement of one run, exactly as stored (#326).

        ``None`` for a run storage does not hold or has not yet settled.
        """

        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            row = connection.execute(
                """SELECT run_id, provider, model, input_tokens, output_tokens,
                          usage_source, cost_micros, settled_at
                   FROM run_settlements WHERE run_id=%s""",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "run_id": str(row[0]),
                "provider": row[1],
                "model": row[2],
                "input_tokens": row[3],
                "output_tokens": row[4],
                "usage_source": row[5],
                "cost_micros": row[6],
                "settled_at": _utc(cast(datetime, row[7])),
            }

        return self._database.transaction(read)

    def _pinned_record(self, manifest_hash: str) -> Any:
        """The JSON record a pinned manifest hash names, as stored.

        A pin names the production-wrapped identity, resolved the way
        :meth:`manifest` resolves one; a pin whose record is tombstoned or
        missing is unavailable rather than skipped.
        """

        def check(connection: Connection[tuple[object, ...]]) -> str | None:
            row = connection.execute(
                """SELECT encode(p.artifact_hash,'hex')
                   FROM artifact_productions p
                   LEFT JOIN artifact_tombstones mt ON mt.artifact_hash = p.manifest_hash
                   LEFT JOIN artifact_tombstones at ON at.artifact_hash = p.artifact_hash
                   WHERE p.manifest_hash = decode(%s,'hex')
                     AND mt.artifact_hash IS NULL AND at.artifact_hash IS NULL""",
                (manifest_hash,),
            ).fetchone()
            return None if row is None else str(row[0])

        artifact_hash = self._database.transaction(check)
        if artifact_hash is None:
            raise UnavailableInput("a pinned card record is unavailable")
        with self._store.open_verified(artifact_hash) as stream:
            return canonical_loads(stream.read())

    def sheet(self, sheet_hash: str) -> dict[str, Any] | None:
        """A sealed sheet with its questions in sealed order."""

        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            sealed = connection.execute(
                "SELECT sealed_at FROM sheets WHERE hash=decode(%s,'hex')",
                (sheet_hash,),
            ).fetchone()
            if sealed is None:
                return None
            questions = connection.execute(
                """SELECT question_id, encode(target_definition_hash,'hex'),
                          resolver_id, resolver_version, horizon
                   FROM sheet_questions WHERE sheet_hash=decode(%s,'hex')
                   ORDER BY ordinal""",
                (sheet_hash,),
            ).fetchall()
            return {
                "sheet_hash": sheet_hash,
                "sealed_at": _utc(cast(datetime, sealed[0])),
                "questions": [
                    {
                        "question_id": str(row[0]),
                        "target_definition_hash": row[1],
                        "resolver_id": row[2],
                        "resolver_version": row[3],
                        "horizon": _utc(cast(datetime, row[4])),
                    }
                    for row in questions
                ],
            }

        return self._database.transaction(read)

    def configurations(
        self, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]:
        """The whole population, run or not, newest admission first."""

        before = (_parse_utc(cursor[0]), cursor[1]) if cursor is not None else None

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[dict[str, Any]]:
            if before is None:
                rows = connection.execute(
                    f"""{_GENOME_SELECT}
                        ORDER BY g.admitted_at DESC, g.configuration_id DESC
                        LIMIT %s""",
                    (PAGE_SIZE + 1,),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""{_GENOME_SELECT}
                        WHERE (g.admitted_at, g.configuration_id) < (%s, %s)
                        ORDER BY g.admitted_at DESC, g.configuration_id DESC
                        LIMIT %s""",
                    (before[0], before[1], PAGE_SIZE + 1),
                ).fetchall()
            return [_genome_fields(connection, row) for row in rows]

        genomes = self._database.transaction(read)
        page, has_more = genomes[:PAGE_SIZE], len(genomes) > PAGE_SIZE
        next_cursor = None
        if has_more:
            last = page[-1]
            next_cursor = (last["admitted_at"], last["configuration_id"])
        return tuple(page), next_cursor

    def configuration(self, configuration_id: str) -> dict[str, Any] | None:
        def read(connection: Connection[tuple[object, ...]]) -> dict[str, Any] | None:
            row = connection.execute(
                f"{_GENOME_SELECT} WHERE g.configuration_id=%s",
                (configuration_id,),
            ).fetchone()
            return None if row is None else _genome_fields(connection, row)

        return self._database.transaction(read)

    def forecasts_by_configuration(
        self, configuration_id: str, *, cursor: tuple[str, str] | None
    ) -> tuple[tuple[dict[str, Any], ...], tuple[str, str] | None]:
        """Sealed claims of the configuration's runs, each with its latest resolution.

        A claim with no resolution carries ``resolution: None``; its horizon
        says when one becomes eligible. Newest seal first.
        """

        before = (_parse_utc(cursor[0]), cursor[1]) if cursor is not None else None
        page_filter = "" if before is None else "AND (s.sealed_at, s.id) < (%s, %s)"
        arguments: tuple[object, ...] = (
            (configuration_id, PAGE_SIZE + 1)
            if before is None
            else (configuration_id, before[0], before[1], PAGE_SIZE + 1)
        )

        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[tuple[object, ...]]:
            return connection.execute(
                f"""SELECT s.id, r.id, s.question_id, s.confidence, s.horizon,
                          s.sealed_at, q.resolver_id, q.resolver_version,
                          z.id, z.status, z.resolver_id,
                          encode(z.resolver_build_digest,'hex'),
                          z.resolution_version, z.resolved_at
                   FROM submissions s
                   JOIN runs r ON r.id = s.submitter_id
                   JOIN sheet_questions q
                     ON q.sheet_hash = s.sheet_hash AND q.question_id = s.question_id
                   LEFT JOIN LATERAL (
                       SELECT id, status, resolver_id, resolver_build_digest,
                              resolution_version, resolved_at
                       FROM resolutions WHERE forecast_id = s.id
                       ORDER BY resolution_version DESC LIMIT 1
                   ) z ON true
                   WHERE r.configuration_id=%s AND s.status='sealed' {page_filter}
                   ORDER BY s.sealed_at DESC, s.id DESC LIMIT %s""",
                arguments,
            ).fetchall()

        rows = self._database.transaction(read)
        page, has_more = rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
        next_cursor = None
        if has_more:
            last = page[-1]
            next_cursor = (_utc(cast(datetime, last[5])), str(last[0]))
        return tuple(_forecast_fields(row) for row in page), next_cursor

    def submissions_by_submitter(self, submitter_id: str) -> tuple[dict[str, Any], ...]:
        def read(
            connection: Connection[tuple[object, ...]],
        ) -> list[dict[str, Any]]:
            rows = connection.execute(
                """SELECT id, encode(sheet_hash,'hex'), question_id, status,
                          confidence, horizon, reason, sealed_at
                   FROM submissions WHERE submitter_id=%s
                   ORDER BY sealed_at, id""",
                (submitter_id,),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                evidence = connection.execute(
                    """SELECT encode(evidence_hash,'hex')
                       FROM submission_evidence
                       WHERE submission_id=%s ORDER BY ordinal""",
                    (row[0],),
                ).fetchall()
                result.append(
                    {
                        "submission_id": str(row[0]),
                        "sheet_hash": row[1],
                        "question_id": str(row[2]),
                        "status": row[3],
                        "confidence": row[4],
                        "horizon": _utc(cast(datetime, row[5]))
                        if row[5] is not None
                        else None,
                        "reason": row[6],
                        "sealed_at": _utc(cast(datetime, row[7])),
                        "evidence_hashes": [item[0] for item in evidence],
                    }
                )
            return result

        return tuple(self._database.transaction(read))

    def manifest(self, manifest_hash: str) -> dict[str, Any] | None:
        """Resolve a manifest reference to the domain artifact it names.

        Every ``*_manifest``/``*_hash`` reference elsewhere in storage (a
        run's ``agent_model_manifest``, a snapshot's ``paper_manifest_hash``)
        names the production-wrapped identity in ``artifact_productions``,
        not a payload's own content hash; this resolves the same way before
        reading the payload it wraps.
        """

        def check(
            connection: Connection[tuple[object, ...]],
        ) -> tuple[str, str, int, datetime] | None:
            row = connection.execute(
                """SELECT encode(p.artifact_hash,'hex'), a.kind, a.media_type,
                          a.byte_length, a.created_at
                   FROM artifact_productions p
                   JOIN artifacts a ON a.hash = p.artifact_hash
                   LEFT JOIN artifact_tombstones mt ON mt.artifact_hash = p.manifest_hash
                   LEFT JOIN artifact_tombstones at ON at.artifact_hash = p.artifact_hash
                   WHERE p.manifest_hash = decode(%s,'hex')
                     AND mt.artifact_hash IS NULL AND at.artifact_hash IS NULL""",
                (manifest_hash,),
            ).fetchone()
            if row is None or row[1] != "manifest":
                return None
            return (
                cast(str, row[0]),
                cast(str, row[2]),
                cast(int, row[3]),
                cast(datetime, row[4]),
            )

        resolved = self._database.transaction(check)
        if resolved is None:
            return None
        artifact_hash, media_type, byte_length, created_at = resolved
        if byte_length > MAXIMUM_MANIFEST_BYTES:
            raise UnavailableInput(
                "manifest artifact exceeds the inspector's size bound"
            )
        with self._store.open_verified(artifact_hash) as stream:
            raw = stream.read()
        value = canonical_loads(raw)
        fields = value if isinstance(value, dict) else {}
        if set(fields) == _REPRESENTATION_MANIFEST_FIELDS:
            manifest_kind = "representation"
        elif set(fields) == _DEPLOYMENT_MANIFEST_FIELDS:
            manifest_kind = "deployment"
        else:
            manifest_kind = "unknown"
        return {
            "manifest_hash": manifest_hash,
            "artifact_hash": artifact_hash,
            "manifest_kind": manifest_kind,
            "media_type": media_type,
            "byte_length": byte_length,
            "created_at": _utc(created_at),
            "fields": fields,
        }


def _run_fields(row: tuple[object, ...]) -> dict[str, Any]:
    return {
        "run_id": str(row[0]),
        "batch_id": row[1],
        "paper_id": row[2],
        "configuration_id": str(row[3]),
        "attempt": row[4],
        "genome_hash": row[5],
        "seed": row[6],
        "snapshot_hash": row[7],
        "budgets": _decode_json(row[8]),
        "allowed_tools": list(cast(list[str], row[9])),
        "model_identity": _decode_json(row[10]),
        "checkpoint_dates": _decode_json(row[11]),
        "created_at": _utc(cast(datetime, row[12])),
    }


def _owner_run(
    connection: Connection[tuple[object, ...]], row: tuple[object, ...]
) -> dict[str, Any]:
    """A run with its model turns by hash, its ending and its verdicts (#301)."""

    run_id = row[0]
    events = connection.execute(
        """SELECT attempt, ordinal, kind, encode(payload_hash,'hex'), recorded_at
           FROM run_events WHERE run_id=%s ORDER BY attempt, ordinal""",
        (run_id,),
    ).fetchall()
    outcomes = connection.execute(
        """SELECT s.id, s.submitter_id, s.question_id, s.confidence, s.horizon,
                  s.sealed_at, q.resolver_id, q.resolver_version,
                  z.id, z.status, z.resolver_id,
                  encode(z.resolver_build_digest,'hex'),
                  z.resolution_version, z.resolved_at
           FROM submissions s
           JOIN sheet_questions q
             ON q.sheet_hash = s.sheet_hash AND q.question_id = s.question_id
           LEFT JOIN LATERAL (
               SELECT id, status, resolver_id, resolver_build_digest,
                      resolution_version, resolved_at
               FROM resolutions WHERE forecast_id = s.id
               ORDER BY resolution_version DESC LIMIT 1
           ) z ON true
           WHERE s.submitter_id=%s AND s.status='sealed'
           ORDER BY s.sealed_at, s.id""",
        (run_id,),
    ).fetchall()
    return {
        **_run_fields(row),
        "events": [_event_fields(event) for event in events],
        "ending": run_ending(connection, run_id),
        "outcomes": [_forecast_fields(outcome) for outcome in outcomes],
    }


def run_ending(
    connection: Connection[tuple[object, ...]], run_id: object
) -> dict[str, Any] | None:
    """How the run ended: its accepted submission, or void with its reason.
    The owner's run read and the live trace stream (#327) share it."""

    terminal = connection.execute(
        "SELECT state, reason, ended_at FROM run_terminal_states WHERE run_id=%s",
        (run_id,),
    ).fetchone()
    if terminal is None:
        return None
    submission: dict[str, Any] | None = None
    accepted = connection.execute(
        "SELECT submission_id, accepted_at FROM run_submissions WHERE run_id=%s",
        (run_id,),
    ).fetchone()
    if accepted is not None:
        forecasts = connection.execute(
            """SELECT f.question_id, f.probability, f.rationale,
                      ARRAY(SELECT encode(e.evidence_hash,'hex')
                            FROM run_forecast_evidence e
                            WHERE e.run_id = f.run_id AND e.question_id = f.question_id
                            ORDER BY e.ordinal)
               FROM run_forecasts f WHERE f.run_id=%s ORDER BY f.question_id""",
            (run_id,),
        ).fetchall()
        nomination = connection.execute(
            """SELECT paper_id, recommend, preference, rationale
               FROM run_nominations WHERE run_id=%s""",
            (run_id,),
        ).fetchone()
        submission = {
            "submission_id": str(accepted[0]),
            "accepted_at": _utc(cast(datetime, accepted[1])),
            "forecasts": [
                {
                    "question_id": str(forecast[0]),
                    "probability": forecast[1],
                    "rationale": forecast[2],
                    "evidence_ids": list(cast(list[str], forecast[3])),
                }
                for forecast in forecasts
            ],
            "nomination": None
            if nomination is None
            else {
                "paper_id": nomination[0],
                "recommend": nomination[1],
                "preference": nomination[2],
                "rationale": nomination[3],
            },
        }
    return {
        "state": terminal[0],
        "reason": terminal[1],
        "ended_at": _utc(cast(datetime, terminal[2])),
        "submission": submission,
    }


def _request_fields(row: tuple[object, ...]) -> dict[str, Any]:
    return {
        "request_id": str(row[0]),
        "run_id": str(row[1]),
        "snapshot_hash": row[2],
        "status": row[3],
        "reason": row[4],
        "requested_at": _utc(cast(datetime, row[5])),
        "started_at": None if row[6] is None else _utc(cast(datetime, row[6])),
        "paper_version_id": None if row[7] is None else str(row[7]),
    }


_GENOME_SELECT = """
    SELECT g.configuration_id, encode(g.configuration_hash,'hex'), g.lineage_id,
           g.island, g.founder, encode(g.infra_hash,'hex'),
           encode(g.parent_hash,'hex'), g.admission, encode(g.profile_hash,'hex'),
           g.admitted_at, a.cycle_id, a.skill, a.resolved_claim_count,
           encode(a.profile_hash,'hex'), a.archived_at
    FROM genomes g
    LEFT JOIN genome_archive a ON a.configuration_id = g.configuration_id
"""


def _genome_fields(
    connection: Connection[tuple[object, ...]], row: tuple[object, ...]
) -> dict[str, Any]:
    parts = connection.execute(
        """SELECT part, value, encode(value_hash,'hex') FROM genome_parts
           WHERE configuration_id=%s ORDER BY part""",
        (row[0],),
    ).fetchall()
    return {
        "configuration_id": str(row[0]),
        "configuration_hash": row[1],
        "lineage_id": row[2],
        "island": row[3],
        "founder": row[4],
        "infra_hash": row[5],
        "parent_hash": row[6],
        "parts": [
            {"part": part[0], "value": part[1], "value_hash": part[2]} for part in parts
        ],
        "admission": {
            "disposition": row[7],
            "profile_hash": row[8],
        },
        "admitted_at": _utc(cast(datetime, row[9])),
        "archive": None
        if row[10] is None
        else {
            "cycle_id": row[10],
            "skill": row[11],
            "resolved_claim_count": row[12],
            "profile_hash": row[13],
            "archived_at": _utc(cast(datetime, row[14])),
        },
    }


def _forecast_fields(row: tuple[object, ...]) -> dict[str, Any]:
    return {
        "submission_id": str(row[0]),
        "run_id": str(row[1]),
        "question_id": str(row[2]),
        "confidence": row[3],
        "horizon": _utc(cast(datetime, row[4])),
        "sealed_at": _utc(cast(datetime, row[5])),
        "resolver_id": row[6],
        "resolver_version": row[7],
        "resolution": None
        if row[8] is None
        else {
            "resolution_id": str(row[8]),
            "status": row[9],
            "resolver_id": row[10],
            "resolver_build_digest": row[11],
            "resolution_version": row[12],
            "resolved_at": _utc(cast(datetime, row[13])),
        },
    }


def _event_fields(row: tuple[object, ...]) -> dict[str, Any]:
    return {
        "attempt": row[0],
        "ordinal": row[1],
        "kind": row[2],
        "payload_hash": row[3],
        "recorded_at": _utc(cast(datetime, row[4])),
    }
