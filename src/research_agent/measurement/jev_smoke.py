"""Run the RD-22 Jev smoke test over a committed corpus release (#319).

``bin/jev-smoke`` draws the Appendix A sample from the release, sends each
sampled paper's eight-field request through ``ingest.jev.JevWorker`` under
the Jev operating limits, folds the stored outcomes with
``measurement.jev.smoke_test_rubric`` and stores the sample and the report
as artifacts. It prints the report hash and the per-field counts. The owner
review is not part of a run: the stored report carries none, so activation
stays refused until one is recorded.

The smoke weeks are the latest 20 publication weeks among the release's
families that ended by the release's selection freeze, so a week the
population enumeration could have cut short never enters. A candidate is
every release family with a publication week and a primary category, except
a family alias. A sampled paper whose version record or exported text is
missing is an unavailable ``missing_input`` result, never a replacement.

Latency is the committed attempt's request-to-completion time; cost prices
the stored response's ``usage.input_tokens`` at the configured prompt rate,
and an attempt whose billing is uncertain costs its worst-case reservation.
A rerun reuses every committed available result and pays nothing for it.

The credential comes from ``JEV_API_KEY`` in the environment, never a flag.
Without it the run is a dry run: every request is answered by the recorded
fixture for the rubric, work is held in memory, artifacts go to a separate
directory, and the printed report is marked as not a smoke test.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from research_agent.artifacts.store import ArtifactStore
from research_agent.assessments.input import (
    ProviderInputLimit,
    build_assessment_input,
)
from research_agent.assessments.rubric import Rubric
from research_agent.assessments.schemas import (
    AssessmentResult,
    JevAvailable,
    JevUnavailable,
)
from research_agent.assessments.tokens import CalibratedCounter
from research_agent.contracts.assessments import (
    V1_RUBRIC_VERSION,
    V2_RUBRIC_VERSION,
)
from research_agent.contracts.canonical import (
    CanonicalJsonError,
    canonical_json,
    canonical_loads,
    sha256_hex,
)
from research_agent.contracts.corpus import CorpusRelease, CorpusRow
from research_agent.contracts.papers import PaperVersionRecord
from research_agent.ingest.jev import (
    HttpSystemOneTransport,
    JevProviderConfig,
    JevWorker,
    JevWorkStore,
    read_committed,
    work_key,
)
from research_agent.measurement import MeasurementError
from research_agent.measurement.jev import (
    SMOKE_SAMPLE_WEEKS,
    SmokeCandidate,
    SmokeObservation,
    SmokeReport,
    SmokeSample,
    select_smoke_sample,
    smoke_test_rubric,
)
from research_agent.models.batch import PaperText, read_paper_text
from research_agent.outcomes.windows import instant, utc

__all__ = [
    "CREDENTIAL_ENV",
    "RECORDED_RESPONSES",
    "RecordedTransport",
    "MemoryWorkStore",
    "SmokeRun",
    "smoke_weeks",
    "smoke_candidates",
    "draw_sample",
    "rubric_for",
    "provider_config",
    "load_papers",
    "run_smoke",
    "store_run",
    "summary_lines",
    "main",
]

CREDENTIAL_ENV = "JEV_API_KEY"
_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "jev"
#: The recorded live response a dry run answers each request with.
RECORDED_RESPONSES: Mapping[str, Path] = {
    V1_RUBRIC_VERSION: _FIXTURES / "systemone-response.json",
    V2_RUBRIC_VERSION: _FIXTURES / "systemone-v2-response.json",
}
_RUBRICS: Mapping[str, Callable[[], Rubric]] = {
    V1_RUBRIC_VERSION: Rubric.v1,
    V2_RUBRIC_VERSION: Rubric.launch,
}
_MAX_RECORD_BYTES = 1024 * 1024


def rubric_for(version: str) -> Rubric:
    try:
        return _RUBRICS[version]()
    except KeyError:
        raise MeasurementError(f"no rubric has version {version!r}") from None


def provider_config(raw: bytes) -> JevProviderConfig:
    """Read the declared provider configuration; it holds no credential."""

    try:
        value = canonical_loads(raw)
    except CanonicalJsonError as error:
        raise MeasurementError("provider configuration is not JSON") from error
    names = set(JevProviderConfig.__slots__)
    if not isinstance(value, dict) or set(value) != names:
        raise MeasurementError(
            "provider configuration must name exactly " + ", ".join(sorted(names))
        )
    fields: dict[str, Any] = dict(value)
    if not isinstance(fields["known_revisions"], list):
        raise MeasurementError("known_revisions must be an array")
    fields["known_revisions"] = frozenset(fields["known_revisions"])
    return JevProviderConfig(**fields)


def _week_end(week: str) -> datetime:
    monday = datetime.strptime(f"{week}-1", "%G-W%V-%u").replace(tzinfo=timezone.utc)
    return monday + timedelta(days=7)


def smoke_candidates(release: CorpusRelease) -> tuple[SmokeCandidate, ...]:
    """Every release family with a publication week and a primary category."""

    return tuple(
        SmokeCandidate(row.paper_family_id, row.categories[0], row.publication_week)
        for row in release.rows
        if row.publication_week is not None
        and row.categories
        and "family_alias" not in row.exclusion_reasons
    )


def smoke_weeks(
    release: CorpusRelease, count: int = SMOKE_SAMPLE_WEEKS
) -> tuple[str, ...]:
    """The latest ``count`` release weeks that ended by the selection freeze."""

    frozen = instant(release.selection_frozen_at)
    weeks = {item.publication_week for item in smoke_candidates(release)}
    complete = sorted(
        (week for week in weeks if _week_end(week) <= frozen), reverse=True
    )
    return tuple(complete[:count])


def draw_sample(release: CorpusRelease) -> SmokeSample:
    """The release's fixed smoke sample, drawn before any request."""

    return select_smoke_sample(smoke_candidates(release), smoke_weeks(release))


def load_papers(
    rows: Sequence[CorpusRow],
    *,
    paper_artifacts: Mapping[str, str | None],
    artifacts: ArtifactStore,
    text_dir: Path,
) -> dict[str, tuple[PaperVersionRecord, PaperText]]:
    """Each row's version record and exported text, when both exist.

    ``paper_artifacts`` maps a family id to its version record's artifact
    hash, as the release's candidates file lists it.
    """

    found: dict[str, tuple[PaperVersionRecord, PaperText]] = {}
    for row in rows:
        paper_hash = paper_artifacts.get(row.paper_family_id)
        if paper_hash is None:
            continue
        with artifacts.open_verified(paper_hash) as stream:
            paper = PaperVersionRecord.from_json(stream.read())
        if paper.version_id != row.original_version_id:
            raise MeasurementError("a candidate's paper record is another version")
        try:
            text = read_paper_text(text_dir, paper.version_id)
        except FileNotFoundError:
            continue
        found[row.paper_family_id] = (paper, text)
    return found


@dataclass(frozen=True, slots=True)
class RecordedTransport:
    """Answers every request with one recorded live response (dry run only)."""

    response: bytes

    def post(self, body: bytes, *, timeout: float) -> tuple[int, bytes]:
        return 200, self.response


class MemoryWorkStore:
    """A dry run's work store: nothing it holds reaches durable storage.

    It enforces the same daily attempt cap and spend sublimit per UTC day,
    so a dry run exercises the operating limits it would run under.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: set[str] = set()
        self._manifests: dict[str, bytes] = {}
        self._usage: dict[str, tuple[int, int]] = {}
        self._reservations: dict[str, str | None] = {}

    def committed_attempt(self, work_key: str) -> bytes | None:
        with self._lock:
            return self._manifests.get(work_key)

    def acquire_lease(self, work_key: str) -> bool:
        with self._lock:
            if work_key in self._leases:
                return False
            self._leases.add(work_key)
            return True

    def release_lease(self, work_key: str) -> None:
        with self._lock:
            self._leases.discard(work_key)

    def reserve_attempt(
        self,
        *,
        work_key: str,
        day: str,
        worst_case_micros: int,
        daily_attempt_cap: int,
        daily_limit_micros: int,
    ) -> str | None:
        with self._lock:
            attempts, reserved = self._usage.get(day, (0, 0))
            if (
                attempts + 1 > daily_attempt_cap
                or reserved + worst_case_micros > daily_limit_micros
            ):
                return None
            self._usage[day] = (attempts + 1, reserved + worst_case_micros)
            reservation = f"{day}:{len(self._reservations)}"
            self._reservations[reservation] = None
            return reservation

    def settle_attempt(self, reservation_id: str, billing_state: str) -> None:
        with self._lock:
            if self._reservations.get(reservation_id, "") is not None:
                raise MeasurementError("reservation is unknown or already settled")
            self._reservations[reservation_id] = billing_state

    def commit_attempt(self, work_key: str, manifest: bytes) -> None:
        with self._lock:
            self._manifests[work_key] = manifest


def _input_tokens(response: bytes) -> int | None:
    try:
        value = canonical_loads(response)
    except CanonicalJsonError:
        return None
    usage = value.get("usage") if isinstance(value, dict) else None
    tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
    if type(tokens) is not int or tokens < 0:
        return None
    return tokens


def _cost_micros(
    config: JevProviderConfig, result: AssessmentResult, response: bytes | None
) -> int:
    billing = (
        "known_completed" if isinstance(result, JevAvailable) else result.billing_state
    )
    if billing == "uncertain":
        return config.worst_case_micros
    if billing != "known_completed" or response is None:
        return 0
    tokens = _input_tokens(response)
    if tokens is None:
        return config.worst_case_micros
    return math.ceil(tokens * config.prompt_price_micros_per_million_tokens / 1e6)


def _elapsed_ms(started: str | None, finished: str) -> int:
    if started is None:
        return 0
    return max(0, round((instant(finished) - instant(started)).total_seconds() * 1000))


@dataclass(frozen=True, slots=True)
class SmokeRun:
    """A run's frozen sample and its report."""

    sample: SmokeSample
    report: SmokeReport


def run_smoke(
    release: CorpusRelease,
    papers: Mapping[str, tuple[PaperVersionRecord, PaperText]],
    *,
    rubric: Rubric,
    config: JevProviderConfig,
    worker: JevWorker,
    store: JevWorkStore,
    artifacts: ArtifactStore,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> SmokeRun:
    """Draw the sample, assess each sampled paper once and fold the outcomes.

    The sample is fixed before any request. ``papers`` holds each sampled
    family's version record and exported text; a family missing from it is
    recorded as ``missing_input`` without a request. The worker and the
    store must be the same pair, so each committed attempt can be read back.
    """

    sample = draw_sample(release)
    rows = {row.paper_family_id: row for row in release.rows}
    configured = config.identity(None)
    counter = CalibratedCounter()
    limit = ProviderInputLimit(config.max_input_tokens)
    observations: list[SmokeObservation] = []
    for candidate in sample.selected:
        found = papers.get(candidate.family_id)
        if found is None:
            missing = JevUnavailable(
                reason="missing_input",
                input_hash=None,
                rubric_hash=rubric.rubric_hash,
                provider_identity=None,
                sanitized_request_hash=None,
                sanitized_response_hash=None,
                billing_state="no_attempt",
                recorded_at=utc(clock()),
            )
            observations.append(
                SmokeObservation(candidate.family_id, missing, "unavailable", 0, 0)
            )
            continue
        paper, text = found
        if paper.version_id != rows[candidate.family_id].original_version_id:
            raise MeasurementError("a sampled paper record is another version")
        assessment = build_assessment_input(
            paper,
            text.extraction,
            text.canonical_text,
            rubric,
            configured,
            limit=limit,
            counter=counter,
            smoke_report_hash=None,
        )
        outcome = worker.assess(assessment)
        if outcome.lease_held_elsewhere:
            raise MeasurementError("another process holds a sampled paper's work")
        record = assessment.record
        committed = read_committed(
            artifacts,
            store,
            work_key(
                record.input_hash,
                record.rubric_hash,
                record.provider_configuration_hash,
            ),
        )
        if committed is None:
            raise MeasurementError("a sampled paper's attempt was not committed")
        attempt, result = committed
        response = None
        if attempt.response_artifact_hash is not None:
            with artifacts.open_verified(attempt.response_artifact_hash) as stream:
                response = stream.read()
        observations.append(
            SmokeObservation(
                candidate.family_id,
                result,
                record.coverage,
                _elapsed_ms(attempt.requested_at, attempt.completed_at),
                _cost_micros(config, result, response),
            )
        )
    identity = next(
        (
            item.result.provider_identity
            for item in observations
            if item.result.provider_identity is not None
        ),
        configured,
    )
    report = smoke_test_rubric(
        sample,
        observations,
        rubric=rubric.record,
        provider_identity=identity,
        owner_review=None,
    )
    return SmokeRun(sample, report)


def _put(artifacts: ArtifactStore, raw: bytes) -> str:
    artifact_hash = sha256_hex(raw)
    artifacts.commit(
        (raw,),
        expected_hash=artifact_hash,
        expected_length=len(raw),
        maximum_length=_MAX_RECORD_BYTES,
    )
    return artifact_hash


def store_run(artifacts: ArtifactStore, run: SmokeRun) -> str:
    """Store the sample, then the report; return the report's artifact hash.

    The sample's artifact hash is the report's ``sample_hash``, so the report
    resolves to the papers it names.
    """

    _put(artifacts, run.sample.to_canonical_json())
    report_hash = _put(artifacts, canonical_json(run.report.to_dict()))
    if report_hash != run.report.report_hash():
        raise MeasurementError("stored report bytes differ from the report")
    return report_hash


def summary_lines(report_hash: str, run: SmokeRun, *, dry_run: bool) -> list[str]:
    report = run.report
    lines = [
        f"report {report_hash}",
        f"sample {report.sample_hash} papers {report.sample_size} "
        f"shortfall {len(report.shortfall_weeks)}",
    ]
    if dry_run:
        lines.append("dry run: recorded fixture responses; this is not a smoke test")
    for field in report.fields:
        counts = " ".join(f"{label}={count}" for label, count in field.category_counts)
        lines.append(
            f"{field.field_id} valid {field.valid_count}/{report.sample_size} "
            f"{'pass' if field.passed else 'fail'} {counts}"
        )
    reasons = report.fields[0].unavailable_reasons if report.fields else ()
    if reasons:
        lines.append(
            "unavailable " + " ".join(f"{name}={count}" for name, count in reasons)
        )
    lines.append(
        f"latency_ms total {report.latency_ms_total} max {report.latency_ms_max} "
        f"cost_micros {report.cost_micros_total}"
    )
    lines.append("owner review: pending; activation stays refused until recorded")
    return lines


def _paper_artifacts(raw: bytes) -> dict[str, str | None]:
    try:
        value = canonical_loads(raw)
    except CanonicalJsonError as error:
        raise MeasurementError("candidates file is not JSON") from error
    items = value.get("candidates") if isinstance(value, dict) else None
    if not isinstance(items, list):
        raise MeasurementError("candidates file must hold a candidates array")
    found: dict[str, str | None] = {}
    for item in items:
        family = item.get("paper_family_id") if isinstance(item, dict) else None
        if not isinstance(family, str):
            raise MeasurementError("a candidate names no family")
        assert isinstance(item, dict)
        paper_hash = item.get("paper_artifact_hash")
        found[family] = paper_hash if isinstance(paper_hash, str) else None
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--release", required=True, help="CorpusRelease hash")
    parser.add_argument("--rubric", required=True, help="rubric version")
    parser.add_argument(
        "--candidates", type=Path, required=True, help="the release's candidates file"
    )
    parser.add_argument("--text", type=Path, required=True, help="bin/export-text dir")
    parser.add_argument(
        "--provider", type=Path, required=True, help="provider configuration JSON"
    )
    parser.add_argument("--dsn", help="storage holding the Jev work and limits")
    args = parser.parse_args(argv)
    credential = os.environ.get(CREDENTIAL_ENV) or None
    if credential is not None and args.dsn is None:
        parser.error("a live run needs --dsn for the Jev work store and limits")

    rubric = rubric_for(args.rubric)
    config = provider_config(args.provider.read_bytes())
    corpus = ArtifactStore(args.state / "artifacts")
    with corpus.open_verified(args.release) as stream:
        release = CorpusRelease.from_json(stream.read())
    sampled = {item.family_id for item in draw_sample(release).selected}
    papers = load_papers(
        [row for row in release.rows if row.paper_family_id in sampled],
        paper_artifacts=_paper_artifacts(args.candidates.read_bytes()),
        artifacts=corpus,
        text_dir=args.text,
    )

    store: JevWorkStore
    if credential is None:
        print(
            f"{CREDENTIAL_ENV} is not set: dry run on the recorded fixture",
            file=sys.stderr,
        )
        artifacts = ArtifactStore(args.state / "jev-smoke-dry-run" / "artifacts")
        store = MemoryWorkStore()
        transport: Any = RecordedTransport(
            RECORDED_RESPONSES[rubric.version].read_bytes()
        )
    else:
        from research_agent.storage.assessments import JevWorkRepository
        from research_agent.storage.database import Database
        from research_agent.storage.migrate import migrate

        database = Database(args.dsn)
        migrate(database)
        artifacts = corpus
        store = JevWorkRepository(database)
        transport = HttpSystemOneTransport(config.endpoint, credential)
    worker = JevWorker(
        store=store,
        artifacts=artifacts,
        transport=transport,
        config=config,
        rubric=rubric,
    )
    run = run_smoke(
        release,
        papers,
        rubric=rubric,
        config=config,
        worker=worker,
        store=store,
        artifacts=artifacts,
    )
    report_hash = store_run(artifacts, run)
    for line in summary_lines(report_hash, run, dry_run=credential is None):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
