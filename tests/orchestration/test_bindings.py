"""Run bindings and the day's remaining spend against real storage (#285),
and the inputs ``bin/bindings`` prints for ``bin/daily`` (#317)."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from research_agent.artifacts import ArtifactStore
from research_agent.agents.model_client import AGENT_PROVIDER, AgentDeploymentManifest
from research_agent.contracts import canonical_loads
from research_agent.contracts.canonical import canonical_json, sha256_hex
from research_agent.contracts.primitives import ContractValidationError
from research_agent.orchestration.bindings import (
    DailyInputs,
    agent_model_manifest_hash,
    current_bindings,
    current_index_identities,
    main,
    remaining_spend,
)
from research_agent.orchestration.daily import _day_window, issued_runs, record_runs
from research_agent.orchestration.stamps import build_run_stamp
from research_agent.platform.builds import ObservedImage
from research_agent.platform.profile import (
    BudgetGroup,
    DisabledCapabilities,
    EvaluationGroup,
    LaunchProfile,
    ModelGroup,
    PrivacyGroup,
    RecoveryGroup,
    RunGroup,
    RuntimeGroup,
    SourceGroup,
    StorageGroup,
)
from research_agent.snapshots.documents import SnapshotDocuments
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.client import StorageClient
from research_agent.storage.database import Database
from research_agent.storage.errors import UnavailableInput

sys.path.insert(0, str(Path(__file__).parents[1] / "storage"))
from test_exclusions import World, identity, world  # noqa: E402
from test_settlements import backdate, repository, served, settle  # noqa: E402

pytestmark = pytest.mark.integration

__all__ = ["served", "world"]

AGENT_MODEL_MANIFEST = "8" * 64
IMAGES = (
    ObservedImage("reader", "9" * 64, {}),
    ObservedImage("storage", "6" * 64, {}),
)
DAY = "2026-09-15"


def _profile(*, funded: bool = True) -> LaunchProfile:
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
            daily_cap_usd="8",
            monthly_cap_usd="200",
            funded=funded,
        ),
        evaluation=EvaluationGroup(replay_integrity_verified=True),
        privacy=PrivacyGroup(retention_years=2),
        recovery=RecoveryGroup(backup_verified=True),
        disabled_capabilities=DisabledCapabilities(capability_ids=frozenset()),
    )


def test_bound_run_is_accepted_by_storage_with_the_profiles_budgets(
    world: World, artifact_root: Path
) -> None:
    profile = _profile()
    bindings = current_bindings(
        profile,
        agent_model_manifest_hash=AGENT_MODEL_MANIFEST,
        observed_images=IMAGES,
    )
    assert bindings.service_image_versions == {"reader": "9" * 64, "storage": "6" * 64}
    assert bindings.budgets == RunGroup().budgets()

    database = Database(world.dsn)
    documents = SnapshotDocuments(
        database, ArtifactRepository(database, ArtifactStore(artifact_root))
    )
    stamp = build_run_stamp(
        documents,
        genome_hash="f" * 64,
        seed=7,
        agent_model_manifest=bindings.agent_model_manifest,
        service_image_versions=bindings.service_image_versions,
        snapshot_hash=world.snapshot_hash,
        paper_version_ids=(),
    )
    run_id = uuid4()
    world.runs.execute(
        "create",
        identity=identity(),
        payload={
            "run_id": str(run_id),
            "slot": {
                "batch_id": world.sheet_hash,
                "paper_id": "p1",
                "configuration_id": str(uuid4()),
                "attempt": 0,
            },
            "genome_hash": stamp.genome_hash,
            "seed": stamp.seed,
            "snapshot_hash": stamp.snapshot_hash,
            "budgets": bindings.budgets,
            "allowed_tools": list(bindings.allowed_tools),
            "model_identity": stamp.model_identity(),
            "checkpoint_dates": [],
            "issued_question_ids": [],
        },
    )
    with psycopg.connect(world.dsn) as connection:
        row = connection.execute(
            "SELECT budgets, allowed_tools, model_identity FROM runs WHERE id=%s",
            (run_id,),
        ).fetchone()
    assert row is not None
    assert canonical_loads(bytes(row[0])) == profile.run.budgets()
    assert sorted(row[1]) == sorted(profile.run.allowed_tools)
    identity_row = canonical_loads(bytes(row[2]))
    assert identity_row["agent_model_manifest"] == AGENT_MODEL_MANIFEST
    assert set(identity_row["prediction_head_bundles"].values()) == {None}


def test_bindings_without_an_observed_image_refuse_with_a_named_reason() -> None:
    with pytest.raises(UnavailableInput, match="no_observed_service_images"):
        current_bindings(
            _profile(),
            agent_model_manifest_hash=AGENT_MODEL_MANIFEST,
            observed_images=(),
        )
    with pytest.raises(UnavailableInput, match="duplicate_service_role:reader"):
        current_bindings(
            _profile(),
            agent_model_manifest_hash=AGENT_MODEL_MANIFEST,
            observed_images=(IMAGES[0], ObservedImage("reader", "5" * 64, {})),
        )


def _settled(world: World, artifact_root: Path, at: str, cost: int | None) -> UUID:
    run_id = world.run(uuid4(), f"p-{uuid4().hex[:8]}")
    settle(repository(world, artifact_root), run_id)
    backdate(world.dsn, run_id, at, cost)
    return run_id


def test_remaining_spend_is_the_tighter_cap_less_settled_and_reserved_spend(
    world: World,
    artifact_root: Path,
    served: tuple[StorageClient, StorageClient],
) -> None:
    orchestrator, owner = served
    profile = _profile()
    reservation = profile.run.spend_micros

    _settled(world, artifact_root, f"{DAY}T09:00:00Z", 1_000_000)
    _settled(world, artifact_root, f"{DAY}T10:00:00Z", None)
    _settled(world, artifact_root, "2026-09-02T10:00:00Z", 150_000_000)
    # Day: 8 USD less 1 USD priced and one unpriced run at its reservation.
    assert remaining_spend(owner, profile, DAY) == 8_000_000 - 1_000_000 - reservation

    _settled(world, artifact_root, "2026-09-10T10:00:00Z", 48_000_000)
    # Month: 200 USD less 199 USD priced and the same unpriced reservation.
    assert remaining_spend(owner, profile, DAY) == (
        200_000_000 - 199_000_000 - reservation
    )

    _settled(world, artifact_root, "2026-09-11T10:00:00Z", 10_000_000)
    assert remaining_spend(owner, profile, DAY) == 0

    # Unfunded spends nothing and reads nothing: this client may not read costs.
    assert remaining_spend(orchestrator, _profile(funded=False), DAY) == 0


ENDPOINT = "https://api.z.ai/api/paas/v4/chat/completions"
REVISION = "a" * 40


def _pinned_profile() -> LaunchProfile:
    """The profile naming the provider the runner pins."""

    profile = _profile()
    return replace(profile, model=replace(profile.model, agent_provider=AGENT_PROVIDER))


def test_agent_model_manifest_hash_is_the_runners_pinned_manifest() -> None:
    profile = _pinned_profile()
    pinned = agent_model_manifest_hash(profile, endpoint=ENDPOINT, revision=REVISION)
    runner = AgentDeploymentManifest(
        provider=profile.model.agent_provider,
        model_id=profile.model.agent_model_id,
        endpoint=ENDPOINT,
        revision=REVISION,
        qualified=profile.model.agent_qualification_passed,
    )
    assert pinned == sha256_hex(canonical_json(runner.to_dict()))
    # The revision the provider reported is part of the identity.
    assert pinned != agent_model_manifest_hash(profile, endpoint=ENDPOINT)
    with pytest.raises(ContractValidationError, match="chat-completions"):
        agent_model_manifest_hash(profile, endpoint="https://api.z.ai/api/paas/v4")
    # A profile naming another provider is refused, as the runner refuses it.
    with pytest.raises(ContractValidationError, match="pinned launch provider"):
        agent_model_manifest_hash(_profile(), endpoint=ENDPOINT)


def test_index_identities_are_the_latest_snapshots_in_its_order(world: World) -> None:
    database = Database(world.dsn)
    assert current_index_identities(database) == ("e" * 64,)
    later = "7" * 64
    with psycopg.connect(world.dsn) as connection:
        connection.execute(
            """INSERT INTO snapshots(hash, paper_manifest_hash, sealed_at)
               SELECT decode(%s,'hex'), paper_manifest_hash,
                      sealed_at + interval '1 day'
               FROM snapshots WHERE hash = decode(%s,'hex')""",
            (later, world.snapshot_hash),
        )
        for ordinal, index_hash in enumerate(("d" * 64, "c" * 64)):
            connection.execute(
                """INSERT INTO snapshot_indexes(snapshot_hash, ordinal, index_hash)
                   VALUES(decode(%s,'hex'), %s, decode(%s,'hex'))""",
                (later, ordinal, index_hash),
            )
    # The later snapshot's identities, in its own order rather than sorted.
    assert current_index_identities(database) == ("d" * 64, "c" * 64)


def test_no_sealed_snapshot_refuses_index_identities(postgres_dsn: str) -> None:
    with pytest.raises(UnavailableInput, match="no_sealed_snapshot"):
        current_index_identities(Database(postgres_dsn))


def test_printed_bindings_are_the_inputs_bin_daily_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile_file = tmp_path / "profile.json"
    profile_file.write_bytes(canonical_json(_pinned_profile().to_dict()))
    images = tmp_path / "images.json"
    images.write_text(json.dumps({"storage": "6" * 64}))
    arguments = [
        "--profile",
        str(profile_file),
        "--endpoint",
        ENDPOINT,
        "--revision",
        REVISION,
        "--images",
        str(images),
        "--image",
        "reader=" + "9" * 64,
        "--index-identity",
        "e" * 64,
    ]
    assert main(arguments) == 0
    inputs = DailyInputs.from_dict(json.loads(capsys.readouterr().out))
    assert inputs.agent_model_manifest == agent_model_manifest_hash(
        _pinned_profile(), endpoint=ENDPOINT, revision=REVISION
    )
    assert {image.role: image.image_digest for image in inputs.observed_images} == {
        "storage": "6" * 64,
        "reader": "9" * 64,
    }
    assert inputs.index_identity_hashes == ("e" * 64,)

    # A role named twice is refused with its reason, and nothing is printed.
    assert main([*arguments, "--image", "storage=" + "5" * 64]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "duplicate_service_role:storage" in captured.err


def test_a_days_runs_are_listed_in_the_order_bin_daily_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "state"
    window = _day_window(state, DAY, DAY)
    # A day whose issue has not finished lists nothing and says so.
    assert main(["--runs", DAY, "--state", str(state)]) == 2
    assert f"day_not_issued:{DAY}" in capsys.readouterr().err

    order = (str(uuid4()), str(uuid4()), str(uuid4()))
    record_runs(state, DAY, order)
    assert main(["--runs", DAY, "--state", str(state)]) == 0
    assert tuple(capsys.readouterr().out.split()) == order
    assert issued_runs(state, DAY) == order
    # Recording the runs keeps the window a repeated day reuses.
    assert _day_window(state, DAY, None) == window
