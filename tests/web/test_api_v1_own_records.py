"""A rater reads back their own ratings of a batch and their preference credit (#252)."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from starlette.testclient import TestClient
from web.api_contract import check, check_refusal
from web import test_private_rater_access as rater_access

from research_agent.artifacts import ArtifactStore
from research_agent.storage.client import StorageClient, StorageClientError
from research_agent.storage.commands import CommandIdentity
from research_agent.storage.database import Database
from research_agent.storage.preference import PreferenceRepository

pytestmark = pytest.mark.integration

storage_server = rater_access.storage_server
storage_client = rater_access.storage_client
_provisioned_raters = rater_access._provisioned_raters
rater_directory = rater_access.rater_directory
rating_app_client = rater_access.rating_app_client

ENTRY = "22222222-2222-4222-8222-222222222222"
BATCH_ID = sha256(b"fixture-digest-batch").hexdigest()
GENOME_HASH = sha256(b"genome-own-records").hexdigest()


def sign_in(client: TestClient, credential: str) -> str:
    response = client.post("/api/v1/login", json={"credential": credential})
    assert response.status_code == 200, response.text
    return str(response.json()["data"]["csrf_token"])


def rate_entry(client: TestClient, token: str) -> dict[str, str]:
    rows = client.get("/api/v1/digest").json()["data"]["rows"]["items"]
    paper_hash = next(
        row["paper_hash"] for row in rows if row["digest_entry_id"] == ENTRY
    )
    response = client.post(
        "/api/v1/ratings",
        json={"digest_entry_id": ENTRY, "paper_hash": paper_hash, "value": "like"},
        headers={"X-CSRF-Token": token, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def iso_week(instant: str) -> str:
    year, week, _ = datetime.fromisoformat(instant).isocalendar()
    return f"{year}-W{week:02d}"


def record_credit(
    postgres_dsn: str, artifact_root: Path, rating_id: str, week: str
) -> None:
    """Credit the rating to one cs genome through the real preference write path."""
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(
            """INSERT INTO genomes(
                   configuration_id, configuration_hash, lineage_id, island,
                   founder, infra_hash, parent_hash, admission, profile_hash,
                   admitted_at
               ) VALUES(%s, decode(%s,'hex'), 'own-records', 'cs', true,
                        decode(%s,'hex'), NULL, 'seeded', decode(%s,'hex'), now())""",
            (uuid4(), GENOME_HASH, "e" * 64, "f" * 64),
        )
    PreferenceRepository(
        Database(postgres_dsn),
        ArtifactStore(artifact_root),
        producer=rater_access.PRODUCER,
        config_hash="c" * 64,
        retention_policy_hash="d" * 64,
    ).execute(
        "record",
        identity=CommandIdentity(uuid4(), uuid4(), uuid4(), uuid4()),
        payload={
            "credits": [
                {
                    "rating_id": rating_id,
                    "genome_hash": GENOME_HASH,
                    "island": "cs",
                    "entry_id": ENTRY,
                    "sealed_probability": 0.5,
                    "share": 1.0,
                    "iso_week": week,
                }
            ]
        },
    )


def test_a_rater_reads_their_own_ratings_of_a_batch_and_no_one_elses(
    rating_app_client: TestClient,
) -> None:
    token = sign_in(rating_app_client, rater_access.RATER_ONE_CREDENTIAL)
    recorded = rate_entry(rating_app_client, token)

    data = check(
        rating_app_client.get(f"/api/v1/ratings?batch_id={BATCH_ID}"),
        "rating",
        "GET",
        "/api/v1/ratings",
    )
    assert data["ratings"]["items"] == [
        {
            "rating_id": recorded["rating_id"],
            "digest_entry_id": ENTRY,
            "paper_hash": data["ratings"]["items"][0]["paper_hash"],
            "value": "like",
            "rated_at": recorded["rated_at"],
        }
    ]
    named_self = rating_app_client.get(
        f"/api/v1/ratings?batch_id={BATCH_ID}&rater_id={rater_access.RATER_ONE_ID}"
    )
    assert named_self.json()["data"] == data
    check_refusal(
        rating_app_client.get(
            f"/api/v1/ratings?batch_id={BATCH_ID}&rater_id={rater_access.RATER_TWO_ID}"
        ),
        403,
        "forbidden",
    )

    sign_in(rating_app_client, rater_access.RATER_TWO_CREDENTIAL)
    other = check(
        rating_app_client.get(f"/api/v1/ratings?batch_id={BATCH_ID}"),
        "rating",
        "GET",
        "/api/v1/ratings",
    )
    assert other["ratings"]["items"] == []
    check_refusal(
        rating_app_client.get(
            f"/api/v1/ratings?batch_id={BATCH_ID}&rater_id={rater_access.RATER_ONE_ID}"
        ),
        403,
        "forbidden",
    )


def test_a_rater_reads_their_credit_as_a_share_per_rating_and_no_one_elses(
    rating_app_client: TestClient, postgres_dsn: str, artifact_root: Path
) -> None:
    token = sign_in(rating_app_client, rater_access.RATER_ONE_CREDENTIAL)
    recorded = rate_entry(rating_app_client, token)
    week = iso_week(recorded["rated_at"])
    record_credit(postgres_dsn, artifact_root, recorded["rating_id"], week)

    data = check(
        rating_app_client.get(f"/api/v1/credit?week={week}"),
        "rating",
        "GET",
        "/api/v1/credit",
    )
    assert data == {
        "credits": {
            "items": [
                {
                    "rating_id": recorded["rating_id"],
                    "genome_hash": GENOME_HASH,
                    "share": 1.0,
                }
            ],
            "next_cursor": None,
        }
    }
    check_refusal(
        rating_app_client.get(
            f"/api/v1/credit?week={week}&rater_id={rater_access.RATER_TWO_ID}"
        ),
        403,
        "forbidden",
    )

    sign_in(rating_app_client, rater_access.RATER_TWO_CREDENTIAL)
    other = check(
        rating_app_client.get(f"/api/v1/credit?week={week}"),
        "rating",
        "GET",
        "/api/v1/credit",
    )
    assert other["credits"]["items"] == []


def test_the_own_record_reads_refuse_no_session_and_malformed_queries(
    rating_app_client: TestClient,
) -> None:
    check_refusal(
        rating_app_client.get(f"/api/v1/ratings?batch_id={BATCH_ID}"),
        401,
        "unauthenticated",
    )
    sign_in(rating_app_client, rater_access.RATER_ONE_CREDENTIAL)
    for path, field in (
        ("/api/v1/ratings", "batch_id"),
        ("/api/v1/ratings?batch_id=not-a-hash", "batch_id"),
        (f"/api/v1/ratings?batch_id={BATCH_ID}&rater_id=nobody", "rater_id"),
        ("/api/v1/credit", "week"),
        ("/api/v1/credit?week=2026-39", "week"),
    ):
        error = check_refusal(rating_app_client.get(path), 422, "invalid_request")
        assert error["field"] == field, path


def test_storage_serves_a_raters_records_only_to_the_rating_app_role(
    storage_server: tuple[tuple[str, int], Path], _provisioned_raters: None
) -> None:
    address, tmp_path = storage_server
    operator = StorageClient(
        connect_host=address[0],
        port=address[1],
        server_hostname="localhost",
        ca_file=tmp_path / "ca.pem",
        client_cert_file=tmp_path / "wrong.pem",
        client_key_file=tmp_path / "wrong.key",
        scopes=frozenset({"raters:read"}),
        timeout_seconds=5,
    )
    rater = rater_access.RATER_ONE_ID
    for read in (
        lambda: operator.list_own_ratings(rater, batch_id=BATCH_ID),
        lambda: operator.list_own_credits(rater, iso_week="2026-W39"),
    ):
        with pytest.raises(StorageClientError) as refused:
            read()
        assert refused.value.status_code == 404
