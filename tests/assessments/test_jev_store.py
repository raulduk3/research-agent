"""The Jev work store and assessment pointers on PostgreSQL (#258)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from research_agent.contracts.canonical import canonical_json
from research_agent.contracts.primitives import ContractValidationError
from research_agent.storage.assessments import (
    AssessmentPointerRepository,
    JevWorkRepository,
)
from research_agent.storage.authorization import StorageAuthorization
from research_agent.storage.client import StorageClient, StorageClientError
from research_agent.storage.database import Database
from research_agent.storage.errors import StateConflict
from research_agent.storage.http import ServiceCapability, create_storage_server
from research_agent.storage.roles import (
    StorageRoles,
    provision_storage_roles,
    validate_runtime_role,
)

# The storage test helpers are flat modules in tests/storage, whose own
# test_assessments basename would collide with tests/reader's.
from tests.storage.test_http import Jobs, _tls_material  # noqa: E402
from tests.storage.test_roles import _current_schema, _drop_test_roles, _has  # noqa: E402

pytestmark = pytest.mark.integration

T = TypeVar("T")
DAY = "2026-09-23"


def _hash(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _manifest(work_key: str, label: str = "a") -> bytes:
    return canonical_json({"work_key": work_key, "label": label})


def _race(count: int, operation: Callable[[int], T]) -> list[T]:
    """Run `operation` on `count` threads released together."""

    barrier = threading.Barrier(count)
    results: list[T] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def run(index: int) -> None:
        try:
            barrier.wait()
            value = operation(index)
            with guard:
                results.append(value)
        except BaseException as error:  # noqa: BLE001
            with guard:
                errors.append(error)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    return results


def test_a_second_connection_cannot_take_a_held_lease(postgres_dsn: str) -> None:
    first = JevWorkRepository(Database(postgres_dsn))
    second = JevWorkRepository(Database(postgres_dsn))
    key = _hash("held")

    assert first.acquire_lease(key)
    assert not second.acquire_lease(key)
    assert not first.acquire_lease(key)
    first.release_lease(key)
    assert second.acquire_lease(key)
    first.release_lease(key)
    assert not first.acquire_lease(key)


def test_an_expired_lease_is_taken_over_and_the_old_holder_cannot_free_it(
    postgres_dsn: str,
) -> None:
    database = Database(postgres_dsn)
    crashed = JevWorkRepository(database)
    survivor = JevWorkRepository(database)
    key = _hash("expired")
    assert crashed.acquire_lease(key)
    with database.connect() as connection:
        connection.execute(
            "UPDATE jev_work_leases SET expires_at = clock_timestamp() - interval '1 s'"
        )

    assert survivor.acquire_lease(key)
    crashed.release_lease(key)
    assert not JevWorkRepository(database).acquire_lease(key)


def test_concurrent_workers_on_one_key_yield_exactly_one_lease(
    postgres_dsn: str,
) -> None:
    key = _hash("contended")
    workers = [JevWorkRepository(Database(postgres_dsn)) for _ in range(8)]

    won = _race(8, lambda index: workers[index].acquire_lease(key))

    assert won.count(True) == 1


def test_concurrent_reservations_never_pass_the_daily_attempt_cap(
    postgres_dsn: str,
) -> None:
    workers = [JevWorkRepository(Database(postgres_dsn)) for _ in range(12)]

    ids = _race(
        12,
        lambda index: workers[index].reserve_attempt(
            work_key=_hash(f"work-{index}"),
            day=DAY,
            worst_case_micros=10,
            daily_attempt_cap=5,
            daily_limit_micros=1_000_000,
        ),
    )

    granted = [reservation for reservation in ids if reservation is not None]
    assert len(granted) == 5 and len(set(granted)) == 5
    with Database(postgres_dsn).connect() as connection:
        usage = connection.execute(
            "SELECT attempts, reserved_micros FROM jev_daily_usage"
        ).fetchall()
        rows = connection.execute("SELECT count(*) FROM jev_attempt_reservations")
        assert rows.fetchone() == (5,)
    assert usage == [(5, 50)]


def test_concurrent_reservations_never_pass_the_spend_sublimit(
    postgres_dsn: str,
) -> None:
    workers = [JevWorkRepository(Database(postgres_dsn)) for _ in range(6)]

    ids = _race(
        6,
        lambda index: workers[index].reserve_attempt(
            work_key=_hash("one-key"),
            day=DAY,
            worst_case_micros=400,
            daily_attempt_cap=1000,
            daily_limit_micros=1000,
        ),
    )

    assert sum(reservation is not None for reservation in ids) == 2


def test_the_daily_totals_reset_on_the_next_utc_day(postgres_dsn: str) -> None:
    store = JevWorkRepository(Database(postgres_dsn))
    key = _hash("days")

    def reserve(day: str) -> str | None:
        return store.reserve_attempt(
            work_key=key,
            day=day,
            worst_case_micros=1,
            daily_attempt_cap=1,
            daily_limit_micros=10,
        )

    assert reserve("2026-09-23") is not None
    assert reserve("2026-09-23") is None
    assert reserve("2026-09-24") is not None
    with pytest.raises(ContractValidationError):
        reserve("yesterday")


def test_a_reservation_settles_once(postgres_dsn: str) -> None:
    database = Database(postgres_dsn)
    store = JevWorkRepository(database)
    reservation = store.reserve_attempt(
        work_key=_hash("settle"),
        day=DAY,
        worst_case_micros=7,
        daily_attempt_cap=10,
        daily_limit_micros=100,
    )
    assert reservation is not None

    with pytest.raises(ContractValidationError):
        store.settle_attempt(reservation, "paid")
    store.settle_attempt(reservation, "uncertain")
    with pytest.raises(StateConflict):
        store.settle_attempt(reservation, "known_completed")
    with pytest.raises(StateConflict):
        store.settle_attempt(str(uuid4()), "known_completed")

    with database.connect() as connection:
        row = connection.execute(
            "SELECT billing_state, settled_at IS NOT NULL FROM jev_attempt_reservations"
        ).fetchone()
        totals = connection.execute(
            "SELECT reserved_micros FROM jev_daily_usage"
        ).fetchone()
    assert row == ("uncertain", True)
    assert totals == (7,)


def test_a_committed_manifest_round_trips_and_the_latest_commit_is_current(
    postgres_dsn: str,
) -> None:
    database = Database(postgres_dsn)
    store = JevWorkRepository(database)
    key = _hash("manifest")
    assert store.committed_attempt(key) is None

    first, second = _manifest(key, "first"), _manifest(key, "second")
    store.commit_attempt(key, first)
    assert JevWorkRepository(database).committed_attempt(key) == first
    store.commit_attempt(key, second)
    assert store.committed_attempt(key) == second
    assert store.committed_attempt(_hash("other")) is None
    with database.connect() as connection:
        stamped = connection.execute(
            "SELECT count(*) FROM jev_attempt_manifests"
            " WHERE committed_at <= clock_timestamp() AND manifest_hash = decode(%s,'hex')",
            (sha256(first).hexdigest(),),
        ).fetchone()
        assert stamped == (1,)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute("UPDATE jev_attempt_manifests SET manifest = '\\x00'")


def test_a_manifest_for_another_key_or_not_json_is_refused(postgres_dsn: str) -> None:
    store = JevWorkRepository(Database(postgres_dsn))
    key = _hash("guard")
    for bad in (_manifest(_hash("elsewhere")), b"not json", b"", b"[]"):
        with pytest.raises(ContractValidationError):
            store.commit_attempt(key, bad)
    assert store.committed_attempt(key) is None


def test_the_pointer_moves_only_by_compare_and_swap(postgres_dsn: str) -> None:
    pointers = AssessmentPointerRepository(Database(postgres_dsn))
    paper = str(uuid4())
    one, two, three = _hash("one"), _hash("two"), _hash("three")
    assert pointers.current(paper) is None

    assert pointers.compare_and_swap(paper, None, one)
    assert not pointers.compare_and_swap(paper, None, two)
    assert pointers.current(paper) == one
    assert not pointers.compare_and_swap(paper, two, three)
    assert pointers.compare_and_swap(paper, one, two)
    assert pointers.current(paper) == two
    assert not pointers.compare_and_swap(paper, one, three)


def test_concurrent_swaps_from_one_value_have_one_winner(postgres_dsn: str) -> None:
    paper = str(uuid4())
    base = _hash("base")
    AssessmentPointerRepository(Database(postgres_dsn)).compare_and_swap(
        paper, None, base
    )
    writers = [AssessmentPointerRepository(Database(postgres_dsn)) for _ in range(8)]

    outcomes = _race(
        8,
        lambda index: (
            index,
            writers[index].compare_and_swap(paper, base, _hash(f"candidate-{index}")),
        ),
    )

    winners = [index for index, moved in outcomes if moved]
    assert len(winners) == 1
    assert writers[0].current(paper) == _hash(f"candidate-{winners[0]}")


def _seed_snapshot(database: Database, paper_version_id: str) -> str:
    """A sealed snapshot holding one paper, by raw rows: only the item matters here."""

    snapshot_hash = _hash(f"snapshot-{paper_version_id}")
    manifest_hash, card_hash = _hash("manifest-" + snapshot_hash), _hash("card")
    with database.connect() as connection:
        for artifact in (manifest_hash, card_hash):
            connection.execute(
                """INSERT INTO artifacts(
                       hash, byte_length, media_type, kind, retention_policy_hash,
                       producer_image_digest, producer_source_commit,
                       producer_contract_version, config_hash
                   ) VALUES (decode(%s,'hex'), 0, 'application/json', 'manifest',
                             decode(%s,'hex'), decode(%s,'hex'), decode(%s,'hex'), 1,
                             decode(%s,'hex'))
                   ON CONFLICT DO NOTHING""",
                (artifact, "9" * 64, "8" * 64, "7" * 40, "6" * 64),
            )
        connection.execute(
            """INSERT INTO snapshots(hash, paper_manifest_hash, sealed_at)
               VALUES(decode(%s,'hex'), decode(%s,'hex'), now())""",
            (snapshot_hash, manifest_hash),
        )
        connection.execute(
            """INSERT INTO snapshot_items(
                   snapshot_hash, paper_family_id, paper_version_id, card_hash
               ) VALUES(decode(%s,'hex'), %s, %s, decode(%s,'hex'))""",
            (snapshot_hash, uuid4(), paper_version_id, card_hash),
        )
    return snapshot_hash


def test_a_snapshot_keeps_the_section_current_when_it_was_pinned(
    postgres_dsn: str,
) -> None:
    database = Database(postgres_dsn)
    pointers = AssessmentPointerRepository(database)
    paper = str(uuid4())
    snapshot = _seed_snapshot(database, paper)
    one, two = _hash("section-one"), _hash("section-two")

    assert pointers.pin_snapshot(snapshot, paper) is None
    assert pointers.snapshot_pin(snapshot, paper) is None
    pointers.compare_and_swap(paper, None, one)
    assert pointers.pin_snapshot(snapshot, paper) == one
    assert pointers.compare_and_swap(paper, one, two)

    assert pointers.current(paper) == two
    assert pointers.snapshot_pin(snapshot, paper) == one
    assert pointers.pin_snapshot(snapshot, paper) == one
    with database.connect() as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute("UPDATE assessment_snapshot_pins SET pinned_at = now()")


def test_only_a_paper_in_the_snapshot_can_be_pinned(postgres_dsn: str) -> None:
    database = Database(postgres_dsn)
    pointers = AssessmentPointerRepository(database)
    member, stranger = str(uuid4()), str(uuid4())
    snapshot = _seed_snapshot(database, member)
    pointers.compare_and_swap(stranger, None, _hash("stranger"))

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        pointers.pin_snapshot(snapshot, stranger)


def test_the_reader_reads_the_pointer_and_the_pin_over_mtls_and_no_other_role_can(
    postgres_dsn: str, tmp_path: Path
) -> None:
    database = Database(postgres_dsn)
    pointers = AssessmentPointerRepository(database)
    paper = uuid4()
    snapshot = _seed_snapshot(database, str(paper))
    one, two = _hash("read-one"), _hash("read-two")
    pointers.compare_and_swap(str(paper), None, one)
    pointers.pin_snapshot(snapshot, str(paper))
    pointers.compare_and_swap(str(paper), one, two)
    (
        server_context,
        _client_context,
        fingerprint,
        _wrong_context,
        wrong_fingerprint,
        _no_certificate_context,
    ) = _tls_material(tmp_path)
    scopes = frozenset({"assessments:read"})
    httpd = create_storage_server(
        ("127.0.0.1", 0),
        Jobs(),
        {
            fingerprint: ServiceCapability(uuid4(), "reader", scopes),
            wrong_fingerprint: ServiceCapability(uuid4(), "ingest", scopes),
        },
        tls_context=server_context,
        authorization=StorageAuthorization(database),
        assessments=pointers,
    )
    thread = threading.Thread(target=httpd.serve_forever)
    thread.start()
    try:
        host, port = httpd.server_address[:2]

        def client(cert: str, granted: frozenset[str]) -> StorageClient:
            return StorageClient(
                connect_host=str(host),
                port=int(port),
                server_hostname="localhost",
                ca_file=tmp_path / "ca.pem",
                client_cert_file=tmp_path / f"{cert}.pem",
                client_key_file=tmp_path / f"{cert}.key",
                scopes=granted,
                timeout_seconds=5,
            )

        reader = client("client", scopes)
        pinned = reader.read_assessment_pointers(paper, snapshot_hash=snapshot)
        assert dict(pinned.data) == {
            "paper_version_id": str(paper),
            "current": two,
            "pinned": one,
        }
        assert reader.read_assessment_pointers(paper).data["pinned"] is None
        unknown = reader.read_assessment_pointers(uuid4())
        assert unknown.data["current"] is None

        with pytest.raises(StorageClientError, match="route not found"):
            client("wrong", scopes).read_assessment_pointers(paper)
        with pytest.raises(PermissionError):
            client("client", frozenset({"digests:read"})).read_assessment_pointers(
                paper
            )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_runtime_role_can_move_leases_and_pointers_but_not_rewrite_history(
    postgres_dsn: str,
) -> None:
    roles = StorageRoles(
        application=f"storage_app_{uuid4().hex}",
        migrator=f"storage_migrator_{uuid4().hex}",
    )
    appendable = ("jev_attempt_manifests", "assessment_snapshot_pins")
    movable = (
        "jev_work_leases",
        "jev_daily_usage",
        "jev_attempt_reservations",
        "assessment_pointers",
    )
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        schema = _current_schema(connection)
        try:
            provision_storage_roles(connection, roles, schema=schema, fresh=True)
            connection.execute(
                sql.SQL("GRANT {} TO CURRENT_USER").format(
                    sql.Identifier(roles.application)
                )
            )
            with connection.transaction():
                connection.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(
                        sql.Identifier(roles.application)
                    )
                )
                validate_runtime_role(connection, schema)
                for table in appendable + movable:
                    assert _has(connection, table, "select")
                    assert _has(connection, table, "insert")
                    assert not _has(connection, table, "delete")
                    assert not _has(connection, table, "truncate")
                for table in appendable:
                    assert not _has(connection, table, "update")
                for table in movable:
                    assert _has(connection, table, "update")
        finally:
            _drop_test_roles(connection, roles, schema)


def test_a_reader_route_carries_uuid_paper_versions_only(postgres_dsn: str) -> None:
    pointers = AssessmentPointerRepository(Database(postgres_dsn))
    with pytest.raises(ContractValidationError):
        pointers.current("not-a-uuid")
    with pytest.raises(ContractValidationError):
        pointers.compare_and_swap(str(uuid4()), None, "short")
