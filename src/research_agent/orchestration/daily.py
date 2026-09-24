"""Issue one UTC day: its papers, sheets, snapshot and run records (EN-09, AG-05).

``issue_day`` drives ``ingest/daily.py#run_once`` with the requested-paper
pass, the sheet seal and the snapshot seal bound to storage, then issues
the day's runs through the owners that already exist (decision 0027):

1. ``run_once`` lists, acquires and cards the day's papers, seals one
   sheet per island per chunk of up to twenty questions, and seals the
   day's snapshot after those sheets, pinned to each of them;
2. for each island, ``scheduler.draw_coverage_sample`` draws the papers
   its genomes read, keyed on the day and island, from the island's share
   of ``bindings.remaining_spend``, and the draw is published;
3. every sampled paper gets one run record per active genome of its
   island: the slot (``slots.build_slot``) names the sheet holding the
   paper's questions, the specification (``specifications``) fixes the
   seed, and the stamp (``stamps.build_run_stamp``) reads the paper's
   pinned card.

Every command carries a key fixed by its content, so a second call on the
same day replays the stored answers: it seals no second sheet or snapshot
and creates no second run, and reports what exists. No run starts here.

``main`` records the day's run ids in slot order (``scheduler.order_queue``:
earliest paper seal deadline, then slot) beside the day's window, and
``issued_runs`` reads them back for ``bin/bindings --runs`` (#317).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from psycopg import Connection

from research_agent.contracts import canonical_loads
from research_agent.contracts.learning import TargetDefinition
from research_agent.contracts.questions import sheet_identity, validate_sheet_payload
from research_agent.ingest.arxiv import ArxivListing
from research_agent.ingest.daily import (
    DailyRun,
    DailyWindow,
    DayPass,
    EligibleFamily,
    issue_questions,
    next_window,
    parse_pages,
    route_islands,
    run_once,
)
from research_agent.ingest.pilot import PilotWorker, derived_uuid
from research_agent.ingest.pilot_local import LocalStorage
from research_agent.ingest.requests import (
    AcquisitionReport,
    RequestReader,
    acquire_requests,
    listing_identities,
)
from research_agent.orchestration.bindings import (
    CostReader,
    RunBindings,
    remaining_spend,
)
from research_agent.orchestration.scheduler import (
    CoverageSample,
    QueuedSlot,
    draw_coverage_sample,
    order_queue,
)
from research_agent.orchestration.slots import Slot, build_slot
from research_agent.orchestration.specifications import build_run_specification
from research_agent.orchestration.stamps import build_run_stamp
from research_agent.evolution.population import PopulationStore
from research_agent.platform.profile import LaunchProfile
from research_agent.snapshots.compose import seal_next_snapshot
from research_agent.snapshots.documents import SnapshotDocuments
from research_agent.storage.client import (
    CommandResult,
    PaperRequestRecord,
    ResponseMetadata,
)
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput
from research_agent.storage.idempotency import StoredResponse
from research_agent.storage.requests import PaperRequestRepository
from research_agent.storage.runs import RunRepository
from research_agent.storage.settlements import SettlementRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository

__all__ = [
    "DayRepositories",
    "IssuedDay",
    "IssuedIsland",
    "LocalCosts",
    "LocalRequestLedger",
    "issue_day",
    "issued_runs",
    "record_runs",
]

#: The principal every command of the day's issue is recorded under.
OPERATOR = derived_uuid("daily-operator")
#: A question closes this long after its paper is first public (EN-13).
QUESTION_WINDOW = timedelta(hours=24)
_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _identity(*key: object) -> CommandIdentity:
    """One command's identity; the key replays a repeated command's answer."""

    fixed = derived_uuid("daily-command", *key)
    return CommandIdentity(OPERATOR, fixed, fixed, uuid4())


def _data(answer: StoredResponse) -> dict[str, Any]:
    body = cast(dict[str, Any], canonical_loads(answer.body))
    return cast(dict[str, Any], body["data"])


@dataclass(frozen=True, slots=True)
class DayRepositories:
    """The storage owners one day's issue writes through."""

    sheets: SheetRepository
    snapshots: SnapshotRepository
    runs: RunRepository
    population: PopulationStore
    documents: SnapshotDocuments


@dataclass(frozen=True, slots=True)
class IssuedIsland:
    """One island's draw and the runs issued on it."""

    sample: CoverageSample
    configurations: int
    remaining_spend_micros: int
    draw_manifest: str
    run_ids: tuple[str, ...]


def _run_id(slot: Slot) -> str:
    return str(derived_uuid("daily-run", *slot.to_dict().values()))


@dataclass(frozen=True, slots=True)
class IssuedDay:
    """What one day holds after ``issue_day``; ``created`` counts this call's
    new run records, so a repeated call reports zero. ``run_order`` is every
    run id in slot order, the order its runs are dispatched in."""

    daily: DailyRun
    islands: dict[str, IssuedIsland]
    created: int
    run_order: tuple[str, ...]

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(
            run_id for island in self.islands.values() for run_id in island.run_ids
        )


class LocalRequestLedger:
    """The ingest role's paper-request routes, answered by the operator's own
    storage owner in process, as ``ingest/pilot_local.py`` answers jobs."""

    def __init__(self, requests: PaperRequestRepository) -> None:
        self._requests = requests

    def list_open_paper_requests(self) -> tuple[PaperRequestRecord, ...]:
        return tuple(
            PaperRequestRecord(
                request_id=UUID(row["request_id"]),
                family_id=UUID(row["family_id"]),
                run_id=UUID(row["run_id"]),
                snapshot_hash=row["snapshot_hash"],
                requested_at=row["requested_at"],
                status=row["status"],
            )
            for row in self._requests.open_requests()
        )

    def transition_paper_request(
        self,
        *,
        paper_request_id: UUID,
        status: str,
        reason: str | None,
        paper_version_id: UUID | None,
        command_id: UUID,
        request_id: UUID,
        idempotency_key: UUID,
    ) -> CommandResult:
        answer = self._requests.execute(
            "transition",
            identity=CommandIdentity(OPERATOR, idempotency_key, command_id, request_id),
            payload={
                "request_id": str(paper_request_id),
                "status": status,
                "reason": reason,
                "paper_version_id": None
                if paper_version_id is None
                else str(paper_version_id),
            },
        )
        headers = (("x-replayed", "true"),) if answer.replayed else ()
        return CommandResult(
            str(request_id),
            _data(answer),
            ResponseMetadata(answer.status_code, headers, answer.body),
        )


@dataclass(frozen=True, slots=True)
class _CostRead:
    data: Mapping[str, Any]


class LocalCosts:
    """The owner cost read (#251), answered by the settlement owner in process."""

    def __init__(self, settlements: SettlementRepository) -> None:
        self._settlements = settlements

    def read_costs(self, day: str) -> _CostRead:
        return _CostRead(self._settlements.costs(day))


def _sheet_sealer(
    sheets: SheetRepository, sealed: dict[str, tuple[str, ...]]
) -> Callable[[tuple[dict[str, Any], ...]], str]:
    """Seal one sheet, keyed by its content hash; record its question ids."""

    def seal(questions: tuple[dict[str, Any], ...]) -> str:
        payload = {"questions": list(questions)}
        expected = sheet_identity(validate_sheet_payload("seal", payload)["questions"])
        answer = sheets.execute(
            "seal", identity=_identity("sheet", expected), payload=payload
        )
        sheet_hash = str(_data(answer)["sheet_hash"])
        sealed[sheet_hash] = tuple(q["question_id"] for q in questions)
        return sheet_hash

    return seal


def _read(database: Database, sql: str, parameters: tuple[object, ...]) -> list[Any]:
    def read(connection: Connection[tuple[object, ...]]) -> list[Any]:
        return connection.execute(sql, parameters).fetchall()

    return database.transaction(read)


def _snapshot_sealer(
    storage: LocalStorage,
    snapshots: SnapshotRepository,
    index_identity_hashes: tuple[str, ...],
) -> Callable[[tuple[dict[str, Any], ...], tuple[str, ...]], str]:
    """Seal the day's snapshot over the last one, once.

    A snapshot already pinned to every one of the day's sheets is the day's
    snapshot, and is returned rather than sealed again. Otherwise the prior
    snapshot is the latest one pinned to none of the day's sheets, and the
    day's items are composed onto its pinned items (decision 0025).
    """

    def seal(items: tuple[dict[str, Any], ...], sheet_hashes: tuple[str, ...]) -> str:
        sheets = [bytes.fromhex(sheet_hash) for sheet_hash in set(sheet_hashes)]
        existing = _read(
            storage.database,
            """SELECT encode(snapshot_hash,'hex') FROM snapshot_sheets
               WHERE sheet_hash = ANY(%s)
               GROUP BY snapshot_hash HAVING count(*) = %s""",
            (sheets, len(sheets)),
        )
        if existing:
            return str(existing[0][0])
        prior = _read(
            storage.database,
            """SELECT encode(s.hash,'hex') FROM snapshots s
               WHERE NOT EXISTS (
                   SELECT 1 FROM snapshot_sheets p
                   WHERE p.snapshot_hash = s.hash AND p.sheet_hash = ANY(%s))
               ORDER BY s.sealed_at DESC, s.hash LIMIT 1""",
            (sheets,),
        )
        prior_items = (
            []
            if not prior
            else [
                {
                    "paper_family_id": str(row[0]),
                    "paper_version_id": str(row[1]),
                    "card_hash": bytes(row[2]).hex(),
                    "overview_hash": None if row[3] is None else bytes(row[3]).hex(),
                    "passage_index_hash": None
                    if row[4] is None
                    else bytes(row[4]).hex(),
                    "graph_hash": None if row[5] is None else bytes(row[5]).hex(),
                }
                for row in _read(
                    storage.database,
                    """SELECT paper_family_id, paper_version_id, card_hash,
                              overview_hash, passage_index_hash, graph_hash
                       FROM snapshot_items WHERE snapshot_hash = decode(%s,'hex')
                       ORDER BY paper_version_id""",
                    (prior[0][0],),
                )
            ]
        )
        return seal_next_snapshot(
            snapshots,
            storage.publish_spec,
            principal_id=OPERATOR,
            prior_items=prior_items,
            acquired=items,
            index_identity_hashes=index_identity_hashes,
            sheet_hashes=sheet_hashes,
        )

    return seal


def _configuration_ids(database: Database, hashes: Sequence[str]) -> dict[str, str]:
    """Configuration hash -> the configuration id the genome was admitted under."""

    rows = _read(
        database,
        """SELECT encode(configuration_hash,'hex'), configuration_id::text
           FROM genomes WHERE configuration_hash = ANY(%s)""",
        ([bytes.fromhex(value) for value in hashes],),
    )
    return {str(row[0]): str(row[1]) for row in rows}


def _families(daily: DailyRun) -> tuple[EligibleFamily, ...]:
    return tuple(
        EligibleFamily(
            item["family_id"],
            item["first_public_at"],
            tuple(item["categories"]),
            None,
            item["primary_category"],
        )
        for item in daily.batch["eligible_families"]
    )


def _seal_deadline(first_public_at: str) -> str:
    opened = datetime.strptime(first_public_at, _INSTANT).replace(tzinfo=timezone.utc)
    return (opened + QUESTION_WINDOW).strftime(_INSTANT)


def coverage_seed(profile_hash: str) -> int:
    """Return the coverage draw's seed: the profile hash's first 60 bits.

    Fifteen hex digits always fit a signed int64, which the draw and the
    stored seed both require; sixteen overflow whenever the hash starts
    with 8 through f.
    """
    return int(profile_hash[:15], 16)


def issue_day(
    storage: LocalStorage,
    *,
    window: DailyWindow,
    worker: PilotWorker,
    reader: RequestReader,
    targets: tuple[TargetDefinition, ...],
    repositories: DayRepositories,
    index_identity_hashes: tuple[str, ...],
    bindings: RunBindings,
    profile: LaunchProfile,
    costs: CostReader,
    acquisition: Callable[[], AcquisitionReport] | None = None,
    mode: str = "study",
) -> IssuedDay:
    """Issue the day ``window.until_date`` names; safe to call again.

    The draw's seed is fixed by the profile hash, and each island's share of
    the day's remaining spend is in proportion to its carded papers that
    day. A day with no sealed snapshot, or an island with no active genome,
    issues no run.
    """

    day = window.until_date
    sealed: dict[str, tuple[str, ...]] = {}
    daily = run_once(
        storage,
        window=window,
        worker=worker,
        acquisition=acquisition,
        day=DayPass(reader, targets, _sheet_sealer(repositories.sheets, sealed)),
        seal_snapshot=_snapshot_sealer(
            storage, repositories.snapshots, index_identity_hashes
        ),
    )
    if daily.snapshot_hash is None or daily.cards is None:
        return IssuedDay(daily, {}, 0, ())
    snapshot_hash = daily.snapshot_hash
    cards = daily.cards.items
    carded = [family for family in _families(daily) if family.family_id in cards]
    sheet_of = {
        question_id: sheet_hash
        for sheet_hash, question_ids in sealed.items()
        for question_id in question_ids
    }
    profile_hash = profile.compute_hash()
    seed = coverage_seed(profile_hash)
    spend = remaining_spend(costs, profile, day)
    islands: dict[str, IssuedIsland] = {}
    queued: list[QueuedSlot] = []
    created = 0
    for island, members in sorted(route_islands(carded).items()):
        active, _archived = repositories.population.island_population(island)
        if not active:
            continue
        ids = _configuration_ids(
            storage.database, [genome.configuration_hash for genome in active]
        )
        genomes = sorted(
            (ids[genome.configuration_hash], genome.configuration_hash)
            for genome in active
        )
        share = spend * len(members) // len(carded)
        sample = draw_coverage_sample(
            utc_day=day,
            island=island,
            family_ids=[family.family_id for family in members],
            seed=seed,
            remaining_spend_micros=share,
            cost_per_run_micros=profile.run.spend_micros,
            configurations=len(genomes),
        )
        draw_manifest = storage.publish_spec(
            {
                "schema_version": 1,
                "kind": "daily_coverage_sample",
                "day": day,
                "island": island,
                "seed": sample.seed,
                "remaining_spend_micros": share,
                "cost_per_run_micros": profile.run.spend_micros,
                "configurations": len(genomes),
                "coverage": sample.coverage,
                "sampled_family_ids": list(sample.sampled_family_ids),
                "excluded_family_ids": list(sample.excluded_family_ids),
            }
        )
        by_id = {family.family_id: family for family in members}
        run_ids: list[str] = []
        for family_id in sample.sampled_family_ids:
            family = by_id[family_id]
            card = cards[family_id]
            (questions,) = issue_questions(day, island, [family], targets=targets)
            question_ids = [str(question["question_id"]) for question in questions]
            sheet_hash = sheet_of[question_ids[0]]
            seal_deadline = _seal_deadline(family.first_public_at)
            for configuration_id, genome_hash in genomes:
                slot = build_slot(sheet_hash, card["paper_family_id"], configuration_id)
                run_id = _run_id(slot)
                specification = build_run_specification(
                    run_id=run_id,
                    slot=slot,
                    genome_hash=genome_hash,
                    snapshot_hash=snapshot_hash,
                    budgets=bindings.budgets,
                    allowed_tools=bindings.allowed_tools,
                    profile_hash=profile_hash,
                    mode=mode,
                    model_manifest=bindings.agent_model_manifest,
                    service_manifests=bindings.service_image_versions,
                    question_seal_deadline=seal_deadline,
                )
                stamp = build_run_stamp(
                    repositories.documents,
                    genome_hash=genome_hash,
                    # runs.seed is a bigint: the stamp records the first 63
                    # of the specification seed's 64 bits.
                    seed=specification.specification_seed >> 1,
                    agent_model_manifest=bindings.agent_model_manifest,
                    service_image_versions=bindings.service_image_versions,
                    snapshot_hash=snapshot_hash,
                    paper_version_ids=(card["paper_version_id"],),
                )
                answer = repositories.runs.execute(
                    "create",
                    identity=_identity("run", run_id),
                    payload={
                        "run_id": run_id,
                        "slot": slot.to_dict(),
                        "genome_hash": genome_hash,
                        "seed": stamp.seed,
                        "snapshot_hash": snapshot_hash,
                        "budgets": dict(specification.budgets),
                        "allowed_tools": list(specification.allowed_tools),
                        "model_identity": stamp.model_identity(),
                        "checkpoint_dates": [],
                        "issued_question_ids": question_ids,
                    },
                )
                created += not answer.replayed
                run_ids.append(run_id)
                queued.append(QueuedSlot(slot, seal_deadline))
        islands[island] = IssuedIsland(
            sample, len(genomes), share, draw_manifest, tuple(run_ids)
        )
    return IssuedDay(
        daily,
        islands,
        created,
        tuple(_run_id(entry.slot) for entry in order_queue(queued)),
    )


def _day_window(state: Path, day: str, since: str | None) -> DailyWindow:
    """The window a day was first issued with, or the next one after the
    watermark ``ingest/daily.py#main`` keeps; a repeated day reuses its own."""

    days = state / "days"
    days.mkdir(parents=True, exist_ok=True)
    recorded = days / f"{day}.json"
    if recorded.exists():
        value = json.loads(recorded.read_text())
        return DailyWindow(value["from_date"], value["until_date"])
    watermark = state / "watermark.json"
    prior = (
        json.loads(watermark.read_text())["until_date"] if watermark.exists() else None
    )
    window = next_window(prior, today=day, since=since)
    recorded.write_text(
        json.dumps({"from_date": window.from_date, "until_date": window.until_date})
        + "\n"
    )
    return window


def record_runs(state: Path, day: str, run_order: Sequence[str]) -> None:
    """Record the day's run ids, in slot order, beside its window."""

    recorded = state / "days" / f"{day}.json"
    value = json.loads(recorded.read_text())
    value["run_ids"] = list(run_order)
    recorded.write_text(json.dumps(value) + "\n")


def issued_runs(state: Path, day: str) -> tuple[str, ...]:
    """The run ids ``bin/daily`` issued for *day*, in slot order.

    A day never issued, or one whose issue did not finish, refuses as
    ``day_not_issued:<day>`` rather than reading as a day without runs.
    """

    recorded = state / "days" / f"{day}.json"
    value = json.loads(recorded.read_text()) if recorded.exists() else {}
    if "run_ids" not in value:
        raise UnavailableInput(f"day_not_issued:{day}")
    return tuple(str(run_id) for run_id in value["run_ids"])


def main(argv: list[str] | None = None) -> int:
    from research_agent.ingest.daily import (
        _identity as ingest_identity,
        _jobs_by_stage,
        _listing_pages,
        _sources,
    )
    from research_agent.ingest.pilot_local import local_storage, worker_principal
    from research_agent.learning.release import _TARGET_META
    from research_agent.models.batch import (
        OffsetTokenizer,
        detect_platform,
        load_device_embedder,
    )
    from research_agent.outcomes.targets import definitions
    from research_agent.orchestration.bindings import (
        DailyInputs,
        current_bindings,
        parse_image,
    )
    from research_agent.storage.artifacts import ArtifactRepository
    from research_agent.storage.migrate import require_schema

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--bindings",
        type=Path,
        help="bin/bindings output, in place of the three flags that follow",
    )
    parser.add_argument("--agent-model-manifest")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="ROLE=SHA256",
        help="an observed service image digest; repeat once per role",
    )
    parser.add_argument(
        "--index-identity",
        action="append",
        default=[],
        metavar="SHA256",
        help="an index identity the day's snapshot freezes; repeat up to ten",
    )
    parser.add_argument("--day", help="UTC date to issue (default today)")
    parser.add_argument("--since", help="UTC date; required only for the first run")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args(argv)
    if args.bindings is not None:
        if args.agent_model_manifest or args.image or args.index_identity:
            parser.error(
                "--bindings replaces --agent-model-manifest, --image and "
                "--index-identity"
            )
        inputs = DailyInputs.from_dict(json.loads(args.bindings.read_text()))
    elif args.agent_model_manifest is None:
        parser.error("--bindings or --agent-model-manifest is required")
    else:
        inputs = DailyInputs(
            args.agent_model_manifest,
            tuple(parse_image(image) for image in args.image),
            tuple(args.index_identity),
        )
    database = Database(args.dsn)
    # Migrating is the operator's own step under the migrator's DSN; a day
    # runs under the runtime identity, which may not migrate (#352). A stale
    # schema refuses the day before its window is recorded.
    try:
        require_schema(database)
    except RuntimeError as error:
        print(f"{error}; apply migrations first", file=sys.stderr)
        return 1
    state: Path = args.state
    day = args.day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    window = _day_window(state, day, args.since)
    identity = ingest_identity(window)
    profile = LaunchProfile.from_json(args.profile.read_bytes())
    bindings = current_bindings(
        profile,
        agent_model_manifest_hash=inputs.agent_model_manifest,
        observed_images=inputs.observed_images,
    )
    embedder, backend = load_device_embedder(args.device, args.cache_dir)
    with local_storage(
        dsn=args.dsn,
        artifact_root=state / "artifacts",
        tls_directory=state / "tls",
        identity=identity,
    ) as storage:
        assert storage.store is not None
        keys: dict[str, Any] = {
            "producer": identity.producer,
            "config_hash": identity.config_hash,
            "retention_policy_hash": identity.retention_policy_hash,
        }
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(state / "tls"),
            identity=identity,
            sources=_sources(),
        )
        # Filled from every committed listing once the day's own listing
        # has run, before the requested-paper pass reads it.
        identities: dict[str, ArxivListing] = {}
        reader = RequestReader(
            storage,
            worker,
            identities=identities,
            work_dir=state / "work",
            namespace_dir=state / "index",
            embedder=embedder,
            tokenizer=OffsetTokenizer(backend.tokenizer),
            platform=detect_platform(args.device),
        )
        ledger = LocalRequestLedger(
            PaperRequestRepository(database, storage.store, **keys)
        )

        def acquisition() -> AcquisitionReport:
            listed = tuple(
                job["report_manifest"]
                for job in _jobs_by_stage(storage).get("listing", [])
                if job["state"] == "committed"
            )
            identities.update(
                listing_identities(parse_pages(_listing_pages(storage, listed)))
            )
            return acquire_requests(ledger, reader)

        issued = issue_day(
            storage,
            window=window,
            worker=worker,
            reader=reader,
            # The heads' own fixed definitions, so a question's target hash
            # is the one a qualified bundle was fitted and resolves against.
            targets=definitions(_TARGET_META),
            repositories=DayRepositories(
                SheetRepository(database, storage.store, **keys),
                SnapshotRepository(database, storage.store, **keys),
                RunRepository(database, storage.store, **keys),
                PopulationStore(database, storage.store, **keys),
                SnapshotDocuments(
                    database, ArtifactRepository(database, storage.store)
                ),
            ),
            index_identity_hashes=inputs.index_identity_hashes,
            bindings=bindings,
            profile=profile,
            costs=LocalCosts(SettlementRepository(database, storage.store, **keys)),
            acquisition=acquisition,
        )
    watermark = state / "watermark.json"
    prior = (
        json.loads(watermark.read_text())["until_date"] if watermark.exists() else ""
    )
    if window.until_date > prior:
        watermark.write_text(json.dumps({"until_date": window.until_date}) + "\n")
    record_runs(state, day, issued.run_order)
    print(
        json.dumps(
            {
                "day": day,
                "batch_manifest": issued.daily.batch_manifest,
                "sheet_hashes": list(issued.daily.sheet_hashes),
                "snapshot_hash": issued.daily.snapshot_hash,
                "islands": {
                    island: {
                        "coverage": item.sample.coverage,
                        "excluded": len(item.sample.excluded_family_ids),
                        "configurations": item.configurations,
                        "draw_manifest": item.draw_manifest,
                        "runs": len(item.run_ids),
                    }
                    for island, item in issued.islands.items()
                },
                "runs_created": issued.created,
                "runs": len(issued.run_ids),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
