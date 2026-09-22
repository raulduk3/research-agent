"""Operator for the source acquisition harness: stages, caps and measurements.

Explicit opt-in: nothing runs unless invoked. The operator provisions a local
storage service, enqueues each stage's capture jobs once its prerequisites
have committed, runs the worker, and reports what was requested and retained.
It resumes from storage state on every invocation. Omitted selection
parameters (population rule, cap, seed, per-month stratification) reproduce
the 100-family pilot exactly; a corpus release passes its own values.
"""

from __future__ import annotations

import argparse
import json
import resource
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from research_agent.contracts import RecordMeta, canonical_json
from research_agent.contracts.papers import SourceAccess
from research_agent.contracts.primitives import ProducerVersion, validate_utc_instant
from research_agent.ingest.arxiv import (
    MINIMUM_INTERVAL_SECONDS,
    fetch_document,
    fetch_listing_page,
    listing_window,
    target_sets,
)
from research_agent.ingest.fetch import (
    FetchedOpenAlexPage,
    fetch_openalex_arxiv_match,
    fetch_openalex_citation_page,
)
from research_agent.ingest.pilot import Identity, PilotWorker, RateGate, Sources
from research_agent.ingest.pilot_local import (
    LocalStorage,
    local_storage,
    worker_principal,
)
from research_agent.learning.corpus import (
    DEFAULT_CAP,
    DEFAULT_CATEGORIES,
    DEFAULT_PER_MONTH,
    DEFAULT_POPULATION_RULE,
    SELECTION_SEED,
    mature_months,
)
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate

RECORD_CAP = 100_000
OPENALEX_INTERVAL_SECONDS = 0.2
_LISTING_ATTEMPTS = 3
_ROOT = Path(__file__).resolve().parents[3]
_ACCESS_RULES = _ROOT / "docs" / "evidence" / "source-pilot" / "access-rules.md"
_RETENTION = (
    b"Pilot originals and responses are retained privately for this research, "
    b"with each paper's license recorded; they are not redistributed."
)


def _commit() -> str:
    return subprocess.run(
        ("git", "-C", str(_ROOT), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _identity(frozen_at: str, categories: tuple[str, ...]) -> Identity:
    # No container image runs this local pilot; the image digest names that fact.
    producer = ProducerVersion(sha256(b"local-process").hexdigest(), _commit(), 1)
    config = {
        "frozen_at": frozen_at,
        "record_cap": RECORD_CAP,
        "arxiv_interval_seconds": MINIMUM_INTERVAL_SECONDS,
        "openalex_interval_seconds": OPENALEX_INTERVAL_SECONDS,
        "categories": list(categories),
        "sets": list(target_sets(categories)),
    }
    return Identity(
        producer,
        sha256(canonical_json(config)).hexdigest(),
        sha256(_RETENTION).hexdigest(),
        sha256(_ACCESS_RULES.read_bytes()).hexdigest(),
    )


def _sources(identity: Identity) -> Sources:
    def match(family: str, meta: RecordMeta) -> FetchedOpenAlexPage:
        return fetch_openalex_arxiv_match(
            arxiv_family_id=family,
            provenance=meta,
            permission_evidence_hash=identity.permission_evidence_hash,
            retention_policy_hash=identity.retention_policy_hash,
        )

    def cites(work: str, cursor: str | None, meta: RecordMeta) -> FetchedOpenAlexPage:
        return fetch_openalex_citation_page(
            target_provider_ids=(work,),
            cursor=cursor,
            per_page=100,
            provenance=meta,
            permission_evidence_hash=identity.permission_evidence_hash,
            retention_policy_hash=identity.retention_policy_hash,
        )

    # listing and document share one gate: arXiv's limit spans all its hosts.
    arxiv = RateGate(MINIMUM_INTERVAL_SECONDS)
    return Sources(
        listing=fetch_listing_page,
        document=fetch_document,
        openalex_match=match,
        openalex_cites=cites,
        arxiv_gate=arxiv,
        openalex_gate=RateGate(OPENALEX_INTERVAL_SECONDS),
    )


def _jobs(storage: LocalStorage) -> list[dict[str, Any]]:
    """Every capture job with its stage specification and committed report."""
    rows = storage.database.transaction(
        lambda connection: connection.execute(
            """SELECT j.id, j.state, encode(j.input_manifest_hash,'hex'),
                      encode(o.artifact_hash,'hex')
               FROM jobs j LEFT JOIN job_outputs o ON o.job_id=j.id
               ORDER BY j.scheduled_at, j.id"""
        ).fetchall()
    )
    jobs = []
    for job_id, state, manifest, output in rows:
        jobs.append(
            {
                "id": str(job_id),
                "state": str(state),
                "spec": storage.report(str(manifest)),
                "report_manifest": None if output is None else str(output),
                "report": None if output is None else storage.report(str(output)),
            }
        )
    return jobs


def _advance(
    storage: LocalStorage,
    frozen_at: str,
    *,
    population_rule: str = DEFAULT_POPULATION_RULE,
    cap: int = DEFAULT_CAP,
    seed: int = SELECTION_SEED,
    per_month: int = DEFAULT_PER_MONTH,
    categories: tuple[str, ...] = DEFAULT_CATEGORIES,
) -> bool:
    """Enqueue whatever the committed stages now allow; True if work was added."""
    jobs = _jobs(storage)
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        by_stage.setdefault(job["spec"]["stage"], []).append(job)
    listings = by_stage.get("listing", [])
    first, last = listing_window(mature_months(frozen_at), frozen_at)
    sets = target_sets(categories)
    added = False
    for set_spec in sets:
        attempts = [j for j in listings if j["spec"]["set_spec"] == set_spec]
        if attempts and any(j["state"] != "failed" for j in attempts):
            continue
        if len(attempts) >= _LISTING_ATTEMPTS:
            raise RuntimeError(f"listing {set_spec} failed {len(attempts)} times")
        storage.enqueue(
            {
                "stage": "listing",
                "set_spec": set_spec,
                "from_date": first,
                "until_date": last,
                "attempt": len(attempts) + 1,
            }
        )
        added = True
    committed = [j for j in listings if j["state"] == "committed"]
    if added or len({j["spec"]["set_spec"] for j in committed}) < len(sets):
        return added
    if "select" not in by_stage:
        reports = [j["report_manifest"] for j in committed]
        storage.enqueue(
            {
                "stage": "select",
                "frozen_at": frozen_at,
                "listing_reports": reports,
                "population_rule": population_rule,
                "cap": cap,
                "seed": seed,
                "per_month": per_month,
                "categories": list(categories),
            },
            tuple(reports),
        )
        return True
    selection = by_stage["select"][0]
    if selection["state"] != "committed":
        return False
    families = selection["report"]["selected"]
    selection_manifest = selection["report_manifest"]
    if "documents" not in by_stage:
        for family in families:
            storage.enqueue(
                {"stage": "documents", "family": family}, (selection_manifest,)
            )
        added = True
    # OpenAlex runs one family at a time so the global record cap holds.
    openalex = by_stage.get("openalex", [])
    if any(j["state"] != "committed" for j in openalex):
        return added
    received = sum(j["report"]["records_received"] for j in openalex)
    done = {j["spec"]["family"]["family_id"] for j in openalex}
    pending = [f for f in families if f["family_id"] not in done]
    if pending and received < RECORD_CAP:
        storage.enqueue(
            {
                "stage": "openalex",
                "family": pending[0],
                "record_budget": RECORD_CAP - received,
            },
            (selection_manifest,),
        )
        added = True
    return added


def _requests(storage: LocalStorage) -> dict[str, Any]:
    """Count every retained request record by adapter and outcome."""
    rows = storage.database.transaction(
        lambda connection: connection.execute(
            """SELECT encode(a.hash,'hex') FROM artifacts a
               JOIN artifact_productions p ON p.artifact_hash=a.hash
               JOIN job_productions jp ON jp.manifest_hash=p.manifest_hash
               WHERE a.kind='source_response' AND a.media_type='application/json'"""
        ).fetchall()
    )
    counts: dict[str, dict[str, int]] = {}
    seconds: dict[str, float] = {}
    seen: set[str] = set()
    for (value,) in rows:
        raw = str(value)
        if raw in seen:
            continue
        seen.add(raw)
        (_, _), stream = storage.artifacts.read(raw)
        with stream:
            body = stream.read()
        try:
            access = SourceAccess.from_json(body)
        except ValueError:
            continue
        outcome = access.failure or "retained"
        bucket = counts.setdefault(access.adapter_version, {})
        bucket[outcome] = bucket.get(outcome, 0) + 1
        started = datetime.fromisoformat(
            access.capture_started_at.replace("Z", "+00:00")
        )
        ended = datetime.fromisoformat(
            access.capture_completed_at.replace("Z", "+00:00")
        )
        seconds[access.adapter_version] = (
            seconds.get(access.adapter_version, 0.0) + (ended - started).total_seconds()
        )
    return {"by_adapter": counts, "request_seconds": seconds}


def _bytes(storage: LocalStorage) -> dict[str, int]:
    rows = storage.database.transaction(
        lambda connection: connection.execute(
            """SELECT a.kind, a.media_type, sum(a.byte_length)::bigint FROM artifacts a
               WHERE a.hash IN (SELECT p.artifact_hash FROM artifact_productions p
                                JOIN job_productions jp USING (manifest_hash))
               GROUP BY a.kind, a.media_type"""
        ).fetchall()
    )
    return {f"{kind}:{media}": int(str(total)) for kind, media, total in rows}


def report(storage: LocalStorage, state: Path) -> dict[str, Any]:
    jobs = _jobs(storage)
    stages: dict[str, dict[str, int]] = {}
    for job in jobs:
        bucket = stages.setdefault(job["spec"]["stage"], {})
        bucket[job["state"]] = bucket.get(job["state"], 0) + 1
    selection = next(
        (j["report"] for j in jobs if j["spec"]["stage"] == "select" and j["report"]),
        None,
    )
    documents = [
        j["report"] for j in jobs if j["spec"]["stage"] == "documents" and j["report"]
    ]
    openalex = [
        j["report"] for j in jobs if j["spec"]["stage"] == "openalex" and j["report"]
    ]

    def tally(values: list[str]) -> dict[str, int]:
        result: dict[str, int] = {}
        for value in values:
            result[value] = result.get(value, 0) + 1
        return result

    runs = []
    runs_file = state / "runs.jsonl"
    if runs_file.exists():
        runs = [json.loads(line) for line in runs_file.read_text().splitlines() if line]
    return {
        "frozen_at": json.loads((state / "state.json").read_text())["frozen_at"],
        "jobs": stages,
        "selection": None
        if selection is None
        else {
            "publication_months": selection["publication_months"],
            "eligible_counts": selection["eligible_counts"],
            "eligible_total": sum(n for _, n in selection["eligible_counts"]),
            "selected": len(selection["selected"]),
            "shortfall": sum(n for _, n in selection["month_shortfalls"]),
            "population_hash": selection["population_hash"],
            "population_rule": selection["population_rule"],
            "cap": selection["intended_count"],
            "seed": selection["seed"],
            "categories": selection["categories"],
            "sets": list(target_sets(selection["categories"])),
            "per_category_counts": selection["per_category_counts"],
            "licenses": tally(
                [f["license_url"] or "none" for f in selection["selected"]]
            ),
        },
        "documents": {
            "src": tally([d.get("src", "unrecorded") for d in documents]),
            "pdf": tally([d.get("pdf", "unrecorded") for d in documents]),
        },
        "openalex": {
            "states": tally([o["state"] for o in openalex]),
            "records_received": sum(o["records_received"] for o in openalex),
            "record_cap": RECORD_CAP,
        },
        "requests": _requests(storage),
        "retained_bytes": _bytes(storage),
        "artifact_disk_bytes": sum(
            f.stat().st_size for f in (state / "artifacts").rglob("*") if f.is_file()
        ),
        "runs": runs,
    }


def _parse_categories(value: str) -> tuple[str, ...]:
    categories = tuple(item.strip() for item in value.split(","))
    if not categories or any(not item for item in categories):
        raise ValueError("--categories must be a non-empty comma-separated list")
    target_sets(categories)  # raises ValueError on an unsupported category
    return categories


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "report"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--dsn", required=True, help="DSN selecting a pilot schema")
    parser.add_argument(
        "--frozen-at", help="UTC freeze instant; fixed on the first run only"
    )
    parser.add_argument(
        "--population-rule",
        help="rule text recorded verbatim; fixed on the first run only",
    )
    parser.add_argument(
        "--cap", type=int, help="maximum selected families; fixed on the first run only"
    )
    parser.add_argument(
        "--seed", type=int, help="selection hash seed; fixed on the first run only"
    )
    parser.add_argument(
        "--per-month",
        type=int,
        help=(
            "families selected per mature month, 0 for a single uniform draw "
            "over the whole window; fixed on the first run only"
        ),
    )
    parser.add_argument(
        "--categories",
        help=(
            "comma-separated corpus categories (cs.AI, cs.LG, quant-ph, "
            "q-bio); fixed on the first run only"
        ),
    )
    args = parser.parse_args(argv)
    if args.cap is not None and args.cap < 0:
        parser.error("--cap must not be negative")
    if args.per_month is not None and args.per_month < 0:
        parser.error("--per-month must not be negative")
    categories_given: tuple[str, ...] | None = None
    if args.categories is not None:
        try:
            categories_given = _parse_categories(args.categories)
        except ValueError as error:
            parser.error(str(error))
    state: Path = args.state
    state.mkdir(parents=True, exist_ok=True)
    state_file = state / "state.json"
    if state_file.exists():
        stored = json.loads(state_file.read_text())
        frozen_at = stored["frozen_at"]
        population_rule = stored.get("population_rule", DEFAULT_POPULATION_RULE)
        cap = stored.get("cap", DEFAULT_CAP)
        seed = stored.get("seed", SELECTION_SEED)
        per_month = stored.get("per_month", DEFAULT_PER_MONTH)
        categories = tuple(stored.get("categories", DEFAULT_CATEGORIES))
        for flag, given, fixed in (
            ("--frozen-at", args.frozen_at, frozen_at),
            ("--population-rule", args.population_rule, population_rule),
            ("--cap", args.cap, cap),
            ("--seed", args.seed, seed),
            ("--per-month", args.per_month, per_month),
            ("--categories", categories_given, categories),
        ):
            if given is not None and given != fixed:
                parser.error(f"this pilot's {flag} is already fixed at {fixed!r}")
    else:
        if args.command != "run":
            parser.error("no pilot state exists yet")
        frozen_at = args.frozen_at or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        validate_utc_instant(frozen_at)
        population_rule = args.population_rule or DEFAULT_POPULATION_RULE
        cap = DEFAULT_CAP if args.cap is None else args.cap
        seed = SELECTION_SEED if args.seed is None else args.seed
        per_month = DEFAULT_PER_MONTH if args.per_month is None else args.per_month
        categories = (
            DEFAULT_CATEGORIES if categories_given is None else categories_given
        )
        state_file.write_text(
            json.dumps(
                {
                    "frozen_at": frozen_at,
                    "population_rule": population_rule,
                    "cap": cap,
                    "seed": seed,
                    "per_month": per_month,
                    "categories": list(categories),
                }
            )
            + "\n"
        )
    identity = _identity(frozen_at, categories)
    migrate(Database(args.dsn))
    with local_storage(
        dsn=args.dsn,
        artifact_root=state / "artifacts",
        tls_directory=state / "tls",
        identity=identity,
    ) as storage:
        if args.command == "report":
            print(json.dumps(report(storage, state), indent=2, sort_keys=True))
            return 0
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(state / "tls"),
            identity=identity,
            sources=_sources(identity),
        )
        started = time.monotonic()
        budget_stop = False
        while True:
            _advance(
                storage,
                frozen_at,
                population_rule=population_rule,
                cap=cap,
                seed=seed,
                per_month=per_month,
                categories=categories,
            )
            summary = worker.run()
            if summary.stopped_for_budget:
                budget_stop = True
                break
            if summary.jobs_completed == 0 and not _advance(
                storage,
                frozen_at,
                population_rule=population_rule,
                cap=cap,
                seed=seed,
                per_month=per_month,
                categories=categories,
            ):
                break
        run = {
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": round(time.monotonic() - started, 3),
            # macOS reports bytes, Linux kibibytes.
            "peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "platform": sys.platform,
            "stopped_for_openalex_budget": budget_stop,
            "free_disk_bytes": shutil.disk_usage(state).free,
        }
        with (state / "runs.jsonl").open("a") as runs:
            runs.write(json.dumps(run) + "\n")
        print(json.dumps(run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
