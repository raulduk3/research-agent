"""SDD-RD-22: `bin/jev-smoke` draws the sample, runs it and stores the report."""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from research_agent.artifacts.store import ArtifactStore
from research_agent.assessments.rubric import Rubric
from research_agent.contracts import ProducerVersion
from research_agent.contracts.canonical import sha256_hex
from research_agent.contracts.corpus import CorpusRelease, CorpusRow
from research_agent.contracts.learning import PRIMARY_CATEGORY_IDS
from research_agent.contracts.papers import ExternalIdentifier, PaperVersionRecord
from research_agent.contracts.passages import (
    ExtractedBlock,
    ExtractionRecord,
    SourceLocator,
)
from research_agent.ingest.jev import AmbiguousTimeout, JevWorker
from research_agent.measurement import MeasurementError
from research_agent.measurement.jev_smoke import (
    CREDENTIAL_ENV,
    RECORDED_RESPONSES,
    MemoryWorkStore,
    draw_sample,
    main,
    provider_config,
    rubric_for,
    run_smoke,
    smoke_candidates,
    smoke_weeks,
)
from research_agent.models.batch import PaperText, paper_text_path

_STAMP = "2026-09-21T00:00:00.000000Z"
_META = (1, (), ProducerVersion("a" * 64, "b" * 40, 1), "c" * 64, _STAMP)
_FIRST_MONDAY = datetime(2026, 1, 5, tzinfo=timezone.utc)
#: The freeze falls at the start of week index 21: weeks 0 to 20 are complete.
_FREEZE = _FIRST_MONDAY + timedelta(weeks=21)
_RECORDED_V2 = RECORDED_RESPONSES["jev-rubric-v2"].read_bytes()
_TOKENS = json.loads(_RECORDED_V2)["usage"]["input_tokens"]
_PRICE = 42000
_MAX_TOKENS = 32768
_KEY = "test-credential-4b1d"


def _utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _uuid(n: int) -> str:
    return f"{n:08x}-0000-4000-8000-000000000000"


def _row(
    n: int, week_index: int, category: str, reasons: tuple[str, ...] = ()
) -> CorpusRow:
    t0 = _FIRST_MONDAY + timedelta(weeks=week_index, hours=12)
    return CorpusRow(
        _uuid(n),
        _uuid(100000 + n),
        _utc(t0),
        t0.strftime("%G-W%V"),
        category,
        n,
        None,
        (None, None, None),
        (False, False, False),
        "excluded" if reasons else "pilot",
        reasons,
        3,
        (category,),
        1,
    )


def _release() -> CorpusRelease:
    rows = [
        _row(week * 10 + index, week, category)
        for week in range(22)
        for index, category in enumerate(PRIMARY_CATEGORY_IDS)
    ]
    # An alias of an eligible family is never a candidate.
    rows.append(_row(900, 20, "cs.AI", ("family_alias",)))
    rows.sort(key=lambda row: row.selection_rank)
    return CorpusRelease(
        *_META,
        "acquisition_pilot",
        "d" * 64,
        "e" * 64,
        20260920,
        _utc(_FREEZE),
        _utc(_FREEZE),
        100,
        "f" * 64,
        tuple(rows),
        100 - len(rows),
        "1" * 64,
        "2" * 64,
        (),
        None,
    )


def _paper(row: CorpusRow) -> PaperVersionRecord:
    return PaperVersionRecord(
        1,
        ("e" * 64,),
        ProducerVersion("f" * 64, "1" * 40, 1),
        "2" * 64,
        "2026-01-02T00:00:00.000000Z",
        row.paper_family_id,
        row.original_version_id,
        (ExternalIdentifier("arxiv", "2401.01234v1"),),
        True,
        row.t0,
        None,
        ("a" * 64,),
        ("b" * 64,),
        "Title",
        "Abstract",
        ("author",),
        row.source_subfield,
        "c" * 64,
        "latex",
        "v1",
        3,
        row.categories or (),
        1,
    )


def _text(version_id: str) -> PaperText:
    body = f"We propose a method for paper {version_id} and compare it with baselines."
    extraction = ExtractionRecord(
        paper_version_id=version_id,
        source_hash="a" * 64,
        extractor_manifest_hash="b" * 64,
        text_hash=sha256_hex(body.encode("utf-8")),
        text_codepoints=len(body),
        blocks=(
            ExtractedBlock(
                block_id="b0",
                section_path=("body",),
                section_order=0,
                block_order=0,
                kind="body",
                char_start=0,
                char_end_exclusive=len(body),
                included_in_passages=True,
                omission_reason=None,
                locator=SourceLocator("a" * 64, "latex", None, None, None, None),
            ),
        ),
        coverage="complete",
        coverage_reasons=(),
        included_block_count=1,
        omitted_block_count=0,
        created_at="2026-01-01T00:00:00.000000Z",
    )
    return PaperText(
        version_id,
        "Title",
        "Abstract",
        sha256_hex(extraction.to_canonical_json()),
        body,
        extraction,
    )


def _provider(endpoint: str = "https://gateway.example/v1/systemone") -> bytes:
    return json.dumps(
        {
            "endpoint": endpoint,
            "configured_model": "typesafeai/jev-latest",
            "known_revisions": ["jev-1.13.0"],
            "capability_evidence_hash": "c" * 64,
            "max_input_tokens": _MAX_TOKENS,
            "prompt_price_micros_per_million_tokens": _PRICE,
            "daily_limit_micros": 2_000_000,
            "smoke_revision": None,
        },
        indent=2,
    ).encode()


def _put(store: ArtifactStore, raw: bytes) -> str:
    digest = sha256_hex(raw)
    store.commit(
        (raw,), expected_hash=digest, expected_length=len(raw), maximum_length=len(raw)
    )
    return digest


@dataclass
class _State:
    root: Path
    release: CorpusRelease
    release_hash: str
    missing_family: str

    def argv(self) -> list[str]:
        return [
            "--state", str(self.root / "state"),
            "--release", self.release_hash,
            "--rubric", "jev-rubric-v2",
            "--candidates", str(self.root / "candidates.json"),
            "--text", str(self.root / "text"),
            "--provider", str(self.root / "provider.json"),
        ]  # fmt: skip


def _state(root: Path, endpoint: str | None = None) -> _State:
    """A release in an artifact store, its candidates file and exported text.

    The first sampled family has a paper record but no exported text.
    """

    release = _release()
    store = ArtifactStore(root / "state" / "artifacts")
    release_hash = _put(store, release.to_canonical_json())
    missing = draw_sample(release).selected[0].family_id
    text_dir = root / "text"
    text_dir.mkdir()
    candidates = []
    for row in release.rows:
        paper = _paper(row)
        candidates.append(
            {
                "paper_family_id": row.paper_family_id,
                "original_version_id": row.original_version_id,
                "paper_artifact_hash": _put(store, paper.to_canonical_json()),
            }
        )
        if row.paper_family_id != missing:
            path = paper_text_path(text_dir, row.original_version_id)
            path.write_bytes(_text(row.original_version_id).to_canonical_json())
    (root / "candidates.json").write_text(json.dumps({"candidates": candidates}))
    (root / "provider.json").write_bytes(
        _provider(endpoint) if endpoint else _provider()
    )
    return _State(root, release, release_hash, missing)


def _report(store_root: Path, printed: str) -> tuple[str, dict[str, Any]]:
    report_hash = printed.splitlines()[0].removeprefix("report ")
    with ArtifactStore(store_root).open_verified(report_hash) as stream:
        return report_hash, json.loads(stream.read())


def _cost(tokens: int) -> int:
    return math.ceil(tokens * _PRICE / 1_000_000)


def test_weeks_are_the_latest_twenty_that_ended_by_the_freeze() -> None:
    release = _release()
    weeks = smoke_weeks(release)
    # Week index 21 ends after the freeze and never enters.
    expected = tuple(
        (_FIRST_MONDAY + timedelta(weeks=index)).strftime("%G-W%V")
        for index in range(20, 0, -1)
    )
    assert weeks == expected
    candidates = smoke_candidates(release)
    assert _uuid(900) not in {item.family_id for item in candidates}
    assert len(candidates) == 22 * 4


def test_dry_run_uses_the_fixture_and_keeps_its_report_apart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(CREDENTIAL_ENV, raising=False)
    state = _state(tmp_path)
    assert main(state.argv()) == 0
    printed = capsys.readouterr()
    assert "dry run" in printed.err
    assert "not a smoke test" in printed.out
    dry_root = tmp_path / "state" / "jev-smoke-dry-run" / "artifacts"
    report_hash, report = _report(dry_root, printed.out)
    # Nothing a dry run stores reaches the release's own artifact store.
    assert (
        not ArtifactStore(tmp_path / "state" / "artifacts")
        .path_for(report_hash)
        .exists()
    )

    sample = draw_sample(state.release)
    assert report["sample_size"] == 20 and report["shortfall_weeks"] == []
    with ArtifactStore(dry_root).open_verified(report["sample_hash"]) as stream:
        assert stream.read() == sample.to_canonical_json()
    assert report["rubric_hash"] == Rubric.launch().rubric_hash
    assert report["owner_review"] is None
    for item in report["fields"]:
        assert item["valid_count"] == 19 and item["passed"]
        assert item["unavailable_reasons"] == [["missing_input", 1]]
    assert report["input_coverage_counts"] == [
        ["complete", 19],
        ["partial", 0],
        ["unavailable", 1],
    ]
    assert report["cost_micros_total"] == 19 * _cost(_TOKENS)
    assert len(report["request_artifact_hashes"]) == 19
    assert f"{report['fields'][0]['field_id']} valid 19/20 pass" in printed.out


@dataclass
class _Scripted:
    """A transport that answers from a script, then with the recording."""

    script: list[Exception] = field(default_factory=list)
    calls: int = 0

    def post(self, body: bytes, *, timeout: float) -> tuple[int, bytes]:
        self.calls += 1
        if self.script:
            raise self.script.pop(0)
        return 200, _RECORDED_V2


def test_a_timeout_costs_its_worst_case_and_a_rerun_reuses_answers(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    store = ArtifactStore(tmp_path / "state" / "artifacts")
    config = provider_config((tmp_path / "provider.json").read_bytes())
    rubric = Rubric.launch()
    release = state.release
    sampled = {item.family_id for item in draw_sample(release).selected}
    papers = {
        row.paper_family_id: (_paper(row), _text(row.original_version_id))
        for row in release.rows
        if row.paper_family_id in sampled
        and row.paper_family_id != state.missing_family
    }
    work = MemoryWorkStore()
    transport = _Scripted([AmbiguousTimeout("read timed out")])

    def run() -> Any:
        worker = JevWorker(
            store=work, artifacts=store, transport=transport, config=config,
            rubric=rubric, sleep=lambda _: None,
        )  # fmt: skip
        return run_smoke(
            release, papers, rubric=rubric, config=config, worker=worker,
            store=work, artifacts=store,
        ).report  # fmt: skip

    first = run()
    reasons = dict(first.fields[0].unavailable_reasons)
    assert reasons == {"missing_input": 1, "timeout_ambiguous": 1}
    assert all(item.valid_count == 18 and item.passed for item in first.fields)
    assert first.cost_micros_total == config.worst_case_micros + 18 * _cost(_TOKENS)
    assert transport.calls == 19

    # The rerun sends only the timed-out paper again; 18 answers are reused.
    second = run()
    assert transport.calls == 20
    assert all(item.valid_count == 19 for item in second.fields)


def test_inputs_are_refused_before_any_request(tmp_path: Path) -> None:
    with pytest.raises(MeasurementError, match="no rubric"):
        rubric_for("jev-rubric-v9")
    body = json.loads(_provider())
    body["api_key"] = _KEY
    # A credential in a file is refused: it comes from the environment only.
    with pytest.raises(MeasurementError, match="must name exactly"):
        provider_config(json.dumps(body).encode())
    with pytest.raises(SystemExit):
        main([*_state(tmp_path).argv(), "--api-key", _KEY])


@dataclass
class _Endpoint:
    headers: list[dict[str, str]] = field(default_factory=list)
    url: str = ""


@pytest.fixture
def endpoint() -> Iterator[_Endpoint]:
    state = _Endpoint()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers["Content-Length"]))
            state.headers.append(dict(self.headers.items()))
            self.send_response(200)
            self.send_header("Content-Length", str(len(_RECORDED_V2)))
            self.end_headers()
            self.wfile.write(_RECORDED_V2)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}/v1/systemone"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def test_live_run_sends_the_environment_credential_and_stores_the_report(
    tmp_path: Path,
    endpoint: _Endpoint,
    postgres_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _state(tmp_path, endpoint.url)
    argv = [*state.argv(), "--dsn", postgres_dsn]
    monkeypatch.setenv(CREDENTIAL_ENV, _KEY)
    assert main(argv) == 0
    printed = capsys.readouterr().out
    assert "dry run" not in printed
    artifacts = tmp_path / "state" / "artifacts"
    report_hash, report = _report(artifacts, printed)
    assert len(endpoint.headers) == 19
    assert {item["Authorization"] for item in endpoint.headers} == {f"Bearer {_KEY}"}
    assert report["provider_identity"]["returned_model_identity"] == "jev-1.13.0"
    assert report["provider_identity"]["identity_kind"] == "immutable_revision"
    assert all(item["valid_count"] == 19 for item in report["fields"])
    # The credential travels in a header and is stored nowhere.
    for path in artifacts.rglob("*"):
        if path.is_file():
            assert _KEY.encode() not in path.read_bytes()

    # A rerun reuses every committed answer and reproduces the same report.
    assert main(argv) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"report {report_hash}"
    assert len(endpoint.headers) == 19


def test_live_run_needs_the_durable_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CREDENTIAL_ENV, _KEY)
    with pytest.raises(SystemExit):
        main(_state(tmp_path).argv())
