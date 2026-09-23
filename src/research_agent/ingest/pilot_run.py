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
from typing import Any, cast
from uuid import UUID

from research_agent.contracts import RecordMeta, canonical_json
from research_agent.contracts.papers import SourceAccess
from research_agent.contracts.primitives import ProducerVersion, validate_utc_instant
from research_agent.ingest.arxiv import (
    MINIMUM_INTERVAL_SECONDS,
    fetch_bucket_pdf,
    fetch_document,
    fetch_listing_page,
    listing_window,
    target_sets,
)
from research_agent.ingest.fetch import (
    FetchedOpenAlexPage,
    FetchedSnapshotRange,
    fetch_openalex_arxiv_match,
    fetch_openalex_citation_page,
    fetch_openalex_snapshot_range,
)
from research_agent.ingest.pilot import (
    Identity,
    PilotWorker,
    RateGate,
    RunSummary,
    Sources,
    utc_now,
)
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


def _identity(frozen_at: str, categories: tuple[str, ...], record_cap: int) -> Identity:
    # No container image runs this local pilot; the image digest names that fact.
    producer = ProducerVersion(sha256(b"local-process").hexdigest(), _commit(), 1)
    config = {
        "frozen_at": frozen_at,
        "record_cap": record_cap,
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

    def snapshot_range(key: str, range_spec: str) -> FetchedSnapshotRange:
        return fetch_openalex_snapshot_range(
            key=key,
            range_spec=range_spec,
            provenance=RecordMeta(
                1, (), identity.producer, identity.config_hash, utc_now()
            ),
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
        pdf_bucket=fetch_bucket_pdf,
        snapshot_range=snapshot_range,
    )


_manifest_cache: dict[str, dict[str, Any]] = {}


def _jobs(storage: LocalStorage) -> list[dict[str, Any]]:
    """Every capture job with its stage specification and committed report.

    A spec or report's content never changes once its manifest hash is
    known, so both are cached here by that hash: a run with a large queued
    backlog pays to read each one once, not on every `_advance` call.
    """
    rows = storage.database.transaction(
        lambda connection: connection.execute(
            """SELECT j.id, j.state, j.scheduled_at,
                      encode(j.input_manifest_hash,'hex'),
                      encode(o.artifact_hash,'hex')
               FROM jobs j LEFT JOIN job_outputs o ON o.job_id=j.id
               ORDER BY j.scheduled_at, j.id"""
        ).fetchall()
    )
    jobs = []
    for job_id, state, scheduled_at, manifest, output in rows:
        manifest_hash = str(manifest)
        if manifest_hash not in _manifest_cache:
            _manifest_cache[manifest_hash] = storage.report(manifest_hash)
        report_manifest = None if output is None else str(output)
        if report_manifest is not None and report_manifest not in _manifest_cache:
            _manifest_cache[report_manifest] = storage.report(report_manifest)
        jobs.append(
            {
                "id": str(job_id),
                "state": str(state),
                "scheduled_at": scheduled_at,
                "spec": _manifest_cache[manifest_hash],
                "report_manifest": report_manifest,
                "report": (
                    None
                    if report_manifest is None
                    else _manifest_cache[report_manifest]
                ),
            }
        )
    return jobs


def _by_stage(storage: LocalStorage) -> dict[str, list[dict[str, Any]]]:
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for job in _jobs(storage):
        by_stage.setdefault(job["spec"]["stage"], []).append(job)
    return by_stage


def _openalex_pending(storage: LocalStorage) -> bool:
    """True once a selection has committed but a selected family's `openalex`
    report has not, so the run loop should claim one job at a time (#151)."""
    by_stage = _by_stage(storage)
    selection = next(
        (j for j in by_stage.get("select", []) if j["state"] == "committed"), None
    )
    if selection is None:
        return False
    families = {f["family_id"] for f in selection["report"]["selected"]}
    observed = {
        family_id
        for family_id, job in _latest_by_family(by_stage.get("openalex", [])).items()
        if job["state"] in _TERMINAL
    }
    return not families <= observed


_TERMINAL = frozenset({"committed", "failed"})


def _latest_by_family(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each family's most recently enqueued job of one stage.

    Jobs arrive in enqueue order, so a family requeued after a failure is
    represented by the fresh job, not the failed one.
    """
    latest: dict[str, dict[str, Any]] = {}
    for job in jobs:
        latest[job["spec"]["family"]["family_id"]] = job
    return latest


def _advance(
    storage: LocalStorage,
    frozen_at: str,
    *,
    population_rule: str = DEFAULT_POPULATION_RULE,
    cap: int = DEFAULT_CAP,
    seed: int = SELECTION_SEED,
    per_month: int = DEFAULT_PER_MONTH,
    categories: tuple[str, ...] = DEFAULT_CATEGORIES,
    gate_on_labels: bool = False,
    record_cap: int | None = None,
) -> bool:
    """Enqueue whatever the committed stages now allow; True if work was added."""
    by_stage = _by_stage(storage)
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
    openalex = by_stage.get("openalex", [])
    documents_jobs = by_stage.get("documents", [])
    # A build started before #151 queued its documents jobs ahead of any
    # openalex job; expedite the one still queued so it claims first on
    # restart, without waiting for it to reach the front on its own.
    queued_documents_at = [
        j["scheduled_at"] for j in documents_jobs if j["state"] == "queued"
    ]
    if queued_documents_at:
        earliest_documents_at = min(queued_documents_at)
        for job in openalex:
            if job["state"] == "queued" and job["scheduled_at"] > earliest_documents_at:
                storage.expedite(UUID(job["id"]))
    if gate_on_labels:
        # Label-first gating (#144): a family is only worth downloading once
        # its own citation observation resolved every target label, so
        # documents wait on that family's committed openalex report instead
        # of the selection alone.
        documents_started = {j["spec"]["family"]["family_id"] for j in documents_jobs}
        openalex_by_family = {
            j["spec"]["family"]["family_id"]: j
            for j in openalex
            if j["state"] == "committed"
        }
        for family in families:
            family_id = family["family_id"]
            if family_id in documents_started:
                continue
            openalex_job = openalex_by_family.get(family_id)
            if (
                openalex_job is None
                or openalex_job["report"].get("gate", {}).get("decision") != "acquire"
            ):
                continue
            storage.enqueue(
                {"stage": "documents", "family": family}, (selection_manifest,)
            )
            added = True
    elif "documents" not in by_stage:
        for family in families:
            storage.enqueue(
                {"stage": "documents", "family": family}, (selection_manifest,)
            )
        added = True
    # OpenAlex runs one family at a time so the global record cap holds. A
    # failed family is passed over, not retried: its job carries the error,
    # and `requeue` enqueues a fresh job for it once the cause is fixed.
    if any(j["state"] not in _TERMINAL for j in openalex):
        return added
    received = sum(
        j["report"]["records_received"] for j in openalex if j["state"] == "committed"
    )
    done = set(_latest_by_family(openalex))
    pending = [f for f in families if f["family_id"] not in done]
    cap_value = RECORD_CAP if record_cap is None else record_cap
    if pending and received < cap_value:
        storage.enqueue(
            {
                "stage": "openalex",
                "family": pending[0],
                "record_budget": cap_value - received,
            },
            (selection_manifest,),
            ahead=True,
        )
        added = True
    return added


def requeue(
    storage: LocalStorage,
    *,
    stages: tuple[str, ...] = ("openalex", "documents"),
    families: tuple[str, ...] = (),
    record_cap: int | None = None,
) -> list[dict[str, Any]]:
    """Enqueue a fresh job for each family whose latest job of a stage failed.

    Storage keeps the failed job and its recorded error; the fresh job has
    the same specification and inputs, so once the cause of the failure is
    fixed the run picks the family up again exactly as the operator would
    have enqueued it. `families` narrows to those ids; `listing` requeues a
    failed set as its next attempt. Returns what was enqueued.
    """
    by_stage = _by_stage(storage)
    selection = next(
        (j for j in by_stage.get("select", []) if j["state"] == "committed"), None
    )
    wanted = set(families)
    enqueued: list[dict[str, Any]] = []
    if "listing" in stages:
        for set_spec, attempts in _group(by_stage.get("listing", []), "set_spec"):
            last = attempts[-1]
            if last["state"] != "failed" or (wanted and set_spec not in wanted):
                continue
            spec = dict(last["spec"], attempt=len(attempts) + 1)
            job_id = storage.enqueue(spec)
            enqueued.append(
                {"job_id": str(job_id), "stage": "listing", "set_spec": set_spec}
            )
    if selection is None:
        return enqueued
    selection_manifest = selection["report_manifest"]
    openalex = by_stage.get("openalex", [])
    cap_value = RECORD_CAP if record_cap is None else record_cap
    received = sum(
        j["report"]["records_received"] for j in openalex if j["state"] == "committed"
    )
    for stage in stages:
        if stage == "listing":
            continue
        for family_id, last in _latest_by_family(by_stage.get(stage, [])).items():
            if last["state"] != "failed" or (wanted and family_id not in wanted):
                continue
            spec = dict(last["spec"])
            if stage == "openalex":
                spec["record_budget"] = max(cap_value - received, 0)
            job_id = storage.enqueue(
                spec, (selection_manifest,), ahead=(stage == "openalex")
            )
            enqueued.append(
                {"job_id": str(job_id), "stage": stage, "family_id": family_id}
            )
    return enqueued


def _group(
    jobs: list[dict[str, Any]], key: str
) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        grouped.setdefault(str(job["spec"][key]), []).append(job)
    return list(grouped.items())


def verify_store(storage: LocalStorage, *, heal: bool = False) -> dict[str, Any]:
    """Check every artifact the database knows against the bytes on disk.

    Read-only unless `heal`, which rewrites each damaged or missing copy from
    the other verified copy and refuses to run while any job holds a live
    lease: a running worker is the only other writer of the store, and it
    installs under the same atomic discipline, so the two never overlap.
    Returns the counts after the pass and the identities still not `ok`.
    """
    store = storage.store
    if store is None:
        raise RuntimeError("this storage keeps no local artifact store to verify")
    if heal:
        live = storage.database.transaction(
            lambda connection: connection.execute(
                """SELECT count(*) FROM jobs
                   WHERE state='running' AND expires_at > clock_timestamp()"""
            ).fetchone()
        )
        if live is not None and cast(int, live[0]) > 0:
            raise RuntimeError(
                "a job holds a live lease; stop the runner before healing"
            )
    hashes = storage.database.transaction(
        lambda connection: [
            str(row[0])
            for row in connection.execute(
                "SELECT encode(hash,'hex') FROM artifacts ORDER BY hash"
            ).fetchall()
        ]
    )
    states = list(store.heal(hashes) if heal else store.verify(hashes))
    if heal:
        states = list(store.verify(hashes))
    counts = {"artifacts": len(states), "damaged": 0, "missing": 0, "mirror_bad": 0}
    unhealthy: list[dict[str, str]] = []
    for state in states:
        if state.primary == "damaged":
            counts["damaged"] += 1
        elif state.primary == "missing":
            counts["missing"] += 1
        if state.mirror in {"damaged", "missing"}:
            counts["mirror_bad"] += 1
        if state.primary != "ok" or state.mirror in {"damaged", "missing"}:
            unhealthy.append(
                {
                    "artifact_hash": state.artifact_hash,
                    "primary": state.primary,
                    "mirror": state.mirror,
                }
            )
    return {
        **counts,
        "mirror": None if store.mirror is None else str(store.mirror),
        "healed": heal,
        "unhealthy": unhealthy[:200],
    }


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


def _gate_counts(
    selection: dict[str, Any] | None,
    openalex: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> dict[str, int]:
    """Selected, labeled, gated-out, acquired and embedded counts (#144).

    Labeled/gated-out are zero whenever a run never resolved
    ``--gate-on-labels``: its openalex reports carry no ``gate`` key, so
    documents were (and remain) enqueued unconditionally. No embedding
    pipeline exists in this harness, so "embedded" is always zero.
    """
    gates = [o["gate"] for o in openalex if "gate" in o]
    return {
        "selected": 0 if selection is None else len(selection["selected"]),
        "labeled": len(gates),
        "gated_out": sum(1 for g in gates if g["decision"] != "acquire"),
        "acquired": len(documents),
        "embedded": 0,
    }


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
    stored_state = json.loads((state / "state.json").read_text())
    return {
        "frozen_at": stored_state["frozen_at"],
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
            "pdf_source": tally([d.get("pdf_source", "unrecorded") for d in documents]),
        },
        "openalex": {
            "states": tally([o["state"] for o in openalex]),
            "records_received": sum(o["records_received"] for o in openalex),
            "record_cap": stored_state.get("record_cap", RECORD_CAP),
        },
        "gate": _gate_counts(selection, openalex, documents),
        "requests": _requests(storage),
        "retained_bytes": _bytes(storage),
        "artifact_disk_bytes": sum(
            f.stat().st_size for f in (state / "artifacts").rglob("*") if f.is_file()
        ),
        "runs": runs,
    }


def _drain(
    storage: LocalStorage,
    worker: PilotWorker,
    frozen_at: str,
    *,
    population_rule: str,
    cap: int,
    seed: int,
    per_month: int,
    categories: tuple[str, ...],
    gate_on_labels: bool,
    record_cap: int,
) -> RunSummary:
    """Advance and run until nothing is left to claim.

    While a selected family's `openalex` report has not yet committed, one
    job runs per `_advance` so labels resolve family by family instead of
    behind the whole `documents` backlog (#151); once every family is
    observed, the drain is unbounded as it was before.
    """
    completed = 0
    while True:
        _advance(
            storage,
            frozen_at,
            population_rule=population_rule,
            cap=cap,
            seed=seed,
            per_month=per_month,
            categories=categories,
            gate_on_labels=gate_on_labels,
            record_cap=record_cap,
        )
        maximum_jobs = 1 if _openalex_pending(storage) else None
        summary = worker.run(maximum_jobs=maximum_jobs)
        completed += summary.jobs_completed
        if summary.stopped_for_budget:
            return RunSummary(completed, True)
        if summary.jobs_completed == 0 and not _advance(
            storage,
            frozen_at,
            population_rule=population_rule,
            cap=cap,
            seed=seed,
            per_month=per_month,
            categories=categories,
            gate_on_labels=gate_on_labels,
            record_cap=record_cap,
        ):
            return RunSummary(completed, False)


def _parse_categories(value: str) -> tuple[str, ...]:
    categories = tuple(item.strip() for item in value.split(","))
    if not categories or any(not item for item in categories):
        raise ValueError("--categories must be a non-empty comma-separated list")
    target_sets(categories)  # raises ValueError on an unsupported category
    return categories


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "report", "requeue", "verify"))
    parser.add_argument(
        "--stage",
        action="append",
        choices=("listing", "openalex", "documents"),
        help="requeue only this stage (repeatable; default openalex and documents)",
    )
    parser.add_argument(
        "--family",
        action="append",
        help="requeue only this family id (repeatable)",
    )
    parser.add_argument(
        "--mirror",
        type=Path,
        help=(
            "second root, on another device, that keeps a copy of every "
            "artifact; a damaged primary copy is rewritten from it"
        ),
    )
    parser.add_argument(
        "--heal",
        action="store_true",
        help="with verify: rewrite each damaged or missing copy from the good one",
    )
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
    parser.add_argument(
        "--gate-on-labels",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "resolve labels from each family's own OpenAlex citation "
            "observation before downloading its text, skipping acquisition "
            "for any family with an unknown label; fixed on the first run "
            "only, off by default so the committed 100-family pilot "
            "reproduces exactly"
        ),
    )
    parser.add_argument(
        "--record-cap",
        type=int,
        help=(
            "global cap on retained citation records for the whole run; "
            "fixed on the first run only, default 100000"
        ),
    )
    args = parser.parse_args(argv)
    if args.cap is not None and args.cap < 0:
        parser.error("--cap must not be negative")
    if args.per_month is not None and args.per_month < 0:
        parser.error("--per-month must not be negative")
    if args.record_cap is not None and args.record_cap < 0:
        parser.error("--record-cap must not be negative")
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
        gate_on_labels = stored.get("gate_on_labels", False)
        record_cap = stored.get("record_cap", RECORD_CAP)
        for flag, given, fixed in (
            ("--frozen-at", args.frozen_at, frozen_at),
            ("--population-rule", args.population_rule, population_rule),
            ("--cap", args.cap, cap),
            ("--seed", args.seed, seed),
            ("--per-month", args.per_month, per_month),
            ("--categories", categories_given, categories),
            ("--gate-on-labels", args.gate_on_labels, gate_on_labels),
            ("--record-cap", args.record_cap, record_cap),
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
        gate_on_labels = False if args.gate_on_labels is None else args.gate_on_labels
        record_cap = RECORD_CAP if args.record_cap is None else args.record_cap
        state_file.write_text(
            json.dumps(
                {
                    "frozen_at": frozen_at,
                    "population_rule": population_rule,
                    "cap": cap,
                    "seed": seed,
                    "per_month": per_month,
                    "categories": list(categories),
                    "gate_on_labels": gate_on_labels,
                    "record_cap": record_cap,
                }
            )
            + "\n"
        )
    identity = _identity(frozen_at, categories, record_cap)
    migrate(Database(args.dsn))
    with local_storage(
        dsn=args.dsn,
        artifact_root=state / "artifacts",
        tls_directory=state / "tls",
        identity=identity,
        mirror=args.mirror,
    ) as storage:
        if args.command == "report":
            print(json.dumps(report(storage, state), indent=2, sort_keys=True))
            return 0
        if args.command == "requeue":
            enqueued = requeue(
                storage,
                stages=tuple(args.stage or ("openalex", "documents")),
                families=tuple(args.family or ()),
                record_cap=record_cap,
            )
            print(json.dumps(enqueued, indent=2, sort_keys=True))
            return 0
        if args.command == "verify":
            outcome = verify_store(storage, heal=args.heal)
            print(json.dumps(outcome, indent=2, sort_keys=True))
            return 0 if outcome["damaged"] == 0 and outcome["missing"] == 0 else 1
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(state / "tls"),
            identity=identity,
            sources=_sources(identity),
            gate_on_labels=gate_on_labels,
        )
        started = time.monotonic()
        summary = _drain(
            storage,
            worker,
            frozen_at,
            population_rule=population_rule,
            cap=cap,
            seed=seed,
            per_month=per_month,
            categories=categories,
            gate_on_labels=gate_on_labels,
            record_cap=record_cap,
        )
        run = {
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": round(time.monotonic() - started, 3),
            # macOS reports bytes, Linux kibibytes.
            "peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "platform": sys.platform,
            "stopped_for_openalex_budget": summary.stopped_for_budget,
            "free_disk_bytes": shutil.disk_usage(state).free,
        }
        with (state / "runs.jsonl").open("a") as runs:
            runs.write(json.dumps(run) + "\n")
        print(json.dumps(run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
