"""The daily job cards its papers, issues their questions as sheets, and only
then seals the day's snapshot, with the requested papers it acquired pinned
beside the day's own, before it seals its batch.

Decision 0025: requested papers ride the daily worker and arXiv gate, after
the day's own documents and before the day's batch record is sealed, and
stay out of that batch record. #283's recommended grain: one sheet per
island per chunk of whole papers, and the day's snapshot sealed after the
day's sheets and pinned to each. Same real storage, worker and loopback
arXiv as the daily ingest tests, the real reader, embedding loop, card
assembly, sheet seal and snapshot seal; only the PDF text layer and the
model's forward pass stand in.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import RecordMeta, canonical_loads
from research_agent.contracts.primitives import ProducerVersion
from research_agent.ingest.daily import DayPass, run_once
from research_agent.ingest.pilot import PilotWorker, derived_uuid
from research_agent.ingest.pilot_local import local_storage, worker_principal
from research_agent.ingest.requests import AcquisitionReport, RequestReader
from research_agent.models.batch import PlatformIdentity
from research_agent.outcomes.targets import definitions as target_definitions
from research_agent.reader.extract import PdfPage
from research_agent.snapshots.compose import seal_next_snapshot
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository

from tests.ingest.test_requests import _Backend, _embedder, _Words  # noqa: E402
from tests.integration.corpus.test_daily_ingest import (
    IDENTITY,
    WINDOW,
    _remote,
    _sources,
)  # noqa: E402

pytestmark = pytest.mark.integration

DAY_PAPERS = ("2601.00001", "2601.00002", "2601.00003")
TARGETS = target_definitions(
    RecordMeta(
        1,
        (),
        ProducerVersion("a" * 64, "b" * 40, 1),
        "c" * 64,
        "2026-01-01T00:00:00.000000Z",
    )
)


def _pages(_pdf: bytes) -> Sequence[PdfPage]:
    """The text layer of the loopback arXiv's one-line PDF."""

    return (PdfPage(1, "A daily paper about forecasting citations early.", False),)


def test_the_days_snapshot_is_sealed_after_its_cards_and_sheets(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    events: list[str] = []
    sealed: list[tuple[tuple[dict[str, Any], ...], tuple[str, ...]]] = []
    store = ArtifactStore(artifact_root)
    sheets = SheetRepository(
        Database(postgres_dsn),
        store,
        producer=IDENTITY.producer,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    snapshots = SnapshotRepository(
        Database(postgres_dsn),
        store,
        producer=IDENTITY.producer,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    )
    with (
        _remote(tmp_path) as (_, port, context),
        local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):
        publish = storage.publish_spec

        def recording_publish(
            spec: dict[str, Any], inputs: tuple[str, ...] = ()
        ) -> str:
            kind = spec.get("kind", spec.get("stage"))
            if "head_predictions" in spec:
                kind = "card"
            events.append(str(kind))
            return publish(spec, inputs)

        storage.publish_spec = recording_publish  # type: ignore[method-assign]
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        # A requested paper the acquisition pass carded; its card is stored.
        acquired = AcquisitionReport(
            acquired=(
                {
                    "paper_family_id": str(uuid4()),
                    "paper_version_id": str(uuid4()),
                    "card_hash": publish({"acquired": True}),
                    "overview_hash": None,
                    "passage_index_hash": None,
                    "graph_hash": None,
                },
            )
        )

        def acquisition() -> AcquisitionReport:
            states = storage.database.transaction(
                lambda connection: connection.execute(
                    "SELECT DISTINCT state FROM jobs"
                ).fetchall()
            )
            assert states == [("committed",)]
            events.append("acquisition")
            return acquired

        def seal_sheet(questions: tuple[dict[str, Any], ...]) -> str:
            events.append("sheet")
            answer = sheets.execute(
                "seal",
                identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
                payload={"questions": list(questions)},
            )
            body = cast(dict[str, Any], canonical_loads(answer.body))
            return str(body["data"]["sheet_hash"])

        def seal_snapshot(
            items: tuple[dict[str, Any], ...], sheet_hashes: tuple[str, ...]
        ) -> str:
            events.append("snapshot")
            sealed.append((items, sheet_hashes))
            return seal_next_snapshot(
                snapshots,
                publish,
                principal_id=uuid4(),
                prior_items=(),
                acquired=items,
                index_identity_hashes=("e" * 64,),
                sheet_hashes=sheet_hashes,
            )

        backend = _Backend()
        day = DayPass(
            RequestReader(
                storage,
                worker,
                identities={},
                work_dir=tmp_path / "work",
                namespace_dir=tmp_path / "index",
                embedder=_embedder(backend),
                tokenizer=_Words(),
                platform=PlatformIdentity("cpu", "test", "0", {"torch": "0"}),
                pdf_reader=_pages,
            ),
            TARGETS,
            seal_sheet,
        )

        def once() -> Any:
            return run_once(
                storage,
                window=WINDOW,
                worker=worker,
                acquisition=acquisition,
                day=day,
                seal_snapshot=seal_snapshot,
            )

        run = once()
        first_events = list(events)
        cards = {
            family: storage.report(i["card_hash"])
            for family, i in run.cards.items.items()
        }
        # A second run over the sealed day cards nothing again and issues and
        # seals the same sheets and the same snapshot.
        events.clear()
        again = once()

    assert "documents" in first_events[: first_events.index("acquisition")]
    assert (
        first_events.index("acquisition")
        < first_events.index("card")
        < first_events.index("sheet")
    )
    last_card = len(first_events) - first_events[::-1].index("card") - 1
    assert last_card < first_events.index("sheet")
    assert (
        max(i for i, event in enumerate(first_events) if event == "sheet")
        < first_events.index("snapshot")
        < first_events.index("daily_ingest_batch")
    )
    assert run.acquired is acquired
    batch_families = {f["family_id"] for f in run.batch["eligible_families"]}
    assert batch_families == set(DAY_PAPERS)

    # Every committed paper of the day has one card, as a first-public paper
    # nobody requested.
    assert run.cards is not None and run.cards.failed == ()
    assert set(run.cards.items) == set(DAY_PAPERS)
    for family, card in cards.items():
        assert card["paper_family_id"] == str(derived_uuid("gate-paper-family", family))
        assert card["head_feature_eligible"] is True
        for head in card["head_predictions"]:
            assert head["forecast_eligibility"] == "eligible"
            assert head["unavailable_reason"] == "no_active_bundle"
            assert head["horizon_end"] == "2027-01-02T09:00:00.000000Z"
    assert "card" not in events
    assert again.cards is not None and again.cards.items == run.cards.items

    # Three papers of three questions: one cs sheet, the same on both runs.
    assert len(run.sheet_hashes) == 1
    assert again.sheet_hashes == run.sheet_hashes
    assert sealed[1] == sealed[0]

    # The seal received the day's papers and the acquired one, and the
    # acquired paper is pinned in the day's snapshot beside them.
    items, sheet_hashes = sealed[0]
    assert sheet_hashes == run.sheet_hashes
    assert items == (*run.cards.items.values(), *acquired.acquired)
    with psycopg.connect(postgres_dsn) as connection:
        pinned = connection.execute(
            """SELECT paper_version_id::text FROM snapshot_items
               WHERE snapshot_hash=decode(%s,'hex')""",
            (run.snapshot_hash,),
        ).fetchall()
        bound = connection.execute(
            """SELECT encode(sheet_hash,'hex') FROM snapshot_sheets
               WHERE snapshot_hash=decode(%s,'hex')""",
            (run.snapshot_hash,),
        ).fetchall()
        questions = connection.execute(
            "SELECT count(*) FROM sheet_questions"
        ).fetchone()
    assert sorted(row[0] for row in pinned) == sorted(
        i["paper_version_id"] for i in items
    )
    assert [row[0] for row in bound] == list(run.sheet_hashes)
    assert questions == (len(DAY_PAPERS) * len(TARGETS),)
    assert backend.calls >= 1


def test_a_day_without_a_sheet_seals_no_snapshot(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    tls = tmp_path / "tls"
    calls: list[object] = []
    with (
        _remote(tmp_path) as (_, port, context),
        local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):
        run = run_once(
            storage,
            window=WINDOW,
            worker=PilotWorker(
                storage.client,
                worker_id=worker_principal(tls),
                identity=IDENTITY,
                sources=_sources(port, context),
            ),
            acquisition=lambda: AcquisitionReport(),
            seal_snapshot=lambda items, sheets: str(calls.append((items, sheets))),
        )
    assert calls == []
    assert run.snapshot_hash is None and run.sheet_hashes == ()
