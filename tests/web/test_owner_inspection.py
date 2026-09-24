"""The owner session serves the inspector's reads and guards the digest (#255)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient


from tests.storage.test_digests import _hash, entry, store_payload  # noqa: E402
from tests.storage.test_http import Authorization, Jobs, _tls_material  # noqa: E402
from tests.web.api_contract import check  # noqa: E402

from research_agent.artifacts import ArtifactStore
from research_agent.contracts import ProducerVersion, sha256_hex
from research_agent.evolution.genome import Genome
from research_agent.evolution.population import PopulationStore
from research_agent.storage.actions import OwnerActions
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.client import StorageClient, StorageClientError
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.digests import DigestRepository
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.owners import OwnerRepository
from research_agent.storage.queries import InspectorQueries
from research_agent.storage.raters import RaterRepository
from research_agent.storage.ratings import RatingRepository
from research_agent.web.actions.app import ActionsAppConfig, create_app
from research_agent.web.auth import OwnerDirectory, hash_credential

pytestmark = pytest.mark.integration

PRODUCER = ProducerVersion("a" * 64, "b" * 40, 1)
SETTINGS = {
    "producer": PRODUCER,
    "config_hash": "c" * 64,
    "retention_policy_hash": "d" * 64,
}
OWNER_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
OWNER_RATER_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
OTHER_RATER_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
CREDENTIAL = "owner-credential-for-tests"
OWNER_SCOPES = frozenset({"owner:admit", "owner:seed", "owner:retire", "owner:read"})
INSPECTOR_SCOPES = frozenset(
    {
        "runs:read",
        "submissions:read",
        "manifests:read",
        "configurations:read",
        "forecasts:read",
        "digests:provenance",
        "ratings:rated",
    }
)


@dataclass
class Owner:
    client: TestClient
    configuration_id: UUID
    digest_hash: str
    rated_entry: UUID
    unrated_entry: UUID
    directory: OwnerDirectory
    ratings: RatingRepository
    inspector: StorageClient
    connect: Callable[[str, frozenset[str]], StorageClient]
    artifacts: ArtifactRepository


def _paper(entry_id: UUID) -> str:
    return _hash(f"paper-{entry_id}")


def _provision(raters: RaterRepository, rater_id: UUID, island: str) -> None:
    raters.execute(
        "provision",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "rater_id": str(rater_id),
            "island": island,
            "salt": "a" * 32,
            "credential_hash": "b" * 64,
        },
    )


def _rate(
    ratings: RatingRepository,
    rater_id: UUID,
    entry_id: UUID,
    paper_hash: str | None = None,
) -> None:
    ratings.execute(
        "record",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "rater_id": str(rater_id),
            "paper_hash": paper_hash or _paper(entry_id),
            "digest_entry_id": str(entry_id),
            "value": "like",
        },
    )


@pytest.fixture
def owner(postgres_dsn: str, artifact_root: Path, tmp_path: Path) -> Iterator[Owner]:
    database, store = Database(postgres_dsn), ArtifactStore(artifact_root)
    owners = OwnerRepository(database, store, **SETTINGS)
    salt, credential_hash = hash_credential(CREDENTIAL)
    owners.execute(
        "provision",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "owner_id": str(OWNER_ID),
            "salt": salt,
            "credential_hash": credential_hash,
        },
    )
    configuration_id = uuid4()
    PopulationStore(database, store, **SETTINGS).record_seed(
        configuration_id=configuration_id,
        genome=Genome(
            lineage_id="lineage-1",
            island="cs",
            infra_hash="b" * 64,
            emphasis={
                "prompt": "prompt",
                "scan_policy": "scan",
                "read_policy": "read",
                "probability_assignment_rule": "one sample",
            },
            founder=True,
        ),
        profile_hash="a" * 64,
        command_id=uuid4(),
    )
    digests = DigestRepository(database, store, **SETTINGS)
    rated_entry, unrated_entry = uuid4(), uuid4()
    payload = store_payload(
        entries=(
            entry(rated_entry, origin="population", position=0),
            entry(unrated_entry, origin="service", position=1),
        )
    )
    digests.execute(
        "store",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload=payload,
    )
    raters = RaterRepository(database, store, **SETTINGS)
    _provision(raters, OWNER_RATER_ID, "cs")
    _provision(raters, OTHER_RATER_ID, "quant_ph")
    # The other rater rates the unrated entry's paper in its own island's digest.
    other_entry = uuid4()
    digests.execute(
        "store",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload=store_payload(
            island="quant-ph",
            entries=(entry(other_entry, paper_hash=_paper(unrated_entry)),),
        ),
    )
    ratings = RatingRepository(database, store, **SETTINGS)
    _rate(ratings, OWNER_RATER_ID, rated_entry)
    artifacts = ArtifactRepository(database, store)
    _rate(ratings, OTHER_RATER_ID, other_entry, _paper(unrated_entry))

    server_context, _client, fingerprint, _wrong, inspector_fingerprint, _none = (
        _tls_material(tmp_path)
    )
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {
            fingerprint: ServiceCapability(uuid4(), "owner", OWNER_SCOPES),
            inspector_fingerprint: ServiceCapability(
                uuid4(), "inspector", INSPECTOR_SCOPES
            ),
        },
        tls_context=server_context,
        authorization=Authorization(),
        queries=InspectorQueries(database, store),
        digests=digests,
        ratings=ratings,
        owners=OwnerActions(database, store, **SETTINGS),
        artifacts=artifacts,
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        host, port = httpd.server_address[:2]

        def storage_client(certificate: str, scopes: frozenset[str]) -> StorageClient:
            return StorageClient(
                connect_host=str(host),
                port=int(port),
                server_hostname="localhost",
                ca_file=tmp_path / "ca.pem",
                client_cert_file=tmp_path / f"{certificate}.pem",
                client_key_file=tmp_path / f"{certificate}.key",
                scopes=scopes,
                timeout_seconds=10,
            )

        inspector = storage_client("wrong", INSPECTOR_SCOPES)
        app = create_app(
            ActionsAppConfig(
                actions=storage_client("client", OWNER_SCOPES),
                directory=OwnerDirectory(owners),
                inspector=inspector,
                owner_rater_id=OWNER_RATER_ID,
            )
        )
        client = TestClient(app, base_url="https://testserver", follow_redirects=False)
        yield Owner(
            client,
            configuration_id,
            payload["digest_hash"],
            rated_entry,
            unrated_entry,
            OwnerDirectory(owners),
            ratings,
            inspector,
            storage_client,
            artifacts,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def sign_in(owner: Owner) -> None:
    response = owner.client.post("/login", data={"credential": CREDENTIAL})
    assert response.status_code == 303


def test_no_inspector_read_is_served_without_an_owner_session(owner: Owner) -> None:
    for path in (
        "/agents",
        f"/runs/{uuid4()}",
        f"/models/{'a' * 64}",
        f"/api/v1/digests/{owner.digest_hash}",
    ):
        assert owner.client.get(path).status_code == 401


def test_the_islands_read_counts_the_seeded_genome_under_the_owner_session(
    owner: Owner,
) -> None:
    assert owner.client.get("/api/v1/islands").status_code == 401
    sign_in(owner)
    data = check(
        owner.client.get("/api/v1/islands"), "actions", "GET", "/api/v1/islands"
    )
    assert data["islands"]["items"] == [
        {
            "island": "cs",
            "genomes": 1,
            "founders": 1,
            "lineages": 1,
            "runs": 0,
            "last_run_at": None,
        }
    ]


def test_the_reports_read_lists_each_seeded_island_week_under_the_owner_session(
    owner: Owner,
) -> None:
    assert owner.client.get("/api/v1/reports").status_code == 401
    sign_in(owner)
    data = check(
        owner.client.get("/api/v1/reports"), "actions", "GET", "/api/v1/reports"
    )
    rows = data["reports"]["items"]
    assert [row["iso_week"] for row in rows] == [rows[0]["iso_week"]] * 2
    assert [
        (row["island"], row["digests"], row["entries"], row["ratings"], row["credits"])
        for row in rows
    ] == [("cs", 1, 2, 1, 0), ("quant-ph", 1, 1, 1, 0)]


def test_the_selection_read_lists_the_week_the_genome_was_seeded_in(
    owner: Owner,
) -> None:
    assert owner.client.get("/api/v1/reports/cs/2026-W01/selection").status_code == 401
    sign_in(owner)
    [genome] = check(
        owner.client.get("/api/v1/islands/cs"),
        "actions",
        "GET",
        "/api/v1/islands/{island}",
    )["genomes"]["items"]
    admitted = datetime.fromisoformat(genome["admitted_at"].replace("Z", "+00:00"))
    year, week, _ = admitted.astimezone(timezone.utc).isocalendar()
    path = f"/api/v1/reports/cs/{year:04d}-W{week:02d}/selection"
    data = check(
        owner.client.get(path),
        "actions",
        "GET",
        "/api/v1/reports/{island}/{iso_week}/selection",
    )
    assert data["archived"]["items"] == []
    [row] = data["admitted"]["items"]
    assert (row["configuration_hash"], row["founder"], row["admission"]) == (
        genome["configuration_hash"],
        True,
        "seeded",
    )
    assert (
        owner.client.get("/api/v1/reports/atoll/2026-W01/selection").status_code == 404
    )
    assert owner.client.get("/api/v1/reports/cs/2026-01/selection").status_code == 404


def _publish(owner: Owner, payload: bytes, kind: str, media_type: str) -> str:
    digest = sha256_hex(payload)
    owner.artifacts.publish(
        [payload],
        expected_hash=digest,
        byte_length=len(payload),
        maximum_length=1024 * 1024,
        media_type=media_type,
        kind=kind,
        input_hashes=(),
        producer_version=PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
        command_id=uuid4(),
    )
    return digest


def test_the_document_reads_serve_a_stored_pdf_and_nothing_else(
    owner: Owner,
) -> None:
    pdf = b"%PDF-1.7 owner document"
    stored = _publish(owner, pdf, "source_document", "application/pdf")
    other = _publish(owner, b'{"not":"a pdf"}', "manifest", "application/json")
    family = uuid4()
    for path in (
        f"/api/v1/owner/papers/{family}/documents",
        f"/api/v1/owner/documents/{stored}",
    ):
        assert owner.client.get(path).status_code == 401
    sign_in(owner)
    data = check(
        owner.client.get(f"/api/v1/owner/papers/{family}/documents"),
        "actions",
        "GET",
        "/api/v1/owner/papers/{paper_id}/documents",
    )
    assert data == {
        "paper_id": str(family),
        "documents": {"items": [], "next_cursor": None},
    }
    assert owner.client.get("/api/v1/owner/papers/x/documents").status_code == 404
    response = owner.client.get(f"/api/v1/owner/documents/{stored}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["etag"] == f'"{stored}"'
    assert response.content == pdf
    for refused in (other, "0" * 64, "not-a-hash"):
        response = owner.client.get(f"/api/v1/owner/documents/{refused}")
        assert response.status_code == 404, refused
        assert response.json()["error"]["field"] == "artifact_hash"


def test_the_impact_read_counts_each_seeded_rating_week_under_the_owner_session(
    owner: Owner,
) -> None:
    assert owner.client.get("/api/v1/impact").status_code == 401
    sign_in(owner)
    data = check(owner.client.get("/api/v1/impact"), "actions", "GET", "/api/v1/impact")
    rows = data["impact"]["items"]
    assert [(row["island"], row["ratings"], row["credits"]) for row in rows] == [
        ("cs", 1, 0),
        ("quant-ph", 1, 0),
    ]
    for row in rows:
        assert row["likes"] + row["dislikes"] + row["skips"] == row["ratings"]


def test_the_models_read_lists_no_manifest_before_any_run_under_the_owner_session(
    owner: Owner,
) -> None:
    assert owner.client.get("/api/v1/models").status_code == 401
    sign_in(owner)
    data = check(owner.client.get("/api/v1/models"), "actions", "GET", "/api/v1/models")
    assert data["models"] == {"items": [], "next_cursor": None}


def test_the_genomes_read_counts_the_seeded_genome_under_the_owner_session(
    owner: Owner,
) -> None:
    assert owner.client.get("/api/v1/genomes").status_code == 401
    sign_in(owner)
    data = check(
        owner.client.get("/api/v1/genomes"), "actions", "GET", "/api/v1/genomes"
    )
    [genome] = data["genomes"]["items"]
    assert (
        genome["island"],
        genome["founder"],
        genome["runs"],
        genome["forecasts"],
        genome["credits"],
    ) == ("cs", True, 0, 0, 0)


def test_the_genome_runs_read_serves_a_stored_genome_and_refuses_others(
    owner: Owner,
) -> None:
    path = f"/api/v1/genomes/{owner.configuration_id}/runs"
    assert owner.client.get(path).status_code == 401
    sign_in(owner)
    data = check(
        owner.client.get(path),
        "actions",
        "GET",
        "/api/v1/genomes/{configuration_id}/runs",
    )
    assert data == {
        "configuration_id": str(owner.configuration_id),
        "days": {"items": [], "next_cursor": None},
        "runs": {"items": [], "next_cursor": None},
    }
    assert owner.client.get(f"/api/v1/genomes/{uuid4()}/runs").status_code == 404
    assert owner.client.get("/api/v1/genomes/not-a-uuid/runs").status_code == 404
    assert owner.client.get(f"{path}?cursor=nope").status_code == 422


def test_the_questions_reads_serve_the_owner_and_refuse_an_unknown_question(
    owner: Owner,
) -> None:
    assert owner.client.get("/api/v1/questions").status_code == 401
    sign_in(owner)
    data = check(
        owner.client.get("/api/v1/questions"), "actions", "GET", "/api/v1/questions"
    )
    assert data["questions"] == {"items": [], "next_cursor": None}
    assert owner.client.get(f"/api/v1/questions/{uuid4()}").status_code == 404
    assert owner.client.get("/api/v1/questions/not-a-uuid").status_code == 404


def test_the_island_read_lists_the_seeded_genome_under_the_owner_session(
    owner: Owner,
) -> None:
    assert owner.client.get("/api/v1/islands/cs").status_code == 401
    sign_in(owner)
    data = check(
        owner.client.get("/api/v1/islands/cs"),
        "actions",
        "GET",
        "/api/v1/islands/{island}",
    )
    assert data["island"] == "cs"
    [genome] = data["genomes"]["items"]
    assert (genome["founder"], genome["admission"], genome["runs"]) == (
        True,
        "seeded",
        0,
    )
    empty = check(
        owner.client.get("/api/v1/islands/q-bio"),
        "actions",
        "GET",
        "/api/v1/islands/{island}",
    )
    assert empty["genomes"]["items"] == []
    assert owner.client.get("/api/v1/islands/atoll").status_code == 404


def test_the_population_page_lists_the_genome_under_the_owner_session(
    owner: Owner,
) -> None:
    sign_in(owner)
    page = owner.client.get("/agents")
    assert page.status_code == 200
    assert str(owner.configuration_id) in page.text
    assert owner.client.get("/agents?cursor=malformed").status_code == 422


def test_the_agent_page_merges_the_inspector_reads_with_the_owner_history(
    owner: Owner,
) -> None:
    sign_in(owner)
    page = owner.client.get(f"/agents/{owner.configuration_id}")
    assert page.status_code == 200
    # the owner's own pieces and the inspector's, on one page
    assert "admit an edited genome" in page.text
    assert "no owner action recorded for this genome" in page.text
    assert "<h2>runs</h2>" in page.text
    assert "<h2>verdicts</h2>" in page.text


def test_an_unknown_run_and_manifest_are_not_found(owner: Owner) -> None:
    sign_in(owner)
    assert owner.client.get(f"/runs/{uuid4()}").status_code == 404
    assert owner.client.get("/runs/not-a-uuid").status_code == 404
    assert owner.client.get(f"/models/{'a' * 64}").status_code == 404
    assert owner.client.get("/models/not-a-hash").status_code == 404


def test_the_digest_shows_provenance_only_for_entries_the_owner_rated(
    owner: Owner,
) -> None:
    sign_in(owner)
    response = owner.client.get(f"/api/v1/digests/{owner.digest_hash}")
    assert response.status_code == 200
    entries = {item["entry_id"]: item for item in response.json()["data"]["entries"]}
    rated = entries[str(owner.rated_entry)]
    assert rated["rated"] is True
    assert rated["origin"] == "population"
    assert "nominations" in rated
    # another rater's rating does not unlock the entry for the owner
    unrated = entries[str(owner.unrated_entry)]
    assert set(unrated) == {"entry_id", "paper_hash", "display_position", "rated"}
    assert unrated["rated"] is False


def test_rating_an_entry_unlocks_it_on_the_next_read(owner: Owner) -> None:
    sign_in(owner)
    _rate(owner.ratings, OWNER_RATER_ID, owner.unrated_entry)
    response = owner.client.get(f"/api/v1/digests/{owner.digest_hash}")
    entries = {item["entry_id"]: item for item in response.json()["data"]["entries"]}
    assert entries[str(owner.unrated_entry)]["origin"] == "service"


def test_an_unknown_digest_is_not_found(owner: Owner) -> None:
    sign_in(owner)
    assert owner.client.get(f"/api/v1/digests/{'a' * 64}").status_code == 404
    assert owner.client.get("/api/v1/digests/not-a-hash").status_code == 404


def test_only_the_inspector_role_reads_rated_entries(owner: Owner) -> None:
    owner_role = owner.connect("client", OWNER_SCOPES | {"ratings:rated"})
    with pytest.raises(StorageClientError, match="route not found"):
        owner_role.list_rated_entries(OWNER_RATER_ID)
    listed = owner.inspector.list_rated_entries(OWNER_RATER_ID)
    assert [item["entry_id"] for item in listed.data["entries"]] == [
        str(owner.rated_entry)
    ]
    assert set(listed.data["entries"][0]) == {"entry_id", "paper_hash"}


def test_the_inspector_routes_are_unavailable_without_the_second_client(
    owner: Owner,
) -> None:
    app = create_app(
        ActionsAppConfig(
            actions=owner.inspector,
            directory=owner.directory,
        )
    )
    bare = TestClient(app, base_url="https://testserver", follow_redirects=False)
    assert bare.post("/login", data={"credential": CREDENTIAL}).status_code == 303
    assert bare.get("/agents").status_code == 503
    assert bare.get(f"/api/v1/digests/{'a' * 64}").status_code == 503
