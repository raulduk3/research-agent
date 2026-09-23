"""Daily arXiv ingest job for the pilot harness.

Lists new cs.AI and cs.LG submissions since the last watermark, admits a
family when its listed categories intersect the configured corpus
categories and records its primary category (decision 0016; the OAI listing
itself still covers the two sets this job is reviewed for), enqueues
document acquisition through the existing pilot harness, records per-paper
publication and arrival lateness and daily coverage, and publishes the
day's parent batch record. Explicit opt-in: nothing runs unless invoked.
Every invocation resumes entirely from storage and the local watermark
file, so a killed run starts again from the last committed listing page and
never refetches or reseals a day already built.
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from research_agent.contracts import canonical_json
from research_agent.contracts.primitives import ProducerVersion, validate_utc_date
from research_agent.ingest.arxiv import (
    MINIMUM_INTERVAL_SECONDS,
    TARGET_CATEGORIES,
    TARGET_SETS,
    ArxivListing,
    fetch_document,
    fetch_listing_page,
    parse_listing_page,
)
from research_agent.ingest.coverage import DailyCoverage, build_daily_coverage
from research_agent.ingest.fetch import FetchedOpenAlexPage
from research_agent.ingest.pilot import Identity, PilotWorker, RateGate, Sources
from research_agent.ingest.pilot_local import (
    LocalStorage,
    local_storage,
    worker_principal,
)
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate

BATCH_SCHEMA_VERSION = 2
_ROOT = Path(__file__).resolve().parents[3]
_ACCESS_RULES = _ROOT / "docs" / "evidence" / "source-pilot" / "access-rules.md"
_RETENTION = (
    b"Daily ingest originals and listing responses are retained privately for "
    b"this research; each paper's license is recorded and nothing is redistributed."
)
_LISTING_ATTEMPTS = 3
# The configured corpus category list decision 0016 names as eligible_families'
# own default: cs.AI, cs.LG, quant-ph and q-bio. Widening the OAI listing
# itself to the two new sets is a separate, not-yet-reviewed change (it would
# also change this job's request and job counts), so `advance` below still
# lists only TARGET_SETS; a family in a category this job never lists cannot
# be admitted regardless of this default.
CORPUS_CATEGORIES: tuple[str, ...] = ("cs.AI", "cs.LG", "quant-ph", "q-bio")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class DailyWindow:
    """A closed OAI listing window: [from_date, until_date]."""

    from_date: str
    until_date: str


def next_window(
    prior_until_date: str | None, *, today: str, since: str | None = None
) -> DailyWindow:
    """The window for one day's incremental pull.

    arXiv datestamps are last-modified dates, so harvesting from the day
    after the last watermark through today picks up every record touched
    since the last run, exactly once. The first run has no watermark and
    must be given an explicit starting date.
    """
    end = validate_utc_date(today)
    if prior_until_date is None:
        if since is None:
            raise ValueError("no watermark yet; an explicit starting date is required")
        start = validate_utc_date(since)
    else:
        start = (
            date.fromisoformat(validate_utc_date(prior_until_date)) + timedelta(days=1)
        ).isoformat()
    if start > end:
        raise ValueError("watermark is not before today")
    return DailyWindow(start, end)


#: Island routing (AG-36, TDD-3.1.13): a family's primary category selects
#: the one island of the population that reads it. ``TARGET_CATEGORIES``
#: only admits the cs.AI/cs.LG categories into the corpus today (#65 adds
#: quant-ph and q-bio); this mapping is complete for all three regardless,
#: so routing does not silently misclassify once that admission widens.
_ISLAND_PREFIXES: tuple[tuple[str, str], ...] = (
    ("cs.", "cs"),
    ("quant-ph", "quant-ph"),
    ("q-bio", "q-bio"),
)


def island_for_category(category: str) -> str:
    """The island one primary arXiv category routes to (AG-36).

    Raises ``ValueError`` for a category outside the three island prefixes;
    a corpus category the routing table does not cover is a defect to fix,
    not a family to route arbitrarily.
    """

    for prefix, island in _ISLAND_PREFIXES:
        if category.startswith(prefix):
            return island
    raise ValueError(f"category {category!r} does not route to an admitted island")


@dataclass(frozen=True, slots=True)
class EligibleFamily:
    family_id: str
    first_public_at: str
    categories: tuple[str, ...]
    license_url: str | None
    primary_category: str

    @property
    def island(self) -> str:
        return island_for_category(self.primary_category)


def parse_pages(pages: Iterable[bytes]) -> tuple[ArxivListing, ...]:
    """Every record from a run's stored listing pages, in page order."""
    records: list[ArxivListing] = []
    for raw in pages:
        records.extend(parse_listing_page(raw).records)
    return tuple(records)


def eligible_families(
    records: Iterable[ArxivListing], *, categories: Iterable[str] = CORPUS_CATEGORIES
) -> tuple[EligibleFamily, ...]:
    """In-category, non-legacy families, sorted by first_public_at then family
    id; a family cross-listed across target sets is merged once and keeps the
    primary category of the record it was first admitted from (arXiv lists a
    paper's own category first; decision 0016 admits by primary category).

    ``primary_category`` is fixed from the first record this function ever
    sees for a family and never overwritten by a later cross-listed
    record, so a family's island (AG-36) is derived once and does not
    depend on listing page order.
    """
    target_categories = frozenset(categories)
    merged: dict[str, EligibleFamily] = {}
    for item in records:
        if item.legacy_identifier or target_categories.isdisjoint(item.categories):
            continue
        existing = merged.get(item.family_id)
        if existing is None:
            merged[item.family_id] = EligibleFamily(
                item.family_id,
                item.first_public_at,
                item.categories,
                item.license_url,
                item.categories[0],
            )
        else:
            merged[item.family_id] = EligibleFamily(
                existing.family_id,
                existing.first_public_at,
                tuple(sorted(set(existing.categories) | set(item.categories))),
                existing.license_url
                if existing.license_url is not None
                else item.license_url,
                existing.primary_category,
            )
    return tuple(
        sorted(
            merged.values(),
            key=lambda family: (family.first_public_at, family.family_id),
        )
    )


def route_islands(
    families: Sequence[EligibleFamily],
) -> dict[str, tuple[EligibleFamily, ...]]:
    """Route eligible families to the island of their primary category (TDD-3.1.13).

    Within each island, families keep the first_public_at-then-family_id
    order :func:`eligible_families` already sorted them in; a paper never
    mixes two islands. Islands with no eligible family today are simply
    absent from the result rather than present with an empty tuple.
    """

    routed: dict[str, list[EligibleFamily]] = {}
    for family in families:
        routed.setdefault(family.island, []).append(family)
    return {island: tuple(members) for island, members in routed.items()}


@dataclass(frozen=True, slots=True)
class LatenessRecord:
    family_id: str
    first_public_at: str
    observed_at: str
    lateness_seconds: float


def lateness_records(
    families: Iterable[EligibleFamily], *, observed_at: str
) -> tuple[LatenessRecord, ...]:
    """Arrival lateness: how long after first publication ingest observed it."""
    observed = datetime.strptime(observed_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    records = []
    for family in families:
        published = datetime.fromisoformat(
            family.first_public_at.replace("Z", "+00:00")
        )
        records.append(
            LatenessRecord(
                family.family_id,
                family.first_public_at,
                observed_at,
                (observed - published).total_seconds(),
            )
        )
    return tuple(records)


def batch_record(
    *,
    day: str,
    categories: tuple[str, ...],
    families: tuple[EligibleFamily, ...],
    lateness: tuple[LatenessRecord, ...],
    listing_report_manifests: tuple[str, ...],
) -> dict[str, Any]:
    """The daily parent batch record: one per day, eligible families sorted."""
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "kind": "daily_ingest_batch",
        "day": day,
        "categories": sorted(categories),
        "listing_report_manifests": sorted(listing_report_manifests),
        "eligible_families": [
            {
                "family_id": family.family_id,
                "first_public_at": family.first_public_at,
                "categories": list(family.categories),
                "primary_category": family.primary_category,
                "island": family.island,
            }
            for family in families
        ],
        "lateness": [
            {
                "family_id": record.family_id,
                "first_public_at": record.first_public_at,
                "observed_at": record.observed_at,
                "lateness_seconds": record.lateness_seconds,
            }
            for record in lateness
        ],
    }


def _listing_pages(
    storage: LocalStorage, report_manifests: tuple[str, ...]
) -> list[bytes]:
    """The raw retained bytes of every page behind a set of committed listing
    job reports, read directly by the operator without a job lease."""
    if not report_manifests:
        return []
    rows = storage.database.transaction(
        lambda connection: connection.execute(
            """SELECT encode(ap.artifact_hash,'hex')
               FROM artifact_production_edges e
               JOIN artifact_productions ap ON ap.manifest_hash = e.input_hash
               JOIN artifacts a ON a.hash = ap.artifact_hash
               WHERE e.manifest_hash = ANY(%s)
                 AND a.kind = 'source_response' AND a.media_type = 'text/plain'
               ORDER BY e.manifest_hash, e.ordinal""",
            ([bytes.fromhex(manifest) for manifest in report_manifests],),
        ).fetchall()
    )
    pages: list[bytes] = []
    for (hash_hex,) in rows:
        (_, _), stream = storage.artifacts.read(str(hash_hex))
        with stream:
            pages.append(stream.read())
    return pages


def _jobs_by_stage(storage: LocalStorage) -> dict[str, list[dict[str, Any]]]:
    """Every capture job this operator drives, grouped by its spec stage."""
    rows = storage.database.transaction(
        lambda connection: connection.execute(
            """SELECT j.id, j.state, encode(j.input_manifest_hash,'hex'),
                      encode(o.artifact_hash,'hex'), j.terminal_at
               FROM jobs j LEFT JOIN job_outputs o ON o.job_id=j.id
               ORDER BY j.scheduled_at, j.id"""
        ).fetchall()
    )
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for job_id, state, manifest, output, terminal_at in rows:
        spec = storage.report(str(manifest))
        stage = spec.get("stage")
        if not isinstance(stage, str):
            continue
        by_stage.setdefault(stage, []).append(
            {
                "id": str(job_id),
                "state": str(state),
                "spec": spec,
                "report_manifest": None if output is None else str(output),
                "report": None if output is None else storage.report(str(output)),
                "terminal_at": terminal_at,
            }
        )
    return by_stage


def advance(storage: LocalStorage, window: DailyWindow) -> bool:
    """Enqueue whatever this window newly allows; True if work was added."""
    by_stage = _jobs_by_stage(storage)
    listings = [
        job
        for job in by_stage.get("listing", [])
        if job["spec"].get("from_date") == window.from_date
        and job["spec"].get("until_date") == window.until_date
    ]
    added = False
    for set_spec in TARGET_SETS:
        attempts = [job for job in listings if job["spec"]["set_spec"] == set_spec]
        if attempts and any(job["state"] != "failed" for job in attempts):
            continue
        if len(attempts) >= _LISTING_ATTEMPTS:
            raise RuntimeError(f"listing {set_spec} failed {len(attempts)} times")
        storage.enqueue(
            {
                "stage": "listing",
                "set_spec": set_spec,
                "from_date": window.from_date,
                "until_date": window.until_date,
                "attempt": len(attempts) + 1,
            }
        )
        added = True
    committed = [job for job in listings if job["state"] == "committed"]
    if added or len({job["spec"]["set_spec"] for job in committed}) < len(TARGET_SETS):
        return added
    report_manifests = tuple(sorted(job["report_manifest"] for job in committed))
    families = eligible_families(parse_pages(_listing_pages(storage, report_manifests)))
    done = {job["spec"]["family"]["family_id"] for job in by_stage.get("documents", [])}
    for family in families:
        if family.family_id in done:
            continue
        storage.enqueue(
            {
                "stage": "documents",
                "family": {
                    "family_id": family.family_id,
                    "license_url": family.license_url,
                },
            },
            report_manifests,
        )
        added = True
    return added


def _skip_reasons(
    records: tuple[ArxivListing, ...], families: tuple[EligibleFamily, ...]
) -> tuple[tuple[str, str], ...]:
    """One reason per listed family this run did not admit."""
    admitted = {family.family_id for family in families}
    reasons: dict[str, str] = {}
    for item in records:
        if item.family_id in admitted or item.family_id in reasons:
            continue
        reasons[item.family_id] = (
            "legacy_identifier" if item.legacy_identifier else "category_excluded"
        )
    return tuple(sorted(reasons.items()))


def _document_status(by_stage: dict[str, list[dict[str, Any]]], family_id: str) -> str:
    """This run's own fetch outcome for one admitted family's original source."""
    jobs = [
        job
        for job in by_stage.get("documents", [])
        if job["spec"].get("family", {}).get("family_id") == family_id
    ]
    committed = [job for job in jobs if job["state"] == "committed"]
    if committed:
        outcome = committed[-1]["report"] or {}
        return "present" if outcome.get("src") == "retained" else "error"
    if any(job["state"] == "failed" for job in jobs):
        return "error"
    return "missing"


@dataclass(frozen=True, slots=True)
class DailyRun:
    window: DailyWindow
    batch: dict[str, Any]
    batch_manifest: str
    coverage: DailyCoverage
    wall_seconds: float
    peak_rss: int
    papers_listed: int
    bytes_fetched: int


def run_once(
    storage: LocalStorage, *, window: DailyWindow, worker: PilotWorker
) -> DailyRun:
    """Drive listing and document acquisition to completion, then seal the
    day's batch record; safe to call again for an already-sealed day."""
    started = time.monotonic()
    while True:
        added = advance(storage, window)
        completed = worker.run().jobs_completed
        if completed == 0 and not added:
            break
    by_stage = _jobs_by_stage(storage)
    listings = [
        job
        for job in by_stage.get("listing", [])
        if job["spec"].get("from_date") == window.from_date
        and job["spec"].get("until_date") == window.until_date
        and job["state"] == "committed"
    ]
    report_manifests = tuple(sorted(job["report_manifest"] for job in listings))
    pages = _listing_pages(storage, report_manifests)
    records = parse_pages(pages)
    families = eligible_families(records)
    # The moment listing was captured and committed, not wall-clock "now": a
    # reseal of an already-sealed day must reproduce the identical batch.
    observed_at = (
        max(job["terminal_at"] for job in listings)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )
    lateness = lateness_records(families, observed_at=observed_at)
    record = batch_record(
        day=window.until_date,
        categories=tuple(sorted(TARGET_CATEGORIES)),
        families=families,
        lateness=lateness,
        listing_report_manifests=report_manifests,
    )
    storage.publish_spec(record, report_manifests)
    # The batch's identity is the record's own content hash, not the
    # publication event's manifest hash, so a reseal reports the same id.
    manifest = sha256(canonical_json(record)).hexdigest()
    admitted_ids = tuple(family.family_id for family in families)
    coverage = build_daily_coverage(
        day=window.until_date,
        listed=len(records),
        admitted_family_ids=admitted_ids,
        skipped=_skip_reasons(records, families),
        source_status={
            family_id: _document_status(by_stage, family_id)
            for family_id in admitted_ids
        },
        text_status={},
        figure_status={},
        bibliography_status={},
    )
    return DailyRun(
        window,
        record,
        manifest,
        coverage,
        round(time.monotonic() - started, 3),
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        len(records),
        sum(len(page) for page in pages),
    )


def _commit() -> str:
    return subprocess.run(
        ("git", "-C", str(_ROOT), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _identity(window: DailyWindow) -> Identity:
    # No container image runs this local job; the image digest names that fact.
    producer = ProducerVersion(sha256(b"local-process").hexdigest(), _commit(), 1)
    config = {
        "from_date": window.from_date,
        "until_date": window.until_date,
        "categories": sorted(TARGET_CATEGORIES),
        "arxiv_interval_seconds": MINIMUM_INTERVAL_SECONDS,
        "sets": list(TARGET_SETS),
    }
    return Identity(
        producer,
        sha256(canonical_json(config)).hexdigest(),
        sha256(_RETENTION).hexdigest(),
        sha256(_ACCESS_RULES.read_bytes()).hexdigest(),
    )


def _no_citations(*_args: object, **_kwargs: object) -> FetchedOpenAlexPage:
    raise NotImplementedError("the daily ingest job does not capture citations")


def _sources() -> Sources:
    return Sources(
        listing=fetch_listing_page,
        document=fetch_document,
        openalex_match=_no_citations,
        openalex_cites=_no_citations,
        arxiv_gate=RateGate(MINIMUM_INTERVAL_SECONDS),
        openalex_gate=RateGate(MINIMUM_INTERVAL_SECONDS),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument(
        "--dsn", required=True, help="DSN selecting a daily-ingest schema"
    )
    parser.add_argument("--since", help="UTC date; required only for the first run")
    parser.add_argument("--today", help="UTC date to treat as today (testing only)")
    args = parser.parse_args(argv)
    state: Path = args.state
    state.mkdir(parents=True, exist_ok=True)
    watermark_file = state / "watermark.json"
    prior = (
        json.loads(watermark_file.read_text())["until_date"]
        if watermark_file.exists()
        else None
    )
    today = args.today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    window = next_window(prior, today=today, since=args.since)
    identity = _identity(window)
    migrate(Database(args.dsn))
    with local_storage(
        dsn=args.dsn,
        artifact_root=state / "artifacts",
        tls_directory=state / "tls",
        identity=identity,
    ) as storage:
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(state / "tls"),
            identity=identity,
            sources=_sources(),
        )
        run = run_once(storage, window=window, worker=worker)
    watermark_file.write_text(json.dumps({"until_date": window.until_date}) + "\n")
    demand = {
        "ended_at": utc_now(),
        "window": {"from_date": window.from_date, "until_date": window.until_date},
        "wall_seconds": run.wall_seconds,
        # macOS reports bytes, Linux kibibytes.
        "peak_rss": run.peak_rss,
        "papers_listed": run.papers_listed,
        "bytes_fetched": run.bytes_fetched,
        "eligible_families": len(run.batch["eligible_families"]),
        "batch_manifest": run.batch_manifest,
        "coverage": {
            "listed": run.coverage.listed,
            "admitted": len(run.coverage.admitted),
            "skipped": len(run.coverage.skipped),
            "source_present": run.coverage.source.present,
            "source_missing": run.coverage.source.missing,
            "source_error": run.coverage.source.error,
            "audit_state": run.coverage.audit_state,
        },
    }
    with (state / "runs.jsonl").open("a") as runs:
        runs.write(json.dumps(demand) + "\n")
    print(json.dumps(demand))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
