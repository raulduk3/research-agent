"""One day issued twice through real storage: one snapshot, one sheet and one
run record per sampled paper and genome, and nothing new the second time.

The daily ingest's real storage, worker and loopback arXiv, the real reader,
embedding loop, card assembly, sheet, snapshot and run owners, the real
population store and settlement cost read. Only the PDF text layer and the
model's forward pass stand in (as in the daily acquisition test).
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import RecordMeta
from research_agent.contracts.primitives import ProducerVersion
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.ingest.pilot import PilotWorker
from research_agent.ingest.pilot_local import local_storage, worker_principal
from research_agent.ingest.requests import (
    AcquisitionReport,
    RequestReader,
    acquire_requests,
)
from research_agent.models.batch import PlatformIdentity
from research_agent.orchestration.bindings import current_bindings
from research_agent.orchestration.daily import (
    DayRepositories,
    IssuedDay,
    LocalCosts,
    LocalRequestLedger,
    issue_day,
    main,
)
from research_agent.outcomes.targets import definitions as target_definitions
from research_agent.platform.builds import ObservedImage
from research_agent.platform.profile import (
    BudgetGroup,
    DisabledCapabilities,
    EvaluationGroup,
    LaunchProfile,
    ModelGroup,
    PrivacyGroup,
    RecoveryGroup,
    RuntimeGroup,
    SourceGroup,
    StorageGroup,
)
from research_agent.reader.extract import PdfPage
from research_agent.snapshots.documents import SnapshotDocuments
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.database import Database
from research_agent.storage.requests import PaperRequestRepository
from research_agent.storage.runs import RunRepository
from research_agent.storage.settlements import SettlementRepository
from research_agent.storage.sheets import SheetRepository
from research_agent.storage.snapshots import SnapshotRepository

sys.path.insert(0, str(Path(__file__).parents[1] / "integration" / "corpus"))
sys.path.insert(0, str(Path(__file__).parents[1]))
from ingest.test_requests import _Backend, _embedder, _Words  # noqa: E402
from test_daily_ingest import IDENTITY, WINDOW, _remote, _sources  # noqa: E402

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
KEYS = {
    "producer": IDENTITY.producer,
    "config_hash": "c" * 64,
    "retention_policy_hash": "d" * 64,
}


def _profile() -> LaunchProfile:
    # USD 0.04 a day at the USD 0.01 reservation covers four runs: two of
    # the three papers for two genomes.
    return LaunchProfile(
        profile_version="launch-v2",
        runtime=RuntimeGroup(python_version="3.12.12", uv_version="0.8.22"),
        storage=StorageGroup(
            postgres_version="17",
            backup_endpoint_bound=True,
            anchor_endpoint_bound=True,
        ),
        model=ModelGroup(
            agent_model_id="glm-5.3-flash",
            agent_provider="z.ai",
            embedding_model_revision="d556a88e332558790b210f7bdbe87da2fa94a8d8",
            agent_qualification_passed=True,
        ),
        source=SourceGroup(licensed_source_ids=frozenset({"arxiv"})),
        budget=BudgetGroup(
            paid_execution_enabled=True,
            daily_cap_usd="0.04",
            monthly_cap_usd="200",
            funded=True,
        ),
        evaluation=EvaluationGroup(replay_integrity_verified=True),
        privacy=PrivacyGroup(retention_years=2),
        recovery=RecoveryGroup(backup_verified=True),
        disabled_capabilities=DisabledCapabilities(capability_ids=frozenset()),
    )


def _genome(lineage: str, prompt: str) -> Genome:
    return Genome(
        lineage_id=lineage,
        island="cs",
        infra_hash="1" * 64,
        emphasis={
            "prompt": prompt,
            "scan_policy": "scan",
            "read_policy": "read",
            "probability_assignment_rule": "rule",
        },
        founder=lineage == "founder",
    )


def _pages(_pdf: bytes) -> Sequence[PdfPage]:
    return (PdfPage(1, "A daily paper about forecasting citations early.", False),)


def _kinds(dsn: str) -> Counter[str]:
    with psycopg.connect(dsn) as connection:
        rows = connection.execute("SELECT event_kind FROM ledger_records").fetchall()
    return Counter(str(row[0]) for row in rows)


def test_a_day_issued_twice_seals_once_and_issues_each_run_once(
    postgres_dsn: str, artifact_root: Path, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    store = ArtifactStore(artifact_root)
    population = PopulationStore(database, store, **KEYS)
    genomes = (_genome("founder", "evidence first"), _genome("second", "skim"))
    for genome in genomes:
        population.record_seed(
            configuration_id=uuid4(),
            genome=genome,
            profile_hash="f" * 64,
            command_id=uuid4(),
        )
    profile = _profile()
    bindings = current_bindings(
        profile,
        agent_model_manifest_hash="8" * 64,
        observed_images=(
            ObservedImage("reader", "9" * 64, {}),
            ObservedImage("storage", "6" * 64, {}),
        ),
    )
    repositories = DayRepositories(
        SheetRepository(database, store, **KEYS),
        SnapshotRepository(database, store, **KEYS),
        RunRepository(database, store, **KEYS),
        population,
        SnapshotDocuments(database, ArtifactRepository(database, store)),
    )
    ledger = LocalRequestLedger(PaperRequestRepository(database, store, **KEYS))
    tls = tmp_path / "tls"
    issued: list[IssuedDay] = []
    kinds: list[Counter[str]] = []
    with (
        _remote(tmp_path) as (_, port, context),
        local_storage(
            dsn=postgres_dsn,
            artifact_root=artifact_root,
            tls_directory=tls,
            identity=IDENTITY,
        ) as storage,
    ):
        worker = PilotWorker(
            storage.client,
            worker_id=worker_principal(tls),
            identity=IDENTITY,
            sources=_sources(port, context),
        )
        reader = RequestReader(
            storage,
            worker,
            identities={},
            work_dir=tmp_path / "work",
            namespace_dir=tmp_path / "index",
            embedder=_embedder(_Backend()),
            tokenizer=_Words(),
            platform=PlatformIdentity("cpu", "test", "0", {"torch": "0"}),
            pdf_reader=_pages,
        )

        def acquisition() -> AcquisitionReport:
            return acquire_requests(ledger, reader)

        for _ in range(2):
            issued.append(
                issue_day(
                    storage,
                    window=WINDOW,
                    worker=worker,
                    reader=reader,
                    targets=TARGETS,
                    repositories=repositories,
                    index_identity_hashes=("e" * 64,),
                    bindings=bindings,
                    profile=profile,
                    costs=LocalCosts(SettlementRepository(database, store, **KEYS)),
                    acquisition=acquisition,
                )
            )
            kinds.append(_kinds(postgres_dsn))

    first, again = issued
    daily = first.daily
    assert daily.snapshot_hash is not None and daily.cards is not None
    assert set(daily.cards.items) == set(DAY_PAPERS)

    # One sealed snapshot and one sheet: three papers of three questions.
    with psycopg.connect(postgres_dsn) as connection:
        snapshots = connection.execute(
            "SELECT encode(hash,'hex') FROM snapshots"
        ).fetchall()
        sheets = connection.execute("SELECT encode(hash,'hex') FROM sheets").fetchall()
        runs = connection.execute(
            """SELECT id::text, encode(batch_id,'hex'), paper_id,
                      configuration_id::text, attempt, encode(snapshot_hash,'hex'),
                      issued_question_ids
               FROM runs"""
        ).fetchall()
        questions = connection.execute(
            "SELECT question_id::text FROM sheet_questions"
        ).fetchall()
        configurations = connection.execute(
            "SELECT configuration_id::text FROM genomes"
        ).fetchall()
    assert snapshots == [(daily.snapshot_hash,)]
    assert [row[0] for row in sheets] == list(daily.sheet_hashes)
    assert len(daily.sheet_hashes) == 1

    # The spend covers two papers for both genomes; the third gets no run.
    island = first.islands["cs"]
    assert island.configurations == 2
    assert island.remaining_spend_micros == 40_000
    assert island.sample.coverage == 2
    assert len(island.sample.excluded_family_ids) == 1
    sampled = {
        daily.cards.items[family]["paper_family_id"]
        for family in island.sample.sampled_family_ids
    }
    excluded = daily.cards.items[island.sample.excluded_family_ids[0]]
    slots = Counter((row[2], row[3]) for row in runs)
    assert set(slots) == {
        (paper, str(row[0])) for paper in sampled for row in configurations
    }
    assert set(slots.values()) == {1}
    assert excluded["paper_family_id"] not in {row[2] for row in runs}
    # Each paper's runs carry that paper's own questions, and no other's.
    by_paper: dict[str, set[frozenset[str]]] = {}
    for row in runs:
        by_paper.setdefault(row[2], set()).add(frozenset(map(str, row[6])))
    assert all(len(sets) == 1 for sets in by_paper.values())
    (one, two) = (next(iter(sets)) for sets in by_paper.values())
    assert not one & two
    assert one | two <= {str(row[0]) for row in questions}
    for _run_id, batch_id, _paper, _configuration, attempt, snapshot, ids in runs:
        assert batch_id == daily.sheet_hashes[0]
        assert snapshot == daily.snapshot_hash
        assert attempt == 0
        assert len(ids) == len(TARGETS)

    # The second call issues nothing new and reports what exists.
    assert first.created == 4 and again.created == 0
    assert sorted(first.run_ids) == sorted(row[0] for row in runs)
    assert again.run_ids == first.run_ids

    # The run order is dispatch order: earliest paper seal deadline, then the
    # slot's own (batch, paper, configuration, attempt), whatever the draw's.
    opened = {
        daily.cards.items[item["family_id"]]["paper_family_id"]: item["first_public_at"]
        for item in daily.batch["eligible_families"]
        if item["family_id"] in daily.cards.items
    }
    by_slot = sorted(
        runs, key=lambda row: (opened[row[2]], row[1], row[2], row[3], row[4])
    )
    assert first.run_order == tuple(row[0] for row in by_slot)
    assert again.run_order == first.run_order
    assert again.daily.snapshot_hash == daily.snapshot_hash
    assert again.daily.sheet_hashes == daily.sheet_hashes
    assert again.islands["cs"].sample == island.sample
    for kind in ("sheet_sealed", "snapshot_sealed", "run_created"):
        assert kinds[1][kind] == kinds[0][kind], kind
    assert kinds[0]["run_created"] == 4


@pytest.mark.parametrize(
    "flag",
    (
        ["--agent-model-manifest", "8" * 64],
        ["--image", "storage=" + "6" * 64],
        ["--index-identity", "e" * 64],
    ),
)
def test_bindings_file_replaces_the_three_flags_rather_than_merging(
    tmp_path: Path, flag: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["--state", str(tmp_path / "state"), "--dsn", "unused"]
    arguments += ["--profile", str(tmp_path / "profile.json")]
    with pytest.raises(SystemExit) as refused:
        main([*arguments, "--bindings", str(tmp_path / "bindings.json"), *flag])
    assert refused.value.code == 2
    assert "--bindings replaces" in capsys.readouterr().err
    with pytest.raises(SystemExit) as missing:
        main(arguments)
    assert missing.value.code == 2
    # Refused before anything is issued or recorded.
    assert not (tmp_path / "state").exists()
