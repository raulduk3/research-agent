"""The owner's read of a paper's embedding view, from acquisition to JSON (#298).

A requested paper is carried through the real acquisition path (documents
job, extraction, one batch embedding, index publication, card) against real
PostgreSQL; its view is then read through the owner actions app, the owner
storage route and the stored artifact, and checked against the contract.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "storage"))

from ingest.test_requests import (  # noqa: E402
    IDENTITY,
    MISSING,
    READABLE,
    _arxiv,
    _Backend,
    _embedder,
    _family,
    _inputs,
    _listing,
    _sources,
    _Words,
)
from test_exclusions import World, identity, world  # noqa: E402
from test_http import Jobs, _tls_material  # noqa: E402
from test_requests import record, repository, served  # noqa: E402
from web.api_contract import check, check_refusal  # noqa: E402
from web.test_costs import CREDENTIAL, OWNER_ID, SETTINGS, sign_in  # noqa: E402

from research_agent.artifacts import ArtifactStore
from research_agent.ingest.pilot import PilotWorker, derived_uuid
from research_agent.ingest.pilot_local import local_storage, worker_principal
from research_agent.ingest.requests import (
    RequestReader,
    acquire_requests,
    listing_identities,
)
from research_agent.models.batch import PlatformIdentity
from research_agent.storage.artifacts import ArtifactRepository
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient
from research_agent.storage.database import Database
from research_agent.storage.embedding_views import EmbeddingViewRepository
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.owners import OwnerRepository
from research_agent.web.actions.app import ActionsAppConfig, create_app
from research_agent.web.auth import OwnerDirectory, hash_credential

pytestmark = pytest.mark.integration

__all__ = ["served", "world"]

ROUTE = "/api/v1/papers/{paper_id}/embedding"


@pytest.fixture
def owner_client(
    world: World, artifact_root: Path, tmp_path: Path
) -> Iterator[TestClient]:
    """The owner actions app over an owner storage identity whose one read
    is the stored embedding views."""

    database = Database(world.dsn)
    owners = OwnerRepository(database, ArtifactStore(artifact_root), **SETTINGS)
    salt, credential_hash = hash_credential(CREDENTIAL)
    owners.execute(
        "provision",
        identity=identity(),
        payload={
            "owner_id": str(OWNER_ID),
            "salt": salt,
            "credential_hash": credential_hash,
        },
    )
    tls = tmp_path / "owner-tls"
    tls.mkdir()
    server_context, _client, fingerprint, _wrong, _other, _none = _tls_material(tls)
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {fingerprint: ServiceCapability(uuid4(), "owner", frozenset({"owner:read"}))},
        tls_context=server_context,
        authorization=StorageAuthorization(database),
        embedding_views=EmbeddingViewRepository(
            database, ArtifactRepository(database, ArtifactStore(artifact_root))
        ),
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    host, port = httpd.server_address[:2]
    storage = StorageClient(
        connect_host=str(host),
        port=int(port),
        server_hostname="localhost",
        ca_file=tls / "ca.pem",
        client_cert_file=tls / "client.pem",
        client_key_file=tls / "client.key",
        scopes=frozenset({"owner:read"}),
        timeout_seconds=10,
    )
    app = create_app(
        ActionsAppConfig(actions=storage, directory=OwnerDirectory(owners))
    )
    try:
        yield TestClient(app, base_url="https://testserver")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_a_requested_paper_gets_a_view_the_owner_reads_and_a_paper_without_vectors_is_404(
    world: World,
    artifact_root: Path,
    tmp_path: Path,
    served: tuple[StorageClient, StorageClient],
    owner_client: TestClient,
) -> None:
    _tools, ingest = served
    requests = repository(world, artifact_root)
    run_id = world.run(uuid4(), "p1")
    for arxiv_id in (*READABLE, MISSING):
        record(requests, run_id, _family(arxiv_id), world.snapshot_hash)

    with (
        _arxiv(tmp_path) as (port, context, _log),
        local_storage(
            dsn=world.dsn,
            artifact_root=artifact_root,
            tls_directory=tmp_path / "worker-tls",
            identity=IDENTITY,
        ) as storage,
    ):
        reader = RequestReader(
            storage,
            PilotWorker(
                storage.client,
                worker_id=worker_principal(tmp_path / "worker-tls"),
                identity=IDENTITY,
                sources=_sources(port, context),
            ),
            identities=listing_identities(
                _listing(arxiv_id) for arxiv_id in (*READABLE, MISSING)
            ),
            work_dir=tmp_path / "work",
            namespace_dir=tmp_path / "index",
            embedder=_embedder(_Backend()),
            tokenizer=_Words(),
            platform=PlatformIdentity("cpu", "test", "0", {"torch": "0"}),
        )
        report = acquire_requests(ingest, reader)
        assert len(report.acquired) == len(READABLE)
        # Each view is stored derived from the index artifact its card
        # pass published, and names it by hash in its body too.
        with psycopg.connect(world.dsn) as connection:
            stored = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    """SELECT paper_family_id, encode(view_hash,'hex')
                       FROM embedding_views"""
                ).fetchall()
            }
        assert set(stored) == {str(_family(arxiv_id)) for arxiv_id in READABLE}
        for item in report.acquired:
            view_hash = stored[item["paper_family_id"]]
            assert _inputs(storage, view_hash) == (item["passage_index_hash"],)
            # The index artifact's content hash is the hash of its body.
            assert storage.report(view_hash)["derived_from"][
                "passage_index_hash"
            ] == storage._raw(item["passage_index_hash"])

    sign_in(owner_client)
    for arxiv_id, other in (READABLE, READABLE[::-1]):
        data = check(
            owner_client.get(ROUTE.format(paper_id=_family(arxiv_id))),
            "actions",
            "GET",
            ROUTE,
        )
        assert data["paper_id"] == str(_family(arxiv_id))
        assert data["paper_version_id"] == str(
            derived_uuid("gate-paper-version", arxiv_id)
        )
        passages = data["passages"]["items"]
        assert passages and data["passages"]["next_cursor"] is None
        assert [p["section_path"][-1] for p in passages][-1] == "Method"
        assert len(data["similarity"]["rows"]) == len(passages)
        # The failed request has an identity but no vectors, so the other
        # readable paper is the one neighbor; both appeared the same day.
        assert data["neighbors"]["items"] == [
            {
                "paper_id": str(_family(other)),
                "title": f"Requested paper {other}",
                "cos": data["neighbors"]["items"][0]["cos"],
                "earlier": False,
            }
        ]

    missing = check_refusal(
        owner_client.get(ROUTE.format(paper_id=_family(MISSING))), 404, "not_found"
    )
    assert missing["field"] == "paper_id"
    check_refusal(
        owner_client.get(ROUTE.format(paper_id="not-a-uuid")), 404, "not_found"
    )


def test_only_an_owner_session_reads_an_embedding_view(
    owner_client: TestClient,
) -> None:
    check_refusal(
        owner_client.get(ROUTE.format(paper_id=_family(READABLE[0]))),
        401,
        "unauthenticated",
    )
